"""
SystemParameter repository for database operations on SystemParameter entities.

SystemParameter 数据访问层。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SystemParameter
from .base import BaseRepository


class SystemParameterRepository(BaseRepository[SystemParameter]):
    """
    Repository for SystemParameter entity.
    
    SystemParameter 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with SystemParameter model."""
        super().__init__(SystemParameter, db=db)

    async def get_by_key(
        self,
        db: AsyncSession,
        key: str,
    ) -> Optional[SystemParameter]:
        """
        Get parameter by key.
        
        按键获取参数。
        
        Args:
            db: AsyncSession - Database session
            key: str - Parameter key
        
        Returns:
            SystemParameter or None
        """
        return await self.get_one_by_filter(db, key=key)

    async def get_by_category(
        self,
        db: AsyncSession,
        category: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[SystemParameter]:
        """
        Get parameters by category.
        
        按分类获取参数。
        
        Args:
            db: AsyncSession - Database session
            category: str - Parameter category
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[SystemParameter] - Parameters in category
        """
        stmt = (
            select(self.model)
            .where(self.model.category == category)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_value(
        self,
        db: AsyncSession,
        key: str,
        default: Optional[str] = None,
    ) -> Optional[str]:
        """
        Get parameter value directly.
        
        直接获取参数值。
        
        Args:
            db: AsyncSession - Database session
            key: str - Parameter key
            default: str - Default value if not found
        
        Returns:
            str or None - Parameter value or default
        """
        param = await self.get_by_key(db, key)
        return param.value if param else default

    async def set_value(
        self,
        db: AsyncSession,
        key: str,
        value: str,
        description: str = "",
        category: str = "general",
        is_secret: bool = False,
    ) -> SystemParameter:
        """
        Set parameter value (create or update).
        
        设置参数值（创建或更新）。
        
        Args:
            db: AsyncSession - Database session
            key: str - Parameter key
            value: str - New value
            description: str - Parameter description
            category: str - Parameter category
            is_secret: bool - Whether value is secret
        
        Returns:
            SystemParameter - Created or updated parameter
        """
        existing = await self.get_by_key(db, key)
        if existing:
            return await self.update(
                db, existing.id,
                value=value,
                description=description,
                category=category,
                is_secret=is_secret
            )
        else:
            return await self.create(
                db,
                key=key,
                value=value,
                description=description,
                category=category,
                is_secret=is_secret
            )

    async def key_exists(
        self,
        db: AsyncSession,
        key: str,
    ) -> bool:
        """
        Check if parameter key exists.
        
        检查参数键是否存在。
        
        Args:
            db: AsyncSession - Database session
            key: str - Parameter key
        
        Returns:
            bool - True if exists
        """
        return await self.exists(db, key=key)

    async def get_non_secret_params(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[SystemParameter]:
        """
        Get all non-secret parameters.
        
        获取所有非机密参数。
        
        Args:
            db: AsyncSession - Database session
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[SystemParameter] - Non-secret parameters
        """
        stmt = (
            select(self.model)
            .where(self.model.is_secret == False)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()
