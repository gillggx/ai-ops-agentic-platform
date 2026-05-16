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


def _flush_sse_events(state_after: dict, offset: int) -> tuple[list[StreamEvent], int]:
    """Yield only events appended to sse_events since the last flush.

    state.sse_events is extend-only (see _extend_sse in state.py). Without
    an offset, every astream tick re-yields the full buffer — the same
    "加入 node X" event surfaces twice as the graph passes through nodes
    that don't return sse_events (e.g. advance_macro_step).
    """
    events = state_after.get("sse_events") or []
    new_events = events[offset:]
    out = [StreamEvent(type=ev.get("event", "operation"), data=ev.get("data") or {})
           for ev in new_events]
    return out, len(events)


async def stream_graph_build(
    *,
    instruction: str,
    base_pipeline: Optional[dict] = None,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    skip_confirm: bool = False,
    skill_step_mode: bool = False,
    trigger_payload: Optional[dict] = None,
    v30_mode: bool = False,
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
    config = {"configurable": {"thread_id": sid}, "recursion_limit": 300}

    init = initial_state(
        session_id=sid,
        instruction=instruction,
        base_pipeline=base_pipeline,
        user_id=user_id,
        skip_confirm=skip_confirm,
        skill_step_mode=skill_step_mode,
        trigger_payload=trigger_payload,
    )
    if v30_mode:
        init["v30_mode"] = True
        logger.info("stream_graph_build: v30_mode enabled — using ReAct path")
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
    paused_kind: Optional[str] = None
    paused_payload: dict = {}

    if tracer is not None:
        await tracer.__aenter__()
    try:
        # Stream node-by-node updates. astream(stream_mode="values") yields
        # the full state after each node finishes, which lets us flush
        # sse_events incrementally. interrupt() shows up as a special
        # __interrupt__ entry.
        sse_offset = 0
        async for chunk in graph.astream(init, config=config, stream_mode="values"):
            last_state = chunk if isinstance(chunk, dict) else {}
            new_events, sse_offset = _flush_sse_events(last_state, sse_offset)
            for ev in new_events:
                yield ev

        # Detect pause-state INSIDE the try so tracer can record the
        # actual reason ("confirm_pending" / "clarify_required") before
        # __aexit__ defaults the status. Without this the trace shows
        # status:null for paused builds — admin viewer can't tell paused
        # from unknown-failure.
        try:
            _state_obj_pre = await graph.aget_state(config)
            if _state_obj_pre.next:
                interrupted = True
                try:
                    paused_payload = (
                        _state_obj_pre.tasks[0].interrupts[0].value
                        if _state_obj_pre.tasks else {}
                    )
                except Exception:  # noqa: BLE001
                    paused_payload = {}
                paused_kind = (
                    paused_payload.get("kind")
                    if isinstance(paused_payload, dict) else None
                )
                if tracer is not None:
                    pause_status = paused_kind if paused_kind in ("clarify_required", "intent_confirm_required", "goal_plan_confirm_required", "handover_pending") else "confirm_pending"
                    tracer.set_status(pause_status)
                    tracer.record_step(
                        "graph_paused",
                        status=pause_status,
                        kind=paused_kind or "confirm_pending",
                        questions=paused_payload.get("clarifications") if isinstance(paused_payload, dict) else None,
                    )
        except Exception as _ex:  # noqa: BLE001
            logger.warning("stream_graph_build: pause detection failed: %s", _ex)
    finally:
        if tracer is not None:
            tracer.set_final_pipeline(
                last_state.get("final_pipeline") or last_state.get("base_pipeline")
            )
            # v18: push state.status into trace so refused/failed/finished
            # is recorded explicitly (don't let __aexit__ default it).
            terminal_status = last_state.get("status")
            if terminal_status and not interrupted:
                tracer.set_status(terminal_status)
            await tracer.__aexit__(None, None, None)

    # Re-emit pause as SSE event (reuse already-detected payload)
    if interrupted:
        event_type = paused_kind if paused_kind in ("clarify_required", "intent_confirm_required", "goal_plan_confirm_required", "handover_pending") else "confirm_pending"
        yield StreamEvent(
            type=event_type,
            data={
                "session_id": sid,
                **(paused_payload if isinstance(paused_payload, dict) else {}),
            },
        )
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
    """Resume a paused graph (post-confirm_gate) with user's decision.

    v18 (2026-05-14): attaches BuildTracer so the post-Apply compile
    journey (compile_chunk × N → dispatch_op → call_tool × N → finalize
    → dry_run) lands in /tmp/builder-traces. Without this the admin
    /admin/build-traces viewer only sees the paused trace (intent confirm
    + macro_plan) and can't see what was actually built.
    """
    graph = build_graph()
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 300}

    logger.info("resume_graph_build: session=%s confirmed=%s", session_id, confirmed)
    last_state: dict = {}
    paused_kind: Optional[str] = None
    paused_payload: dict = {}
    interrupted = False

    tracer = make_tracer(
        instruction=f"[resume:confirm session={session_id} confirmed={confirmed}]",
        session_id=session_id,
        skip_confirm=False,
        skill_step_mode=True,
        base_pipeline=None,
    )

    # Seed offset with the pre-existing sse_events length so we don't
    # re-yield events from before the resume.
    pre_state = await graph.aget_state(config)
    sse_offset = len((pre_state.values or {}).get("sse_events") or [])

    if tracer is not None:
        await tracer.__aenter__()
    try:
        async for chunk in graph.astream(
            Command(resume={"confirmed": confirmed}),
            config=config,
            stream_mode="values",
        ):
            last_state = chunk if isinstance(chunk, dict) else {}
            new_events, sse_offset = _flush_sse_events(last_state, sse_offset)
            for ev in new_events:
                yield ev

        # Pause-detection same pattern as the other resume function so the
        # admin viewer shows confirm_pending status in the trace instead of
        # a stale default.
        try:
            _state_obj_pre = await graph.aget_state(config)
            if _state_obj_pre.next:
                interrupted = True
                try:
                    paused_payload = (
                        _state_obj_pre.tasks[0].interrupts[0].value
                        if _state_obj_pre.tasks else {}
                    )
                except Exception:  # noqa: BLE001
                    paused_payload = {}
                paused_kind = (
                    paused_payload.get("kind")
                    if isinstance(paused_payload, dict) else None
                )
                if tracer is not None:
                    pause_status = paused_kind if paused_kind in ("clarify_required", "intent_confirm_required", "goal_plan_confirm_required", "handover_pending") else "confirm_pending"
                    tracer.set_status(pause_status)
                    tracer.record_step(
                        "graph_paused",
                        status=pause_status,
                        kind=paused_kind or "confirm_pending",
                    )
        except Exception as _ex:  # noqa: BLE001
            logger.warning("resume_graph_build: pause detection failed: %s", _ex)
    finally:
        if tracer is not None:
            tracer.set_final_pipeline(
                last_state.get("final_pipeline") or last_state.get("base_pipeline")
            )
            terminal_status = last_state.get("status")
            if terminal_status and not interrupted:
                tracer.set_status(terminal_status)
            await tracer.__aexit__(None, None, None)

    if interrupted:
        yield StreamEvent(
            type=(paused_kind if paused_kind in ("clarify_required", "intent_confirm_required", "goal_plan_confirm_required", "handover_pending") else "confirm_pending"),
            data={
                "session_id": session_id,
                **(paused_payload if isinstance(paused_payload, dict) else {}),
            },
        )
        return

    yield StreamEvent(
        type="done",
        data={
            "status": last_state.get("status") or ("finished" if confirmed else "cancelled"),
            "pipeline_json": last_state.get("final_pipeline") or last_state.get("base_pipeline"),
            "summary": last_state.get("summary"),
            "session_id": session_id,
        },
    )


