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

        # Stream LangGraph events and translate to v1 SSE format
        try:
            event_stream = graph.astream_events(
                initial_state,
                config=config,
                version="v2",
            )

            async for v1_event in adapt_events(event_stream, initial_state):
                yield v1_event
        except Exception as exc:
            logger.exception("v2 graph run failed")
            yield {"type": "error", "message": f"v2 graph error: {exc}"}
            yield {"type": "done"}

        # Save session after completion (Phase 2-B: simple approach)
        try:
            from app.services.agent_orchestrator_v2.session import save_session
            # Get final state to persist conversation
            # For now, we save a minimal history
            await save_session(
                db=self._db,
                session_id=initial_state.get("session_id", session_id) or "ephemeral",
                user_id=self._user_id,
                messages=[],  # TODO: collect from final graph state
                cumulative_tokens=0,
            )
        except Exception as exc:
            logger.warning("Session save failed (non-blocking): %s", exc)
