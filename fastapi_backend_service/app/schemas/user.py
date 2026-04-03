## app/schemas/user.py
"""User-related Pydantic schemas for the FastAPI Backend Service.

This module provides all Pydantic v2 schema classes for user-related
request validation, response serialization, authentication, and token
management throughout the application.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    """Schema for creating a new user.

    Validates the incoming request body when registering a new user account.
    Enforces username length constraints and minimum password length.

    Attributes:
        username: The desired username. Must be 3–150 characters long,
                  containing only alphanumeric characters and underscores.
        email: A valid email address for the user.
        password: The plain-text password. Must be at least 6 characters long.

    Examples:
        >>> user = UserCreate(
        ...     username="alice",
        ...     email="alice@example.com",
        ...     password="secret123",
        ... )
    """

    username: str = Field(
        ...,
        min_length=3,
        max_length=150,
        description="Unique username for the user. Must be 3–150 characters long.",
        examples=["alice", "bob_smith"],
    )
    email: EmailStr = Field(
        ...,
        description="A valid email address for the user.",
        examples=["alice@example.com"],
    )
    password: str = Field(
        ...,
        min_length=6,
        description="Plain-text password for the user. Must be at least 6 characters.",
        examples=["secret123"],
    )

    @field_validator("username")
    @classmethod
    def username_must_be_alphanumeric_or_underscore(cls, value: str) -> str:
        """Validate that the username contains only alphanumeric characters and underscores.

        Args:
            value: The raw username string from the request.

        Returns:
            The stripped username if valid.

        Raises:
            ValueError: If the username contains invalid characters.
        """
        stripped = value.strip()
        if not all(c.isalnum() or c == "_" for c in stripped):
            raise ValueError(
                "Username must contain only alphanumeric characters and underscores."
            )
        return stripped

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "username": "alice",
                    "email": "alice@example.com",
                    "password": "secret123",
                }
            ]
        }
    }


class UserUpdate(BaseModel):
    """Schema for updating an existing user.

    All fields are optional; only the provided fields will be updated.
    Inherits the same validation constraints as ``UserCreate`` for
    fields that are supplied.

    Attributes:
        username: New username. Optional; must be 3–150 characters if provided,
                  containing only alphanumeric characters and underscores.
        email: New email address. Optional.
        password: New plain-text password. Optional; must be at least 6 characters.
        is_active: Whether the account should be active. Optional.

    Examples:
        Partial update (only username)::

            update = UserUpdate(username="alice_v2")

        Full update::

            update = UserUpdate(
                username="alice_v2",
                email="alice_v2@example.com",
                password="newpassword",
                is_active=True,
            )
    """

    username: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=150,
        description="New username. Must be 3–150 characters if provided.",
        examples=["alice_v2"],
    )
    email: Optional[EmailStr] = Field(
        default=None,
        description="New email address.",
        examples=["alice_v2@example.com"],
    )
    password: Optional[str] = Field(
        default=None,
        min_length=6,
        description="New plain-text password. Must be at least 6 characters if provided.",
        examples=["newpassword123"],
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Whether the user account should be active.",
        examples=[True, False],
    )

    @field_validator("username")
    @classmethod
    def username_must_be_alphanumeric_or_underscore(cls, value: str) -> str:
        """Validate that the username (if provided) contains only allowed characters.

        In Pydantic v2, this validator is only invoked when a non-None value
        is explicitly provided for an ``Optional`` field with ``default=None``,
        so ``value`` is guaranteed to be ``str`` at this point.

        Args:
            value: The raw username string from the request.

        Returns:
            The stripped username if valid.

        Raises:
            ValueError: If the username contains invalid characters.
        """
        stripped = value.strip()
        if not all(c.isalnum() or c == "_" for c in stripped):
            raise ValueError(
                "Username must contain only alphanumeric characters and underscores."
            )
        return stripped

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "username": "alice_v2",
                    "email": "alice_v2@example.com",
                    "password": "newpassword123",
                    "is_active": True,
                }
            ]
        }
    }


class UserResponse(BaseModel):
    """Schema for serializing user data in API responses.

    Used as the response model for user-related endpoints. Excludes sensitive
    fields such as ``hashed_password`` to prevent unintended data exposure.
    Configured with ``from_attributes=True`` to support direct ORM model
    serialization.

    Attributes:
        id: The unique identifier of the user.
        username: The user's username.
        email: The user's email address.
        is_active: Whether the user account is currently active.
        is_superuser: Whether the user has superuser (admin) privileges.
        created_at: UTC timestamp of when the user account was created.

    Examples:
        >>> response = UserResponse(
        ...     id=1,
        ...     username="alice",
        ...     email="alice@example.com",
        ...     is_active=True,
        ...     is_superuser=False,
        ...     created_at=datetime.now(timezone.utc),
        ... )
    """

    id: int = Field(
        ...,
        description="Unique identifier of the user.",
        examples=[1, 42],
    )
    username: str = Field(
        ...,
        description="The user's username.",
        examples=["alice"],
    )
    email: str = Field(
        ...,
        description="The user's email address.",
        examples=["alice@example.com"],
    )
    is_active: bool = Field(
        ...,
        description="Whether the user account is currently active.",
        examples=[True],
    )
    is_superuser: bool = Field(
        ...,
        description="Whether the user has superuser (admin) privileges.",
        examples=[False],
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp of when the user account was created.",
    )

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "username": "alice",
                    "email": "alice@example.com",
                    "is_active": True,
                    "is_superuser": False,
                    "created_at": "2024-01-01T00:00:00Z",
                }
            ]
        },
    }


class LoginRequest(BaseModel):
    """Schema for user login request body.

    Validates the credentials provided by the user when attempting to
    authenticate and receive a JWT access token.

    Attributes:
        username: The user's registered username.
        password: The user's plain-text password.

    Examples:
        >>> login = LoginRequest(username="alice", password="secret123")
    """

    username: str = Field(
        ...,
        description="The user's registered username.",
        examples=["alice"],
    )
    password: str = Field(
        ...,
        description="The user's plain-text password.",
        examples=["secret123"],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "username": "alice",
                    "password": "secret123",
                }
            ]
        }
    }


class TokenSchema(BaseModel):
    """Schema for the JWT access token response.

    Returned by the ``POST /auth/login`` endpoint upon successful authentication.
    The client should store the ``access_token`` and include it as a
    ``Bearer`` token in the ``Authorization`` header for protected endpoints.

    Attributes:
        access_token: The signed JWT access token string.
        token_type: The token type; always ``"bearer"`` for JWT Bearer authentication.

    Examples:
        >>> token = TokenSchema(
        ...     access_token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        ...     token_type="bearer",
        ... )
    """

    access_token: str = Field(
        ...,
        description="The signed JWT access token string.",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )
    token_type: str = Field(
        default="bearer",
        description="The token type. Always 'bearer' for JWT Bearer authentication.",
        examples=["bearer"],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "access_token": (
                        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
                        ".eyJzdWIiOiJhbGljZSIsImV4cCI6MTcwNjc0NTYwMH0"
                        ".signature"
                    ),
                    "token_type": "bearer",
                }
            ]
        }
    }
