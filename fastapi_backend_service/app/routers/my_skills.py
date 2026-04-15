"""My Skills router — /api/v1/my-skills.

User-created Skills (source='skill') for Agent chat.
Reuses DiagnosticRuleService's generate_steps pipeline for LLM code generation.
"""

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.services.diagnostic_rule_service import DiagnosticRuleService
from app.services.skill_executor_service import SkillExecutorService, build_mcp_executor
from app.utils.llm_client import get_llm_client

router = APIRouter(prefix="/my-skills", tags=["my-skills"])

_SOURCE = "skill"


# ── Schemas ──────────────────────────────────────────────────────────────────

class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    auto_check_description: str = Field(default="", description="Skill 用途描述 (Agent 從 catalog 判斷何時使用)")
    steps_mapping: List[Dict[str, Any]] = Field(default_factory=list)
    input_schema: List[Dict[str, Any]] = Field(default_factory=list)
    output_schema: List[Dict[str, Any]] = Field(default_factory=list)


class SkillFromPipelineRequest(BaseModel):
    """Save a completed pipeline as a My Skill."""
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    pipeline_plan: Dict[str, Any] = Field(..., description="LLM plan from Stage 2")
    transform_code: Optional[str] = Field(default=None, description="Stage 4 generated code")
    compute_code: Optional[str] = Field(default=None, description="Stage 5 generated code")
    input_schema: List[Dict[str, Any]] = Field(default_factory=list)
    output_schema: List[Dict[str, Any]] = Field(default_factory=list)


class SkillUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    auto_check_description: Optional[str] = None
    steps_mapping: Optional[List[Dict[str, Any]]] = None
    input_schema: Optional[List[Dict[str, Any]]] = None
    output_schema: Optional[List[Dict[str, Any]]] = None
    is_active: Optional[bool] = None
    binding_type: Optional[str] = Field(default=None, pattern="^(none|event|alarm)$")


