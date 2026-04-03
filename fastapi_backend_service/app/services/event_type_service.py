"""Service layer for EventType business logic."""

import json
from typing import Any, Dict, List

from app.core.exceptions import AppException
from app.models.event_type import EventTypeModel
from app.repositories.event_type_repository import EventTypeRepository
from app.schemas.event_type import (
    DiagnosisSkillBinding,
    EventTypeCreate,
    EventTypeResponse,
    EventTypeUpdate,
)


def _parse_diagnosis_skills(raw: str) -> List[DiagnosisSkillBinding]:
    """Parse the diagnosis_skill_ids column (may be old int-list or new binding-list)."""
    try:
        data = json.loads(raw) if raw else []
    except Exception:
        return []

    result = []
    for entry in data:
        if isinstance(entry, int):
            result.append(DiagnosisSkillBinding(skill_id=entry, param_mappings=[]))
        elif isinstance(entry, dict) and "skill_id" in entry:
            try:
                result.append(DiagnosisSkillBinding(**entry))
            except Exception:
                result.append(DiagnosisSkillBinding(skill_id=entry["skill_id"], param_mappings=[]))
    return result


def _to_response(obj: EventTypeModel) -> EventTypeResponse:
    def _j(s: str) -> Any:
        try:
            return json.loads(s) if s else []
        except Exception:
            return []

    diagnosis_skills = _parse_diagnosis_skills(
        getattr(obj, "diagnosis_skill_ids", None) or "[]"
    )

    return EventTypeResponse(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        attributes=_j(obj.attributes),
        diagnosis_skills=diagnosis_skills,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


class EventTypeService:
    def __init__(self, repo: EventTypeRepository) -> None:
        self._repo = repo

    async def list_all(self) -> List[EventTypeResponse]:
        return [_to_response(o) for o in await self._repo.get_all()]

    async def get(self, et_id: int) -> EventTypeResponse:
        obj = await self._repo.get_by_id(et_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="EventType 不存在")
        return _to_response(obj)

    async def create(self, data: EventTypeCreate) -> EventTypeResponse:
        if await self._repo.get_by_name(data.name):
            raise AppException(status_code=409, error_code="CONFLICT", detail="EventType 名稱已存在")
        attrs = [a.model_dump() for a in data.attributes]
        obj = await self._repo.create(
            name=data.name,
            description=data.description,
            attributes=attrs,
            diagnosis_skills=data.diagnosis_skills,
        )
        return _to_response(obj)

    async def update(self, et_id: int, data: EventTypeUpdate) -> EventTypeResponse:
        obj = await self._repo.get_by_id(et_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="EventType 不存在")
        updates: Dict[str, Any] = {}
        if data.name is not None:
            updates["name"] = data.name
        if data.description is not None:
            updates["description"] = data.description
        if data.attributes is not None:
            updates["attributes"] = [a.model_dump() for a in data.attributes]
        if data.diagnosis_skills is not None:
            updates["diagnosis_skills"] = data.diagnosis_skills
        obj = await self._repo.update(obj, **updates)
        return _to_response(obj)

    async def delete(self, et_id: int) -> None:
        obj = await self._repo.get_by_id(et_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="EventType 不存在")
        await self._repo.delete(obj)
