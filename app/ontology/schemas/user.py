"""
User-related Pydantic schemas.

用戶相關的驗證模型。
"""

import json
from typing import Any, List, Optional

from pydantic import EmailStr, Field, field_validator

from .common import IdSchema


class UserCreate(IdSchema):
    """
    Schema for creating a new user.
    
    創建新用戶的驗證模型。
    """

    username: str = Field(
        ...,
        min_length=3,
        max_length=150,
        description="Username (3-150 characters)"
    )
    email: EmailStr = Field(
        ...,
        description="Valid email address"
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=255,
        description="Password (8+ characters)"
    )
    roles: Optional[List[str]] = Field(
        default=None,
        description="Initial roles (defaults to ['user'])"
    )


class UserUpdate(IdSchema):
    """
    Schema for updating a user.
    
    更新用戶的驗證模型。
    """

    username: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=150,
        description="New username"
    )
    email: Optional[EmailStr] = Field(
        default=None,
        description="New email address"
    )
    password: Optional[str] = Field(
        default=None,
        min_length=8,
        max_length=255,
        description="New password"
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Whether user is active"
    )


class UserRead(IdSchema):
    """
    Schema for reading/returning user data.
    
    讀取/返回用戶數據的驗證模型。
    """

    id: int = Field(
        ...,
        description="User ID"
    )
    username: str = Field(
        ...,
        description="Username"
    )
    email: str = Field(
        ...,
        description="User email"
    )
    is_active: bool = Field(
        ...,
        description="Whether user is active"
    )
    is_superuser: bool = Field(
        default=False,
        description="Whether user is superuser"
    )
    roles: List[str] = Field(
        default_factory=lambda: ["user"],
        description="User roles"
    )

    @field_validator("roles", mode="before")
    @classmethod
    def parse_roles(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return [v] if v else []
        return v

    class Config:
        """Pydantic config."""

        from_attributes = True


class UserLoginSchema(IdSchema):
    """
    Schema for user login.
    
    用户登录的验证模型。
    """
    
    username: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Username"
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Password"
    )


class UserRegisterSchema(IdSchema):
    """
    Schema for user registration.
    
    用户注册的验证模型。
    """
    
    username: str = Field(
        ...,
        min_length=3,
        max_length=150,
        description="Username (3-150 characters)"
    )
    email: EmailStr = Field(
        ...,
        description="Valid email address"
    )
    password: str = Field(
        ...,
        min_length=4,
        max_length=255,
        description="Password (4+ characters)"
    )
    role: Optional[str] = Field(
        default="user",
        description="User role (defaults to 'user')"
    )
