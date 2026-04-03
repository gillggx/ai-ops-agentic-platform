"""Router for the LLM-powered Skill Builder design-time API.

Endpoints (all under ``/api/v1/builder/``)
------------------------------------------
POST /auto-map
    Semantically maps SPC OOC Event attributes to MCP tool input parameters.

POST /validate-logic
    Validates that a user-written diagnostic prompt only references fields
    that the target MCP tool output schema actually provides.

POST /suggest-logic
    Analyses the Event Schema and returns 3-5 expert PE-grade diagnostic
    logic suggestions to guide Skill configuration.

Authentication
--------------
JWT Bearer token required on all endpoints.
"""

import logging

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.models.user import UserModel
from app.schemas.builder import (
    AutoMapRequest,
    AutoMapResponse,
    SuggestLogicRequest,
    SuggestLogicResponse,
    ValidateLogicRequest,
    ValidateLogicResponse,
)
from app.services.builder_service import BuilderService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/builder", tags=["builder"])


@router.post(
    "/auto-map",
    response_model=AutoMapResponse,
    summary="智能映射 — Event 屬性 → MCP 工具輸入參數",
    description=(
        "傳入 SPC OOC Event Schema 與 MCP 工具的 input_schema，"
        "由 LLM 進行語意比對，自動建立欄位對應關係（如 eqp_id → target_equipment）。"
        "解決 Builder UI 中「空白畫布綜合症」的核心能力。"
    ),
)
async def auto_map(
    request: AutoMapRequest,
    current_user: UserModel = Depends(get_current_user),
) -> AutoMapResponse:
    """Semantically map Event attributes to MCP tool input parameters."""
    logger.info("auto_map called by user=%s", current_user.username)
    service = BuilderService()
    return await service.auto_map(
        event_schema=request.event_schema,
        tool_input_schema=request.tool_input_schema,
    )


@router.post(
    "/validate-logic",
    response_model=ValidateLogicResponse,
    summary="語意防呆 — 驗證診斷 Prompt 的欄位引用合法性",
    description=(
        "傳入使用者撰寫的診斷邏輯提示詞與 MCP 工具輸出結構，"
        "由 LLM 驗證 Prompt 是否引用了工具未提供的欄位，"
        "並檢查是否存在語意矛盾。"
    ),
)
async def validate_logic(
    request: ValidateLogicRequest,
    current_user: UserModel = Depends(get_current_user),
) -> ValidateLogicResponse:
    """Validate user prompt against MCP tool output schema."""
    logger.info("validate_logic called by user=%s", current_user.username)
    service = BuilderService()
    return await service.validate_logic(
        user_prompt=request.user_prompt,
        tool_output_schema=request.tool_output_schema,
    )


@router.post(
    "/suggest-logic",
    response_model=SuggestLogicResponse,
    summary="智能提示引擎 — 根據 Event Schema 產生 PE 排障邏輯建議",
    description=(
        "傳入 SPC OOC Event Schema，由 LLM 扮演台積電資深蝕刻製程工程師，"
        "解析各屬性語意後回傳 3~5 條專業排障邏輯提示，"
        "引導使用者在 Builder UI 中設定正確的 Skill 診斷條件。"
    ),
)
async def suggest_logic(
    request: SuggestLogicRequest,
    current_user: UserModel = Depends(get_current_user),
) -> SuggestLogicResponse:
    """Generate expert PE-grade diagnostic logic suggestions."""
    logger.info("suggest_logic called by user=%s", current_user.username)
    service = BuilderService()
    return await service.suggest_logic(
        event_schema=request.event_schema,
        context=request.context,
    )
