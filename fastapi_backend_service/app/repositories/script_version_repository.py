"""Repository for ScriptVersion CRUD operations."""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.script_version import ScriptVersionModel


class ScriptVersionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_skill(self, skill_id: int) -> List[ScriptVersionModel]:
        result = await self._db.execute(
            select(ScriptVersionModel)
            .where(ScriptVersionModel.skill_id == skill_id)
            .order_by(ScriptVersionModel.version.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, version_id: int) -> Optional[ScriptVersionModel]:
        result = await self._db.execute(
            select(ScriptVersionModel).where(ScriptVersionModel.id == version_id)
        )
        return result.scalar_one_or_none()

    async def get_active(self, skill_id: int) -> Optional[ScriptVersionModel]:
        result = await self._db.execute(
            select(ScriptVersionModel).where(
                ScriptVersionModel.skill_id == skill_id,
                ScriptVersionModel.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_draft(self, skill_id: int) -> Optional[ScriptVersionModel]:
        result = await self._db.execute(
            select(ScriptVersionModel)
            .where(
                ScriptVersionModel.skill_id == skill_id,
                ScriptVersionModel.status == "draft",
            )
            .order_by(ScriptVersionModel.version.desc())
        )
        return result.scalars().first()

    async def get_pending_approval(self) -> List[ScriptVersionModel]:
        """All draft scripts across all skills waiting for human review."""
        result = await self._db.execute(
            select(ScriptVersionModel)
            .where(ScriptVersionModel.status == "draft")
            .order_by(ScriptVersionModel.generated_at.desc())
        )
        return list(result.scalars().all())

    async def next_version(self, skill_id: int) -> int:
        """Calculate next version number for a skill."""
        result = await self._db.execute(
            select(ScriptVersionModel.version)
            .where(ScriptVersionModel.skill_id == skill_id)
            .order_by(ScriptVersionModel.version.desc())
        )
        latest = result.scalars().first()
        return (latest or 0) + 1

    async def create(self, **kwargs) -> ScriptVersionModel:
        obj = ScriptVersionModel(**kwargs)
        self._db.add(obj)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def update(self, obj: ScriptVersionModel, **kwargs) -> ScriptVersionModel:
        for k, v in kwargs.items():
            setattr(obj, k, v)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def deactivate_all(self, skill_id: int) -> None:
        """Deprecate all active versions for a skill (before promoting a new one)."""
        result = await self._db.execute(
            select(ScriptVersionModel).where(
                ScriptVersionModel.skill_id == skill_id,
                ScriptVersionModel.status == "active",
            )
        )
        for row in result.scalars().all():
            row.status = "deprecated"
        await self._db.commit()
