"""Diagnostic Rules router — /api/v1/diagnostic-rules."""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.schemas.diagnostic_rule import (
    DiagnosticRuleCreate,
    DiagnosticRuleUpdate,
    GenerateRuleStepsRequest,
    RuleTryRunDraftRequest,
    RuleTryRunRequest,
)
from app.services.diagnostic_rule_service import DiagnosticRuleService
from app.services.skill_executor_service import SkillExecutorService, build_mcp_executor
from app.utils.llm_client import get_llm_client

router = APIRouter(prefix="/diagnostic-rules", tags=["diagnostic-rules"])


def _get_svc(db: AsyncSession = Depends(get_db)) -> DiagnosticRuleService:
    return DiagnosticRuleService(
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
async def list_rules(
    svc: DiagnosticRuleService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    items = await svc.list_all()
    return StandardResponse.success(data=[i.model_dump() for i in items])


@router.post("", response_model=StandardResponse, status_code=201)
async def create_rule(
    body: DiagnosticRuleCreate,
    svc: DiagnosticRuleService = Depends(_get_svc),
    current_user: UserModel = Depends(get_current_user),
):
    item = await svc.create(body, created_by=current_user.id)
    return StandardResponse.success(data=item.model_dump(), message="Rule 建立成功")


@router.get("/{rule_id}", response_model=StandardResponse)
async def get_rule(
    rule_id: int,
    svc: DiagnosticRuleService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.get(rule_id)
    return StandardResponse.success(data=item.model_dump())


@router.patch("/{rule_id}", response_model=StandardResponse)
async def update_rule(
    rule_id: int,
    body: DiagnosticRuleUpdate,
    svc: DiagnosticRuleService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.update(rule_id, body)
    return StandardResponse.success(data=item.model_dump(), message="Rule 更新成功")


@router.delete("/{rule_id}", response_model=StandardResponse)
async def delete_rule(
    rule_id: int,
    svc: DiagnosticRuleService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    await svc.delete(rule_id)
    return StandardResponse.success(message="Rule 刪除成功")


# ── LLM Builder ───────────────────────────────────────────────────────────────

@router.post("/generate-steps/stream")
async def generate_steps_stream(
    body: GenerateRuleStepsRequest,
    svc: DiagnosticRuleService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    """SSE: two-phase streaming generation — Phase 1 plans MCPs, Phase 2 generates code."""
    return StreamingResponse(
        svc.generate_steps_stream(body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/generate-steps", response_model=StandardResponse)
async def generate_steps(
    body: GenerateRuleStepsRequest,
    svc: DiagnosticRuleService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    """Non-streaming fallback — collects stream and returns final result."""
    result = await svc.generate_steps(body)
    if not result.success:
        return StandardResponse.error(message=result.error or "LLM 生成失敗")
    return StandardResponse.success(data=result.model_dump())


# ── Sandbox / Try-Run ─────────────────────────────────────────────────────────

@router.post("/{rule_id}/try-run", response_model=StandardResponse)
async def try_run_rule(
    rule_id: int,
    body: RuleTryRunRequest = RuleTryRunRequest(),
    executor: SkillExecutorService = Depends(_get_executor),
    _: UserModel = Depends(get_current_user),
):
    """Sandbox try-run with mock event payload — returns SkillFindings."""
    result = await executor.try_run(skill_id=rule_id, mock_payload=body.mock_payload)
    return StandardResponse.success(data=result.model_dump())


@router.post("/{rule_id}/fix", response_model=StandardResponse)
async def fix_rule(
    rule_id: int,
    body: dict,
    svc: DiagnosticRuleService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    """LLM auto-fix: regenerate steps based on error message + optional user feedback."""
    result = await svc.fix_skill(
        rule_id=rule_id,
        error_message=body.get("error_message", ""),
        user_feedback=body.get("user_feedback", ""),
    )
    return StandardResponse.success(data=result)


@router.post("/try-run-draft", response_model=StandardResponse)
async def try_run_draft(
    body: RuleTryRunDraftRequest,
    executor: SkillExecutorService = Depends(_get_executor),
    _: UserModel = Depends(get_current_user),
):
    """Sandbox try-run against inline steps — for testing before first save."""
    result = await executor.try_run_draft(
        steps=body.steps_mapping,
        mock_payload=body.mock_payload,
        output_schema=body.output_schema or [],
    )
    return StandardResponse.success(data=result.model_dump())
