"""Repository for CronJob CRUD operations."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cron_job import CronJobModel


class CronJobRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_all_active(self) -> List[CronJobModel]:
        result = await self._db.execute(
            select(CronJobModel)
            .where(CronJobModel.status == "active")
            .order_by(CronJobModel.id)
        )
        return list(result.scalars().all())

    async def get_by_skill(self, skill_id: int) -> List[CronJobModel]:
        result = await self._db.execute(
            select(CronJobModel)
            .where(CronJobModel.skill_id == skill_id)
            .order_by(CronJobModel.id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, job_id: int) -> Optional[CronJobModel]:
        result = await self._db.execute(
            select(CronJobModel).where(CronJobModel.id == job_id)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> CronJobModel:
        obj = CronJobModel(**kwargs)
        self._db.add(obj)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def update(self, obj: CronJobModel, **kwargs) -> CronJobModel:
        for k, v in kwargs.items():
            setattr(obj, k, v)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def mark_run(self, obj: CronJobModel, next_run_at: Optional[datetime]) -> CronJobModel:
        from datetime import timezone
        obj.last_run_at = datetime.now(tz=timezone.utc)
        obj.next_run_at = next_run_at
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def soft_delete(self, obj: CronJobModel) -> None:
        """Mark as deleted (preserve history) rather than hard-delete."""
        obj.status = "deleted"
        await self._db.commit()
