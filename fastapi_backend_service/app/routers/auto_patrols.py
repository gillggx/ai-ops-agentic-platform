"""Auto-Patrol router v2.0 — CRUD + manual trigger endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.alarm_repository import AlarmRepository
from app.repositories.auto_patrol_repository import AutoPatrolRepository
from app.repositories.execution_log_repository import ExecutionLogRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.schemas.auto_patrol import AutoPatrolCreate, AutoPatrolTriggerRequest, AutoPatrolUpdate
from app.services.auto_patrol_service import AutoPatrolService
from app.services.skill_executor_service import SkillExecutorService, build_mcp_executor
from app.config import get_settings

router = APIRouter(prefix="/auto-patrols", tags=["auto-patrols"])


def _get_svc(db: AsyncSession = Depends(get_db)) -> AutoPatrolService:
    settings = get_settings()
    executor = SkillExecutorService(
        skill_repo=SkillDefinitionRepository(db),
        mcp_executor=build_mcp_executor(db, sim_url=settings.ONTOLOGY_SIM_URL),
    )
    return AutoPatrolService(
        repo=AutoPatrolRepository(db),
        alarm_repo=AlarmRepository(db),
        executor=executor,
        sim_url=settings.ONTOLOGY_SIM_URL,
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=StandardResponse)
async def list_patrols(
    active_only: bool = False,
    svc: AutoPatrolService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    items = await svc.list_all(active_only=active_only)
    return StandardResponse.success(data=items)


@router.post("", response_model=StandardResponse, status_code=201)
async def create_patrol(
    body: AutoPatrolCreate,
    svc: AutoPatrolService = Depends(_get_svc),
    current_user: UserModel = Depends(get_current_user),
):
    try:
        item = await svc.create(body, created_by=current_user.id)
        return StandardResponse.success(data=item, message="Auto-Patrol 建立成功")
    except ValueError as e:
        return StandardResponse.error(message=str(e))


@router.get("/{patrol_id}", response_model=StandardResponse)
async def get_patrol(
    patrol_id: int,
    svc: AutoPatrolService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    try:
        item = await svc.get(patrol_id)
        return StandardResponse.success(data=item)
    except ValueError as e:
        return StandardResponse.error(message=str(e))


@router.patch("/{patrol_id}", response_model=StandardResponse)
async def update_patrol(
    patrol_id: int,
    body: AutoPatrolUpdate,
    svc: AutoPatrolService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    try:
        item = await svc.update(patrol_id, body)
        return StandardResponse.success(data=item, message="Auto-Patrol 更新成功")
    except ValueError as e:
        return StandardResponse.error(message=str(e))


@router.delete("/{patrol_id}", response_model=StandardResponse)
async def delete_patrol(
    patrol_id: int,
    svc: AutoPatrolService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    try:
        await svc.delete(patrol_id)
        return StandardResponse.success(message="Auto-Patrol 刪除成功")
    except ValueError as e:
        return StandardResponse.error(message=str(e))


# ── Execution History ─────────────────────────────────────────────────────────

@router.get("/{patrol_id}/executions", response_model=StandardResponse)
async def list_executions(
    patrol_id: int,
    limit: int = 100,
    since: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    """Return execution log entries for this Auto-Patrol, optionally filtered by start time."""
    import json as _json
    from datetime import datetime, timezone
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            pass

    # Fetch output_schema from the patrol's skill so the frontend can render charts
    output_schema = []
    patrol_repo = AutoPatrolRepository(db)
    patrol = await patrol_repo.get_by_id(patrol_id)
    if patrol:
        skill_repo = SkillDefinitionRepository(db)
        skill = await skill_repo.get_by_id(patrol.skill_id)
        if skill and skill.output_schema:
            try:
                raw = skill.output_schema
                output_schema = _json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                output_schema = []

    log_repo = ExecutionLogRepository(db)
    rows = await log_repo.get_by_auto_patrol(patrol_id, limit=limit, since=since_dt)
    data = [
        {
            "id":             r.id,
            "triggered_by":   r.triggered_by,
            "status":         r.status,
            "started_at":     r.started_at.isoformat() if r.started_at else None,
            "finished_at":    r.finished_at.isoformat() if r.finished_at else None,
            "duration_ms":    r.duration_ms,
            "findings":       _json.loads(r.llm_readable_data) if r.llm_readable_data else None,
            "event_context":  _json.loads(r.event_context) if r.event_context else None,
            "error_message":  r.error_message,
            "output_schema":  output_schema,
        }
        for r in rows
    ]
    return StandardResponse.success(data=data)


# ── Manual Trigger ─────────────────────────────────────────────────────────────

@router.post("/{patrol_id}/trigger", response_model=StandardResponse)
async def trigger_patrol(
    patrol_id: int,
    body: AutoPatrolTriggerRequest = AutoPatrolTriggerRequest(),
    svc: AutoPatrolService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    """Manually trigger an Auto-Patrol — runs the Skill and decides alarm."""
    result = await svc.trigger(patrol_id=patrol_id, event_payload=body.event_payload)
    if result.error:
        return StandardResponse.error(message=result.error, data=result.model_dump())
    return StandardResponse.success(data=result.model_dump(), message="Auto-Patrol 執行完成")
