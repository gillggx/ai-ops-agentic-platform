"""
Agent session repository for database operations on Agent entities.

Agent Session/Memory/Tool/Preference 数据访问层。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    AgentMemory,
    AgentPreference,
    AgentSession,
    AgentTool,
)
from .base import BaseRepository


class AgentSessionRepository(BaseRepository[AgentSession]):
    """
    Repository for AgentSession entity.
    
    AgentSession 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with AgentSession model."""
        super().__init__(AgentSession, db=db)

    async def get_by_user(
        self,
        db: AsyncSession,
        user_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AgentSession]:
        """
        Get sessions by user.
        
        按用户获取会话。
        
        Args:
            db: AsyncSession - Database session
            user_id: int - User ID
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[AgentSession] - User's sessions
        """
        stmt = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_active_sessions(
        self,
        db: AsyncSession,
        user_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AgentSession]:
        """
        Get active sessions for user.
        
        获取用户的活跃会话。
        
        Args:
            db: AsyncSession - Database session
            user_id: int - User ID
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[AgentSession] - Active sessions
        """
        stmt = (
            select(self.model)
            .where((self.model.user_id == user_id) & (self.model.is_active == True))
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def count_user_sessions(
        self,
        db: AsyncSession,
        user_id: int,
    ) -> int:
        """
        Count user's sessions.
        
        计数用户的会话。
        
        Args:
            db: AsyncSession - Database session
            user_id: int - User ID
        
        Returns:
            int - Session count
        """
        return await self.count(db, user_id=user_id)


class AgentMemoryRepository(BaseRepository[AgentMemory]):
    """
    Repository for AgentMemory entity.
    
    AgentMemory 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with AgentMemory model."""
        super().__init__(AgentMemory, db=db)

    async def get_by_session(
        self,
        db: AsyncSession,
        session_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AgentMemory]:
        """
        Get memories by session.
        
        按会话获取内存。
        
        Args:
            db: AsyncSession - Database session
            session_id: int - Session ID
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[AgentMemory] - Memories in session
        """
        stmt = (
            select(self.model)
            .where(self.model.session_id == session_id)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_memory_type(
        self,
        db: AsyncSession,
        session_id: int,
        memory_type: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AgentMemory]:
        """
        Get memories by type.
        
        按类型获取内存。
        
        Args:
            db: AsyncSession - Database session
            session_id: int - Session ID
            memory_type: str - Memory type (fact, insight, etc)
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[AgentMemory] - Memories of this type
        """
        stmt = (
            select(self.model)
            .where((self.model.session_id == session_id) & (self.model.memory_type == memory_type))
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_indexed_memories(
        self,
        db: AsyncSession,
        session_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AgentMemory]:
        """
        Get indexed memories for RAG.
        
        获取已索引的内存用于 RAG。
        
        Args:
            db: AsyncSession - Database session
            session_id: int - Session ID
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[AgentMemory] - Indexed memories
        """
        stmt = (
            select(self.model)
            .where((self.model.session_id == session_id) & (self.model.is_indexed == True))
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()


class AgentToolRepository(BaseRepository[AgentTool]):
    """
    Repository for AgentTool entity.
    
    AgentTool 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with AgentTool model."""
        super().__init__(AgentTool, db=db)

    async def get_by_name(
        self,
        db: AsyncSession,
        name: str,
    ) -> Optional[AgentTool]:
        """
        Get tool by name.
        
        按名称获取工具。
        
        Args:
            db: AsyncSession - Database session
            name: str - Tool name
        
        Returns:
            AgentTool or None
        """
        return await self.get_one_by_filter(db, name=name)

    async def get_available_tools(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AgentTool]:
        """
        Get all available tools.
        
        获取所有可用工具。
        
        Args:
            db: AsyncSession - Database session
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[AgentTool] - Available tools
        """
        stmt = (
            select(self.model)
            .where(self.model.is_available == True)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_category(
        self,
        db: AsyncSession,
        category: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AgentTool]:
        """
        Get tools by category.
        
        按分类获取工具。
        
        Args:
            db: AsyncSession - Database session
            category: str - Tool category
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[AgentTool] - Tools in category
        """
        stmt = (
            select(self.model)
            .where(self.model.category == category)
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
        Check if tool name exists.
        
        检查工具名称是否存在。
        
        Args:
            db: AsyncSession - Database session
            name: str - Tool name
        
        Returns:
            bool - True if exists
        """
        return await self.exists(db, name=name)


class AgentPreferenceRepository(BaseRepository[AgentPreference]):
    """
    Repository for AgentPreference entity.
    
    AgentPreference 数据访问库。
    """

    def __init__(self, db=None):
        """Initialize with AgentPreference model."""
        super().__init__(AgentPreference, db=db)

    async def get_by_user(
        self,
        db: AsyncSession,
        user_id: int,
    ) -> Optional[AgentPreference]:
        """
        Get preference by user ID.
        
        按用户 ID 获取偏好。
        
        Args:
            db: AsyncSession - Database session
            user_id: int - User ID
        
        Returns:
            AgentPreference or None
        """
        return await self.get_one_by_filter(db, user_id=user_id)

    async def get_or_create(
        self,
        db: AsyncSession,
        user_id: int,
    ) -> AgentPreference:
        """
        Get preference or create default.
        
        获取偏好或创建默认值。
        
        Args:
            db: AsyncSession - Database session
            user_id: int - User ID
        
        Returns:
            AgentPreference - User's preference
        """
        pref = await self.get_by_user(db, user_id)
        if not pref:
            pref = await self.create(db, user_id=user_id)
        return pref
