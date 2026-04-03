"""
MCP repository for database operations on MCP entities.

MCP 数据访问层。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MCP, MCPDefinition
from .base import BaseRepository


class MCPDefinitionRepository(BaseRepository[MCPDefinition]):
    """
    Repository for MCPDefinition entity.
    
    MCPDefinition 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with MCPDefinition model."""
        super().__init__(MCPDefinition, db=db)

    async def get_by_name(
        self,
        db: AsyncSession,
        name: str,
    ) -> Optional[MCPDefinition]:
        """
        Get MCP definition by name.
        
        按名称获取 MCP 定义。
        
        Args:
            db: AsyncSession - Database session
            name: str - MCP name
        
        Returns:
            MCPDefinition or None
        """
        return await self.get_one_by_filter(db, name=name)

    async def name_exists(
        self,
        db: AsyncSession,
        name: str,
    ) -> bool:
        """
        Check if MCP name exists.
        
        检查 MCP 名称是否存在。
        
        Args:
            db: AsyncSession - Database session
            name: str - MCP name
        
        Returns:
            bool - True if exists
        """
        return await self.exists(db, name=name)

    async def get_by_data_source_type(
        self,
        db: AsyncSession,
        data_source_type: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[MCPDefinition]:
        """
        Get MCP definitions by data source type.
        
        按数据源类型获取 MCP 定义。
        
        Args:
            db: AsyncSession - Database session
            data_source_type: str - Data source type
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[MCPDefinition] - MCP definitions
        """
        return await self.get_by_filter(db, data_source_type=data_source_type)


class MCPRepository(BaseRepository[MCP]):
    """
    Repository for MCP entity.
    
    MCP 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with MCP model."""
        super().__init__(MCP, db=db)

    async def get_by_mcp_definition(
        self,
        db: AsyncSession,
        mcp_definition_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[MCP]:
        """
        Get MCP instances by definition.
        
        按定义获取 MCP 实例。
        
        Args:
            db: AsyncSession - Database session
            mcp_definition_id: int - MCP definition ID
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[MCP] - MCP instances
        """
        stmt = (
            select(self.model)
            .where(self.model.mcp_definition_id == mcp_definition_id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_active_mcps(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[MCP]:
        """
        Get all active MCP instances.
        
        获取所有活跃 MCP 实例。
        
        Args:
            db: AsyncSession - Database session
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[MCP] - Active MCP instances
        """
        stmt = (
            select(self.model)
            .where(self.model.is_active == True)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_name(
        self,
        db: AsyncSession,
        name: str,
    ) -> Optional[MCP]:
        """
        Get MCP instance by name.
        
        按名称获取 MCP 实例。
        
        Args:
            db: AsyncSession - Database session
            name: str - MCP name
        
        Returns:
            MCP or None
        """
        return await self.get_one_by_filter(db, name=name)

    async def count_active(
        self,
        db: AsyncSession,
    ) -> int:
        """
        Count active MCP instances.
        
        计数活跃 MCP 实例。
        
        Args:
            db: AsyncSession - Database session
        
        Returns:
            int - Count of active MCPs
        """
        return await self.count(db, is_active=True)
