"""Repository for RoutineCheck CRUD operations (Phase 11)."""

import json
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ontology.models.routine_check import RoutineCheckModel


class RoutineCheckRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_all(self) -> List[RoutineCheckModel]:
        result = await self._db.execute(
            select(RoutineCheckModel).order_by(RoutineCheckModel.id)
        )
        return list(result.scalars().all())

    async def get_active(self) -> List[RoutineCheckModel]:
        result = await self._db.execute(
            select(RoutineCheckModel)
            .where(RoutineCheckModel.is_active == True)  # noqa: E712
            .order_by(RoutineCheckModel.id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, check_id: int) -> Optional[RoutineCheckModel]:
        result = await self._db.execute(
            select(RoutineCheckModel).where(RoutineCheckModel.id == check_id)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> RoutineCheckModel:
        # skill_input is the new name (maps to DB column 'preset_parameters')
        if "skill_input" in kwargs and isinstance(kwargs["skill_input"], dict):
            kwargs["skill_input"] = json.dumps(kwargs["skill_input"], ensure_ascii=False)
        if "event_param_mappings" in kwargs and isinstance(kwargs["event_param_mappings"], list):
            kwargs["event_param_mappings"] = json.dumps(kwargs["event_param_mappings"], ensure_ascii=False)
        obj = RoutineCheckModel(**kwargs)
        self._db.add(obj)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def update(self, obj: RoutineCheckModel, **kwargs) -> RoutineCheckModel:
        if "skill_input" in kwargs and isinstance(kwargs["skill_input"], dict):
            kwargs["skill_input"] = json.dumps(kwargs["skill_input"], ensure_ascii=False)
        if "event_param_mappings" in kwargs and isinstance(kwargs["event_param_mappings"], list):
            kwargs["event_param_mappings"] = json.dumps(kwargs["event_param_mappings"], ensure_ascii=False)
        for k, v in kwargs.items():
            setattr(obj, k, v)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def delete(self, obj: RoutineCheckModel) -> None:
        await self._db.delete(obj)
        await self._db.commit()
