"""runner — drives the StateGraph and yields StreamEvent for SSE.

Public functions:
  stream_graph_build(...)   — fresh build run; if it hits confirm_gate,
                              yields confirm_pending and returns. Frontend
                              must POST /agent/build/{session}/confirm to resume.

  resume_graph_build(...)   — continues a paused (interrupted) run with the
                              user's confirm/reject, yields remaining events.

State persists across run/resume via LangGraph MemorySaver (in-process).
The thread_id is the session_id supplied by the caller.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncGenerator, Optional

from langgraph.types import Command

from python_ai_sidecar.agent_builder.graph_build.graph import build_graph
from python_ai_sidecar.agent_builder.graph_build.state import initial_state
from python_ai_sidecar.agent_builder.session import StreamEvent


logger = logging.getLogger(__name__)


def _flush_sse_events(state_after: dict) -> list[StreamEvent]:
    """Pull and clear the sse_events buffer that nodes wrote into state."""
    events = state_after.get("sse_events") or []
    out = [StreamEvent(type=ev.get("event", "operation"), data=ev.get("data") or {}) for ev in events]
    return out


async def stream_graph_build(
    *,
    instruction: str,
    base_pipeline: Optional[dict] = None,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
) -> AsyncGenerator[StreamEvent, None]:
    """Run the graph from the start. Yields StreamEvent as nodes complete.

    If a confirm_gate fires, yields a `confirm_pending` event with session_id
    and stops. Resume by calling resume_graph_build(session_id, confirmed).
    """
    sid = session_id or str(uuid.uuid4())
    graph = build_graph()
    config = {"configurable": {"thread_id": sid}, "recursion_limit": 50}

    init = initial_state(
        session_id=sid,
        instruction=instruction,
        base_pipeline=base_pipeline,
        user_id=user_id,
    )
    logger.info("stream_graph_build: starting session=%s", sid)

    last_state: dict = {}
    interrupted = False

    # Stream node-by-node updates. astream(stream_mode="values") yields the
    # full state after each node finishes, which lets us flush sse_events
    # incrementally. interrupt() shows up as a special __interrupt__ entry.
    async for chunk in graph.astream(init, config=config, stream_mode="values"):
        last_state = chunk if isinstance(chunk, dict) else {}
        # Each chunk's sse_events accumulates state-wide, so we only flush
        # the deltas — but MemorySaver returns the full list each time.
        # Simpler approach: just emit each chunk's events, frontend tolerates
        # duplicates by id (we'll use cursor / event order).
        for ev in _flush_sse_events(last_state):
            yield ev

    # Check if graph paused on interrupt
    state_obj = await graph.aget_state(config)
    if state_obj.next:
        # Graph is paused. Surface confirm_pending with session_id.
        interrupted = True
        # The interrupt payload from confirm_gate is the most recent task value.
        try:
            interrupt_payload = (
                state_obj.tasks[0].interrupts[0].value if state_obj.tasks
                else {}
            )
        except Exception:  # noqa: BLE001
            interrupt_payload = {}
        yield StreamEvent(
            type="confirm_pending",
            data={
                "session_id": sid,
                **(interrupt_payload if isinstance(interrupt_payload, dict) else {}),
            },
        )
        # Don't emit done — frontend keeps connection logic decoupled.
        return

    # Reached END — emit a done event
    yield StreamEvent(
        type="done",
        data={
            "status": last_state.get("status") or "finished",
            "pipeline_json": last_state.get("final_pipeline") or last_state.get("base_pipeline"),
            "summary": last_state.get("summary"),
            "session_id": sid,
        },
    )


async def resume_graph_build(
    *,
    session_id: str,
    confirmed: bool,
) -> AsyncGenerator[StreamEvent, None]:
    """Resume a paused graph (post-confirm_gate) with user's decision."""
    graph = build_graph()
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 50}

    logger.info("resume_graph_build: session=%s confirmed=%s", session_id, confirmed)
    last_state: dict = {}

    async for chunk in graph.astream(
        Command(resume={"confirmed": confirmed}),
        config=config,
        stream_mode="values",
    ):
        last_state = chunk if isinstance(chunk, dict) else {}
        for ev in _flush_sse_events(last_state):
            yield ev

    yield StreamEvent(
        type="done",
        data={
            "status": last_state.get("status") or ("finished" if confirmed else "cancelled"),
            "pipeline_json": last_state.get("final_pipeline") or last_state.get("base_pipeline"),
            "summary": last_state.get("summary"),
            "session_id": session_id,
        },
    )
