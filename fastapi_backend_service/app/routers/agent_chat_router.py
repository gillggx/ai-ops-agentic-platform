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

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
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
    base_url = f"{request.url.scheme}://{request.url.netloc}"

    # Extract JWT token from Authorization header for internal API calls
    auth_header = request.headers.get("Authorization", "")
    auth_token = auth_header.removeprefix("Bearer ").strip()

    orchestrator = AgentOrchestrator(
        db=db,
        base_url=base_url,
        auth_token=auth_token,
        user_id=current_user.id,
    )

    async def event_stream():
        try:
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