async def resume_graph_build_with_modify(
    *,
    session_id: str,
    step_idx: int | None,
    request: str,
) -> AsyncGenerator[StreamEvent, None]:
    """v15 G2 — user reviewed the plan in confirm_gate and asked for a
    change ("改 Step 3 變成 trend chart"). Append the request to
    state.modify_requests, decline the confirm, force replan.

    Implementation note: confirm_gate's interrupt resumes with whatever we
    Command(resume=...) — if we resume with confirmed=False, the existing
    route_after_confirm sends to finalize. We instead need a path back to
    plan_node. The least invasive approach is to resume confirm_gate with
    a special marker that route_after_confirm interprets as "replan".
    """
    graph = build_graph()
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 300}

    logger.info(
        "resume_graph_build_with_modify: session=%s step_idx=%s request=%r",
        session_id, step_idx, request[:120],
    )
    last_state: dict = {}

    pre_state = await graph.aget_state(config)
    sse_offset = len((pre_state.values or {}).get("sse_events") or [])

    async for chunk in graph.astream(
        Command(resume={"modify": True, "step_idx": step_idx, "request": request}),
        config=config,
        stream_mode="values",
    ):
        last_state = chunk if isinstance(chunk, dict) else {}
        new_events, sse_offset = _flush_sse_events(last_state, sse_offset)
        for ev in new_events:
            yield ev

    state_obj = await graph.aget_state(config)
    if state_obj.next:
        try:
            interrupt_payload = (
                state_obj.tasks[0].interrupts[0].value if state_obj.tasks else {}
            )
        except Exception:  # noqa: BLE001
            interrupt_payload = {}
        kind = (interrupt_payload or {}).get("kind") if isinstance(interrupt_payload, dict) else None
        yield StreamEvent(
            type=(kind if kind in ("clarify_required", "intent_confirm_required", "goal_plan_confirm_required", "handover_pending") else "confirm_pending"),
            data={
                "session_id": session_id,
                **(interrupt_payload if isinstance(interrupt_payload, dict) else {}),
            },
        )
        return

    yield StreamEvent(
        type="done",
        data={
            "status": last_state.get("status") or "finished",
            "pipeline_json": last_state.get("final_pipeline") or last_state.get("base_pipeline"),
            "summary": last_state.get("summary"),
            "session_id": session_id,
        },
    )


