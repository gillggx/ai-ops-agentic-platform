"""Service layer for DataSubject business logic."""

import json
from typing import Any, Dict, List, Optional

from app.core.exceptions import AppException
from app.ontology.models.data_subject import DataSubjectModel
from app.ontology.repositories.data_subject_repository import DataSubjectRepository
from app.ontology.schemas.data_subject import DataSubjectCreate, DataSubjectResponse, DataSubjectUpdate


def _to_response(obj: DataSubjectModel) -> DataSubjectResponse:
    """Deserialize JSON string fields back to dicts for API response."""
    def _j(s: str) -> Any:
        try:
            return json.loads(s) if s else {}
        except Exception:
            return {}

    return DataSubjectResponse(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        api_config=_j(obj.api_config),
        input_schema=_j(obj.input_schema),
        output_schema=_j(obj.output_schema),
        is_builtin=obj.is_builtin,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


class DataSubjectService:
    def __init__(self, repo: DataSubjectRepository) -> None:
        self._repo = repo

    async def list_all(self) -> List[DataSubjectResponse]:
        objs = await self._repo.get_all()
        return [_to_response(o) for o in objs]

    async def get(self, ds_id: int) -> DataSubjectResponse:
        obj = await self._repo.get_by_id(ds_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="DataSubject 不存在")
        return _to_response(obj)

    async def create(self, data: DataSubjectCreate) -> DataSubjectResponse:
        existing = await self._repo.get_by_name(data.name)
        if existing:
            raise AppException(status_code=409, error_code="CONFLICT", detail="DataSubject 名稱已存在")
        obj = await self._repo.create(
            name=data.name,
            description=data.description,
            api_config=data.api_config.model_dump(),
            input_schema=data.input_schema,
            output_schema=data.output_schema,
            is_builtin=False,
        )
        return _to_response(obj)

    async def update(self, ds_id: int, data: DataSubjectUpdate) -> DataSubjectResponse:
        obj = await self._repo.get_by_id(ds_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="DataSubject 不存在")
        if obj.is_builtin:
            raise AppException(status_code=403, error_code="FORBIDDEN", detail="內建 DataSubject 不可修改")
        updates: Dict[str, Any] = {}
        if data.name is not None:
            updates["name"] = data.name
        if data.description is not None:
            updates["description"] = data.description
        if data.api_config is not None:
            updates["api_config"] = data.api_config.model_dump()
        if data.input_schema is not None:
            updates["input_schema"] = data.input_schema
        if data.output_schema is not None:
            updates["output_schema"] = data.output_schema
        obj = await self._repo.update(obj, **updates)
        return _to_response(obj)

    async def delete(self, ds_id: int) -> None:
        obj = await self._repo.get_by_id(ds_id)
        if not obj:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail="DataSubject 不存在")
        if obj.is_builtin:
            raise AppException(status_code=403, error_code="FORBIDDEN", detail="內建 DataSubject 不可刪除")
        await self._repo.delete(obj)
