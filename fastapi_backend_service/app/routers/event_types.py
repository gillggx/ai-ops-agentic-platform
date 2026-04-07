"""Event Type CRUD router."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.nats_event_log import NatsEventLogModel
from app.models.user import UserModel
from app.repositories.event_type_repository import EventTypeRepository
from app.schemas.event_type import EventTypeCreate, EventTypeUpdate
from app.services.event_type_service import EventTypeService

router = APIRouter(prefix="/event-types", tags=["event-types"])


def _get_service(db: AsyncSession = Depends(get_db)) -> EventTypeService:
    return EventTypeService(EventTypeRepository(db))


@router.get("", response_model=StandardResponse)
async def list_event_types(
    svc: EventTypeService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    items = await svc.list_all()
    return StandardResponse.success(data=[i.model_dump() for i in items])


@router.get("/{et_id}", response_model=StandardResponse)
async def get_event_type(
    et_id: int,
    svc: EventTypeService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.get(et_id)
    return StandardResponse.success(data=item.model_dump())


@router.post("", response_model=StandardResponse, status_code=201)
async def create_event_type(
    body: EventTypeCreate,
    svc: EventTypeService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.create(body)
    return StandardResponse.success(data=item.model_dump(), message="EventType 建立成功")


@router.patch("/{et_id}", response_model=StandardResponse)
async def update_event_type(
    et_id: int,
    body: EventTypeUpdate,
    svc: EventTypeService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    item = await svc.update(et_id, body)
    return StandardResponse.success(data=item.model_dump(), message="EventType 更新成功")


@router.delete("/{et_id}", response_model=StandardResponse)
async def delete_event_type(
    et_id: int,
    svc: EventTypeService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    await svc.delete(et_id)
    return StandardResponse.success(message="EventType 刪除成功")


@router.get("/{name}/log", response_model=StandardResponse)
async def get_event_log(
    name: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    """Return event detection + skill execution history for an event type.

    Merges two sources:
    - nats_event_log: events received via NATS/webhook
    - execution_logs: skill executions triggered by event_poller for this event type
    """
    import json as _json

    # ── Source 1: NATS event log (legacy) ─────────────────────────────
    nats_total_result = await db.execute(
        select(func.count()).where(NatsEventLogModel.event_type_name == name)
    )
    nats_total: int = nats_total_result.scalar_one()

    # ── Source 2: Execution logs from event_poller ────────────────────
    # Find skills bound to this event type
    from app.models.event_type import EventTypeModel
    from app.models.execution_log import ExecutionLogModel
    from app.models.skill_definition import SkillDefinitionModel

    et_result = await db.execute(
        select(EventTypeModel).where(EventTypeModel.name == name)
    )
    et = et_result.scalar_one_or_none()

    exec_logs = []
    exec_total = 0
    if et:
        # Count all poller executions for skills bound to this event type
        exec_count_result = await db.execute(
            select(func.count())
            .select_from(ExecutionLogModel)
            .join(SkillDefinitionModel, ExecutionLogModel.skill_id == SkillDefinitionModel.id)
            .where(SkillDefinitionModel.trigger_event_id == et.id)
            .where(ExecutionLogModel.triggered_by == "event_poller")
        )
        exec_total = exec_count_result.scalar_one()

        # Recent execution logs
        exec_result = await db.execute(
            select(ExecutionLogModel, SkillDefinitionModel.name.label("skill_name"))
            .join(SkillDefinitionModel, ExecutionLogModel.skill_id == SkillDefinitionModel.id)
            .where(SkillDefinitionModel.trigger_event_id == et.id)
            .where(ExecutionLogModel.triggered_by == "event_poller")
            .order_by(ExecutionLogModel.started_at.desc())
            .limit(limit)
        )
        for row in exec_result:
            log = row[0]
            skill_name = row[1]
            ctx = {}
            if log.event_context:
                try:
                    ctx = _json.loads(log.event_context)
                except Exception:
                    pass
            llm_data = {}
            if log.llm_readable_data:
                try:
                    llm_data = _json.loads(log.llm_readable_data)
                except Exception:
                    pass
            exec_logs.append({
                "id": log.id,
                "skill_id": log.skill_id,
                "skill_name": skill_name,
                "equipment_id": ctx.get("equipment_id", ""),
                "lot_id": ctx.get("lot_id", ""),
                "step": ctx.get("step", ""),
                "condition_met": llm_data.get("condition_met", None),
                "summary": llm_data.get("summary", ""),
                "action": log.action_dispatched,
                "status": log.status,
                "duration_ms": log.duration_ms,
                "started_at": log.started_at.isoformat() if log.started_at else None,
            })

    return StandardResponse.success(data={
        "event_type_name": name,
        "total": nats_total + exec_total,
        "nats_total": nats_total,
        "poller_total": exec_total,
        "recent": exec_logs,
    })
