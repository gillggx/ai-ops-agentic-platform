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

    # ── Fetch ALL DR logs per alarm via triggered_by=f"alarm:<id>" ─────────────
    # (alarm.diagnostic_log_id is a scalar and only stores the LAST DR run;
    #  when a patrol has N bound DRs, only the last would display. Here we
    #  query ExecutionLog directly to get every DR run linked to each alarm.)
    alarm_ids = [a.id for a in alarms]
    dr_logs_by_alarm: dict = {aid: [] for aid in alarm_ids}  # alarm_id → [ExecutionLog]
    if alarm_ids:
        triggered_by_values = [f"alarm:{aid}" for aid in alarm_ids]
        dr_log_rows = await db.execute(
            select(ExecutionLogModel)
            .where(ExecutionLogModel.triggered_by.in_(triggered_by_values))
            .order_by(ExecutionLogModel.id)
        )
        for log in dr_log_rows.scalars().all():
            # triggered_by is "alarm:<id>" — strip prefix
            try:
                aid = int(log.triggered_by.split(":", 1)[1])
                dr_logs_by_alarm.setdefault(aid, []).append(log)
            except Exception:
                pass

    # Collect all execution_log ids to fetch findings for (AP logs + DR logs)
    all_log_ids = set()
    for a in alarms:
        if a.execution_log_id:
            all_log_ids.add(a.execution_log_id)
        if a.diagnostic_log_id:  # legacy back-compat
            all_log_ids.add(a.diagnostic_log_id)
    for logs in dr_logs_by_alarm.values():
        for log in logs:
            all_log_ids.add(log.id)

    findings_map: dict = {}   # log_id → parsed findings dict
    log_skill_map: dict = {}  # log_id → skill_id
    if all_log_ids:
        log_rows = await db.execute(
            select(ExecutionLogModel).where(ExecutionLogModel.id.in_(all_log_ids))
        )
        for log in log_rows.scalars().all():
            try:
                findings_map[log.id] = json.loads(log.llm_readable_data) if log.llm_readable_data else None
            except Exception:
                findings_map[log.id] = None
            log_skill_map[log.id] = log.skill_id

    # Fetch skill info (name + output_schema) for all skill_ids we'll reference
    all_skill_ids = set()
    for a in alarms:
        all_skill_ids.add(a.skill_id)
    for sid in log_skill_map.values():
        all_skill_ids.add(sid)
    schema_map: dict = {}       # skill_id → output_schema list
    skill_name_map: dict = {}   # skill_id → name
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
            skill_name_map[skill.id] = skill.name

    # Run ChartMiddleware per DR finding to produce chart DSL
    from app.services.chart_middleware import process as chart_process

    def _build_dr_entry(log) -> dict:
        sid = log_skill_map.get(log.id)
        findings = findings_map.get(log.id) or {}
        output_schema = schema_map.get(sid, []) if sid else []
        outputs = (findings.get("outputs") or {}) if isinstance(findings, dict) else {}
        charts = chart_process(outputs, output_schema) if outputs and output_schema else []
        return {
            "log_id": log.id,
            "skill_id": sid,
            "skill_name": skill_name_map.get(sid, ""),
            "status": log.status,
            "findings": findings,
            "output_schema": output_schema,
            "charts": charts,
        }

    result = []
    for a in alarms:
        d = a.model_dump()
        if a.execution_log_id:
            d["findings"] = findings_map.get(a.execution_log_id)
            d["output_schema"] = schema_map.get(a.skill_id, [])
            # Auto-generate charts for the Auto-Patrol findings too
            ap_outputs = (d["findings"] or {}).get("outputs") if d.get("findings") else None
            if ap_outputs:
                d["charts"] = chart_process(ap_outputs, d["output_schema"] or [])
        # New: full list of DR results (one entry per bound Diagnostic Rule)
        d["diagnostic_results"] = [_build_dr_entry(l) for l in dr_logs_by_alarm.get(a.id, [])]
        # Legacy single-DR fields (back-compat) — still populated from alarm.diagnostic_log_id
        if a.diagnostic_log_id:
            d["diagnostic_findings"] = findings_map.get(a.diagnostic_log_id)
            dr_skill_id = log_skill_map.get(a.diagnostic_log_id)
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
