"""
User service for user management.

用戶管理服務。
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User, UserRole
from ..schemas import UserCreate, UserUpdate
from .base import BaseService


class UserService(BaseService[User, UserCreate, UserUpdate]):
    """
    Service for user management operations.
    
    用戶管理服務。
    
    Handles:
    - User CRUD operations
    - Role management
    - Authentication helpers
    - User queries
    
    功能:
    - 用戶 CRUD 操作
    - 角色管理
    - 認證助手
    - 用戶查詢
    """

    model = User
    create_schema = UserCreate
    update_schema = UserUpdate

    async def get_by_username(
        self,
        db: AsyncSession,
        username: str,
    ) -> Optional[User]:
        """
        Get user by username.
        
        Args:
            db: AsyncSession - Database session
            username: str - Username to search
        
        Returns:
            User or None - Found user or None
        
        根據用戶名查詢用戶。
        """
        from sqlalchemy import select

        stmt = select(User).where(User.username == username)
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_by_email(
        self,
        db: AsyncSession,
        email: str,
    ) -> Optional[User]:
        """
        Get user by email.
        
        Args:
            db: AsyncSession - Database session
            email: str - Email to search
        
        Returns:
            User or None - Found user or None
        
        根據郵箱查詢用戶。
        """
        from sqlalchemy import select

        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_active_users(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[User]:
        """
        Get all active users.
        
        Args:
            db: AsyncSession - Database session
            skip: int - Offset
            limit: int - Limit
        
        Returns:
            list[User] - Active users
        
        獲取所有活躍用戶。
        """
        from sqlalchemy import select

        stmt = (
            select(User)
            .where(User.is_active == True)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def add_role(
        self,
        db: AsyncSession,
        user_id: int,
        role: UserRole,
    ) -> Optional[User]:
        """
        Add a role to user.
        
        Args:
            db: AsyncSession - Database session
            user_id: int - User ID
            role: UserRole - Role to add
        
        Returns:
            User or None - Updated user or None
        
        Raises:
            ValueError: If role is invalid
        
        為用戶添加角色。
        """
        user = await self.read(db, user_id)
        if not user:
            return None

        user.add_role(role)
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user

    async def remove_role(
        self,
        db: AsyncSession,
        user_id: int,
        role: UserRole,
    ) -> Optional[User]:
        """
        Remove a role from user.
        
        Args:
            db: AsyncSession - Database session
            user_id: int - User ID
            role: UserRole - Role to remove
        
        Returns:
            User or None - Updated user or None
        
        Raises:
            ValueError: If role is invalid
        
        從用戶移除角色。
        """
        user = await self.read(db, user_id)
        if not user:
            return None

        user.remove_role(role)
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user

    async def has_role(
        self,
        db: AsyncSession,
        user_id: int,
        role: UserRole,
    ) -> bool:
        """
        Check if user has a role.
        
        Args:
            db: AsyncSession - Database session
            user_id: int - User ID
            role: UserRole - Role to check
        
        Returns:
            bool - True if user has role
        
        檢查用戶是否擁有角色。
        """
        user = await self.read(db, user_id)
        if not user:
            return False

        return user.has_role(role)

    async def deactivate_user(
        self,
        db: AsyncSession,
        user_id: int,
    ) -> Optional[User]:
        """
        Deactivate a user.
        
        Args:
            db: AsyncSession - Database session
            user_id: int - User ID
        
        Returns:
            User or None - Updated user or None
        
        停用用戶。
        """
        user = await self.read(db, user_id)
        if not user:
            return None

        user.is_active = False
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user

    async def activate_user(
        self,
        db: AsyncSession,
        user_id: int,
    ) -> Optional[User]:
        """
        Activate a user.
        
        Args:
            db: AsyncSession - Database session
            user_id: int - User ID
        
        Returns:
            User or None - Updated user or None
        
        激活用戶。
        """
        user = await self.read(db, user_id)
        if not user:
            return None

        user.is_active = True
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user