async def resume_graph_build_with_clarify(
    *,
    session_id: str,
    answers: dict[str, str],
) -> AsyncGenerator[StreamEvent, None]:
    """Resume a graph paused at clarify_intent_node, providing the user's
    answers to the clarification questions. The graph continues into
    plan_node (or pauses again at confirm_gate as the normal flow)."""
    graph = build_graph()
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 300}

    logger.info("resume_graph_build_with_clarify: session=%s answers=%s",
                session_id, list(answers.keys()))

    # 2026-05-13: enable BuildTracer for the resume path too. Without
    # this, plan_node + validate + repair + finalize all run during
    # resume but no trace is written, leaving v15 builds opaque for
    # debugging. Same opt-in flag (BUILDER_TRACE_DIR) as the entry
    # stream_graph_build call.
    tracer = make_tracer(
        instruction=f"[resume:clarify session={session_id}]",
        session_id=session_id,
        skip_confirm=False,
        skill_step_mode=True,
        base_pipeline=None,
    )

    last_state: dict = {}
    paused_kind: Optional[str] = None
    paused_payload: dict = {}
    interrupted = False

    if tracer is not None:
        await tracer.__aenter__()
    try:
        pre_state = await graph.aget_state(config)
        sse_offset = len((pre_state.values or {}).get("sse_events") or [])
        # v19 (2026-05-14): pass-through the answers dict directly so the
        # caller can send EITHER `{answers: {qid: value}}` (legacy MCQ)
        # OR `{confirmations: {bid: {action, edit_text}}}` (intent bullets).
        # Previously we wrapped as `{"answers": answers}` which broke the
        # bullets path because clarify_intent_node looks for top-level
        # `confirmations` key, not nested under `answers`.
        async for chunk in graph.astream(
            Command(resume=answers),
            config=config,
            stream_mode="values",
        ):
            last_state = chunk if isinstance(chunk, dict) else {}
            new_events, sse_offset = _flush_sse_events(last_state, sse_offset)
            for ev in new_events:
                yield ev

        # Same pause-detection pattern as stream_graph_build — record the
        # confirm_pending state into the tracer so the admin viewer shows
        # the actual reason instead of status:null.
        try:
            _state_obj_pre = await graph.aget_state(config)
            if _state_obj_pre.next:
                interrupted = True
                try:
                    paused_payload = (
                        _state_obj_pre.tasks[0].interrupts[0].value
                        if _state_obj_pre.tasks else {}
                    )
                except Exception:  # noqa: BLE001
                    paused_payload = {}
                paused_kind = (
                    paused_payload.get("kind")
                    if isinstance(paused_payload, dict) else None
                )
                if tracer is not None:
                    pause_status = paused_kind if paused_kind in ("clarify_required", "intent_confirm_required", "goal_plan_confirm_required", "handover_pending") else "confirm_pending"
                    tracer.set_status(pause_status)
                    tracer.record_step(
                        "graph_paused",
                        status=pause_status,
                        kind=paused_kind or "confirm_pending",
                    )
        except Exception as _ex:  # noqa: BLE001
            logger.warning("resume_graph_build_with_clarify: pause detection failed: %s", _ex)
    finally:
        if tracer is not None:
            tracer.set_final_pipeline(
                last_state.get("final_pipeline") or last_state.get("base_pipeline")
            )
            terminal_status = last_state.get("status")
            if terminal_status and not interrupted:
                tracer.set_status(terminal_status)
            await tracer.__aexit__(None, None, None)

    if interrupted:
        yield StreamEvent(
            type=(paused_kind if paused_kind in ("clarify_required", "intent_confirm_required", "goal_plan_confirm_required", "handover_pending") else "confirm_pending"),
            data={
                "session_id": session_id,
                **(paused_payload if isinstance(paused_payload, dict) else {}),
            },
        )
        return

    yield StreamEvent(
        type="done",
        data={
            "status": last_state.get("status") or "finished",
            "pipeline_json": last_state.get("final_pipeline") or last_state.get("base_pipeline"),
            "summary": last_state.get("summary"),
            "session_id": session_id,
        },
    )


