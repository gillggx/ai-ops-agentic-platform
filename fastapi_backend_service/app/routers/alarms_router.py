"""Alarms router — v18 Alarm lifecycle management."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.database import get_db
from app.dependencies import get_current_user
from app.models.execution_log import ExecutionLogModel
from app.models.skill_definition import SkillDefinitionModel
from app.models.user import UserModel
from app.repositories.alarm_repository import AlarmRepository
from app.schemas.alarm import AlarmAcknowledgeRequest, AlarmResolveRequest
from app.services.alarm_service import AlarmService

router = APIRouter(prefix="/alarms", tags=["alarms"])


def _get_service(db: AsyncSession = Depends(get_db)) -> AlarmService:
    return AlarmService(repo=AlarmRepository(db))


@router.get("/stats", response_model=StandardResponse)
async def get_alarm_stats(
    days: int = Query(default=7, ge=1, le=90),
    svc: AlarmService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    """Severity counts for the homepage badge bar (CRITICAL / HIGH / MEDIUM / LOW)."""
    stats = await svc.get_stats(days=days)
    return StandardResponse.success(data=stats.model_dump())


@router.get("", response_model=StandardResponse)
async def list_alarms(
    status: Optional[str] = Query(default="active", description="active / acknowledged / resolved / all"),
    severity: Optional[str] = Query(default=None, description="LOW / MEDIUM / HIGH / CRITICAL"),
    equipment_id: Optional[str] = Query(default=None),
    lot_id: Optional[str] = Query(default=None),
    trigger_event: Optional[str] = Query(default=None),
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: UserModel = Depends(get_current_user),
):
    """List alarms with optional filters. Default: active alarms from last 7 days."""
    svc = AlarmService(repo=AlarmRepository(db))
    alarms = await svc.list_alarms(
        status=status,
        severity=severity,
        equipment_id=equipment_id,
        lot_id=lot_id,
        trigger_event=trigger_event,
        days=days,
        limit=limit,
        offset=offset,
    )

    # Collect all execution_log ids to fetch (AP logs + DR logs)
    all_log_ids = list({
        lid for a in alarms
        for lid in (a.execution_log_id, a.diagnostic_log_id) if lid
    })
    findings_map: dict = {}   # log_id → parsed findings dict
    if all_log_ids:
        log_rows = await db.execute(
            select(ExecutionLogModel).where(ExecutionLogModel.id.in_(all_log_ids))
        )
        for log in log_rows.scalars().all():
            try:
                findings_map[log.id] = json.loads(log.llm_readable_data) if log.llm_readable_data else None
            except Exception:
                findings_map[log.id] = None

    # Fetch output_schema for skill_ids that appear in logs
    # AP skill: alarm.skill_id; DR skill: diagnostic log's skill_id
    dr_log_skill_map: dict = {}   # dr_log_id → skill_id
    if all_log_ids:
        # Re-fetch logs to get their skill_ids (needed for DR output_schema)
        log_skill_rows = await db.execute(
            select(ExecutionLogModel.id, ExecutionLogModel.skill_id)
            .where(ExecutionLogModel.id.in_(all_log_ids))
        )
        for row in log_skill_rows.fetchall():
            dr_log_skill_map[row[0]] = row[1]

    all_skill_ids = list({sid for sid in dr_log_skill_map.values()} | {a.skill_id for a in alarms})
    schema_map: dict = {}   # skill_id → output_schema list
    if all_skill_ids:
        skill_rows = await db.execute(
            select(SkillDefinitionModel).where(SkillDefinitionModel.id.in_(all_skill_ids))
        )
        for skill in skill_rows.scalars().all():
            try:
                raw = skill.output_schema
                schema_map[skill.id] = json.loads(raw) if isinstance(raw, str) else (raw or [])
            except Exception:
                schema_map[skill.id] = []

    result = []
    for a in alarms:
        d = a.model_dump()
        if a.execution_log_id:
            d["findings"] = findings_map.get(a.execution_log_id)
            d["output_schema"] = schema_map.get(a.skill_id, [])
        if a.diagnostic_log_id:
            d["diagnostic_findings"] = findings_map.get(a.diagnostic_log_id)
            dr_skill_id = dr_log_skill_map.get(a.diagnostic_log_id)
            d["diagnostic_output_schema"] = schema_map.get(dr_skill_id, []) if dr_skill_id else []
        result.append(d)

    return StandardResponse.success(data=result)


@router.get("/{alarm_id}", response_model=StandardResponse)
async def get_alarm(
    alarm_id: int,
    svc: AlarmService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    alarm = await svc.get(alarm_id)
    return StandardResponse.success(data=alarm.model_dump())


@router.patch("/{alarm_id}/acknowledge", response_model=StandardResponse)
async def acknowledge_alarm(
    alarm_id: int,
    body: AlarmAcknowledgeRequest,
    svc: AlarmService = Depends(_get_service),
    current_user: UserModel = Depends(get_current_user),
):
    """Acknowledge an active alarm. Sets status → acknowledged."""
    operator = body.acknowledged_by or current_user.username
    alarm = await svc.acknowledge(alarm_id, acknowledged_by=operator)
    return StandardResponse.success(data=alarm.model_dump(), message="Alarm 已認領")


@router.patch("/{alarm_id}/resolve", response_model=StandardResponse)
async def resolve_alarm(
    alarm_id: int,
    body: AlarmResolveRequest = AlarmResolveRequest(),
    svc: AlarmService = Depends(_get_service),
    _: UserModel = Depends(get_current_user),
):
    """Resolve an alarm. Sets status → resolved."""
    alarm = await svc.resolve(alarm_id)
    return StandardResponse.success(data=alarm.model_dump(), message="Alarm 已解決")
