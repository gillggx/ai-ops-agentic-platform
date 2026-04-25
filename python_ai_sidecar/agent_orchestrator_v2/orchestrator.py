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

from python_ai_sidecar.agent_orchestrator_v2.adapter import adapt_events
from python_ai_sidecar.agent_orchestrator_v2.graph import build_graph
from python_ai_sidecar.agent_orchestrator_v2.state import DEFAULT_STATE

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
        roles: Optional[tuple[str, ...]] = None,
    ) -> None:
        self._db = db
        self._base_url = base_url
        self._auth_token = auth_token
        self._user_id = user_id
        # Phase v1.3 P0: caller roles drive tool-list filtering in llm_call.
        # None / empty → fail-closed to ON_DUTY in _is_on_duty_only.
        self._roles = tuple(roles or ())
        self._canvas_overrides = canvas_overrides

    async def run(
        self,
        message: str,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Run the agent graph and yield v1-compatible SSE events.

        Same signature as AgentOrchestrator.run() so the router can
        switch between v1 and v2 without changing any calling code.

        Phase 5-UX-5: an in-process event queue is attached to `configurable`
        so tool_execute can push pipeline-builder lifecycle events from the
        PipelineExecutor callback. A background relay task drains the queue
        and yields the events alongside the graph's own SSE events, giving
        the chat UI a live stream of `pb_structure` + `pb_node_start/done`.
        """
        import asyncio as _asyncio
        graph = _get_compiled_graph()

        # Build initial state
        initial_state = {
            **DEFAULT_STATE,
            "user_id": self._user_id,
            "session_id": session_id,
            "user_message": message,
            "canvas_overrides": self._canvas_overrides,
        }

        # Phase 5-UX-5: event bus for tool → SSE progressive events.
        # Callable is sync (executor is sync at the callsite), asyncio queue is
        # thread-safe enough for same-loop puts.
        _pb_queue: _asyncio.Queue = _asyncio.Queue()
        _loop = _asyncio.get_running_loop()

        def _pb_event_emit(event: Dict[str, Any]) -> None:
            # Called from sync context inside tool_execute; schedule put onto loop.
            try:
                _loop.call_soon_threadsafe(_pb_queue.put_nowait, event)
            except Exception:  # noqa: BLE001
                pass

        # Config carries request-scoped dependencies (DB session, auth, etc.)
        # so nodes can access them without being coupled to FastAPI.
        config = {
            "configurable": {
                "db": self._db,
                "base_url": self._base_url,
                "auth_token": self._auth_token,
                "user_id": self._user_id,
                # Phase v1.3 P0: caller roles flow into llm_call._visible_tools
                # so ON_DUTY users get a restricted tool catalog.
                "caller_roles": self._roles,
                "thread_id": session_id or "ephemeral",
                # Phase 5-UX-5: callback into which tool_execute pushes
                # pipeline-builder lifecycle events.
                "pb_event_emit": _pb_event_emit,
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

            # Phase 5-UX-5: race the graph events with the pb event queue so
            # per-node lifecycle events interleave with LLM events. Runs a
            # background task that reads the graph stream into a second queue;
            # then this coroutine drains both queues until the graph finishes.
            _graph_queue: _asyncio.Queue = _asyncio.Queue()
            _graph_done = _asyncio.Event()

            async def _drain_graph():
                try:
                    async for v1_event in adapt_events(event_stream, initial_state):
                        await _graph_queue.put(v1_event)
                except Exception as exc:  # noqa: BLE001
                    await _graph_queue.put({
                        "type": "error", "message": f"v2 graph error: {exc}",
                    })
                finally:
                    _graph_done.set()

            _graph_task = _asyncio.create_task(_drain_graph())

            while True:
                graph_is_done = _graph_done.is_set() and _graph_queue.empty()
                pb_is_empty = _pb_queue.empty()
                if graph_is_done and pb_is_empty:
                    break
                # Prefer pb events when available (they're time-sensitive
                # progress updates). Otherwise wait on graph with short timeout
                # so new pb events still get flushed quickly.
                if not pb_is_empty:
                    v1_event = _pb_queue.get_nowait()
                else:
                    get_graph = _asyncio.create_task(_graph_queue.get())
                    get_done  = _asyncio.create_task(_graph_done.wait())
                    done, pending = await _asyncio.wait(
                        {get_graph, get_done},
                        return_when=_asyncio.FIRST_COMPLETED,
                        timeout=0.1,
                    )
                    for p in pending:
                        p.cancel()
                    if get_graph in done:
                        v1_event = get_graph.result()
                    else:
                        continue

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
            from python_ai_sidecar.agent_orchestrator_v2.session import (
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

            # Sliding window: keep last 3 turns (6 messages) as raw.
            # Also trigger compression if total text exceeds TOKEN_THRESHOLD
            # even within the window (long tool results can bloat a single turn).
            RAW_WINDOW = 6
            TOKEN_THRESHOLD = 8000  # ~chars; rough proxy for tokens (1 token ≈ 2 chars for Chinese)
            total_chars = sum(len(m.get("content", "")) for m in full_history)
            needs_compress = len(full_history) > RAW_WINDOW or total_chars > TOKEN_THRESHOLD

            if needs_compress and len(full_history) > 2:
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
            import datetime as _dt
            from datetime import timedelta, timezone as _tz

            v1_payload = _json.dumps(full_history, ensure_ascii=False)
            expires = _dt.datetime.now(tz=_tz.utc) + timedelta(hours=24)

            if self._db is None:
                # Phase 8-A-1d: native chat — save via Java upsert.
                from python_ai_sidecar.clients.java_client import JavaAPIClient
                from python_ai_sidecar.config import CONFIG
                java = JavaAPIClient(
                    CONFIG.java_api_url, CONFIG.java_internal_token,
                    timeout_sec=CONFIG.java_timeout_sec,
                )
                try:
                    await java.upsert_agent_session(_final_session_id or "ephemeral", {
                        "userId": self._user_id,
                        "messages": v1_payload,
                        "cumulativeTokens": existing_tokens + _total_tokens,
                        "expiresAt": expires.isoformat(),
                    })
                except Exception as exc:
                    logger.warning("session save via java failed: %s", exc)
            else:
                from sqlalchemy import select
                from python_ai_sidecar.agent_helpers._model_stubs import AgentSessionModel
                result = await self._db.execute(
                    select(AgentSessionModel).where(
                        AgentSessionModel.session_id == (_final_session_id or "ephemeral")
                    )
                )
                row = result.scalar_one_or_none()
                if row:
                    row.messages = v1_payload
                    row.cumulative_tokens = existing_tokens + _total_tokens
                    row.expires_at = expires
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
