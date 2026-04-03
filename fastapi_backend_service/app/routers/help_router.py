"""Help Chat router — LLM assistant for answering user usage questions."""

import json
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.dependencies import get_current_user
from app.models.user import UserModel
from app.services.help_chat_service import HelpChatService

router = APIRouter(prefix="/help", tags=["help"])


class HelpChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []


@router.post("/chat", summary="使用說明 AI 助理對話")
async def help_chat(
    body: HelpChatRequest,
    current_user: UserModel = Depends(get_current_user),
) -> StreamingResponse:
    """Stream LLM answers to usage questions based on product documentation."""
    svc = HelpChatService()

    async def generate():
        gen = await svc.stream_chat(body.message, body.history)
        async for event in gen:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
