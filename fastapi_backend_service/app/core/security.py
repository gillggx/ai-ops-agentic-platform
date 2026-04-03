## app/core/security.py
"""Security utilities module for the FastAPI Backend Service.

This module provides password hashing and JWT token management utilities.
All password operations and token operations should be performed exclusively
through the functions defined in this module to ensure consistent security
practices throughout the application.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt as _bcrypt
from jose import JWTError, jwt

from app.config import get_settings


# ---------------------------------------------------------------------------
# Password Utilities  (direct bcrypt — bypasses passlib incompatibility)
# ---------------------------------------------------------------------------


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    pw_bytes = plain_password.encode("utf-8")
    hash_bytes = (
        hashed_password.encode("utf-8")
        if isinstance(hashed_password, str)
        else hashed_password
    )
    return _bcrypt.checkpw(pw_bytes, hash_bytes)


def get_password_hash(password: str) -> str:
    """Return a bcrypt hash of *password*."""
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


# ---------------------------------------------------------------------------
# JWT Token Utilities
# ---------------------------------------------------------------------------


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token.

    Encodes the provided ``data`` payload into a JWT token, signed using the
    application's ``SECRET_KEY`` and ``ALGORITHM`` from the configuration.
    An expiration claim (``exp``) is automatically added to the payload.

    Args:
        data: A dictionary of claims to encode into the token. Typically
              contains at minimum ``{"sub": username}``.
        expires_delta: Optional custom expiration duration. If ``None``, the
                       default expiration from ``ACCESS_TOKEN_EXPIRE_MINUTES``
                       in application settings is used.

    Returns:
        A signed JWT token string that can be returned to the client.

    Examples:
        >>> token = create_access_token(data={"sub": "alice"})
        >>> isinstance(token, str)
        True

        >>> token = create_access_token(
        ...     data={"sub": "alice"},
        ...     expires_delta=timedelta(hours=1),
        ... )
        >>> isinstance(token, str)
        True
    """
    settings = get_settings()

    to_encode: dict[str, Any] = data.copy()

    if expires_delta is not None:
        expire: datetime = datetime.now(tz=timezone.utc) + expires_delta
    else:
        expire = datetime.now(tz=timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode["exp"] = expire

    encoded_jwt: str = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Decodes the given JWT token string using the application's ``SECRET_KEY``
    and ``ALGORITHM``. Validates the token signature and expiration claim.

    Args:
        token: The JWT token string to decode and verify.

    Returns:
        A dictionary containing the decoded token payload (claims),
        e.g. ``{"sub": "alice", "exp": 1234567890}``.

    Raises:
        JWTError: If the token is invalid, expired, or the signature cannot
                  be verified. Callers should catch this and raise an
                  ``AppException`` with an appropriate HTTP 401 status.

    Examples:
        >>> token = create_access_token(data={"sub": "alice"})
        >>> payload = decode_access_token(token)
        >>> payload["sub"]
        'alice'

        >>> decode_access_token("invalid.token.string")
        Traceback (most recent call last):
            ...
        jose.exceptions.JWTError: ...
    """
    settings = get_settings()

    payload: dict[str, Any] = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )

    return payload
