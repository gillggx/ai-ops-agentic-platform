"""Repository for MCPDefinition CRUD operations."""

import json
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ontology.models.mcp_definition import MCPDefinitionModel

_JSON_FIELDS = ("output_schema", "ui_render_config", "input_definition", "sample_output")


class MCPDefinitionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_all(self) -> List[MCPDefinitionModel]:
        result = await self._db.execute(select(MCPDefinitionModel).order_by(MCPDefinitionModel.id))
        return list(result.scalars().all())

    async def get_by_id(self, mcp_id: int) -> Optional[MCPDefinitionModel]:
        result = await self._db.execute(
            select(MCPDefinitionModel).where(MCPDefinitionModel.id == mcp_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[MCPDefinitionModel]:
        result = await self._db.execute(
            select(MCPDefinitionModel).where(MCPDefinitionModel.name == name)
        )
        return result.scalar_one_or_none()

    async def get_all_by_type(self, mcp_type: str) -> List[MCPDefinitionModel]:
        result = await self._db.execute(
            select(MCPDefinitionModel)
            .where(MCPDefinitionModel.mcp_type == mcp_type)
            .order_by(MCPDefinitionModel.id)
        )
        return list(result.scalars().all())

    async def get_by_data_subject(self, ds_id: int) -> List[MCPDefinitionModel]:
        result = await self._db.execute(
            select(MCPDefinitionModel).where(MCPDefinitionModel.data_subject_id == ds_id)
        )
        return list(result.scalars().all())

    async def create(self, **kwargs) -> MCPDefinitionModel:
        for field in _JSON_FIELDS:
            if field in kwargs and isinstance(kwargs[field], (dict, list)):
                kwargs[field] = json.dumps(kwargs[field], ensure_ascii=False)
        obj = MCPDefinitionModel(**kwargs)
        self._db.add(obj)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def update(self, obj: MCPDefinitionModel, **kwargs) -> MCPDefinitionModel:
        for field in _JSON_FIELDS:
            if field in kwargs and isinstance(kwargs[field], (dict, list)):
                kwargs[field] = json.dumps(kwargs[field], ensure_ascii=False)
        for k, v in kwargs.items():
            setattr(obj, k, v)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def delete(self, obj: MCPDefinitionModel) -> None:
        await self._db.delete(obj)
        await self._db.commit()