class SkillBindRequest(BaseModel):
    """Upgrade a Skill to Auto-Patrol or Diagnostic Rule."""
    binding_type: str = Field(..., pattern="^(none|event|alarm)$")
    trigger_event_id: Optional[int] = None
    alarm_severity: Optional[str] = None
    trigger_patrol_id: Optional[int] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_dict(obj) -> Dict[str, Any]:
    """Convert SkillDefinitionModel to response dict."""
    def _j(s):
        if not s:
            return []
        try:
            return json.loads(s) if isinstance(s, str) else s
        except Exception:
            return []

    return {
        "id": obj.id,
        "name": obj.name,
        "description": obj.description,
        "auto_check_description": obj.auto_check_description,
        "steps_mapping": _j(obj.steps_mapping),
        "input_schema": _j(obj.input_schema),
        "output_schema": _j(obj.output_schema),
        "visibility": obj.visibility,
        "is_active": obj.is_active,
        "source": obj.source,
        "pipeline_config": _j(obj.pipeline_config) if obj.pipeline_config else None,
        "binding_type": getattr(obj, "binding_type", "none"),
        "trigger_mode": obj.trigger_mode,
        "created_by": obj.created_by,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
        "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
    }


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=StandardResponse)
async def list_skills(
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    repo = SkillDefinitionRepository(db)
    objs = await repo.list_by_source(_SOURCE)
    return StandardResponse.success(data=[_to_dict(o) for o in objs])


@router.post("", response_model=StandardResponse, status_code=201)
async def create_skill(
    body: SkillCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    repo = SkillDefinitionRepository(db)
    obj = await repo.create({
        **body.model_dump(),
        "source": _SOURCE,
        "binding_type": "none",
        "trigger_mode": "manual",
        "visibility": "public",
        "created_by": current_user.id,
    })
    return StandardResponse.success(data=_to_dict(obj), message="Skill 建立成功")


@router.post("/from-pipeline", response_model=StandardResponse, status_code=201)
async def create_skill_from_pipeline(
    body: SkillFromPipelineRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """Save a completed pipeline (Stage 3~6) as a My Skill."""
    repo = SkillDefinitionRepository(db)

    # Build pipeline_config from plan + generated code
    pipeline_config = dict(body.pipeline_plan)
    if body.transform_code:
        pipeline_config.setdefault("data_transform", {})["code"] = body.transform_code
    if body.compute_code:
        pipeline_config.setdefault("compute", {})["code"] = body.compute_code

    # Auto-derive input_schema from data_retrieval.params if not provided
    input_schema = body.input_schema
    if not input_schema:
        retrieval_params = (body.pipeline_plan.get("data_retrieval") or {}).get("params", {})
        input_schema = [
            {"key": k, "type": "string", "required": True, "description": f"Pipeline param: {k}"}
            for k, v in retrieval_params.items() if v
        ]

    obj = await repo.create({
        "name": body.name,
        "description": body.description or f"Pipeline Skill: {body.name}",
        "auto_check_description": body.description or body.name,
        "steps_mapping": [],
        "input_schema": input_schema,
        "output_schema": body.output_schema,
        "pipeline_config": pipeline_config,
        "source": _SOURCE,
        "binding_type": "none",
        "trigger_mode": "manual",
        "visibility": "public",
        "created_by": current_user.id,
    })
    return StandardResponse.success(data=_to_dict(obj), message="Pipeline Skill 儲存成功")


@router.get("/{skill_id}", response_model=StandardResponse)
async def get_skill(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    repo = SkillDefinitionRepository(db)
    obj = await repo.get_by_id(skill_id)
    if not obj or obj.source != _SOURCE:
        return StandardResponse.error(message=f"Skill id={skill_id} 不存在", status_code=404)
    return StandardResponse.success(data=_to_dict(obj))


@router.patch("/{skill_id}", response_model=StandardResponse)
async def update_skill(
    skill_id: int,
    body: SkillUpdate,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    repo = SkillDefinitionRepository(db)
    obj = await repo.get_by_id(skill_id)
    if not obj or obj.source != _SOURCE:
        return StandardResponse.error(message=f"Skill id={skill_id} 不存在", status_code=404)
    updated = await repo.update(skill_id, body.model_dump(exclude_none=True))
    return StandardResponse.success(data=_to_dict(updated), message="Skill 更新成功")


@router.delete("/{skill_id}", response_model=StandardResponse)
async def delete_skill(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    repo = SkillDefinitionRepository(db)
    obj = await repo.get_by_id(skill_id)
    if not obj or obj.source != _SOURCE:
        return StandardResponse.error(message=f"Skill id={skill_id} 不存在", status_code=404)
    await repo.delete(skill_id)
    return StandardResponse.success(message="Skill 刪除成功")


# ── LLM Generation (reuse DiagnosticRuleService pipeline) ────────────────────

@router.post("/generate-steps/stream")
async def generate_steps_stream(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    """SSE: two-phase streaming generation — same pipeline as Diagnostic Rules."""
    from app.schemas.diagnostic_rule import GenerateRuleStepsRequest
    svc = DiagnosticRuleService(
        repo=SkillDefinitionRepository(db),
        db=db,
        llm=get_llm_client(),
    )
    req = GenerateRuleStepsRequest(
        auto_check_description=body.get("description", ""),
        patrol_context=None,  # My Skill — no patrol context
        skip_clarify=body.get("skip_clarify", False),
    )
    return StreamingResponse(
        svc.generate_steps_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Try-Run ──────────────────────────────────────────────────────────────────

@router.post("/{skill_id}/try-run", response_model=StandardResponse)
async def try_run_skill(
    skill_id: int,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    settings = get_settings()
    executor = SkillExecutorService(
        skill_repo=SkillDefinitionRepository(db),
        mcp_executor=build_mcp_executor(db, sim_url=settings.ONTOLOGY_SIM_URL),
    )
    mock_payload = body.get("mock_payload", {
        "equipment_id": "EQP-01",
        "lot_id": "LOT-0001",
        "step": "STEP_020",
    })
    result = await executor.try_run(skill_id=skill_id, mock_payload=mock_payload)
    return StandardResponse.success(data=result.model_dump())


@router.post("/try-run-draft", response_model=StandardResponse)
async def try_run_draft(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    settings = get_settings()
    executor = SkillExecutorService(
        skill_repo=SkillDefinitionRepository(db),
        mcp_executor=build_mcp_executor(db, sim_url=settings.ONTOLOGY_SIM_URL),
    )
    result = await executor.try_run_draft(
        steps=body.get("steps_mapping", []),
        mock_payload=body.get("mock_payload", {}),
        output_schema=body.get("output_schema", []),
    )
    return StandardResponse.success(data=result.model_dump())


# ── Fix (LLM auto-fix) ──────────────────────────────────────────────────────

@router.post("/{skill_id}/fix", response_model=StandardResponse)
async def fix_skill(
    skill_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    svc = DiagnosticRuleService(
        repo=SkillDefinitionRepository(db),
        db=db,
        llm=get_llm_client(),
    )
    result = await svc.fix_skill(
        rule_id=skill_id,
        error_message=body.get("error_message", ""),
        user_feedback=body.get("user_feedback", ""),
    )
    return StandardResponse.success(data=result)


# ── Binding (upgrade to Auto-Patrol / Diagnostic Rule) ───────────────────────

@router.post("/{skill_id}/bind", response_model=StandardResponse)
async def bind_skill(
    skill_id: int,
    body: SkillBindRequest,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    """Change a Skill's binding_type to upgrade it to Auto-Patrol or Diagnostic Rule."""
    repo = SkillDefinitionRepository(db)
    obj = await repo.get_by_id(skill_id)
    if not obj:
        return StandardResponse.error(message=f"Skill id={skill_id} 不存在", status_code=404)

    update_data: Dict[str, Any] = {"binding_type": body.binding_type}

    if body.binding_type == "event":
        # Validate: input_schema must have event-compatible fields
        input_schema = json.loads(obj.input_schema) if isinstance(obj.input_schema, str) else obj.input_schema or []
        event_fields = {"equipment_id", "lot_id", "step", "event_time"}
        required_event = [
            f for f in input_schema
            if f.get("required") and f.get("source") == "event" and f.get("key") not in event_fields
        ]
        if required_event:
            missing = [f["key"] for f in required_event]
            return StandardResponse.error(
                message=f"無法升級為 Auto-Patrol：以下必要參數無法從事件自動取得: {missing}"
            )
        update_data["trigger_mode"] = "event"
        if body.trigger_event_id:
            update_data["trigger_event_id"] = body.trigger_event_id

    elif body.binding_type == "alarm":
        update_data["trigger_mode"] = "event"
        if body.trigger_patrol_id:
            update_data["trigger_patrol_id"] = body.trigger_patrol_id

    elif body.binding_type == "none":
        update_data["trigger_mode"] = "manual"

    updated = await repo.update(skill_id, update_data)
    return StandardResponse.success(
        data=_to_dict(updated),
        message=f"Skill 已更新為 {body.binding_type}",
    )
