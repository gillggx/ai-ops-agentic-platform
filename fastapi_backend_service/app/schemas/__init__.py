## app/schemas/__init__.py
"""Schemas package for the FastAPI Backend Service.

This package exposes all Pydantic schema classes used for request validation,
response serialization, and data transfer throughout the application.

Modules:
    common: Shared schemas such as StandardResponse and PaginationParams.
    user: User-related schemas for creation, update, response, login, and token.
    item: Item-related schemas for creation, update, and response.
"""

from app.schemas.common import HealthResponse, PaginationParams, StandardResponse
from app.schemas.user import (
    LoginRequest,
    TokenSchema,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.schemas.item import (
    ItemCreate,
    ItemResponse,
    ItemUpdate,
)

__all__ = [
    # Common
    "HealthResponse",
    "PaginationParams",
    "StandardResponse",
    # User
    "LoginRequest",
    "TokenSchema",
    "UserCreate",
    "UserResponse",
    "UserUpdate",
    # Item
    "ItemCreate",
    "ItemResponse",
    "ItemUpdate",
]
