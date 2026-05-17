"""Agent chat + Pipeline Builder Glass Box.

Phase 8-A-1d: chat goes through AgentOrchestratorV2 (LangGraph) natively.
DB-coupled nodes were rewired to JavaAPIClient + ported pure-compute helpers
under ``agent_helpers_native/``; the sidecar no longer needs an AsyncSession.

The old fallback path (proxy → :8001) is retained behind ``FALLBACK_ENABLED=1``
purely as an emergency rollback switch — production should run with it ``0``.
Phase 8-D drops the fallback proxy outright + decommissions :8001.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional
from typing import AsyncGenerator

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from ..auth import CallerContext, ServiceAuth
from ..clients.java_client import JavaAPIClient
from ..config import CONFIG

log = logging.getLogger("python_ai_sidecar.agent_router")
router = APIRouter(prefix="/internal/agent", tags=["agent"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(..., min_length=1)
    session_id: str | None = Field(default=None, alias="sessionId")
    # Part B (SPEC_context_engineering): client-side state hint for the agent.
    # Currently carries `selected_equipment_id` from AppContext.selectedEquipment;
    # may grow with `current_page`, `last_viewed_alarm_id`, etc.
    client_context: dict | None = Field(default=None, alias="clientContext")
    # Phase E2: "chat" (default) or "builder". When "builder", the agent
    # biases toward aggressive build_pipeline_live invocation because the
    # caller is on the Pipeline Builder canvas and pipeline modification
    # is the default intent. Sent by AIAgentPanel when mounted inside
    # BuilderLayout (via E3 wiring).
    mode: str | None = Field(default=None)
    # Phase E3 follow-up: when AIAgentPanel runs in builder context, the
    # current canvas pipeline_json (with its declared inputs) flows here so
    # the orchestrator can surface "Pipeline 已宣告的 inputs" in the user
    # opening message — same context the Glass Box subsession used to get
    # via /agent/build's pipelineSnapshot param.
    pipeline_snapshot: dict | None = Field(default=None, alias="pipelineSnapshot")


class BuildRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    instruction: str = Field(..., min_length=1)
    pipeline_id: int | None = Field(default=None, alias="pipelineId")
    pipeline_snapshot: dict | None = Field(default=None, alias="pipelineSnapshot")
    # 2026-05-12: explicit flag so the skill-step terminal + anti-alert
    # validators fire when caller is building a Skill step pipeline.
    # Frontend embed=skill flow + chat orchestrator's build_pipeline_live
    # both set this true; standalone Pipeline Builder builds keep default.
    skill_step_mode: bool = Field(default=False, alias="skillStepMode")
    # 2026-05-13: sample trigger payload (production /run input). When the
    # caller is building a Skill, this should mirror what the alarm/event
    # will actually fire — so finalize's dry-run exercises the same code
    # path production will, and inspect/reflect catches mismatches.
    trigger_payload: dict | None = Field(default=None, alias="triggerPayload")
    # v30 (2026-05-16): opt-in to ReAct goal-oriented pipeline builder.
    # When true, graph entry routes through goal_plan_node + agentic_phase_loop
    # instead of v27 macro_plan + compile_chunk.
    # v30.14 (2026-05-17): default flipped True. All 3 surfaces (chat,
    # builder, skill GUI) now share the v30 path. Emergency revert via env
    # AGENT_BUILD_V30=0 on sidecar. Explicit `false` here still opts out
    # per-request if a client needs to compare paths.
    v30_mode: bool = Field(default=True, alias="v30Mode")
    # v30.7 (2026-05-16): debug step-mode. When true, agentic_phase_loop
    # pauses after each round (via step_pause_gate), emitting full prompt +
    # response + state for debugging. Resume with /build/step-continue.
    debug_step_mode: bool = Field(default=False, alias="debugStepMode")


async def _chat_stream_native(req: ChatRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    """Phase 8-A-1d: native LangGraph orchestrator.

    The orchestrator uses ``db=None`` and routes every state read/write
    through JavaAPIClient + the ported pure-compute helpers.
    """
    from ..agent_orchestrator_v2.orchestrator import AgentOrchestratorV2

    orchestrator = AgentOrchestratorV2(
        db=None,
        base_url=CONFIG.java_api_url,
        auth_token=CONFIG.java_internal_token,
        user_id=caller.user_id or 0,
        roles=caller.roles,
    )
    async for v1_event in orchestrator.run(
        req.message,
        session_id=req.session_id,
        client_context=req.client_context,
        mode=req.mode or "chat",
        pipeline_snapshot=req.pipeline_snapshot,
    ):
        # AgentOrchestratorV2 yields v1-style {type, ...} dicts; convert to SSE
        ev_type = v1_event.get("type") or "message"
        yield {"event": ev_type, "data": json.dumps(v1_event, ensure_ascii=False)}


async def _chat_stream(req: ChatRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    """Chat entry — always native via the in-process LangGraph orchestrator.

    The :8001 fallback proxy was retired in 2026-05-02 cleanup; the native
    orchestrator (rewired to Java client in Phase 8-A-1d) covers the full
    chat surface end-to-end.
    """
    async for ev in _chat_stream_native(req, caller):
        yield ev


async def _build_stream(req: BuildRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    """Phase 10-B: unified Glass Box build via graph_build (LangGraph).

    1. classify_advisor_intent → 6 buckets (BUILD vs Q&A advisor)
    2. BUILD → stream_graph_build (10-node graph; FROM_SCRATCH pauses on
       confirm_gate, frontend POSTs /build/confirm to resume)
    3. Q&A → stream_block_advisor (unchanged advisor sub-graph)

    The old v1 stream_agent_build (Anthropic 80-turn free tool-use loop)
    was retired in this commit. No more feature flag — graph is the only
    path.
    """
    import os
    from python_ai_sidecar.agent_builder.advisor import (
        classify_advisor_intent, stream_block_advisor,
    )
    from python_ai_sidecar.agent_builder.graph_build import stream_graph_build
    from python_ai_sidecar.clients.java_client import JavaAPIClient

    if not os.environ.get("ANTHROPIC_API_KEY"):
        yield {"event": "error", "data": json.dumps({
            "message": "ANTHROPIC_API_KEY not set on sidecar — /agent/build unavailable",
        })}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}
        return

    try:
        intent, conf, reason = await classify_advisor_intent(req.instruction)
        log.info("build: intent=%s conf=%.2f reason=%r", intent, conf, reason)

        if intent != "BUILD":
            java = JavaAPIClient.for_caller(caller)
            async for stream_event in stream_block_advisor(req.instruction, intent, java=java):
                yield {
                    "event": stream_event.type,
                    "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
                }
            return

        async for stream_event in stream_graph_build(
            instruction=req.instruction,
            base_pipeline=req.pipeline_snapshot,
            user_id=caller.user_id,
            skill_step_mode=req.skill_step_mode,
            skip_confirm=False,  # Builder Mode shows the Apply/Cancel card
            trigger_payload=req.trigger_payload,
            v30_mode=req.v30_mode,  # v30 opt-in
            debug_step_mode=req.debug_step_mode,  # v30.7 step-mode pause
        ):
            yield {
                "event": stream_event.type,
                "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
            }
    except Exception as ex:  # noqa: BLE001
        log.exception("build failed")
        yield {"event": "error", "data": json.dumps({
            "message": f"build failed: {ex.__class__.__name__}: {str(ex)[:200]}",
        })}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/chat")
async def agent_chat(req: ChatRequest, caller: CallerContext = ServiceAuth) -> EventSourceResponse:
    return EventSourceResponse(_chat_stream(req, caller))


# ── v19 (2026-05-14): chat intent confirmation resume endpoint ──────


class ChatIntentRespondRequest(BaseModel):
    """v19: when chat user confirms intent bullets via BulletConfirmCard,
    frontend POSTs this. We look up the pending build session, resume
    via resume_graph_build_with_clarify, and stream the build progress
    back. No LLM continuation in v1 — the chat agent's pre-pause text
    reply ('我先確認...') stays; this resume just builds + returns the
    pipeline result as an SSE stream that frontend renders into a new
    synthesized assistant message.
    """
    model_config = ConfigDict(populate_by_name=True)

    chat_session_id: str = Field(..., alias="chatSessionId")
    confirmations: dict[str, dict] = Field(default_factory=dict)
    # v30.17j — when set, the endpoint resumes a judge_clarify pause
    # instead of an intent_confirm pause. Mutually exclusive with
    # confirmations (frontend picks one based on which card was shown).
    # Shape: {"phase_id": "p1", "action": "continue"|"replan"|"cancel"}
    judge_decision: Optional[dict] = None


async def _emit_pipeline_charts(
    pipeline_json: dict, session_id: str,
) -> AsyncGenerator[dict, None]:
    """v19 (2026-05-14): run the built pipeline once and emit:
      1. pb_run_start  — so chat LiteCanvasOverlay flips to running phase
      2. pb_run_done   — so LiteCanvasOverlay's 「結果」tab populates
                         (carries node_results + result_summary)
      3. pb_glass_chart — per chart_spec snapshot, for chat-history inline rendering

    Without (1)(2), chat mode's left-side Lite Canvas 結果 tab stays empty;
    user sees the build node but no chart on the canvas side.
    """
    try:
        from python_ai_sidecar.executor.real_executor import get_real_executor
        from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON

        executor = get_real_executor()
        pj_model = PipelineJSON.model_validate(pipeline_json)
        n_nodes = len((pipeline_json.get("nodes") or [])) if isinstance(pipeline_json, dict) else 0

        # Phase 1: pb_run_start
        start_payload = {
            "type": "pb_run_start",
            "session_id": session_id,
            "node_count": n_nodes,
        }
        yield {
            "event": "pb_run_start",
            "data": json.dumps(start_payload, default=str, ensure_ascii=False),
        }

        import time as _time
        t0 = _time.perf_counter()
        try:
            result = await asyncio.wait_for(
                executor.execute(pj_model, inputs={}),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            err_payload = {
                "type": "pb_run_error",
                "session_id": session_id,
                "error_message": "auto-run timed out after 30s",
            }
            yield {
                "event": "pb_run_error",
                "data": json.dumps(err_payload, default=str, ensure_ascii=False),
            }
            return
        duration_ms = int((_time.perf_counter() - t0) * 1000)

        node_results = (result or {}).get("node_results") or {}
        result_summary = (result or {}).get("result_summary") or {}

        # Phase 2: emit per-chart pb_glass_chart events first (chat history)
        n_charts = 0
        for nid, info in node_results.items():
            if not isinstance(info, dict):
                continue
            ports = info.get("preview") or {}
            for port_name, blob in ports.items():
                if not isinstance(blob, dict):
                    continue
                snap = blob.get("snapshot")
                if (
                    isinstance(snap, dict)
                    and isinstance(snap.get("data"), list)
                    and isinstance(snap.get("type"), str)
                ):
                    payload = {
                        "type": "pb_glass_chart",
                        "session_id": session_id,
                        "node_id": nid,
                        "port": port_name,
                        "chart_spec": snap,
                    }
                    yield {
                        "event": "pb_glass_chart",
                        "data": json.dumps(payload, default=str, ensure_ascii=False),
                    }
                    n_charts += 1

        # Phase 3: pb_run_done — Lite Canvas 結果 tab populates from this
        done_payload = {
            "type": "pb_run_done",
            "session_id": session_id,
            "duration_ms": duration_ms,
            "node_results": node_results,
            "result_summary": result_summary,
        }
        yield {
            "event": "pb_run_done",
            "data": json.dumps(done_payload, default=str, ensure_ascii=False),
        }

        log.info(
            "chat/intent-respond: emitted pb_run_start/done + %d chart(s) "
            "(%dms, %d nodes) session=%s",
            n_charts, duration_ms, n_nodes, session_id,
        )
    except asyncio.TimeoutError:
        log.warning("emit_pipeline_charts: executor timed out")
    except Exception as ex:  # noqa: BLE001
        log.warning("emit_pipeline_charts failed: %s", ex)


async def _chat_intent_respond_stream(
    req: ChatIntentRespondRequest,
    caller: CallerContext,
) -> AsyncGenerator[dict, None]:
    from python_ai_sidecar.agent_orchestrator_v2 import pending_clarify as _pc
    from python_ai_sidecar.agent_orchestrator_v2 import pending_judge as _pj
    from python_ai_sidecar.agent_builder.graph_build.runner import (
        resume_graph_build_with_clarify,
        resume_graph_build_with_judge_decision,
    )
    from python_ai_sidecar.agent_builder.event_wrapper import wrap_build_event_for_chat

    # v30.17j — judge_decision branch takes priority over confirmations
    # (frontend sends one or the other based on which card was shown).
    if req.judge_decision is not None:
        judge_pending = _pj.consume(req.chat_session_id)
        if judge_pending is None:
            yield {"event": "error", "data": json.dumps({
                "message": "no pending judge clarification for this chat session",
            })}
            yield {"event": "done", "data": json.dumps({"status": "no_pending"})}
            return
        action = str(req.judge_decision.get("action") or "cancel").lower()
        log.info(
            "chat/intent-respond: judge resume chat_session=%s build_session=%s "
            "phase=%s action=%s",
            req.chat_session_id, judge_pending.build_session_id,
            judge_pending.phase_id, action,
        )
        final_pipeline_for_exec: Optional[dict] = None
        try:
            async for stream_event in resume_graph_build_with_judge_decision(
                session_id=judge_pending.build_session_id,
                phase_id=judge_pending.phase_id,
                action=action,
            ):
                # v30.17j (2026-05-17 hotfix): if the resume hits ANOTHER
                # judge pause (e.g. user picked replan and the new plan
                # ALSO triggers deficit), re-register pending_judge so the
                # next /chat/intent-respond click can find it. Without
                # this the 2nd card freezes silently.
                if stream_event.type == "judge_clarify_pending":
                    sd = stream_event.data or {}
                    try:
                        _pj.register(_pj.PendingJudge(
                            chat_session_id=req.chat_session_id,
                            build_session_id=str(sd.get("session_id")
                                                 or judge_pending.build_session_id),
                            phase_id=str(sd.get("phase_id") or "?"),
                            requested_n=int(sd.get("requested_n") or 0),
                            actual_rows=int(sd.get("actual_rows") or 0),
                            value_desc=str(sd.get("value_desc") or ""),
                            block_id=str(sd.get("block_id") or ""),
                            instruction=judge_pending.instruction,
                            base_pipeline=judge_pending.base_pipeline,
                            skill_step_mode=judge_pending.skill_step_mode,
                            user_id=judge_pending.user_id,
                        ))
                        log.info(
                            "chat/intent-respond: re-registered pending_judge "
                            "(2nd pause) for chat_session=%s phase=%s",
                            req.chat_session_id, sd.get("phase_id"),
                        )
                    except Exception as ex:  # noqa: BLE001
                        log.warning("re-register pending_judge failed: %s", ex)
                    # Also explicitly emit pb_judge_clarify so the frontend
                    # receives the card prompt (the sse_events path in
                    # phase_verifier already emits via _flush_sse_events, but
                    # the pause envelope itself doesn't carry the prompt).
                    yield {
                        "event": "pb_judge_clarify",
                        "data": json.dumps({
                            "type": "pb_judge_clarify",
                            "session_id": req.chat_session_id,
                            "build_session_id": sd.get("session_id"),
                            "phase_id": sd.get("phase_id"),
                            "requested_n": sd.get("requested_n"),
                            "actual_rows": sd.get("actual_rows"),
                            "ratio": sd.get("ratio"),
                            "value_desc": sd.get("value_desc"),
                            "block_id": sd.get("block_id"),
                        }, default=str, ensure_ascii=False),
                    }
                    continue

                wrapped = wrap_build_event_for_chat(
                    stream_event, judge_pending.build_session_id,
                )
                if wrapped is not None:
                    ev_type = wrapped.get("type") or "message"
                    yield {
                        "event": ev_type,
                        "data": json.dumps(wrapped, default=str, ensure_ascii=False),
                    }
                elif stream_event.type == "done":
                    yield {
                        "event": "done",
                        "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
                    }
                if stream_event.type == "done" and stream_event.data:
                    pj = stream_event.data.get("pipeline_json")
                    if isinstance(pj, dict):
                        final_pipeline_for_exec = pj
            if final_pipeline_for_exec is not None:
                async for chart_ev in _emit_pipeline_charts(
                    final_pipeline_for_exec, judge_pending.build_session_id,
                ):
                    yield chart_ev
        except Exception as ex:  # noqa: BLE001
            log.exception("chat/intent-respond judge resume failed")
            yield {"event": "error", "data": json.dumps({
                "message": f"judge resume failed: {ex.__class__.__name__}: {str(ex)[:200]}",
            }, ensure_ascii=False)}
            yield {"event": "done", "data": json.dumps({"status": "failed"})}
        return

    # Existing intent_confirm path
    pending = _pc.consume(req.chat_session_id)
    if pending is None:
        yield {"event": "error", "data": json.dumps({
            "message": "no pending intent clarification for this chat session",
        })}
        yield {"event": "done", "data": json.dumps({"status": "no_pending"})}
        return

    log.info(
        "chat/intent-respond: chat_session=%s build_session=%s n_confirmations=%d",
        req.chat_session_id, pending.build_session_id, len(req.confirmations),
    )

    # Convert confirmations to format clarify_intent_node expects
    answers_payload = {"confirmations": req.confirmations}

    final_pipeline_for_exec: Optional[dict] = None
    try:
        async for stream_event in resume_graph_build_with_clarify(
            session_id=pending.build_session_id,
            answers=answers_payload,
        ):
            # v19: translate raw build StreamEvent → pb_glass_* shape so the
            # AIAgentPanel SSE handler (same one /chat uses) renders ops +
            # applies them to the canvas. Caller drains via the SAME chat
            # handleStreamEvent — no need to also yield raw events (that
            # would cause duplicate processing).
            wrapped = wrap_build_event_for_chat(stream_event, pending.build_session_id)
            if wrapped is not None:
                ev_type = wrapped.get("type") or "message"
                yield {
                    "event": ev_type,
                    "data": json.dumps(wrapped, default=str, ensure_ascii=False),
                }
            elif stream_event.type == "done":
                yield {
                    "event": "done",
                    "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
                }
            # Capture final_pipeline for post-build chart rendering.
            if stream_event.type == "done" and stream_event.data:
                pj = stream_event.data.get("pipeline_json")
                if isinstance(pj, dict):
                    final_pipeline_for_exec = pj

        # v19 post-build chart emit: after build done, run the pipeline
        # once and emit chart_spec snapshots so chat shows the actual
        # output inline (not just '✓ done' text). User feedback: chat
        # mode build appeared to "fail" because no chart was rendered.
        if final_pipeline_for_exec is not None:
            async for chart_ev in _emit_pipeline_charts(
                final_pipeline_for_exec, pending.build_session_id,
            ):
                yield chart_ev
    except Exception as ex:  # noqa: BLE001
        log.exception("chat/intent-respond resume failed")
        yield {"event": "error", "data": json.dumps({
            "message": f"resume failed: {ex.__class__.__name__}: {str(ex)[:200]}",
        }, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/chat/intent-respond")
async def agent_chat_intent_respond(
    req: ChatIntentRespondRequest, caller: CallerContext = ServiceAuth,
) -> EventSourceResponse:
    """v19 chat intent confirmation resume."""
    return EventSourceResponse(_chat_intent_respond_stream(req, caller))


@router.post("/build")
async def agent_build(req: BuildRequest, caller: CallerContext = ServiceAuth) -> EventSourceResponse:
    return EventSourceResponse(_build_stream(req, caller))


# ── Phase 10: graph_build confirm endpoint (resume after confirm_gate) ────


class BuildConfirmRequest(BaseModel):
    """Phase 10-B: resume a paused graph_build session after confirm_pending.

    Only fires for Builder Mode FROM_SCRATCH builds. Chat Mode passes
    skip_confirm=True so confirm_gate never fires there.
    """
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    confirmed: bool = Field(...)


async def _build_confirm_stream(
    req: BuildConfirmRequest, caller: CallerContext,
) -> AsyncGenerator[dict, None]:
    from python_ai_sidecar.agent_builder.graph_build import resume_graph_build

    try:
        async for stream_event in resume_graph_build(
            session_id=req.session_id, confirmed=req.confirmed,
        ):
            yield {
                "event": stream_event.type,
                "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
            }
    except Exception as ex:  # noqa: BLE001
        log.exception("build/confirm failed for session=%s", req.session_id)
        yield {"event": "error", "data": json.dumps({
            "message": f"build/confirm failed: {ex.__class__.__name__}: {str(ex)[:200]}",
            "session_id": req.session_id,
        }, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/build/confirm")
async def agent_build_confirm(
    req: BuildConfirmRequest, caller: CallerContext = ServiceAuth,
) -> EventSourceResponse:
    """Resume a graph_build session paused at confirm_gate. Only used when
    AGENT_BUILD_GRAPH=v2 — v1 doesn't have this gate."""
    return EventSourceResponse(_build_confirm_stream(req, caller))


