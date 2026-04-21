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


async def _build_stream(req: BuildRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    if fb.fallback_enabled():
        try:
            body: dict = {"instruction": req.instruction}
            if req.pipeline_id is not None:
                body["pipeline_id"] = req.pipeline_id
            if req.pipeline_snapshot is not None:
                body["pipeline_snapshot"] = req.pipeline_snapshot
            async for ev in fb.stream_sse("/api/v1/agent/build", body, caller):
                yield ev
            return
        except Exception as ex:  # noqa: BLE001
            log.warning("build fallback failed (%s) — using native scaffold", ex.__class__.__name__)
            yield fb.format_fallback_error(ex)

    # Native scaffold (Phase 5b): emit pb_glass_* envelope from Java catalog.
    java = JavaAPIClient.for_caller(caller)
    yield {"event": "pb_glass_start", "data": json.dumps({
        "instruction": req.instruction,
        "pipeline_id": req.pipeline_id,
        "caller_user_id": caller.user_id,
    })}
    try:
        blocks = await java.list_blocks(status="active")
        yield {"event": "pb_glass_chat", "data": json.dumps({
            "content": f"Loaded {len(blocks)} active blocks from Java.",
        })}
        picked = blocks[0] if blocks else None
        if picked:
            yield {"event": "pb_glass_op", "data": json.dumps({
                "op": "add_node",
                "payload": {
                    "node_id": "n_1",
                    "block": picked.get("name"),
                    "category": picked.get("category"),
                },
                "reasoning": "first active block as placeholder (native scaffold)",
            })}
        else:
            yield {"event": "pb_glass_chat", "data": json.dumps({
                "content": "No active blocks — seed pb_blocks first.",
            })}
    except Exception as ex:  # noqa: BLE001
        log.exception("build native failure")
        yield {"event": "pb_glass_error", "data": json.dumps({"message": str(ex)[:200]})}

    yield {"event": "pb_glass_done", "data": json.dumps({
        "summary": "Phase 7 native scaffold — fallback disabled or failed.",
    })}


@router.post("/chat")
async def agent_chat(req: ChatRequest, caller: CallerContext = ServiceAuth) -> EventSourceResponse:
    return EventSourceResponse(_chat_stream(req, caller))


@router.post("/build")
async def agent_build(req: BuildRequest, caller: CallerContext = ServiceAuth) -> EventSourceResponse:
    return EventSourceResponse(_build_stream(req, caller))
