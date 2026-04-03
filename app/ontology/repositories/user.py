"""
User repository for database operations on User entities.

User 数据访问层。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .base import BaseRepository


class UserRepository(BaseRepository[User]):
    """
    Repository for User entity.
    
    User 数据访问库。
    
    Handles all database operations for users including authentication,
    role management, and queries.
    """

    def __init__(self, db=None):
        """Initialize with User model."""
        super().__init__(User, db=db)

    async def get_by_username(
        self,
        db: AsyncSession,
        username: str,
    ) -> Optional[User]:
        """
        Get user by username.
        
        按用户名获取用户。
        
        Args:
            db: AsyncSession - Database session
            username: str - Username
        
        Returns:
            User or None - Found user or None
        """
        return await self.get_one_by_filter(db, username=username)

    async def get_by_email(
        self,
        db: AsyncSession,
        email: str,
    ) -> Optional[User]:
        """
        Get user by email.
        
        按邮箱获取用户。
        
        Args:
            db: AsyncSession - Database session
            email: str - Email address
        
        Returns:
            User or None - Found user or None
        """
        return await self.get_one_by_filter(db, email=email)

    async def get_active_users(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[User]:
        """
        Get all active users.
        
        获取所有活跃用户。
        
        Args:
            db: AsyncSession - Database session
            skip: int - Records to skip
            limit: int - Max records
        
        Returns:
            list[User] - Active users
        """
        stmt = select(self.model).where(self.model.is_active == True).offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_superusers(
        self,
        db: AsyncSession,
    ) -> list[User]:
        """
        Get all superusers.
        
        获取所有超级用户。
        
        Args:
            db: AsyncSession - Database session
        
        Returns:
            list[User] - Superusers
        """
        return await self.get_by_filter(db, is_superuser=True)

    async def username_exists(
        self,
        db: AsyncSession,
        username: str,
    ) -> bool:
        """
        Check if username exists.
        
        检查用户名是否存在。
        
        Args:
            db: AsyncSession - Database session
            username: str - Username
        
        Returns:
            bool - True if exists
        """
        return await self.exists(db, username=username)

    async def email_exists(
        self,
        db: AsyncSession,
        email: str,
    ) -> bool:
        """
        Check if email exists.
        
        检查邮箱是否存在。
        
        Args:
            db: AsyncSession - Database session
            email: str - Email address
        
        Returns:
            bool - True if exists
        """
        return await self.exists(db, email=email)
