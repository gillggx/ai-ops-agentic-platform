## app/core/__init__.py
"""Core package for the FastAPI Backend Service.

This package provides core utilities and shared components used throughout
the application, including exception handling, response formatting, and
security utilities.

Modules:
    exceptions: Custom exception classes and error code constants.
    response: Standardized API response formatting.
    security: Password hashing and JWT token management utilities.
"""

from app.core.exceptions import (
    AppException,
    ERROR_CODE_BAD_REQUEST,
    ERROR_CODE_CONFLICT,
    ERROR_CODE_FORBIDDEN,
    ERROR_CODE_INTERNAL_SERVER_ERROR,
    ERROR_CODE_NOT_FOUND,
    ERROR_CODE_UNAUTHORIZED,
    ERROR_CODE_UNPROCESSABLE_ENTITY,
)
from app.core.response import StandardResponse
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)

__all__ = [
    # Exceptions
    "AppException",
    "ERROR_CODE_BAD_REQUEST",
    "ERROR_CODE_CONFLICT",
    "ERROR_CODE_FORBIDDEN",
    "ERROR_CODE_INTERNAL_SERVER_ERROR",
    "ERROR_CODE_NOT_FOUND",
    "ERROR_CODE_UNAUTHORIZED",
    "ERROR_CODE_UNPROCESSABLE_ENTITY",
    # Response
    "StandardResponse",
    # Security
    "create_access_token",
    "decode_access_token",
    "get_password_hash",
    "verify_password",
]
