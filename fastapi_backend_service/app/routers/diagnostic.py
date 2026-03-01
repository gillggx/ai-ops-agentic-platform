"""Router for the AI diagnostic agent SSE endpoint.

Endpoint
--------
POST /api/v1/diagnose/
    Accepts ``{"issue_description": "..."}`` and returns a
    ``text/event-stream`` (Server-Sent Events) response.

    The stream emits the following events in order:

    1. ``session_start`` — immediately, confirms receipt.
    2. ``tool_call``     — before each skill execution.
    3. ``tool_result``   — after each skill execution.
    4. ``report``        — final Markdown diagnosis report.
    5. ``done``          — always emitted last.

Authentication
--------------
JWT Bearer token required (``get_current_user`` dependency).
The 401 / 422 error responses are returned as standard JSON by FastAPI's
exception handlers *before* the stream is opened, so clients receive them
in the normal way.
"""

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.data_subject_repository import DataSubjectRepository
from app.repositories.event_type_repository import EventTypeRepository
from app.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.repositories.system_parameter_repository import SystemParameterRepository
from app.schemas.diagnostic import DiagnoseRequest, EventDrivenDiagnoseRequest
from app.services.diagnostic_service import DiagnosticService
from app.services.event_pipeline_service import EventPipelineService
from app.services.mcp_builder_service import MCPBuilderService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diagnose", tags=["diagnostic"])


@router.post(
    "/",
    summary="執行 AI 診斷 (SSE 串流)",
    description=(
        "接收使用者描述的問題，透過 MCP Agent Loop 動態調度工具，"
        "以 Server-Sent Events 格式即時推播診斷進度與最終 Markdown 報告。"
        "需要 JWT 身份驗證。"
    ),
    responses={
        200: {"description": "SSE 串流（text/event-stream）"},
        401: {"description": "未提供或無效的 JWT Token"},
        422: {"description": "請求格式驗證失敗"},
    },
)
async def diagnose(
    request: DiagnoseRequest,
    current_user: UserModel = Depends(get_current_user),
) -> StreamingResponse:
    """Start the diagnostic agent loop and stream SSE events to the client.

    Args:
        request: Contains ``issue_description``.
        current_user: Authenticated user (from JWT dependency).

    Returns:
        A ``StreamingResponse`` with ``media_type="text/event-stream"``.
    """
    logger.info(
        "SSE diagnostic from user=%s: %s",
        current_user.username,
        request.issue_description[:80],
    )

    service = DiagnosticService()

    return StreamingResponse(
        service.stream(request.issue_description),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _get_pipeline_service(db: AsyncSession = Depends(get_db)) -> EventPipelineService:
    return EventPipelineService(
        skill_repo=SkillDefinitionRepository(db),
        et_repo=EventTypeRepository(db),
        mcp_repo=MCPDefinitionRepository(db),
        ds_repo=DataSubjectRepository(db),
        llm=MCPBuilderService(),
        sp_repo=SystemParameterRepository(db),
    )


@router.post(
    "/event-driven",
    response_model=StandardResponse,
    summary="事件驅動全鏈路診斷",
    description=(
        "接收觸發事件的 event_type 與 params，自動找出綁定的 Skill，"
        "依 param_mappings 代入 DataSubject API，執行 MCP 腳本，"
        "再由 LLM 套用 Diagnostic Prompt，回傳每個 Skill 的結構化診斷報告。"
    ),
)
async def diagnose_event_driven(
    body: EventDrivenDiagnoseRequest,
    http_request: Request,
    svc: EventPipelineService = Depends(_get_pipeline_service),
    current_user: UserModel = Depends(get_current_user),
) -> StandardResponse:
    """Execute the full event-driven diagnosis pipeline and return structured results."""
    logger.info(
        "Event-driven diagnosis from user=%s: event_type=%s event_id=%s",
        current_user.username,
        body.event_type,
        body.event_id,
    )
    # Build base_url from incoming request so relative endpoint_urls resolve correctly
    base_url = str(http_request.base_url).rstrip("/")
    result = await svc.run(
        event_type_name=body.event_type,
        event_id=body.event_id,
        event_params=body.params,
        base_url=base_url,
    )
    return StandardResponse.success(data=result)


@router.post(
    "/event-driven-stream",
    summary="事件驅動漸進式診斷 (SSE 串流)",
    description=(
        "與 /event-driven 相同邏輯，但改為 Server-Sent Events 串流輸出。"
        "每完成一個 Skill 立即推播對應的診斷報告卡，無需等待所有 Skill 完成。"
    ),
    responses={
        200: {"description": "SSE 串流（text/event-stream）"},
        401: {"description": "未提供或無效的 JWT Token"},
    },
)
async def diagnose_event_driven_stream(
    body: EventDrivenDiagnoseRequest,
    http_request: Request,
    svc: EventPipelineService = Depends(_get_pipeline_service),
    current_user: UserModel = Depends(get_current_user),
) -> StreamingResponse:
    """Stream per-skill diagnosis results as SSE events."""
    logger.info(
        "SSE event-driven diagnosis from user=%s: event_type=%s event_id=%s",
        current_user.username,
        body.event_type,
        body.event_id,
    )
    base_url = str(http_request.base_url).rstrip("/")

    async def generate():
        async for event in svc.stream(
            event_type_name=body.event_type,
            event_id=body.event_id,
            event_params=body.params,
            base_url=base_url,
        ):
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
