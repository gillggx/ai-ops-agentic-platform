"""AlarmRepository — CRUD for the alarms table."""

from datetime import datetime, timezone, timedelta
from typing import List, Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alarm import AlarmModel


class AlarmRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        skill_id: int,
        trigger_event: str,
        equipment_id: str,
        lot_id: str,
        step: Optional[str],
        event_time: Optional[datetime],
        severity: str,
        title: str,
        summary: Optional[str] = None,
        execution_log_id: Optional[int] = None,
    ) -> AlarmModel:
        alarm = AlarmModel(
            skill_id=skill_id,
            trigger_event=trigger_event,
            equipment_id=equipment_id,
            lot_id=lot_id,
            step=step,
            event_time=event_time,
            severity=severity.upper(),
            title=title,
            summary=summary,
            status="active",
            execution_log_id=execution_log_id,
        )
        self._db.add(alarm)
        await self._db.commit()
        await self._db.refresh(alarm)
        return alarm

    async def list_alarms(
        self,
        status: Optional[str] = "active",
        severity: Optional[str] = None,
        equipment_id: Optional[str] = None,
        lot_id: Optional[str] = None,
        trigger_event: Optional[str] = None,
        days: int = 7,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AlarmModel]:
        q = select(AlarmModel)
        since = datetime.now(tz=timezone.utc) - timedelta(days=days)
        q = q.where(AlarmModel.created_at >= since)
        if status and status != "all":
            q = q.where(AlarmModel.status == status)
        if severity:
            q = q.where(AlarmModel.severity == severity.upper())
        if equipment_id:
            q = q.where(AlarmModel.equipment_id == equipment_id)
        if lot_id:
            q = q.where(AlarmModel.lot_id == lot_id)
        if trigger_event:
            q = q.where(AlarmModel.trigger_event == trigger_event)
        q = q.order_by(AlarmModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._db.execute(q)
        return list(result.scalars().all())

    async def get_by_id(self, alarm_id: int) -> Optional[AlarmModel]:
        result = await self._db.execute(
            select(AlarmModel).where(AlarmModel.id == alarm_id)
        )
        return result.scalar_one_or_none()

    async def set_diagnostic_log(self, alarm_id: int, diagnostic_log_id: int) -> None:
        """Link a Diagnostic Rule execution log to an alarm."""
        alarm = await self.get_by_id(alarm_id)
        if alarm:
            alarm.diagnostic_log_id = diagnostic_log_id
            await self._db.commit()

    async def acknowledge(self, alarm_id: int, acknowledged_by: str) -> Optional[AlarmModel]:
        alarm = await self.get_by_id(alarm_id)
        if not alarm:
            return None
        alarm.status = "acknowledged"
        alarm.acknowledged_by = acknowledged_by
        alarm.acknowledged_at = datetime.now(tz=timezone.utc)
        await self._db.commit()
        await self._db.refresh(alarm)
        return alarm

    async def resolve(self, alarm_id: int) -> Optional[AlarmModel]:
        alarm = await self.get_by_id(alarm_id)
        if not alarm:
            return None
        alarm.status = "resolved"
        alarm.resolved_at = datetime.now(tz=timezone.utc)
        await self._db.commit()
        await self._db.refresh(alarm)
        return alarm

    async def get_stats(self, days: int = 7) -> dict:
        """Count active alarms by severity for the homepage badge bar."""
        since = datetime.now(tz=timezone.utc) - timedelta(days=days)
        result = await self._db.execute(
            select(AlarmModel.severity, func.count(AlarmModel.id))
            .where(AlarmModel.status == "active")
            .where(AlarmModel.created_at >= since)
            .group_by(AlarmModel.severity)
        )
        counts = {row[0]: row[1] for row in result.fetchall()}
        total = sum(counts.values())
        return {
            "critical": counts.get("CRITICAL", 0),
            "high": counts.get("HIGH", 0),
            "medium": counts.get("MEDIUM", 0),
            "low": counts.get("LOW", 0),
            "total_active": total,
        }
