"""Repository for DataSubject CRUD operations."""

import json
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_subject import DataSubjectModel


class DataSubjectRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_all(self) -> List[DataSubjectModel]:
        result = await self._db.execute(select(DataSubjectModel).order_by(DataSubjectModel.id))
        return list(result.scalars().all())

    async def get_by_id(self, ds_id: int) -> Optional[DataSubjectModel]:
        result = await self._db.execute(
            select(DataSubjectModel).where(DataSubjectModel.id == ds_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[DataSubjectModel]:
        result = await self._db.execute(
            select(DataSubjectModel).where(DataSubjectModel.name == name)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> DataSubjectModel:
        # Serialize dict fields to JSON strings
        for field in ("api_config", "input_schema", "output_schema"):
            if field in kwargs and isinstance(kwargs[field], dict):
                kwargs[field] = json.dumps(kwargs[field], ensure_ascii=False)
        obj = DataSubjectModel(**kwargs)
        self._db.add(obj)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def update(self, obj: DataSubjectModel, **kwargs) -> DataSubjectModel:
        for field in ("api_config", "input_schema", "output_schema"):
            if field in kwargs and isinstance(kwargs[field], dict):
                kwargs[field] = json.dumps(kwargs[field], ensure_ascii=False)
        for k, v in kwargs.items():
            setattr(obj, k, v)
        await self._db.commit()
        await self._db.refresh(obj)
        return obj

    async def delete(self, obj: DataSubjectModel) -> None:
        await self._db.delete(obj)
        await self._db.commit()