# ── v15 G1: clarify-respond endpoint ──────────────────────────────────────


class BuildClarifyRespondRequest(BaseModel):
    """v15 — resume a paused graph from clarify_intent_node with user's
    answers. v18: also accepts intent bullets confirmations.

    Frontend POSTs ONE of these formats (or both for backwards-compat):
      - `answers: {qid: value}` — legacy MCQ format
      - `confirmations: {bid: {action, edit_text}}` — v18 intent bullets
    """
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    answers: dict[str, str] = Field(default_factory=dict)
    confirmations: dict[str, dict] = Field(default_factory=dict)


async def _build_clarify_stream(
    req: BuildClarifyRespondRequest, caller: CallerContext,
) -> AsyncGenerator[dict, None]:
    from python_ai_sidecar.agent_builder.graph_build.runner import (
        resume_graph_build_with_clarify,
    )

    # v19: runner now passes the dict directly to Command(resume=...),
    # so build the right shape here. Support both legacy MCQ answers
    # and intent confirmations in the same payload.
    resume_payload: dict = {}
    if req.answers:
        resume_payload["answers"] = req.answers
    if req.confirmations:
        resume_payload["confirmations"] = req.confirmations

    try:
        async for stream_event in resume_graph_build_with_clarify(
            session_id=req.session_id, answers=resume_payload,
        ):
            yield {
                "event": stream_event.type,
                "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
            }
    except Exception as ex:  # noqa: BLE001
        log.exception("build/clarify-respond failed for session=%s", req.session_id)
        yield {"event": "error", "data": json.dumps({
            "message": f"clarify-respond failed: {ex.__class__.__name__}: {str(ex)[:200]}",
            "session_id": req.session_id,
        }, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/build/clarify-respond")
async def agent_build_clarify_respond(
    req: BuildClarifyRespondRequest, caller: CallerContext = ServiceAuth,
) -> EventSourceResponse:
    """Resume a paused graph at clarify_intent_node with user's answers."""
    return EventSourceResponse(_build_clarify_stream(req, caller))


# ── v30 ReAct: plan-confirm + handover endpoints ────────────────────────


class BuildPlanConfirmRequest(BaseModel):
    """v30 — resume after goal_plan_confirm_gate.

    Frontend POSTs:
      {sessionId, confirmed: true, phases?: [...]}   (optionally edited)
      {sessionId, confirmed: false}                  (cancel build)
    """
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    confirmed: bool = Field(...)
    phases: list[dict] = Field(default_factory=list)


async def _build_plan_confirm_stream(
    req: BuildPlanConfirmRequest, caller: CallerContext,
) -> AsyncGenerator[dict, None]:
    from python_ai_sidecar.agent_builder.graph_build.runner import resume_graph_v30
    payload: dict = {"confirmed": req.confirmed}
    if req.phases:
        payload["phases"] = req.phases
    try:
        async for stream_event in resume_graph_v30(
            session_id=req.session_id, resume_payload=payload,
            trace_label="plan-confirm",
        ):
            yield {
                "event": stream_event.type,
                "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
            }
    except Exception as ex:  # noqa: BLE001
        log.exception("build/plan-confirm failed for session=%s", req.session_id)
        yield {"event": "error", "data": json.dumps({
            "message": f"plan-confirm failed: {ex.__class__.__name__}: {str(ex)[:200]}",
            "session_id": req.session_id,
        }, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/build/plan-confirm")
async def agent_build_plan_confirm(
    req: BuildPlanConfirmRequest, caller: CallerContext = ServiceAuth,
) -> EventSourceResponse:
    """v30 — resume after user confirms / edits the goal plan phases."""
    return EventSourceResponse(_build_plan_confirm_stream(req, caller))


class BuildHandoverRequest(BaseModel):
    """v30 — resume after halt_handover. User picks one of 4 choices:
      edit_goal | take_over | backlog | abort
    edit_goal also supplies a new_goal string for the failed phase.
    """
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    choice: str = Field(...)
    new_goal: str = Field(default="", alias="newGoal")


async def _build_handover_stream(
    req: BuildHandoverRequest, caller: CallerContext,
) -> AsyncGenerator[dict, None]:
    from python_ai_sidecar.agent_builder.graph_build.runner import resume_graph_v30
    payload: dict = {"choice": req.choice}
    if req.new_goal:
        payload["new_goal"] = req.new_goal
    try:
        async for stream_event in resume_graph_v30(
            session_id=req.session_id, resume_payload=payload,
            trace_label="handover",
        ):
            yield {
                "event": stream_event.type,
                "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
            }
    except Exception as ex:  # noqa: BLE001
        log.exception("build/handover failed for session=%s", req.session_id)
        yield {"event": "error", "data": json.dumps({
            "message": f"handover failed: {ex.__class__.__name__}: {str(ex)[:200]}",
            "session_id": req.session_id,
        }, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/build/handover")
async def agent_build_handover(
    req: BuildHandoverRequest, caller: CallerContext = ServiceAuth,
) -> EventSourceResponse:
    """v30 — resume after user picks handover option."""
    return EventSourceResponse(_build_handover_stream(req, caller))


class BuildStepContinueRequest(BaseModel):
    """v30.7 — resume after step_pause_gate (debug step-mode pause).

    Frontend / driver POSTs:
      {sessionId, action: "continue"}  → resume to next round
      {sessionId, action: "abort"}     → cancel build, route to finalize
    """
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    action: str = Field(default="continue")


async def _build_step_continue_stream(
    req: BuildStepContinueRequest, caller: CallerContext,
) -> AsyncGenerator[dict, None]:
    from python_ai_sidecar.agent_builder.graph_build.runner import resume_graph_v30
    payload: dict = {"action": req.action}
    try:
        async for stream_event in resume_graph_v30(
            session_id=req.session_id, resume_payload=payload,
            trace_label="step-continue",
        ):
            yield {
                "event": stream_event.type,
                "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
            }
    except Exception as ex:  # noqa: BLE001
        log.exception("build/step-continue failed for session=%s", req.session_id)
        yield {"event": "error", "data": json.dumps({
            "message": f"step-continue failed: {ex.__class__.__name__}: {str(ex)[:200]}",
            "session_id": req.session_id,
        }, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/build/step-continue")
async def agent_build_step_continue(
    req: BuildStepContinueRequest, caller: CallerContext = ServiceAuth,
) -> EventSourceResponse:
    """v30.7 — resume after step_pause_gate (debug step-mode)."""
    return EventSourceResponse(_build_step_continue_stream(req, caller))


# ── v15 G2: modify-request endpoint ──────────────────────────────────────


class BuildModifyRequestRequest(BaseModel):
    """v15 G2 — user reviewed the plan at confirm_gate and wants a change
    (e.g. "改 Step 3 變成 trend chart"). plan_node re-runs with the
    request appended to state.modify_requests. Bounded by MAX_MODIFY_CYCLES.
    """
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    step_idx: int | None = Field(default=None, alias="stepIdx")
    request: str = Field(..., min_length=1, max_length=2000)


async def _build_modify_stream(
    req: BuildModifyRequestRequest, caller: CallerContext,
) -> AsyncGenerator[dict, None]:
    from python_ai_sidecar.agent_builder.graph_build.runner import (
        resume_graph_build_with_modify,
    )

    try:
        async for stream_event in resume_graph_build_with_modify(
            session_id=req.session_id, step_idx=req.step_idx, request=req.request,
        ):
            yield {
                "event": stream_event.type,
                "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
            }
    except Exception as ex:  # noqa: BLE001
        log.exception("build/modify-request failed for session=%s", req.session_id)
        yield {"event": "error", "data": json.dumps({
            "message": f"modify-request failed: {ex.__class__.__name__}: {str(ex)[:200]}",
            "session_id": req.session_id,
        }, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/build/modify-request")
async def agent_build_modify_request(
    req: BuildModifyRequestRequest, caller: CallerContext = ServiceAuth,
) -> EventSourceResponse:
    """Resume a paused graph at confirm_gate with user's modify request,
    routing back to plan_node for a re-plan."""
    return EventSourceResponse(_build_modify_stream(req, caller))


# ── Phase 11: Skill-step translation (sync) ──────────────────────────────


class SkillStepTranslateRequest(BaseModel):
    """Phase 11 — translate a Skill step's NL description into a pipeline
    ending in block_step_check. Java's POST /skill-documents/{slug}/steps
    calls this synchronously (block until done) and persists the resulting
    pipeline_json as a new pb_pipelines row.
    """
    model_config = ConfigDict(populate_by_name=True)

    text: str = Field(..., min_length=1, description="Natural language step description")
    base_pipeline: dict | None = Field(default=None, alias="basePipeline")


@router.post("/skill/translate-step")
async def skill_translate_step(
    req: SkillStepTranslateRequest, caller: CallerContext = ServiceAuth,
):
    """Sync skill-step translator — drives graph_build with skill_step_mode=True
    and skip_confirm=True, returns the final pipeline_json."""
    from python_ai_sidecar.agent_builder.graph_build import translate_skill_step
    result = await translate_skill_step(
        instruction=req.text,
        base_pipeline=req.base_pipeline,
    )
    return result


# ── Build trace viewer (read-only, for debugging build behavior) ──────
# Reads JSON traces written by BuildTracer when BUILDER_TRACE_DIR env
# is set. Lists most-recent-first; detail page renders graph steps +
# LLM calls + final pipeline. Not meant for production traffic; internal
# debugging only — same X-Service-Token guard as the rest of /internal.

import os as _os
from pathlib import Path as _Path
from fastapi.responses import HTMLResponse as _HTMLResponse, JSONResponse as _JSONResponse


def _trace_dir() -> _Path | None:
    raw = _os.getenv("BUILDER_TRACE_DIR", "").strip()
    if not raw:
        return None
    p = _Path(raw)
    return p if p.exists() else None


@router.get("/build/traces")
async def list_traces(caller: CallerContext = ServiceAuth):
    """Return list of recent build traces (newest first)."""
    d = _trace_dir()
    if not d:
        return _JSONResponse({"error": "BUILDER_TRACE_DIR not set or missing"}, status_code=503)
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]
    out = []
    for f in files:
        try:
            data = json.loads(f.read_text())
            out.append({
                "file": f.name,
                "build_id": data.get("build_id"),
                "session_id": data.get("session_id"),
                "started_at": data.get("started_at"),
                "duration_ms": data.get("duration_ms"),
                "status": data.get("status"),
                "instruction": (data.get("instruction") or "")[:140],
                "n_steps": len(data.get("graph_steps") or []),
                "n_llm": len(data.get("llm_calls") or []),
                "n_nodes": len(((data.get("final_pipeline") or {}).get("nodes")) or []),
                "n_edges": len(((data.get("final_pipeline") or {}).get("edges")) or []),
            })
        except Exception:
            continue
    return {"traces": out, "dir": str(d)}


@router.get("/build/traces/view", response_class=_HTMLResponse)
async def traces_view_inline(caller: CallerContext = ServiceAuth):
    """Single-page HTML viewer. Defined BEFORE the {filename} route so
    /view doesn't get caught by the dynamic path matcher."""
    return _HTMLResponse(_VIEWER_HTML)


@router.get("/build/traces/{filename}")
async def get_trace(filename: str, caller: CallerContext = ServiceAuth):
    d = _trace_dir()
    if not d:
        return _JSONResponse({"error": "BUILDER_TRACE_DIR not set"}, status_code=503)
    # safety: filename must end in .json + no path separators
    if "/" in filename or ".." in filename or not filename.endswith(".json"):
        return _JSONResponse({"error": "bad filename"}, status_code=400)
    f = d / filename
    if not f.exists():
        return _JSONResponse({"error": "not found"}, status_code=404)
    return json.loads(f.read_text())


@router.delete("/build/traces")
async def delete_traces(
    older_than_hours: int | None = None,
    caller: CallerContext = ServiceAuth,
):
    """Delete trace JSON files. When `older_than_hours` is set, only delete
    files whose mtime is older than that. Without it, deletes ALL traces.

    Used by admin /admin/build-traces page to clean up /tmp/builder-traces.
    """
    import time as _time
    d = _trace_dir()
    if not d:
        return _JSONResponse({"error": "BUILDER_TRACE_DIR not set"}, status_code=503)
    cutoff: float | None = None
    if older_than_hours is not None:
        if older_than_hours < 0 or older_than_hours > 24 * 365:
            return _JSONResponse({"error": "older_than_hours must be 0..8760"}, status_code=400)
        cutoff = _time.time() - older_than_hours * 3600.0
    deleted = 0
    skipped = 0
    errors: list[str] = []
    for f in d.glob("*.json"):
        try:
            if cutoff is not None and f.stat().st_mtime >= cutoff:
                skipped += 1
                continue
            f.unlink()
            deleted += 1
        except Exception as ex:  # noqa: BLE001
            errors.append(f"{f.name}: {ex}")
    log.info(
        "delete_traces: deleted=%d skipped=%d older_than_hours=%s",
        deleted, skipped, older_than_hours,
    )
    return {
        "deleted": deleted,
        "skipped_newer": skipped,
        "older_than_hours": older_than_hours,
        "errors": errors[:5],
    }


_VIEWER_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Build Traces</title>
<style>
body{font-family:-apple-system,monospace;margin:0;padding:16px;background:#0d1117;color:#c9d1d9}
h1{font-size:18px;margin:0 0 12px}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid #30363d}
tr:hover{background:#161b22;cursor:pointer}
.ok{color:#3fb950}
.fail{color:#f85149}
.partial{color:#d29922}
#detail{position:fixed;top:0;right:0;bottom:0;width:55%;background:#0d1117;border-left:1px solid #30363d;overflow:auto;padding:16px;display:none;font-size:12px}
#detail.open{display:block}
#close{position:absolute;top:8px;right:12px;cursor:pointer;font-size:20px}
.section{margin:16px 0;border:1px solid #30363d;border-radius:6px;padding:10px}
.section h3{font-size:13px;margin:0 0 8px;color:#58a6ff}
.step{padding:6px 8px;background:#161b22;margin:4px 0;border-radius:4px;border-left:3px solid #30363d}
.step.ok{border-left-color:#3fb950}
.step.fail{border-left-color:#f85149}
pre{white-space:pre-wrap;word-wrap:break-word;font-size:11px;background:#161b22;padding:8px;border-radius:4px;max-height:300px;overflow:auto}
.muted{color:#8b949e}
.token{padding:1px 6px;border-radius:3px;background:#161b22;font-size:11px}
</style></head><body>
<h1>Build Traces <span class="muted" id="dir"></span></h1>
<table><thead><tr><th>Time</th><th>Status</th><th>Dur</th><th>Steps/LLM</th><th>Nodes</th><th>Instruction</th></tr></thead><tbody id="rows"></tbody></table>
<div id="detail"><span id="close" onclick="document.getElementById('detail').classList.remove('open')">×</span><div id="content"></div></div>
<script>
const TOKEN = new URLSearchParams(window.location.search).get('token') || '';
async function api(path) {
  const r = await fetch(path, {headers: {'X-Service-Token': TOKEN}});
  return r.json();
}
function fmtTime(iso) { return iso ? iso.replace('T', ' ').slice(0, 19) : ''; }
function statusClass(s) { return s === 'finished' ? 'ok' : (s === 'plan_unfixable' || s === 'failed' ? 'fail' : 'partial'); }
async function loadList() {
  const data = await api('/internal/agent/build/traces');
  document.getElementById('dir').textContent = data.dir || '';
  const rows = document.getElementById('rows');
  rows.innerHTML = (data.traces || []).map(t => `
    <tr onclick="loadDetail('${t.file}')">
      <td>${fmtTime(t.started_at)}</td>
      <td class="${statusClass(t.status)}">${t.status || '-'}</td>
      <td>${t.duration_ms ? (t.duration_ms / 1000).toFixed(1) + 's' : '-'}</td>
      <td>${t.n_steps}/${t.n_llm}</td>
      <td>${t.n_nodes}/${t.n_edges}</td>
      <td>${t.instruction}</td>
    </tr>
  `).join('');
}
async function loadDetail(file) {
  const t = await api('/internal/agent/build/traces/' + file);
  const steps = (t.graph_steps || []).map(s => `
    <div class="step ${s.status === 'ok' ? 'ok' : (s.status === 'failed' ? 'fail' : '')}">
      <b>${s.node || '?'}</b> <span class="muted">${s.ts || ''}</span>
      ${s.duration_ms ? `<span class="muted">${s.duration_ms}ms</span>` : ''}
      <pre>${JSON.stringify(s, null, 2)}</pre>
    </div>
  `).join('');
  const llm = (t.llm_calls || []).map(c => `
    <div class="step">
      <b>${c.node || '?'}</b> ${c.attempt ? `<span class="token">attempt ${c.attempt}</span>` : ''} <span class="muted">${c.ts}</span>
      <details><summary>user_msg (${(c.user_msg || '').length} chars)</summary><pre>${(c.user_msg || '').replace(/[<>]/g, c => ({'<':'&lt;','>':'&gt;'}[c]))}</pre></details>
      <details><summary>raw_response</summary><pre>${(c.raw_response || '').replace(/[<>]/g, c => ({'<':'&lt;','>':'&gt;'}[c]))}</pre></details>
      ${c.parsed ? `<details><summary>parsed</summary><pre>${JSON.stringify(c.parsed, null, 2)}</pre></details>` : ''}
    </div>
  `).join('');
  const fp = t.final_pipeline || {};
  const nodes = (fp.nodes || []).map(n => `<div class="step"><b>${n.id}</b> [${n.block_id}] <pre>${JSON.stringify(n.params, null, 2)}</pre></div>`).join('');
  document.getElementById('content').innerHTML = `
    <h2>${t.build_id}</h2>
    <div class="muted">Status: ${t.status} · ${t.duration_ms}ms · ${t.session_id}</div>
    <div class="section"><h3>Instruction</h3><pre>${t.instruction || ''}</pre></div>
    <div class="section"><h3>Final Pipeline (${(fp.nodes || []).length} nodes)</h3>${nodes || '(empty)'}</div>
    <div class="section"><h3>Graph Steps (${(t.graph_steps || []).length})</h3>${steps}</div>
    <div class="section"><h3>LLM Calls (${(t.llm_calls || []).length})</h3>${llm}</div>
  `;
  document.getElementById('detail').classList.add('open');
}
loadList();
</script></body></html>"""


# (the /view route is registered above, before /{filename})
