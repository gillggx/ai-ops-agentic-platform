"""
MockData repository for database operations on MockData entities.

MockData 数据访问层。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MockData
from .base import BaseRepository


class MockDataRepository(BaseRepository[MockData]):
    """
    Repository for MockData entity.
    
    MockData 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with MockData model."""
        super().__init__(MockData, db=db)

    async def get_by_name(
        self,
        db: AsyncSession,
        name: str,
    ) -> Optional[MockData]:
        """
        Get mock data by name.
        
        按名称获取模拟数据。
        
        Args:
            db: AsyncSession - Database session
            name: str - Mock data name
        
        Returns:
            MockData or None
        """
        return await self.get_one_by_filter(db, name=name)

    async def get_by_category(
        self,
        db: AsyncSession,
        category: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[MockData]:
        """
        Get mock data by category.
        
        按分类获取模拟数据。
        
        Args:
            db: AsyncSession - Database session
            category: str - Data category
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[MockData] - Mock data in category
        """
        stmt = (
            select(self.model)
            .where(self.model.category == category)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_featured_data(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[MockData]:
        """
        Get featured mock data.
        
        获取特色模拟数据。
        
        Args:
            db: AsyncSession - Database session
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[MockData] - Featured mock data
        """
        stmt = (
            select(self.model)
            .where(self.model.is_featured == True)
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
        Check if mock data name exists.
        
        检查模拟数据名称是否存在。
        
        Args:
            db: AsyncSession - Database session
            name: str - Mock data name
        
        Returns:
            bool - True if exists
        """
        return await self.exists(db, name=name)

    async def count_by_category(
        self,
        db: AsyncSession,
        category: str,
    ) -> int:
        """
        Count mock data by category.
        
        计数按分类的模拟数据。
        
        Args:
            db: AsyncSession - Database session
            category: str - Data category
        
        Returns:
            int - Count of mock data
        """
        return await self.count(db, category=category)
