"""
DataSubject repository for database operations on DataSubject entities.

DataSubject 数据访问层。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DataSubject
from .base import BaseRepository


class DataSubjectRepository(BaseRepository[DataSubject]):
    """
    Repository for DataSubject entity.
    
    DataSubject 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with DataSubject model."""
        super().__init__(DataSubject, db=db)

    async def get_by_name(
        self,
        db: AsyncSession,
        name: str,
    ) -> Optional[DataSubject]:
        """
        Get data subject by name.
        
        按名称获取数据主体。
        
        Args:
            db: AsyncSession - Database session
            name: str - Data subject name
        
        Returns:
            DataSubject or None
        """
        return await self.get_one_by_filter(db, name=name)

    async def get_by_external_id(
        self,
        db: AsyncSession,
        external_id: str,
    ) -> Optional[DataSubject]:
        """
        Get data subject by external ID.
        
        按外部 ID 获取数据主体。
        
        Args:
            db: AsyncSession - Database session
            external_id: str - External system ID
        
        Returns:
            DataSubject or None
        """
        return await self.get_one_by_filter(db, external_id=external_id)

    async def get_by_category(
        self,
        db: AsyncSession,
        category: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[DataSubject]:
        """
        Get data subjects by category.
        
        按分类获取数据主体。
        
        Args:
            db: AsyncSession - Database session
            category: str - Category name
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[DataSubject] - Data subjects in category
        """
        stmt = (
            select(self.model)
            .where(self.model.category == category)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_active_subjects(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[DataSubject]:
        """
        Get all active data subjects.
        
        获取所有活跃数据主体。
        
        Args:
            db: AsyncSession - Database session
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[DataSubject] - Active data subjects
        """
        stmt = (
            select(self.model)
            .where(self.model.is_active == True)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def name_exists(
        self,
        db: AsyncSession,
        name: str,
    ) -> bool:
        """
        Check if data subject name exists.
        
        检查数据主体名称是否存在。
        
        Args:
            db: AsyncSession - Database session
            name: str - Data subject name
        
        Returns:
            bool - True if exists
        """
        return await self.exists(db, name=name)

    async def external_id_exists(
        self,
        db: AsyncSession,
        external_id: str,
    ) -> bool:
        """
        Check if external ID exists.
        
        检查外部 ID 是否存在。
        
        Args:
            db: AsyncSession - Database session
            external_id: str - External ID
        
        Returns:
            bool - True if exists
        """
        return await self.exists(db, external_id=external_id)
