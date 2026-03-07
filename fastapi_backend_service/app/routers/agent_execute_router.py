"""Agent Execute Router — POST /execute/skill/{skill_id}, POST /execute/mcp/{mcp_id}

Implements the PRD v12 Section 3.1 execution contract with strict view separation:
  - llm_readable_data  → for AI agent consumption
  - ui_render_payload → for frontend UI rendering (agent must NOT parse this)
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.data_subject_repository import DataSubjectRepository
from app.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.services.mcp_builder_service import MCPBuilderService
from app.services.mcp_definition_service import MCPDefinitionService
from app.services.skill_execute_service import SkillExecuteService

router = APIRouter(prefix="/execute", tags=["agent-execute"])


@router.post(
    "/skill/{skill_id}",
    summary="執行診斷技能 (Agent 呼叫端點)",
    response_model=Dict[str, Any],
)
async def execute_skill(
    skill_id: int,
    body: Dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Execute a Skill and return strictly separated llm/ui payloads.

    The AI agent MUST only read `llm_readable_data`.
    The frontend MUST only read `ui_render_payload`.

    Request body: free-form dict of parameters required by the Skill's MCP
    (e.g. {"lot_id": "L2603001", "tool_id": "TETCH01", "operation_number": "3200"})
    """
    # Extract base_url from request for internal DataSubject fetching
    base_url = f"{request.url.scheme}://{request.url.netloc}"

    svc = SkillExecuteService(
        skill_repo=SkillDefinitionRepository(db),
        mcp_repo=MCPDefinitionRepository(db),
        ds_repo=DataSubjectRepository(db),
    )

    return await svc.execute(skill_id=skill_id, params=body, base_url=base_url)


@router.post(
    "/mcp/{mcp_id}",
    summary="執行 MCP (含 System MCP Default Wrapper)",
    response_model=Dict[str, Any],
)
async def execute_mcp(
    mcp_id: int,
    body: Dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Execute a single MCP and return the Standard Payload.

    For mcp_type='system': calls the raw HTTP API via Default Wrapper and returns
    {dataset, ui_render: {type:'data_grid', ...}, _raw_dataset}.

    For mcp_type='custom': runs the processing_script against live data from the
    bound system MCP and returns the script's output_data.

    Request body: free-form dict of input parameters (forwarded to the MCP).
    """
    base_url = f"{request.url.scheme}://{request.url.netloc}"

    svc = MCPDefinitionService(
        repo=MCPDefinitionRepository(db),
        ds_repo=DataSubjectRepository(db),
        llm=MCPBuilderService(),
    )

    result = await svc.run_with_data(mcp_id=mcp_id, raw_data=body, base_url=base_url)
    return {
        "status": "success",
        "mcp_id": mcp_id,
        "output_data": result.output_data if hasattr(result, "output_data") else result,
    }
