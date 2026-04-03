"""
User model for the Ontology layer.

Define the User entity and related enums for authentication and authorization.
定義 User 實體和相關的枚舉以支持認證和授權。
"""

from enum import Enum
from typing import List, Optional

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class UserRole(str, Enum):
    """
    User role enumeration.
    
    Define the different roles a user can have in the system.
    定義系統中用戶可以擁有的不同角色。
    """

    ADMIN = "admin"  # 系統管理員
    ARCHITECT = "architect"  # 技術架構師
    BACKEND = "backend"  # 後端工程師
    DEVOPS = "devops"  # DevOps 工程師
    QA = "qa"  # QA 工程師
    USER = "user"  # 普通用戶


class User(BaseModel):
    """
    User model for authentication and identification.
    
    Represents a user account in the system.
    
    代表系統中的用戶賬戶。
    
    Attributes:
        username: str - Unique username (唯一用戶名)
        email: str - User's email address (用戶郵箱)
        hashed_password: str - Hashed password (雜湊密碼，不存儲明文)
        is_active: bool - Whether the user is active (用戶是否活躍)
        is_superuser: bool - Whether user is a superuser (超級用戶)
        roles: str - JSON array of roles (用戶角色，JSON 格式)
        
    Example:
        >>> user = User(
        ...     username="alice",
        ...     email="alice@example.com",
        ...     hashed_password="hashed_...",
        ...     roles='["backend", "user"]'
        ... )
    """

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(
        String(150),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique username (唯一用戶名)"
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        doc="User's email address (用戶郵箱)"
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Hashed password using bcrypt (bcrypt 雜湊密碼，不存儲明文)"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether the user is active (用戶是否活躍，默認激活)"
    )

    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether user is a superuser (超級用戶，默認否)"
    )

    roles: Mapped[str] = mapped_column(
        Text,
        default='["user"]',
        nullable=False,
        doc='User roles as JSON array (用戶角色，JSON 數組格式，例如 ["backend", "user"])'
    )

    def add_role(self, role: UserRole) -> None:
        """
        Add a role to the user.
        
        Args:
            role: UserRole - The role to add
        
        Raises:
            ValueError: If role is invalid
        
        為用戶添加角色。如果角色已存在，不會重複添加。
        """
        import json

        if not isinstance(role, UserRole):
            raise ValueError(f"Invalid role: {role}")

        current_roles = json.loads(self.roles)
        if role.value not in current_roles:
            current_roles.append(role.value)
            self.roles = json.dumps(current_roles)

    def remove_role(self, role: UserRole) -> None:
        """
        Remove a role from the user.
        
        Args:
            role: UserRole - The role to remove
        
        Raises:
            ValueError: If role is invalid
        
        從用戶移除角色。
        """
        import json

        if not isinstance(role, UserRole):
            raise ValueError(f"Invalid role: {role}")

        current_roles = json.loads(self.roles)
        if role.value in current_roles:
            current_roles.remove(role.value)
            self.roles = json.dumps(current_roles)

    def has_role(self, role: UserRole) -> bool:
        """
        Check if user has a specific role.
        
        Args:
            role: UserRole - The role to check
        
        Returns:
            bool - True if user has the role, False otherwise
        
        檢查用戶是否擁有特定角色。
        """
        import json

        if not isinstance(role, UserRole):
            return False

        current_roles = json.loads(self.roles)
        return role.value in current_roles

    def get_roles(self) -> List[str]:
        """
        Get all roles for this user.
        
        Returns:
            List[str] - List of role strings
        
        獲取用戶的所有角色。
        """
        import json

        return json.loads(self.roles)

    def __repr__(self) -> str:
        """Return detailed representation."""
        return f"User(id={self.id}, username={self.username!r}, email={self.email!r}, is_active={self.is_active})"

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"{self.username} ({self.email})"