# ── v30 generic resume helper ─────────────────────────────────────────────

async def resume_graph_v30(
    *,
    session_id: str,
    resume_payload: dict,
    trace_label: str,
) -> AsyncGenerator[StreamEvent, None]:
    """Resume a v30 graph paused at goal_plan_confirm_gate or halt_handover.

    Generic Command(resume=payload) wrapper — caller (endpoint) builds the
    right shape:
      - plan-confirm: {confirmed: bool, phases?: [...]}
      - handover:    {choice: str, new_goal?: str}
    """
    graph = build_graph()
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 300}

    logger.info("resume_graph_v30: session=%s label=%s payload_keys=%s",
                session_id, trace_label, list(resume_payload.keys()))

    tracer = make_tracer(
        instruction=f"[resume:{trace_label} session={session_id}]",
        session_id=session_id,
        skip_confirm=False,
        skill_step_mode=False,
        base_pipeline=None,
    )

    last_state: dict = {}
    paused_kind: Optional[str] = None
    paused_payload: dict = {}
    interrupted = False

    if tracer is not None:
        await tracer.__aenter__()
    try:
        pre_state = await graph.aget_state(config)
        sse_offset = len((pre_state.values or {}).get("sse_events") or [])
        async for chunk in graph.astream(
            Command(resume=resume_payload),
            config=config,
            stream_mode="values",
        ):
            last_state = chunk if isinstance(chunk, dict) else {}
            new_events, sse_offset = _flush_sse_events(last_state, sse_offset)
            for ev in new_events:
                yield ev

        try:
            _state_obj_pre = await graph.aget_state(config)
            if _state_obj_pre.next:
                interrupted = True
                try:
                    paused_payload = (
                        _state_obj_pre.tasks[0].interrupts[0].value
                        if _state_obj_pre.tasks else {}
                    )
                except Exception:  # noqa: BLE001
                    paused_payload = {}
                paused_kind = (
                    paused_payload.get("kind")
                    if isinstance(paused_payload, dict) else None
                )
                if tracer is not None:
                    pause_status = paused_kind if paused_kind in (
                        "clarify_required", "intent_confirm_required",
                        "goal_plan_confirm_required", "handover_pending",
                    ) else "confirm_pending"
                    tracer.set_status(pause_status)
                    tracer.record_step(
                        "graph_paused",
                        status=pause_status,
                        kind=paused_kind or "confirm_pending",
                    )
        except Exception as _ex:  # noqa: BLE001
            logger.warning("resume_graph_v30: pause detection failed: %s", _ex)
    finally:
        if tracer is not None:
            tracer.set_final_pipeline(
                last_state.get("final_pipeline") or last_state.get("base_pipeline")
            )
            terminal_status = last_state.get("status")
            if terminal_status and not interrupted:
                tracer.set_status(terminal_status)
            await tracer.__aexit__(None, None, None)

    if interrupted:
        yield StreamEvent(
            type=(paused_kind if paused_kind in (
                "clarify_required", "intent_confirm_required",
                "goal_plan_confirm_required", "handover_pending",
            ) else "confirm_pending"),
            data={
                "session_id": session_id,
                **(paused_payload if isinstance(paused_payload, dict) else {}),
            },
        )
        return

    yield StreamEvent(
        type="done",
        data={
            "status": last_state.get("status") or "finished",
            "pipeline_json": last_state.get("final_pipeline") or last_state.get("base_pipeline"),
            "summary": last_state.get("summary"),
            "session_id": session_id,
        },
    )
