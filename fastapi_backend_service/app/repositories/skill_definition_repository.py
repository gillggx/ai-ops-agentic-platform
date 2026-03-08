"""Repository for SkillDefinition CRUD operations."""

import json
from typing import List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill_definition import SkillDefinitionModel

_JSON_FIELDS = ("mcp_ids", "param_mappings", "last_diagnosis_result")


class SkillDefinitionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_all(self) -> List[SkillDefinitionModel]:
        result = await self._db.execute(select(SkillDefinitionModel).order_by(SkillDefinitionModel.id))
        return list(result.scalars().all())

    async def get_by_id(self, skill_id: int) -> Optional[SkillDefinitionModel]:
        result = await self._db.execute(
            select(SkillDefinitionModel).where(SkillDefinitionModel.id == skill_id)
        )
        return result.scalar_one_or_none()

    async def get_by_event_type(self, et_id: int) -> List[SkillDefinitionModel]:
        result = await self._db.execute(
            select(SkillDefinitionModel).where(SkillDefinitionModel.event_type_id == et_id)
        )
        return list(result.scalars().all())

    async def get_by_ids(self, ids: List[int]) -> List[SkillDefinitionModel]:
        if not ids:
            return []
        result = await self._db.execute(
            select(SkillDefinitionModel).where(SkillDefinitionModel.id.in_(ids))
        )
        # Preserve caller-specified order
        rows = {r.id: r for r in result.scalars().all()}
        return [rows[i] for i in ids if i in rows]

    async def create(self, **kwargs) -> SkillDefinitionModel:
        for field in _JSON_FIELDS:
            if field in kwargs and isinstance(kwargs[field], (dict, list)):
                kwargs[field] = json.dumps(kwargs[field], ensure_ascii=False)
        obj = SkillDefinitionModel(**kwargs)
        self._db.add(obj)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def update(self, obj: SkillDefinitionModel, **kwargs) -> SkillDefinitionModel:
        for field in _JSON_FIELDS:
            if field in kwargs and isinstance(kwargs[field], (dict, list)):
                kwargs[field] = json.dumps(kwargs[field], ensure_ascii=False)
        for k, v in kwargs.items():
            setattr(obj, k, v)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def delete(self, obj: SkillDefinitionModel) -> None:
        await self._db.delete(obj)
        await self._db.commit()
