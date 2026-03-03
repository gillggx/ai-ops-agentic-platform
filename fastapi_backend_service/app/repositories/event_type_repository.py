"""Repository for EventType CRUD operations."""

import json
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event_type import EventTypeModel


def _serialize_diagnosis_skills(value: Any) -> str:
    """Serialize diagnosis_skills to JSON string stored in diagnosis_skill_ids column.

    Accepts:
      - List[DiagnosisSkillBinding] (Pydantic objects)
      - List[dict] with skill_id keys
      - List[int] (legacy bare IDs — converted to {skill_id, param_mappings: []})
    """
    if isinstance(value, list):
        normalized = []
        for entry in value:
            if hasattr(entry, "model_dump"):
                normalized.append(entry.model_dump())
            elif isinstance(entry, dict):
                normalized.append(entry)
            elif isinstance(entry, int):
                normalized.append({"skill_id": entry, "param_mappings": []})
        return json.dumps(normalized, ensure_ascii=False)
    return json.dumps([], ensure_ascii=False)


class EventTypeRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_all(self) -> List[EventTypeModel]:
        result = await self._db.execute(select(EventTypeModel).order_by(EventTypeModel.id))
        return list(result.scalars().all())

    async def get_by_id(self, et_id: int) -> Optional[EventTypeModel]:
        result = await self._db.execute(
            select(EventTypeModel).where(EventTypeModel.id == et_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[EventTypeModel]:
        result = await self._db.execute(
            select(EventTypeModel).where(EventTypeModel.name == name)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> EventTypeModel:
        if "attributes" in kwargs and isinstance(kwargs["attributes"], list):
            kwargs["attributes"] = json.dumps(kwargs["attributes"], ensure_ascii=False)
        # Accept diagnosis_skills (new name) or diagnosis_skill_ids (old name)
        for key in ("diagnosis_skills", "diagnosis_skill_ids"):
            if key in kwargs:
                kwargs["diagnosis_skill_ids"] = _serialize_diagnosis_skills(kwargs.pop(key))
                break
        obj = EventTypeModel(**kwargs)
        self._db.add(obj)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def update(self, obj: EventTypeModel, **kwargs) -> EventTypeModel:
        if "attributes" in kwargs and isinstance(kwargs["attributes"], list):
            kwargs["attributes"] = json.dumps(kwargs["attributes"], ensure_ascii=False)
        for key in ("diagnosis_skills", "diagnosis_skill_ids"):
            if key in kwargs:
                kwargs["diagnosis_skill_ids"] = _serialize_diagnosis_skills(kwargs.pop(key))
                break
        for k, v in kwargs.items():
            setattr(obj, k, v)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def delete(self, obj: EventTypeModel) -> None:
        await self._db.delete(obj)
        await self._db.commit()
