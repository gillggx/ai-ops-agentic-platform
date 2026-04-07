"""Agent Chat Router — POST /agent/chat/stream (v13 Real Agentic Loop).

This is the main entry point for the v13 agentic platform.
Replaces /diagnose/copilot-chat for new clients (old endpoint preserved for compat).

SSE event types (in order):
  context_load → thinking → tool_start → tool_done → synthesis → memory_write → done/error
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select, delete

from app.database import get_db
from app.dependencies import get_current_user
from app.models.agent_session import AgentSessionModel
from app.models.user import UserModel
from app.config import get_settings
from app.services.agent_orchestrator import AgentOrchestrator

router = APIRouter(prefix="/agent", tags=["agent-v13"])


class AgentChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    # Optional overrides for testing
    context_overrides: Dict[str, Any] = {}


@router.post(
    "/chat/stream",
    summary="v13 真實 Agentic Loop — SSE 串流",
    response_class=StreamingResponse,
)
async def agent_chat_stream(
    body: AgentChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """Run the v13 five-stage agentic loop and stream SSE events.

    Event format: `data: {JSON}\\n\\n`

    Event types:
    - `context_load`  — Context assembled (soul_preview, rag_hits, pref_summary)
    - `thinking`      — LLM thinking block text
    - `tool_start`    — About to execute a tool (tool, input, iteration)
    - `tool_done`     — Tool finished (tool, result_summary, iteration)
    - `synthesis`     — Final natural-language answer
    - `memory_write`  — Long-term memory auto-persisted (content, source)
    - `error`         — Error or MAX_ITERATIONS hit
    - `done`          — Stream complete (session_id)
    """
    # Internal loopback — tool_dispatcher calls self via HTTP.
    # Detect actual listening port from request, fallback to config or 8001.
    base_url = str(request.base_url).rstrip("/")
    if "aiops" in base_url or "443" in base_url or "https" in base_url:
        # Nginx proxied request — use loopback to actual backend port
        base_url = f"http://127.0.0.1:{request.scope.get('server', ('', 8001))[1]}"

    # Extract JWT token from Authorization header for internal API calls
    auth_header = request.headers.get("Authorization", "")
    auth_token = auth_header.removeprefix("Bearer ").strip()

    # Feature flag: v1 (legacy while-loop) or v2 (LangGraph StateGraph)
    settings = get_settings()
    version = request.headers.get("X-Agent-Version") or settings.AGENT_ORCHESTRATOR_VERSION
    if version == "v2":
        from app.services.agent_orchestrator_v2 import AgentOrchestratorV2
        orchestrator = AgentOrchestratorV2(
            db=db,
            base_url=base_url,
            auth_token=auth_token,
            user_id=current_user.id,
            canvas_overrides=body.context_overrides or None,
        )
    else:
        orchestrator = AgentOrchestrator(
            db=db,
            base_url=base_url,
            auth_token=auth_token,
            user_id=current_user.id,
        )

    async def event_stream():
        try:
            # v1's run() is `async def run() -> AsyncIterator` (returns the generator)
            # v2's run() is `async def run() -> AsyncIterator` (is the generator)
            # Both produce an async iterable we can `async for` over.
            if version == "v2":
                gen = orchestrator.run(
                    message=body.message,
                    session_id=body.session_id,
                )
            else:
                gen = await orchestrator.run(
                    message=body.message,
                    session_id=body.session_id,
                )
            async for event in gen:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            err = json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
            yield f"data: {err}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/session/{session_id}", summary="清除指定 Session（開啟新對話）")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    await db.execute(
        delete(AgentSessionModel).where(
            AgentSessionModel.session_id == session_id,
            AgentSessionModel.user_id == current_user.id,
        )
    )
    await db.commit()
    return {"status": "success", "cleared": session_id}
