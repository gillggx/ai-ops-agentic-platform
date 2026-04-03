"""Repository for GeneratedEvent CRUD operations (Phase 11)."""

import json
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generated_event import GeneratedEventModel


class GeneratedEventRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_all(self, limit: int = 200) -> List[GeneratedEventModel]:
        result = await self._db.execute(
            select(GeneratedEventModel)
            .order_by(GeneratedEventModel.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, event_id: int) -> Optional[GeneratedEventModel]:
        result = await self._db.execute(
            select(GeneratedEventModel).where(GeneratedEventModel.id == event_id)
        )
        return result.scalar_one_or_none()

    async def get_by_status(self, status: str) -> List[GeneratedEventModel]:
        result = await self._db.execute(
            select(GeneratedEventModel)
            .where(GeneratedEventModel.status == status)
            .order_by(GeneratedEventModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(self, **kwargs) -> GeneratedEventModel:
        if "mapped_parameters" in kwargs and isinstance(kwargs["mapped_parameters"], dict):
            kwargs["mapped_parameters"] = json.dumps(kwargs["mapped_parameters"], ensure_ascii=False)
        obj = GeneratedEventModel(**kwargs)
        self._db.add(obj)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def update(self, obj: GeneratedEventModel, **kwargs) -> GeneratedEventModel:
        for k, v in kwargs.items():
            setattr(obj, k, v)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def delete(self, obj: GeneratedEventModel) -> None:
        await self._db.delete(obj)
        await self._db.commit()
