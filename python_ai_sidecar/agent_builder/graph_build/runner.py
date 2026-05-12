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
from python_ai_sidecar.agent_builder.graph_build.trace import make_tracer
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
    skip_confirm: bool = False,
    skill_step_mode: bool = False,
) -> AsyncGenerator[StreamEvent, None]:
    """Run the graph from the start. Yields StreamEvent as nodes complete.

    Args:
        skip_confirm: When True, the graph bypasses confirm_gate even for
            FROM_SCRATCH builds. Used by Chat Mode where the conversation
            itself is the confirmation. Builder Mode passes False so users
            still see the Apply/Cancel card before any canvas mutation.

    If confirm_gate fires (skip_confirm=False + FROM_SCRATCH), yields
    `confirm_pending` and returns; caller resumes via resume_graph_build().
    """
    sid = session_id or str(uuid.uuid4())
    graph = build_graph()
    # 2026-05-12: bumped 50 → 150. Each plan op consumes ~2 graph node visits
    # (dispatch_op + call_tool). A 30-op plan needs ~60 visits; 50 was below
    # that and crashed mid-execution on user's skill 54 build. 150 gives
    # headroom for repair_op + repair_plan loops too.
    config = {"configurable": {"thread_id": sid}, "recursion_limit": 150}

    init = initial_state(
        session_id=sid,
        instruction=instruction,
        base_pipeline=base_pipeline,
        user_id=user_id,
        skip_confirm=skip_confirm,
        skill_step_mode=skill_step_mode,
    )
    logger.info("stream_graph_build: starting session=%s", sid)

    # Phase 11 v17 — opt-in BuildTracer (BUILDER_TRACE_DIR env). When the
    # env var is unset, tracer is None and nodes' record_step() are no-ops.
    # Per CLAUDE.md「flow 由 graph 決定」this is purely observational and
    # never affects routing or LLM output.
    tracer = make_tracer(
        instruction=instruction,
        session_id=sid,
        skip_confirm=skip_confirm,
        skill_step_mode=skill_step_mode,
        base_pipeline=base_pipeline,
    )

    last_state: dict = {}
    interrupted = False

    if tracer is not None:
        await tracer.__aenter__()
    try:
        # Stream node-by-node updates. astream(stream_mode="values") yields
        # the full state after each node finishes, which lets us flush
        # sse_events incrementally. interrupt() shows up as a special
        # __interrupt__ entry.
        async for chunk in graph.astream(init, config=config, stream_mode="values"):
            last_state = chunk if isinstance(chunk, dict) else {}
            for ev in _flush_sse_events(last_state):
                yield ev
    finally:
        if tracer is not None:
            tracer.set_final_pipeline(
                last_state.get("final_pipeline") or last_state.get("base_pipeline")
            )
            await tracer.__aexit__(None, None, None)

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


async def dry_run_plan(
    *,
    instruction: str,
    base_pipeline: Optional[dict] = None,
) -> dict[str, Any]:
    """Plan-only mode for Chat's `show_plan` use case.

    Runs plan_node + validate_plan_node manually (no StateGraph, no
    checkpointer, no SSE) and returns the plan + validation status. Used
    by Chat Mode when the user explicitly asks "先給我看 plan" — the
    chat LLM narrates the plan to the user, and a follow-up call (with
    show_plan=False) does the actual build.

    No canvas mutation. No tool calls. Two LLM calls max (plan + maybe
    one repair_plan if validation fails on first pass).
    """
    from python_ai_sidecar.agent_builder.graph_build.nodes.plan import plan_node
    from python_ai_sidecar.agent_builder.graph_build.nodes.validate import validate_plan_node
    from python_ai_sidecar.agent_builder.graph_build.nodes.repair_plan import (
        repair_plan_node, MAX_PLAN_REPAIR,
    )

    state = initial_state(
        session_id="dry_run_" + uuid.uuid4().hex[:8],
        instruction=instruction,
        base_pipeline=base_pipeline,
        skip_confirm=True,  # irrelevant — we never reach confirm_gate
    )

    plan_update = await plan_node(state)
    state.update(plan_update)  # type: ignore[arg-type]

    val_update = await validate_plan_node(state)
    state.update(val_update)  # type: ignore[arg-type]
    errors: list[str] = list(state.get("plan_validation_errors") or [])

    # One repair shot in dry-run — same budget as full graph.
    if errors and len(state.get("plan") or []) > 0:
        repair_update = await repair_plan_node(state)
        state.update(repair_update)  # type: ignore[arg-type]
        if state.get("plan"):
            val2 = await validate_plan_node(state)
            state.update(val2)  # type: ignore[arg-type]
            errors = list(state.get("plan_validation_errors") or [])

    plan = state.get("plan") or []
    return {
        "plan": plan,
        "summary": state.get("summary") or "",
        "validation_errors": errors,
        "n_ops": len(plan),
        "ok": len(errors) == 0 and len(plan) > 0,
    }


async def translate_skill_step(
    *,
    instruction: str,
    base_pipeline: Optional[dict] = None,
) -> dict[str, Any]:
    """Phase 11 — sync (block-until-done) translator for a Skill step's
    natural-language description into a pipeline ending in block_step_check.

    Drives the same graph_build engine as Builder/Chat but with
    skill_step_mode=True (validate enforces step_check terminator) and
    skip_confirm=True (no confirm gate; this is a direct API call from
    Java's POST /skill-documents/{slug}/steps).

    Returns:
      {pipeline_json, summary, expected_outputs, status, error_message}
    """
    final_pipeline: Optional[dict] = None
    summary: Optional[str] = None
    expected: list[str] = []
    status: str = "running"
    last_error: Optional[str] = None

    async for ev in stream_graph_build(
        instruction=instruction,
        base_pipeline=base_pipeline,
        skip_confirm=True,
        skill_step_mode=True,
    ):
        if ev.type == "plan_proposed":
            summary = (ev.data or {}).get("summary") or summary
            outs = (ev.data or {}).get("expected_outputs") or []
            if isinstance(outs, list):
                expected = [str(o) for o in outs]
        elif ev.type == "build_finalized":
            data = ev.data or {}
            status = "success" if data.get("ok") else "failed"
            summary = (data.get("summary") or summary) or summary
        elif ev.type == "done":
            data = ev.data or {}
            final_pipeline = data.get("pipeline_json") or final_pipeline
            status = data.get("status") or status
            summary = (data.get("summary") or summary) or summary
        elif ev.type == "error":
            last_error = (ev.data or {}).get("message") or last_error

    return {
        "status": status,
        "pipeline_json": final_pipeline,
        "summary": summary or "",
        "expected_outputs": expected,
        "error_message": last_error,
    }


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
