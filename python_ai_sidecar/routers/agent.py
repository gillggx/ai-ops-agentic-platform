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


class BuildContinueRequest(BaseModel):
    """SPEC_glassbox_continuation: resume a paused Glass Box build.
    `additional_turns` is bounded server-side to MAX_TURNS_PER_CONTINUATION."""
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    additional_turns: int = Field(default=20, alias="additionalTurns")


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


async def _build_stream_native(req: BuildRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    """Phase 8-A-1c: native Glass Box agent in sidecar.

    Uses the ported `agent_builder.stream_agent_build` (Anthropic SDK +
    BlockRegistry) directly. No DB session needed — the registry is loaded
    seed-side, and there's no cross-request state besides what the
    AgentBuilderSession holds in memory.

    Builder Mode Block Advisor (2026-05-02): the user's message is first
    classified — if it's a block Q&A (EXPLAIN/COMPARE/RECOMMEND) or
    ambiguous, we route to ``stream_block_advisor`` instead of the build
    flow, so the panel answers questions about blocks without polluting
    the canvas. Flow stays in code (graph-deterministic), not in prompt
    — see CLAUDE.md "流程是 agent 決定，LLM 是大腦".
    """
    import os
    from python_ai_sidecar.agent_builder.session import AgentBuilderSession
    from python_ai_sidecar.agent_builder.orchestrator import stream_agent_build
    from python_ai_sidecar.agent_builder.advisor import (
        classify_advisor_intent, stream_block_advisor,
    )
    from python_ai_sidecar.clients.java_client import JavaAPIClient
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
    from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON

    # ── Step 0: classify intent (graph-level routing) ───────────────────
    intent, confidence, reason = await classify_advisor_intent(req.instruction)
    log.info("build/native: intent=%s conf=%.2f reason=%r", intent, confidence, reason)

    if intent != "BUILD":
        # Q&A path — answer directly, no pipeline mutation.
        java = JavaAPIClient.for_caller(caller)
        async for stream_event in stream_block_advisor(req.instruction, intent, java=java):
            yield {
                "event": stream_event.type,
                "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
            }
        return

    # ── BUILD path (existing Glass Box flow) ────────────────────────────
    base_pipeline: PipelineJSON | None = None
    if req.pipeline_snapshot:
        try:
            base_pipeline = PipelineJSON.model_validate(req.pipeline_snapshot)
        except Exception as ex:  # noqa: BLE001
            log.warning("pipeline_snapshot parse failed (%s) — starting empty", ex)

    session = AgentBuilderSession.new(
        user_prompt=req.instruction,
        base_pipeline=base_pipeline,
        base_pipeline_id=req.pipeline_id,
    )
    registry = SeedlessBlockRegistry()
    registry.load()

    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    async for stream_event in stream_agent_build(session, registry, model=model):
        # StreamEvent: {type, data}; sse_starlette EventSourceResponse takes {event, data}
        yield {
            "event": stream_event.type,
            "data": json.dumps(stream_event.data, default=str, ensure_ascii=False),
        }


async def _build_stream(req: BuildRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    """Phase 8-A-3: native-only Glass Box. Fallback removed — native path
    proved stable in A-1c smoke. If native fails, surface the error as an
    SSE frame instead of silently proxying to :8001."""
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        yield {"event": "error", "data": json.dumps({
            "message": "ANTHROPIC_API_KEY not set on sidecar — /agent/build unavailable",
        })}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}
        return

    try:
        async for ev in _build_stream_native(req, caller):
            yield ev
    except Exception as ex:  # noqa: BLE001
        log.exception("native build failed")
        yield {"event": "error", "data": json.dumps({
            "message": f"native build failed: {ex.__class__.__name__}: {str(ex)[:200]}",
        })}
        yield {"event": "done", "data": json.dumps({"status": "failed"})}


@router.post("/chat")
async def agent_chat(req: ChatRequest, caller: CallerContext = ServiceAuth) -> EventSourceResponse:
    return EventSourceResponse(_chat_stream(req, caller))


@router.post("/build")
async def agent_build(req: BuildRequest, caller: CallerContext = ServiceAuth) -> EventSourceResponse:
    return EventSourceResponse(_build_stream(req, caller))


async def _build_continue_stream(req: BuildContinueRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    """SPEC_glassbox_continuation: resume a paused Glass Box build.

    Loads the parked session, bumps continuation_count, and re-enters
    stream_agent_build which detects the snapshot and resumes from where
    the previous run paused.
    """
    import os
    from python_ai_sidecar.agent_builder.orchestrator import (
        stream_agent_build,
        take_paused_session,
        MAX_TURNS_PER_CONTINUATION,
    )
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry

    session = take_paused_session(req.session_id)
    if session is None:
        yield {"event": "error", "data": json.dumps({
            "op": "continue", "message": f"session {req.session_id} not found or already taken",
            "ts": 0.0,
        }, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"status": "failed", "summary": "session not found"}, ensure_ascii=False)}
        return

    if session.status != "paused":
        yield {"event": "error", "data": json.dumps({
            "op": "continue", "message": f"session {req.session_id} status={session.status} (need 'paused')",
            "ts": 0.0,
        }, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"status": "failed", "summary": "session not paused"}, ensure_ascii=False)}
        return

    # Cap the additional turns server-side regardless of what client requested
    capped = max(5, min(MAX_TURNS_PER_CONTINUATION, int(req.additional_turns or 20)))
    log.info("build/continue: session=%s continuation=%d → +%d turns",
             session.session_id, session.continuation_count + 1, capped)

    session.continuation_count += 1
    session.status = "running"

    registry = SeedlessBlockRegistry()
    registry.load()

    from python_ai_sidecar.agent_builder.event_wrapper import wrap_build_event_for_chat

    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    async for stream_event in stream_agent_build(session, registry, model=model):
        wrapped = wrap_build_event_for_chat(stream_event, session.session_id)
        if wrapped is None:
            continue
        yield {
            "event": wrapped["type"],
            "data": json.dumps(wrapped, default=str, ensure_ascii=False),
        }


@router.post("/build/continue")
async def agent_build_continue(
    req: BuildContinueRequest, caller: CallerContext = ServiceAuth,
) -> EventSourceResponse:
    return EventSourceResponse(_build_continue_stream(req, caller))
