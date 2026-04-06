"""AgentOrchestratorV2 — LangGraph-based agent chat loop.

Drop-in replacement for AgentOrchestrator (v1). Exposes the same
.run(message, session_id) → AsyncIterator[dict] interface so the
router can swap between v1 and v2 via feature flag.

Phase 2-B: happy path (load_context → llm_call → tool_execute → synthesis).
Phase 2-C will add: HITL, self-critique, memory lifecycle nodes.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_orchestrator_v2.adapter import adapt_events
from app.services.agent_orchestrator_v2.graph import build_graph
from app.services.agent_orchestrator_v2.state import DEFAULT_STATE

logger = logging.getLogger(__name__)

# Module-level compiled graph (built once, reused across requests)
_compiled_graph = None


def _get_compiled_graph():
    """Lazy-compile the graph (thread-safe: worst case builds twice, same result)."""
    global _compiled_graph
    if _compiled_graph is None:
        graph = build_graph()
        _compiled_graph = graph.compile()
    return _compiled_graph


class AgentOrchestratorV2:
    """LangGraph-based agent orchestrator with v1-compatible SSE interface."""

    def __init__(
        self,
        db: AsyncSession,
        base_url: str,
        auth_token: str,
        user_id: int,
        canvas_overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._db = db
        self._base_url = base_url
        self._auth_token = auth_token
        self._user_id = user_id
        self._canvas_overrides = canvas_overrides

    async def run(
        self,
        message: str,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Run the agent graph and yield v1-compatible SSE events.

        Same signature as AgentOrchestrator.run() so the router can
        switch between v1 and v2 without changing any calling code.
        """
        graph = _get_compiled_graph()

        # Build initial state
        initial_state = {
            **DEFAULT_STATE,
            "user_id": self._user_id,
            "session_id": session_id,
            "user_message": message,
            "canvas_overrides": self._canvas_overrides,
        }

        # Config carries request-scoped dependencies (DB session, auth, etc.)
        # so nodes can access them without being coupled to FastAPI.
        config = {
            "configurable": {
                "db": self._db,
                "base_url": self._base_url,
                "auth_token": self._auth_token,
                "user_id": self._user_id,
                "thread_id": session_id or "ephemeral",
            },
        }

        # Stream LangGraph events and translate to v1 SSE format.
        # Also collect final state for session persistence.
        _final_session_id = session_id
        _final_text = ""
        _total_tokens = 0

        try:
            event_stream = graph.astream_events(
                initial_state,
                config=config,
                version="v2",
            )

            async for v1_event in adapt_events(event_stream, initial_state):
                # Track session_id + final_text + tokens for session save
                if v1_event.get("type") == "context_load":
                    _final_session_id = v1_event.get("session_id") or _final_session_id
                elif v1_event.get("type") == "synthesis":
                    _final_text = v1_event.get("text", "")
                elif v1_event.get("type") == "llm_usage":
                    _total_tokens += v1_event.get("input_tokens", 0) + v1_event.get("output_tokens", 0)
                yield v1_event
        except Exception as exc:
            logger.exception("v2 graph run failed")
            yield {"type": "error", "message": f"v2 graph error: {exc}"}
            yield {"type": "done"}

        # ── Session persistence: sliding window + hierarchical summarization ──
        # Keep the last 3 turns (6 messages) as raw text for pronoun resolution.
        # Older turns are summarized into a compact "session state" prefix.
        try:
            from app.services.agent_orchestrator_v2.session import (
                load_session, save_session, _messages_to_dicts,
            )
            # Load existing history to append this turn
            _, existing_history, existing_tokens = await load_session(
                self._db, _final_session_id, self._user_id,
            )

            # Build v1-format messages for this turn
            from langchain_core.messages import HumanMessage, AIMessage
            this_turn = [
                {"role": "user", "content": message},
                {"role": "assistant", "content": _final_text},
            ]

            full_history = _messages_to_dicts(existing_history) + this_turn

            # Sliding window: keep last 6 messages (3 turns) as raw
            RAW_WINDOW = 6
            if len(full_history) > RAW_WINDOW:
                old_part = full_history[:-RAW_WINDOW]
                recent_part = full_history[-RAW_WINDOW:]

                # Summarize old part into a compact state prefix
                summary = await _summarize_history(old_part, self._llm)
                # Prefix format: a single "system" message with the summary
                compressed = [{"role": "user", "content": f"[歷史摘要] {summary}"},
                              {"role": "assistant", "content": "了解，我會參考這些歷史背景。"}]
                full_history = compressed + recent_part

            await save_session(
                db=self._db,
                session_id=_final_session_id or "ephemeral",
                user_id=self._user_id,
                messages=existing_history,  # LangChain messages for load compatibility
                cumulative_tokens=existing_tokens + _total_tokens,
            )

            # Save in v1 format (for the actual session persistence)
            import json as _json
            from sqlalchemy import select
            from app.models.agent_session import AgentSessionModel
            import datetime as _dt
            from datetime import timedelta, timezone as _tz

            result = await self._db.execute(
                select(AgentSessionModel).where(
                    AgentSessionModel.session_id == (_final_session_id or "ephemeral")
                )
            )
            row = result.scalar_one_or_none()
            if row:
                row.messages = _json.dumps(full_history, ensure_ascii=False)
                row.cumulative_tokens = existing_tokens + _total_tokens
                row.expires_at = _dt.datetime.now(tz=_tz.utc) + timedelta(hours=24)
                await self._db.commit()
            logger.info("Session saved: %s (%d messages, %d tokens)",
                       _final_session_id, len(full_history), existing_tokens + _total_tokens)
        except Exception as exc:
            logger.warning("Session save failed (non-blocking): %s", exc)


async def _summarize_history(
    old_messages: list[dict],
    llm,
) -> str:
    """Summarize old conversation turns into a compact state description.

    Uses a cheap LLM call to compress N turns of dialogue into 2-3 sentences
    that capture the key context (what was discussed, what data was retrieved,
    what conclusions were reached).
    """
    if not old_messages:
        return ""

    # Build a condensed view of the old messages
    lines = []
    for msg in old_messages[-10:]:  # cap at last 10 messages of old part
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, str):
            lines.append(f"{role}: {content[:200]}")

    history_text = "\n".join(lines)

    try:
        resp = await llm.create(
            system="你是對話摘要助手。把以下對話歷史壓縮成 2-3 句中文，保留：討論了什麼主題、查詢了什麼資料、得出了什麼結論。只輸出摘要文字，不要解釋。",
            messages=[{"role": "user", "content": f"請摘要以下對話歷史：\n{history_text}"}],
            max_tokens=200,
        )
        summary = (resp.text or "").strip()
        if summary:
            return summary
    except Exception as exc:
        logger.warning("History summarization failed: %s", exc)

    # Fallback: just take the last user message as summary
    for msg in reversed(old_messages):
        if msg.get("role") == "user":
            return f"之前討論了：{msg.get('content', '')[:100]}"
    return ""
