"""Skill Definition router — v2.0 Diagnostic-First Architecture."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.schemas.skill_definition import (
    CompileStepsRequest,
    GenerateStepsRequest,
    SkillAgentBuildRequest,
    SkillDefinitionCreate,
    SkillDefinitionUpdate,
    SkillExecuteRequest,
    SkillTryRunDraftRequest,
    SkillTryRunRequest,
)
from app.services.skill_definition_service import SkillDefinitionService
from app.utils.llm_client import get_llm_client
from app.services.skill_executor_service import SkillExecutorService, build_mcp_executor
from app.config import get_settings

router = APIRouter(prefix="/skill-definitions", tags=["skill-definitions"])


def _get_svc(db: AsyncSession = Depends(get_db)) -> SkillDefinitionService:
    return SkillDefinitionService(
        repo=SkillDefinitionRepository(db),
        db=db,
        llm=get_llm_client(),
    )


def _get_executor(db: AsyncSession = Depends(get_db)) -> SkillExecutorService:
    settings = get_settings()
    return SkillExecutorService(
        skill_repo=SkillDefinitionRepository(db),
        mcp_executor=build_mcp_executor(db, sim_url=settings.ONTOLOGY_SIM_URL),
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=StandardResponse)
async def list_skills(
    svc: SkillDefinitionService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    items = await svc.list_all()
    return StandardResponse.success(data=[i.model_dump() for i in items])


@router.post("", response_model=StandardResponse, status_code=201)
async def create_skill(
    body: SkillDefinitionCreate,
    svc: SkillDefinitionService = Depends(_get_svc),
    current_user: UserModel = Depends(get_current_user),
):
    item = await svc.create(body, created_by=current_user.id)
    return StandardResponse.success(data=item.model_dump(), message="Skill 建立成功")


@router.get("/{skill_id}", response_model=StandardResponse)
async def get_skill(
    skill_id: int,
    svc: SkillDefinitionService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.get(skill_id)
    return StandardResponse.success(data=item.model_dump())


@router.patch("/{skill_id}", response_model=StandardResponse)
async def update_skill(
    skill_id: int,
    body: SkillDefinitionUpdate,
    svc: SkillDefinitionService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.update(skill_id, body)
    return StandardResponse.success(data=item.model_dump(), message="Skill 更新成功")


@router.delete("/{skill_id}", response_model=StandardResponse)
async def delete_skill(
    skill_id: int,
    svc: SkillDefinitionService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    await svc.delete(skill_id)
    return StandardResponse.success(message="Skill 刪除成功")


# ── LLM Builder ───────────────────────────────────────────────────────────────

@router.post("/generate-steps", response_model=StandardResponse)
async def generate_steps(
    body: GenerateStepsRequest,
    svc: SkillDefinitionService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    """LLM generates steps_mapping + output_schema from natural language."""
    result = await svc.generate_steps(body)
    if not result.success:
        return StandardResponse.error(message=result.error or "LLM 生成失敗")
    return StandardResponse.success(data=result.model_dump())


# ── Sandbox / Execution ───────────────────────────────────────────────────────

@router.post("/{skill_id}/try-run", response_model=StandardResponse)
async def try_run_skill(
    skill_id: int,
    body: SkillTryRunRequest = SkillTryRunRequest(),
    executor: SkillExecutorService = Depends(_get_executor),
    _: UserModel = Depends(get_current_user),
):
    """Sandbox try-run with mock event payload — returns SkillFindings."""
    result = await executor.try_run(skill_id=skill_id, mock_payload=body.mock_payload)
    if not result.success:
        return StandardResponse.error(message=result.error or "Try-run 失敗", data=result.model_dump())
    return StandardResponse.success(data=result.model_dump())


@router.post("/{skill_id}/execute", response_model=StandardResponse)
async def execute_skill(
    skill_id: int,
    body: SkillExecuteRequest,
    executor: SkillExecutorService = Depends(_get_executor),
    _: UserModel = Depends(get_current_user),
):
    """Execute skill — returns SkillFindings for caller to decide on alarms."""
    result = await executor.execute(
        skill_id=skill_id,
        event_payload=body.event_payload,
        triggered_by=body.triggered_by,
    )
    if not result.success:
        return StandardResponse.error(message=result.error or "執行失敗", data=result.model_dump())
    return StandardResponse.success(data=result.model_dump(), message="執行完成")


# ── Draft Try-Run (no saved skill needed — v3.0 flow) ────────────────────────

@router.post("/try-run-draft", response_model=StandardResponse)
async def try_run_draft(
    body: SkillTryRunDraftRequest,
    executor: SkillExecutorService = Depends(_get_executor),
    _: UserModel = Depends(get_current_user),
):
    """Sandbox try-run against inline steps — for testing before first save."""
    result = await executor.try_run_draft(
        steps=body.steps_mapping,
        mock_payload=body.mock_payload,
        output_schema=body.output_schema or [],
    )
    if not result.success:
        return StandardResponse.error(message=result.error or "Try-run 失敗", data=result.model_dump())
    return StandardResponse.success(data=result.model_dump())


# ── Compiler Mode ─────────────────────────────────────────────────────────────

@router.post("/compile-steps", response_model=StandardResponse)
async def compile_steps(
    body: CompileStepsRequest,
    svc: SkillDefinitionService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    """LLM compiles user-defined NL steps into Python code + output_schema."""
    result = await svc.compile_steps(body)
    if not result.success:
        return StandardResponse.error(message=result.error or "AI 編譯失敗")
    return StandardResponse.success(data=result.model_dump())


# ── Agent-initiated build (backward compat) ───────────────────────────────────

@router.post("/agent-build", response_model=StandardResponse, status_code=201)
async def agent_build_skill(
    body: SkillAgentBuildRequest,
    svc: SkillDefinitionService = Depends(_get_svc),
    current_user: UserModel = Depends(get_current_user),
):
    """Agent-initiated: LLM generate steps → create Skill in one shot."""
    result = await svc.agent_build(body, created_by=current_user.id)
    if not result.success:
        return StandardResponse.error(message=result.error or "Skill 建立失敗", data={})
    return StandardResponse.success(data=result.model_dump(), message=f"Skill '{result.name}' 建立成功")
