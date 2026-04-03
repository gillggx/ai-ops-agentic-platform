"""Shadow Analyst Router — v15.2 Async Shadow Analysis.

POST /agent/shadow-analyze
  Accepts: { raw_data, data_profile, mcp_name }
  Returns: SSE stream of shadow analysis events
    data: {"type": "decision", "method": "jit|agent_tool", "message": "..."}
    data: {"type": "stat_card", "label": "...", "value": ..., "unit": "...", "significance": "..."}
    data: {"type": "done", "jit_code": "...", "tool_used": "...", "intro": "..."}
    data: {"type": "error", "message": "..."}
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.services.agent_tool_service import AgentToolService
from app.services.shadow_analyst_service import ShadowAnalystService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["shadow-analyst"])


class ShadowAnalyzeRequest(BaseModel):
    raw_data: List[Dict[str, Any]] = Field(default_factory=list, description="已撈取的資料集 (list-of-dicts)")
    data_profile: Dict[str, Any] = Field(default_factory=dict, description="DataProfile (來自 Smart Sampling)")
    mcp_name: str = Field(default="MCP 查詢", description="觸發此分析的 MCP 名稱")


@router.post("/shadow-analyze")
async def shadow_analyze(
    body: ShadowAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> StreamingResponse:
    """Stream shadow analysis for a freshly fetched MCP dataset."""

    async def _stream():
        try:
            # Load user's agent_tools for P2 matching
            tool_svc = AgentToolService(db)
            agent_tools_models = await tool_svc.get_all(user_id=current_user.id)
            agent_tools = [AgentToolService.to_dict(t) for t in agent_tools_models]

            svc = ShadowAnalystService(db)
            async for event in svc.analyze(
                raw_data=body.raw_data,
                data_profile=body.data_profile,
                mcp_name=body.mcp_name,
                agent_tools=agent_tools,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        except Exception as exc:
            logger.exception("shadow_analyze stream error")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
