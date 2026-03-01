"""Skill Definition CRUD router."""

from fastapi import APIRouter, Depends
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
from app.schemas.skill_definition import (
    SkillAutoMapRequest,
    SkillCheckDiagnosisIntentRequest,
    SkillDefinitionCreate,
    SkillDefinitionUpdate,
    SkillTryDiagnosisRequest,
)
from app.services.mcp_builder_service import MCPBuilderService
from app.services.skill_definition_service import SkillDefinitionService

router = APIRouter(prefix="/skill-definitions", tags=["skill-definitions"])


def _get_service(db: AsyncSession = Depends(get_db)) -> SkillDefinitionService:
    return SkillDefinitionService(
        repo=SkillDefinitionRepository(db),
        et_repo=EventTypeRepository(db),
        mcp_repo=MCPDefinitionRepository(db),
        llm=MCPBuilderService(),
        sp_repo=SystemParameterRepository(db),
        ds_repo=DataSubjectRepository(db),
    )


@router.get("", response_model=StandardResponse)
async def list_skills(
    svc: SkillDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    items = await svc.list_all()
    return StandardResponse.success(data=[i.model_dump() for i in items])


@router.get("/{skill_id}", response_model=StandardResponse)
async def get_skill(
    skill_id: int,
    svc: SkillDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.get(skill_id)
    return StandardResponse.success(data=item.model_dump())


@router.post("", response_model=StandardResponse, status_code=201)
async def create_skill(
    body: SkillDefinitionCreate,
    svc: SkillDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.create(body)
    return StandardResponse.success(data=item.model_dump(), message="Skill 建立成功")


@router.patch("/{skill_id}", response_model=StandardResponse)
async def update_skill(
    skill_id: int,
    body: SkillDefinitionUpdate,
    svc: SkillDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.update(skill_id, body)
    return StandardResponse.success(data=item.model_dump(), message="Skill 更新成功")


@router.delete("/{skill_id}", response_model=StandardResponse)
async def delete_skill(
    skill_id: int,
    svc: SkillDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    await svc.delete(skill_id)
    return StandardResponse.success(message="Skill 刪除成功")


@router.get("/{skill_id}/mcp-output-schemas", response_model=StandardResponse)
async def get_mcp_output_schemas(
    skill_id: int,
    svc: SkillDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    """Return output schemas + sample outputs of all MCPs bound to this Skill."""
    schemas = await svc.get_mcp_output_schemas(skill_id)
    return StandardResponse.success(data=schemas)


@router.post("/auto-map", response_model=StandardResponse)
async def auto_map_skill(
    body: SkillAutoMapRequest,
    svc: SkillDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    """LLM semantic mapping: match DataSubject input fields → Event attributes."""
    result = await svc.auto_map(mcp_id=body.mcp_id, event_type_id=body.event_type_id)
    return StandardResponse.success(data=result)


@router.post("/check-diagnosis-intent", response_model=StandardResponse)
async def check_diagnosis_intent(
    body: SkillCheckDiagnosisIntentRequest,
    svc: SkillDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    """Check if a diagnostic prompt is clear and unambiguous before running LLM diagnosis."""
    result = await svc.check_diagnosis_intent(
        diagnostic_prompt=body.diagnostic_prompt,
        mcp_output_sample=body.mcp_output_sample,
    )
    return StandardResponse.success(data=result)


@router.post("/try-diagnosis", response_model=StandardResponse)
async def try_diagnosis_skill(
    body: SkillTryDiagnosisRequest,
    svc: SkillDefinitionService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    """Simulate Skill diagnosis: send MCP sample_outputs + diagnostic_prompt to LLM."""
    result = await svc.try_diagnosis(
        diagnostic_prompt=body.diagnostic_prompt,
        mcp_sample_outputs=body.mcp_sample_outputs,
    )
    return StandardResponse.success(data=result.model_dump())
