"""Agent chat + Pipeline Builder Glass Box.

Phase 7 hybrid cutover:
  - Both endpoints try fallback proxy to old Python FastAPI first (when
    ``FALLBACK_ENABLED=1``) so the Frontend gets the full LangGraph /
    Glass Box experience while native ports land.
  - On fallback disabled or upstream error, drops to the native sidecar
    graph / scaffold (Phase 5b code path).
  - Phase 8 replaces each fallback with a proper native port.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from ..auth import CallerContext, ServiceAuth
from ..agent_orchestrator.graph import run_chat_turn
from ..clients.java_client import JavaAPIClient
from ..fallback import python_proxy as fb

log = logging.getLogger("python_ai_sidecar.agent_router")
router = APIRouter(prefix="/internal/agent", tags=["agent"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(..., min_length=1)
    session_id: str | None = Field(default=None, alias="sessionId")


class BuildRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    instruction: str = Field(..., min_length=1)
    pipeline_id: int | None = Field(default=None, alias="pipelineId")
    pipeline_snapshot: dict | None = Field(default=None, alias="pipelineSnapshot")


async def _chat_stream(req: ChatRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    if fb.fallback_enabled():
        try:
            body: dict = {"message": req.message}
            if req.session_id:
                body["session_id"] = req.session_id
            # Old Python FastAPI exposes chat at /api/v1/agent/chat/stream.
            async for ev in fb.stream_sse("/api/v1/agent/chat/stream", body, caller):
                yield ev
            return
        except Exception as ex:  # noqa: BLE001
            log.warning("chat fallback failed (%s) — using native graph", ex.__class__.__name__)
            yield fb.format_fallback_error(ex)

    async for event in run_chat_turn(
            user_message=req.message,
            session_id=req.session_id,
            caller=caller):
        yield event


async def _build_stream_native(req: BuildRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    """Phase 8-A-1c: native Glass Box agent in sidecar.

    Uses the ported `agent_builder.stream_agent_build` (Anthropic SDK +
    BlockRegistry) directly. No DB session needed — the registry is loaded
    seed-side, and there's no cross-request state besides what the
    AgentBuilderSession holds in memory.
    """
    import os
    from python_ai_sidecar.agent_builder.session import AgentBuilderSession
    from python_ai_sidecar.agent_builder.orchestrator import stream_agent_build
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
    from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON

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
