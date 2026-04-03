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
