"""Repository for SystemParameter CRUD operations."""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_parameter import SystemParameterModel


class SystemParameterRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_all(self) -> List[SystemParameterModel]:
        result = await self._db.execute(
            select(SystemParameterModel).order_by(SystemParameterModel.key)
        )
        return list(result.scalars().all())

    async def get_by_key(self, key: str) -> Optional[SystemParameterModel]:
        result = await self._db.execute(
            select(SystemParameterModel).where(SystemParameterModel.key == key)
        )
        return result.scalar_one_or_none()

    async def get_value(self, key: str) -> Optional[str]:
        obj = await self.get_by_key(key)
        return obj.value if obj else None

    async def upsert(self, key: str, value: str, description: Optional[str] = None) -> SystemParameterModel:
        obj = await self.get_by_key(key)
        if obj is None:
            obj = SystemParameterModel(key=key, value=value, description=description)
            self._db.add(obj)
        else:
            obj.value = value
            obj.updated_at = datetime.now(timezone.utc)
            if description is not None:
                obj.description = description
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def update_value(self, key: str, value: str) -> Optional[SystemParameterModel]:
        obj = await self.get_by_key(key)
        if obj is None:
            return None
        obj.value = value
        obj.updated_at = datetime.now(timezone.utc)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj
