"""LangGraph chat + Pipeline Builder Glass Box — SSE-streamed.

Phase 4 ships a **mock** response stream so Java can wire and E2E-test the
proxy. Phase 5 swaps the mock for real ``agent_orchestrator_v2`` /
``agent_builder`` calls imported from ``fastapi_backend_service``.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncGenerator

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..auth import CallerContext, ServiceAuth

router = APIRouter(prefix="/internal/agent", tags=["agent"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None


class BuildRequest(BaseModel):
    instruction: str = Field(..., min_length=1)
    pipeline_id: int | None = None
    pipeline_snapshot: dict | None = None


async def _mock_chat_stream(req: ChatRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    """Phase 4 mock — emits an opening event, 3 tokens, and a done event.

    Real implementation (Phase 5+) will forward to the LangGraph orchestrator
    and re-emit its events 1:1.
    """
    yield {
        "event": "open",
        "data": json.dumps({
            "session_id": req.session_id or f"mock-{int(time.time())}",
            "caller_user_id": caller.user_id,
        }),
    }
    for i, word in enumerate(["Hello,", "Java", f"→ {caller.user_id or 'anonymous'}"]):
        await asyncio.sleep(0.05)
        yield {
            "event": "message",
            "data": json.dumps({"index": i, "token": word}),
        }
    yield {
        "event": "done",
        "data": json.dumps({"summary": "mock chat complete"}),
    }


async def _mock_build_stream(req: BuildRequest, caller: CallerContext) -> AsyncGenerator[dict, None]:
    """Phase 4 mock for Pipeline Builder Glass Box — emits pb_glass_* events."""
    yield {
        "event": "pb_glass_start",
        "data": json.dumps({
            "instruction": req.instruction,
            "pipeline_id": req.pipeline_id,
            "caller_user_id": caller.user_id,
        }),
    }
    yield {
        "event": "pb_glass_chat",
        "data": json.dumps({"content": "思考中... (mock)"}),
    }
    yield {
        "event": "pb_glass_op",
        "data": json.dumps({
            "op": "add_node",
            "payload": {"node_id": "n_mock_1", "block": "load_process_history"},
        }),
    }
    yield {
        "event": "pb_glass_done",
        "data": json.dumps({"summary": "mock build complete — replace with real agent_builder"}),
    }


@router.post("/chat")
async def agent_chat(req: ChatRequest, caller: CallerContext = ServiceAuth) -> EventSourceResponse:
    return EventSourceResponse(_mock_chat_stream(req, caller))


@router.post("/build")
async def agent_build(req: BuildRequest, caller: CallerContext = ServiceAuth) -> EventSourceResponse:
    return EventSourceResponse(_mock_build_stream(req, caller))
