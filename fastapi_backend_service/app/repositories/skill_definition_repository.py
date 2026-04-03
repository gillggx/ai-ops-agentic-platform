"""SkillDefinitionRepository v2.0 — CRUD for skill_definitions table."""

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill_definition import SkillDefinitionModel


def _j(s: Optional[str]) -> Any:
    if not s:
        return []
    try:
        return json.loads(s)
    except Exception:
        return []


class SkillDefinitionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_all(self, visibility: Optional[str] = None) -> List[SkillDefinitionModel]:
        q = select(SkillDefinitionModel).order_by(SkillDefinitionModel.id)
        if visibility:
            q = q.where(SkillDefinitionModel.visibility == visibility)
        result = await self._db.execute(q)
        return list(result.scalars().all())

    async def list_by_source(self, source: str) -> List[SkillDefinitionModel]:
        """Return all skills with the given source discriminator."""
        result = await self._db.execute(
            select(SkillDefinitionModel)
            .where(SkillDefinitionModel.source == source)
            .order_by(SkillDefinitionModel.id)
        )
        return list(result.scalars().all())

    async def list_by_trigger_event(self, event_type_id: int) -> List[SkillDefinitionModel]:
        """Return all active skills triggered by a given event type."""
        result = await self._db.execute(
            select(SkillDefinitionModel)
            .where(SkillDefinitionModel.trigger_event_id == event_type_id)
            .where(SkillDefinitionModel.is_active == True)  # noqa: E712
            .where(SkillDefinitionModel.trigger_mode.in_(["event", "both"]))
        )
        return list(result.scalars().all())

    async def get_by_id(self, skill_id: int) -> Optional[SkillDefinitionModel]:
        result = await self._db.execute(
            select(SkillDefinitionModel).where(SkillDefinitionModel.id == skill_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[SkillDefinitionModel]:
        result = await self._db.execute(
            select(SkillDefinitionModel).where(SkillDefinitionModel.name == name)
        )
        return result.scalar_one_or_none()

    async def create(self, data: Dict[str, Any]) -> SkillDefinitionModel:
        steps = data.pop("steps_mapping", [])
        input_schema = data.pop("input_schema", [])
        output_schema = data.pop("output_schema", [])
        obj = SkillDefinitionModel(
            **data,
            steps_mapping=json.dumps(steps, ensure_ascii=False),
            input_schema=json.dumps(input_schema, ensure_ascii=False),
            output_schema=json.dumps(output_schema, ensure_ascii=False),
        )
        self._db.add(obj)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def update(self, skill_id: int, data: Dict[str, Any]) -> Optional[SkillDefinitionModel]:
        obj = await self.get_by_id(skill_id)
        if not obj:
            return None
        if "steps_mapping" in data:
            data["steps_mapping"] = json.dumps(data["steps_mapping"], ensure_ascii=False)
        if "input_schema" in data:
            data["input_schema"] = json.dumps(data["input_schema"], ensure_ascii=False)
        if "output_schema" in data:
            data["output_schema"] = json.dumps(data["output_schema"], ensure_ascii=False)
        for k, v in data.items():
            setattr(obj, k, v)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def delete(self, skill_id: int) -> bool:
        obj = await self.get_by_id(skill_id)
        if not obj:
            return False
        await self._db.delete(obj)
        await self._db.commit()
        return True

    def steps_mapping(self, obj: SkillDefinitionModel) -> List[Dict[str, Any]]:
        """Deserialise steps_mapping JSON from model."""
        return _j(obj.steps_mapping)

    def get_input_schema(self, obj: SkillDefinitionModel) -> List[Dict[str, Any]]:
        """Deserialise input_schema JSON from model."""
        return _j(obj.input_schema)

    def get_output_schema(self, obj: SkillDefinitionModel) -> List[Dict[str, Any]]:
        """Deserialise output_schema JSON from model."""
        return _j(obj.output_schema)
