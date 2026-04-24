"""Agent Builder Router — SSE-based Glass Box Agent endpoints.

Endpoints:
  POST /agent/build                         Create session, returns {session_id}
  GET  /agent/build/stream/{session_id}     SSE stream of Agent events
  POST /agent/build/{session_id}/cancel     Set cancel flag
  GET  /agent/build/{session_id}            Fetch final session state (post-run)
  POST /agent/build/batch                   Fallback: no streaming, returns full payload

See: docs/SPEC_pipeline_builder_phase3.md §2–§15
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repositories.pipeline_repository import PipelineRepository
from app.schemas.pipeline import PipelineJSON
from app.services.agent_builder.orchestrator import stream_agent_build
from app.services.agent_builder.registry import get_session_registry
from app.services.agent_builder.session import AgentBuilderSession, StreamEvent
from app.services.pipeline_builder.block_registry import BlockRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent/build", tags=["agent-builder"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class BuildRequest(BaseModel):
    # Java cutover v2 compat: accept both the legacy Python schema
    # ({prompt, base_pipeline_id, base_pipeline}) and the new Java schema
    # ({instruction, pipelineId, pipelineSnapshot}). Pydantic aliases let
    # either wire-form populate the canonical field. Frontend now sends the
    # new schema; Java accepts both via its own compat; this keeps the
    # Python fallback path green for local dev + any un-updated caller.
    model_config = {"populate_by_name": True}

    prompt: str = Field(..., min_length=1, max_length=4000, alias="instruction")
    base_pipeline_id: Optional[int] = Field(default=None, alias="pipelineId")
    # Phase 5-UX-6 fix: client can push the current canvas state inline so
    # follow-up requests (「加常態分佈圖」) see the pipeline the previous turn
    # built. Wins over base_pipeline_id if both are provided.
    base_pipeline: Optional[PipelineJSON] = Field(default=None, alias="pipelineSnapshot")


def _get_registry(request: Request) -> BlockRegistry:
    reg: Optional[BlockRegistry] = getattr(request.app.state, "block_registry", None)
    if reg is None:
        raise HTTPException(status_code=503, detail="BlockRegistry not initialised")
    return reg


async def _load_base_pipeline(db: AsyncSession, pipeline_id: int) -> PipelineJSON:
    repo = PipelineRepository(db)
    pipe = await repo.get_by_id(pipeline_id)
    if pipe is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    import json as _json
    try:
        data = _json.loads(pipe.pipeline_json)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupt pipeline_json in DB")
    return PipelineJSON.model_validate(data)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
async def create_session(
    body: BuildRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create an ephemeral agent session. Returns {session_id} — client must
    subscribe via GET /stream/{session_id} to actually run the agent."""
    _get_registry(request)  # check registry ready before creating session

    base_pipeline: Optional[PipelineJSON] = None
    # Priority: inline base_pipeline (current canvas state from client) > DB lookup
    if body.base_pipeline is not None:
        base_pipeline = body.base_pipeline
    elif body.base_pipeline_id is not None:
        base_pipeline = await _load_base_pipeline(db, body.base_pipeline_id)

    session = AgentBuilderSession.new(
        user_prompt=body.prompt,
        base_pipeline=base_pipeline,
        base_pipeline_id=body.base_pipeline_id,
    )
    registry = get_session_registry()
    registry.start_cleanup()  # idempotent
    await registry.register(session)

    return {"session_id": session.session_id}


@router.get("/stream/{session_id}")
async def stream(session_id: str, request: Request):
    """Server-Sent Events stream. Keeps connection until orchestrator yields
    a 'done' event (or an error / cancel)."""
    registry = get_session_registry()
    session = await registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found or expired")
    if session.status != "running":
        # Already finished — still emit a single final done event so client
        # can reconcile state without error
        async def _emit_final():
            import json as _json
            payload = {
                "status": session.status,
                "pipeline_json": session.pipeline_json.model_dump(by_alias=True),
                "summary": session.summary,
            }
            yield f"event: done\ndata: {_json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
        return StreamingResponse(_emit_final(), media_type="text/event-stream")

    block_registry = _get_registry(request)

    async def event_source():
        try:
            async for evt in stream_agent_build(session, block_registry):
                yield evt.to_sse()
                # Yield control so cancel / disconnect has a chance
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            logger.info("SSE for session %s cancelled (client disconnect)", session_id)
            session.mark_cancelled()
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("Orchestrator crashed for session %s", session_id)
            session.mark_failed(f"{type(e).__name__}: {e}")
            # Emit one final done event so client doesn't hang
            final = StreamEvent(
                type="done",
                data={
                    "status": "failed",
                    "pipeline_json": session.pipeline_json.model_dump(by_alias=True),
                    "summary": session.summary,
                },
            )
            yield final.to_sse()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering
            "Connection": "keep-alive",
        },
    )


@router.post("/{session_id}/cancel")
async def cancel_session(session_id: str) -> dict:
    registry = get_session_registry()
    ok = await registry.cancel(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"status": "cancelled"}


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict:
    registry = get_session_registry()
    session = await registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found or expired")
    return session.to_public_dict()


@router.post("/batch")
async def build_batch(
    body: BuildRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fallback: non-streaming single-response build. Collects all stream
    events then returns them in one payload. Useful if SSE is blocked."""
    block_registry = _get_registry(request)
    base_pipeline: Optional[PipelineJSON] = None
    if body.base_pipeline_id is not None:
        base_pipeline = await _load_base_pipeline(db, body.base_pipeline_id)
    session = AgentBuilderSession.new(
        user_prompt=body.prompt,
        base_pipeline=base_pipeline,
        base_pipeline_id=body.base_pipeline_id,
    )
    events: list[dict] = []
    async for evt in stream_agent_build(session, block_registry):
        events.append({"type": evt.type, "data": evt.data})
    return {
        "session_id": session.session_id,
        "events": events,
        **session.to_public_dict(),
    }
