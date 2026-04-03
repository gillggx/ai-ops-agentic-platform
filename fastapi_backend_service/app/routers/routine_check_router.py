"""Routine Check CRUD router (Phase 11 v2 — RoutineCheck as bridge)."""

import json

from fastapi import APIRouter, Depends, HTTPException, status, Request

from app.core.response import StandardResponse
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.routine_check_repository import RoutineCheckRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.repositories.event_type_repository import EventTypeRepository
from app.schemas.routine_check import (
    RoutineCheckCreate,
    RoutineCheckResponse,
    RoutineCheckRunResponse,
    RoutineCheckUpdate,
)
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/routine-checks", tags=["routine-checks"])


def _to_response(obj) -> RoutineCheckResponse:
    """Convert ORM model to response schema, deserialising JSON fields."""
    skill_input = {}
    if obj.skill_input:
        try:
            skill_input = json.loads(obj.skill_input)
        except Exception:
            skill_input = {}
    event_param_mappings = None
    if obj.event_param_mappings:
        try:
            event_param_mappings = json.loads(obj.event_param_mappings)
        except Exception:
            event_param_mappings = None
    return RoutineCheckResponse(
        id=obj.id,
        name=obj.name,
        skill_id=obj.skill_id,
        skill_input=skill_input,
        trigger_event_id=obj.trigger_event_id,
        event_param_mappings=event_param_mappings,
        schedule_interval=obj.schedule_interval,
        is_active=obj.is_active,
        last_run_at=obj.last_run_at,
        last_run_status=obj.last_run_status,
        expire_at=getattr(obj, 'expire_at', None),
        schedule_time=getattr(obj, 'schedule_time', None),
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


@router.get("", summary="列出所有排程巡檢", response_model=StandardResponse)
async def list_routine_checks(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    repo = RoutineCheckRepository(db)
    items = await repo.get_all()
    return StandardResponse.success(data=[_to_response(i).model_dump() for i in items])


@router.post("", summary="建立排程巡檢", response_model=StandardResponse, status_code=status.HTTP_201_CREATED)
async def create_routine_check(
    body: RoutineCheckCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    # Verify skill exists
    skill_repo = SkillDefinitionRepository(db)
    skill = await skill_repo.get_by_id(body.skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill id={body.skill_id} 不存在")

    # Auto-create EventType from the Skill's last_diagnosis_result.check_output_schema
    trigger_event_id = None
    event_param_mappings = None

    schema_fields = []
    if skill.last_diagnosis_result:
        try:
            ldr = json.loads(skill.last_diagnosis_result)
            schema_fields = (ldr.get("check_output_schema") or {}).get("fields", [])
        except Exception:
            schema_fields = []

    if schema_fields:
        event_name = body.generated_event_name or f"{body.name} 異常警報"
        attributes = [
            {
                "name": f["name"],
                "type": f.get("type", "string"),
                "description": f.get("description", f["name"]),
                "required": False,
            }
            for f in schema_fields
        ]
        et_repo = EventTypeRepository(db)
        new_et = await et_repo.create(
            name=event_name,
            description=f"由排程巡檢「{body.name}」自動建立",
            attributes=attributes,
        )
        trigger_event_id = new_et.id
        # Identity mapping: event attribute name == Skill output field name
        event_param_mappings = [
            {"event_field": f["name"], "mcp_field": f["name"]} for f in schema_fields
        ]

    repo = RoutineCheckRepository(db)
    obj = await repo.create(
        name=body.name,
        skill_id=body.skill_id,
        skill_input=body.skill_input,
        trigger_event_id=trigger_event_id,
        event_param_mappings=event_param_mappings,
        schedule_interval=body.schedule_interval,
        is_active=body.is_active,
        expire_at=body.expire_at,
        schedule_time=body.schedule_time,
    )

    if body.is_active:
        from app.scheduler import schedule_check
        schedule_check(obj.id, obj.schedule_interval)

    return StandardResponse.success(data=_to_response(obj).model_dump())


@router.get("/{check_id}", summary="取得排程巡檢", response_model=StandardResponse)
async def get_routine_check(
    check_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    repo = RoutineCheckRepository(db)
    obj = await repo.get_by_id(check_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"RoutineCheck id={check_id} 不存在")
    return StandardResponse.success(data=_to_response(obj).model_dump())


@router.put("/{check_id}", summary="更新排程巡檢", response_model=StandardResponse)
async def update_routine_check(
    check_id: int,
    body: RoutineCheckUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    repo = RoutineCheckRepository(db)
    obj = await repo.get_by_id(check_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"RoutineCheck id={check_id} 不存在")

    # Verify trigger event type if being changed
    if body.trigger_event_id is not None:
        et_repo = EventTypeRepository(db)
        et = await et_repo.get_by_id(body.trigger_event_id)
        if et is None:
            raise HTTPException(status_code=404, detail=f"EventType id={body.trigger_event_id} 不存在")

    update_data = body.model_dump(exclude_none=True)
    obj = await repo.update(obj, **update_data)

    from app.scheduler import schedule_check, unschedule_check
    if obj.is_active:
        schedule_check(obj.id, obj.schedule_interval)
    else:
        unschedule_check(obj.id)

    return StandardResponse.success(data=_to_response(obj).model_dump())


@router.delete("/{check_id}", summary="刪除排程巡檢", response_model=StandardResponse)
async def delete_routine_check(
    check_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    repo = RoutineCheckRepository(db)
    obj = await repo.get_by_id(check_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"RoutineCheck id={check_id} 不存在")

    from app.scheduler import unschedule_check
    unschedule_check(check_id)

    await repo.delete(obj)
    return StandardResponse.success(data={"deleted_id": check_id})


@router.post("/{check_id}/run-now", summary="立即執行巡檢", response_model=StandardResponse)
async def run_now(
    check_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """Manually trigger a RoutineCheck job immediately (outside its schedule)."""
    repo = RoutineCheckRepository(db)
    obj = await repo.get_by_id(check_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"RoutineCheck id={check_id} 不存在")

    base_url = str(request.base_url).rstrip("/")
    from app.scheduler import run_routine_check_job
    result = await run_routine_check_job(check_id, base_url=base_url)

    return StandardResponse.success(data=result)
