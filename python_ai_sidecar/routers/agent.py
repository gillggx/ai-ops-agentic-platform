"""Agent chat + Pipeline Builder Glass Box — live in Phase 5b.

- ``/internal/agent/chat``  → ``agent_orchestrator.graph.run_chat_turn`` against Java.
- ``/internal/agent/build`` → Glass Box scaffold emitting ``pb_glass_*`` events
  backed by Java's block catalog. Phase 5c plugs in the real ``agent_builder``
  LangGraph graph; the event envelope is already final.
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


@router.post("/chat")
async def agent_chat(req: ChatRequest, caller: CallerContext = ServiceAuth) -> EventSourceResponse:
    async def _stream():
        async for event in run_chat_turn(
            user_message=req.message,
            session_id=req.session_id,
            caller=caller,
        ):
            yield event
    return EventSourceResponse(_stream())


async def _build_stream(req: BuildRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
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
                "reasoning": "first active block as placeholder (phase 5b)",
            })}
        else:
            yield {"event": "pb_glass_chat", "data": json.dumps({
                "content": "No active blocks — seed pb_blocks first.",
            })}
    except Exception as ex:  # noqa: BLE001
        log.exception("build stream failure")
        yield {"event": "pb_glass_error", "data": json.dumps({"message": str(ex)[:200]})}

    yield {"event": "pb_glass_done", "data": json.dumps({
        "summary": "Phase 5b scaffold — real agent_builder comes in 5c.",
    })}


@router.post("/build")
async def agent_build(req: BuildRequest, caller: CallerContext = ServiceAuth) -> EventSourceResponse:
    return EventSourceResponse(_build_stream(req, caller))
