"""Hand-rolled async graph that runs one chat turn end-to-end.

Node flow:
  1. ``load_session``  → pull prior messages from Java
  2. ``load_context``  → fetch MCPs + skills for LLM prompt
  3. ``recall``        → pull recent memories matching the task
  4. ``llm``           → stream tokens from the LLM
  5. ``remember``      → persist the exchange as a memory row
  6. ``save_session``  → upsert the updated message list in Java

Each step emits one SSE event so Frontend can render progress.
The whole thing lives in ~80 lines of async Python — if we outgrow this we
can drop in real LangGraph; for now the clarity is worth more than the runtime.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from ..auth import CallerContext
from ..clients.java_client import JavaAPIClient
from .context_loader import load_context, snapshot_json
from .llm import llm_stream
from .memory import recall, remember
from .session import SessionState, load_or_new, save

log = logging.getLogger("python_ai_sidecar.orchestrator")


def _event(name: str, payload: dict) -> dict:
    return {"event": name, "data": json.dumps(payload, ensure_ascii=False)}


async def run_chat_turn(
    *,
    user_message: str,
    session_id: str | None,
    caller: CallerContext,
) -> AsyncIterator[dict]:
    """Orchestrate one turn. Yields SSE-shaped dicts the sidecar router turns
    into ``text/event-stream`` frames."""
    java = JavaAPIClient.for_caller(caller)
    user_id = caller.user_id or -1

    # --- 1. Session
    state = await load_or_new(java, session_id, user_id)
    state.append("user", user_message)
    yield _event("open", {
        "session_id": state.session_id,
        "caller_user_id": caller.user_id,
        "prior_messages": max(len(state.messages) - 1, 0),
    })

    # --- 2. Context
    ctx = await load_context(java)
    yield _event("context", ctx.summary())

    # --- 3. Recall
    prior = await recall(java, user_id=user_id, limit=3) if user_id > 0 else []
    yield _event("recall", {"memory_count": len(prior)})

    # --- 4. LLM (streamed)
    system_prompt = (
        "You are AIOps Copilot. Here is the live catalog you can reference:\n"
        + ctx.format_for_llm()
    )
    full_reply_parts: list[str] = []
    index = 0
    async for token in llm_stream(system_prompt, user_message):
        full_reply_parts.append(token)
        yield _event("message", {"index": index, "token": token})
        index += 1
    full_reply = "".join(full_reply_parts).strip()
    state.append("assistant", full_reply)

    # --- 5. Memory
    mem_task_type = "chat_reply"
    if user_id > 0:
        try:
            saved = await remember(
                java,
                user_id=user_id,
                content=f"Q: {user_message}\nA: {full_reply}",
                source="agent_request",
                task_type=mem_task_type,
            )
            yield _event("memory", {"saved_id": saved.get("id") if isinstance(saved, dict) else None})
        except Exception as ex:  # noqa: BLE001 — memory write failure isn't fatal
            log.warning("memory save failed: %s", ex)
            yield _event("memory", {"saved_id": None, "error": str(ex)[:100]})

    # --- 6. Checkpoint
    state.workspace_state = snapshot_json(ctx)
    if not state.title and len(user_message) > 0:
        state.title = user_message[:40]
    try:
        persisted = await save(java, state)
        yield _event("checkpoint", {"session_id": state.session_id,
                                    "persisted": isinstance(persisted, dict)})
    except Exception as ex:  # noqa: BLE001
        log.warning("session checkpoint failed: %s", ex)
        yield _event("checkpoint", {"session_id": state.session_id, "error": str(ex)[:100]})

    # --- done
    yield _event("done", {"summary": full_reply[:200], "turns": len(state.messages)})
