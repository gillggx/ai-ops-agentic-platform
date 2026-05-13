"""Agent chat + Pipeline Builder Glass Box.

Phase 8-A-1d: chat goes through AgentOrchestratorV2 (LangGraph) natively.
DB-coupled nodes were rewired to JavaAPIClient + ported pure-compute helpers
under ``agent_helpers_native/``; the sidecar no longer needs an AsyncSession.

The old fallback path (proxy → :8001) is retained behind ``FALLBACK_ENABLED=1``
purely as an emergency rollback switch — production should run with it ``0``.
Phase 8-D drops the fallback proxy outright + decommissions :8001.
"""

from __future__ import annotations

import json
import logging
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
    answers to the multiple-choice questions emitted earlier. Frontend
    POSTs this when user picks options on the clarification dialog.
    """
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    # {question_id: chosen_value}; values can be option `value`s from the
    # original questions or free-text the user typed.
    answers: dict[str, str] = Field(default_factory=dict)


async def _build_clarify_stream(
    req: BuildClarifyRespondRequest, caller: CallerContext,
) -> AsyncGenerator[dict, None]:
    from python_ai_sidecar.agent_builder.graph_build.runner import (
        resume_graph_build_with_clarify,
    )

    try:
        async for stream_event in resume_graph_build_with_clarify(
            session_id=req.session_id, answers=req.answers,
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
