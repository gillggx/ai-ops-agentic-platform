"""Repository for ExecutionLog — append-only, no updates."""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution_log import ExecutionLogModel


class ExecutionLogRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_skill(self, skill_id: int, limit: int = 50) -> List[ExecutionLogModel]:
        result = await self._db.execute(
            select(ExecutionLogModel)
            .where(ExecutionLogModel.skill_id == skill_id)
            .order_by(ExecutionLogModel.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_auto_patrol(
        self,
        auto_patrol_id: int,
        limit: int = 100,
        since: Optional[datetime] = None,
    ) -> List[ExecutionLogModel]:
        q = (
            select(ExecutionLogModel)
            .where(ExecutionLogModel.auto_patrol_id == auto_patrol_id)
        )
        if since is not None:
            q = q.where(ExecutionLogModel.started_at >= since)
        q = q.order_by(ExecutionLogModel.started_at.desc()).limit(limit)
        result = await self._db.execute(q)
        return list(result.scalars().all())

    async def get_patrol_stats(
        self,
        auto_patrol_id: int,
        hours: int = 24,
    ) -> Dict[str, Any]:
        """Aggregated stats for a single patrol over the last N hours.

        Returns:
          {
            total: int,
            success: int,
            error: int,
            condition_met_count: int,
            by_trigger: {event_poller: int, schedule: int, manual: int, ...},
            by_equipment: {EQP-01: int, ...},  # parsed from event_context
            last_at: ISO datetime str | None,
            last_status: str | None,
            avg_duration_ms: int,
          }
        """
        from sqlalchemy import func, and_, case, Integer
        from datetime import datetime, timezone, timedelta

        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

        # Aggregate counts using CASE WHEN
        success_case = case((ExecutionLogModel.status == "success", 1), else_=0)
        error_case = case((ExecutionLogModel.status == "error", 1), else_=0)

        agg_q = select(
            func.count().label("total"),
            func.sum(success_case).label("success"),
            func.sum(error_case).label("error"),
            func.avg(ExecutionLogModel.duration_ms).label("avg_dur"),
            func.max(ExecutionLogModel.started_at).label("last_at"),
        ).where(
            and_(
                ExecutionLogModel.auto_patrol_id == auto_patrol_id,
                ExecutionLogModel.started_at >= cutoff,
            )
        )
        agg_row = (await self._db.execute(agg_q)).one()

        # Breakdown by triggered_by
        trig_q = select(
            ExecutionLogModel.triggered_by,
            func.count().label("c"),
        ).where(
            and_(
                ExecutionLogModel.auto_patrol_id == auto_patrol_id,
                ExecutionLogModel.started_at >= cutoff,
            )
        ).group_by(ExecutionLogModel.triggered_by)
        trig_rows = (await self._db.execute(trig_q)).all()
        by_trigger: Dict[str, int] = {}
        for row in trig_rows:
            key = row[0] or "unknown"
            # Normalize: triggered_by like "event_poller" or "manual" or "schedule"
            by_trigger[key] = (by_trigger.get(key) or 0) + int(row[1])

        # ALL executions in window (no LIMIT) — for accurate by_equipment + condition_met counts
        all_q = select(
            ExecutionLogModel.event_context,
            ExecutionLogModel.llm_readable_data,
        ).where(
            and_(
                ExecutionLogModel.auto_patrol_id == auto_patrol_id,
                ExecutionLogModel.started_at >= cutoff,
            )
        )
        all_rows = (await self._db.execute(all_q)).all()

        condition_met_count = 0
        by_equipment: Dict[str, int] = {}
        for ctx_str, lrd_str in all_rows:
            try:
                lrd = json.loads(lrd_str) if lrd_str else {}
                if lrd.get("condition_met"):
                    condition_met_count += 1
            except Exception:
                pass
            try:
                ctx = json.loads(ctx_str) if ctx_str else {}
                eq = ctx.get("equipment_id") or ""
                if eq:
                    by_equipment[eq] = by_equipment.get(eq, 0) + 1
            except Exception:
                pass

        # Last status from a small recent query
        last_q = select(ExecutionLogModel.status).where(
            and_(
                ExecutionLogModel.auto_patrol_id == auto_patrol_id,
                ExecutionLogModel.started_at >= cutoff,
            )
        ).order_by(ExecutionLogModel.started_at.desc()).limit(1)
        last_row = (await self._db.execute(last_q)).first()
        last_status = last_row[0] if last_row else None

        return {
            "total": int(agg_row[0] or 0),
            "success": int(agg_row[1] or 0),
            "error": int(agg_row[2] or 0),
            "condition_met_count": condition_met_count,
            "by_trigger": by_trigger,
            "by_equipment": by_equipment,
            "last_at": agg_row[4].isoformat() if agg_row[4] else None,
            "last_status": last_status,
            "avg_duration_ms": int(agg_row[3] or 0),
            "window_hours": hours,
        }

    async def get_by_cron_job(self, cron_job_id: int, limit: int = 50) -> List[ExecutionLogModel]:
        result = await self._db.execute(
            select(ExecutionLogModel)
            .where(ExecutionLogModel.cron_job_id == cron_job_id)
            .order_by(ExecutionLogModel.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, log_id: int) -> Optional[ExecutionLogModel]:
        result = await self._db.execute(
            select(ExecutionLogModel).where(ExecutionLogModel.id == log_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        skill_id: int,
        triggered_by: str,
        event_context: Optional[Dict[str, Any]] = None,
        script_version_id: Optional[int] = None,
        cron_job_id: Optional[int] = None,
        auto_patrol_id: Optional[int] = None,
    ) -> ExecutionLogModel:
        obj = ExecutionLogModel(
            skill_id=skill_id,
            triggered_by=triggered_by,
            script_version_id=script_version_id,
            cron_job_id=cron_job_id,
            auto_patrol_id=auto_patrol_id,
            event_context=json.dumps(event_context, ensure_ascii=False) if event_context else None,
            status="success",
        )
        self._db.add(obj)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def finish(
        self,
        obj: ExecutionLogModel,
        status: str,
        llm_readable_data: Optional[Dict[str, Any]] = None,
        action_dispatched: Optional[str] = None,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> ExecutionLogModel:
        from datetime import datetime, timezone

        obj.status = status
        obj.llm_readable_data = (
            json.dumps(llm_readable_data, ensure_ascii=False) if llm_readable_data else None
        )
        obj.action_dispatched = action_dispatched
        obj.error_message = error_message
        obj.finished_at = datetime.now(tz=timezone.utc)
        obj.duration_ms = duration_ms
        await self._db.commit()
        await self._db.refresh(obj)
        return obj
