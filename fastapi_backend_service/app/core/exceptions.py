## app/core/exceptions.py
"""Custom exception classes and error code constants for the FastAPI Backend Service.

This module provides a unified exception handling mechanism with standardized
error codes, making it easy for clients to programmatically identify and handle
specific error conditions.
"""

from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Error Code Constants
# ---------------------------------------------------------------------------

ERROR_CODE_BAD_REQUEST: str = "BAD_REQUEST"
"""Indicates a malformed or invalid request from the client."""

ERROR_CODE_UNAUTHORIZED: str = "UNAUTHORIZED"
"""Indicates missing or invalid authentication credentials."""

ERROR_CODE_FORBIDDEN: str = "FORBIDDEN"
"""Indicates the authenticated user lacks permission for the requested resource."""

ERROR_CODE_NOT_FOUND: str = "NOT_FOUND"
"""Indicates the requested resource could not be found."""

ERROR_CODE_CONFLICT: str = "CONFLICT"
"""Indicates a conflict with the current state of the resource (e.g., duplicate entry)."""

ERROR_CODE_UNPROCESSABLE_ENTITY: str = "UNPROCESSABLE_ENTITY"
"""Indicates the request is well-formed but contains semantic errors."""

ERROR_CODE_INTERNAL_SERVER_ERROR: str = "INTERNAL_SERVER_ERROR"
"""Indicates an unexpected server-side error."""


# ---------------------------------------------------------------------------
# Custom Exception Class
# ---------------------------------------------------------------------------


class AppException(HTTPException):
    """Application-level exception with a structured error code.

    Extends FastAPI's ``HTTPException`` to include an ``error_code`` field,
    enabling clients to distinguish between different error conditions
    programmatically without relying solely on HTTP status codes.

    Attributes:
        status_code: The HTTP status code to return to the client.
        error_code: A machine-readable string constant identifying the error type.
        detail: A human-readable description of the error.

    Examples:
        Raise a 404 Not Found exception:

        >>> raise AppException(
        ...     status_code=404,
        ...     error_code=ERROR_CODE_NOT_FOUND,
        ...     detail="使用者不存在",
        ... )

        Raise a 409 Conflict exception:

        >>> raise AppException(
        ...     status_code=409,
        ...     error_code=ERROR_CODE_CONFLICT,
        ...     detail="電子郵件已被使用",
        ... )

        Raise a 401 Unauthorized exception:

        >>> raise AppException(
        ...     status_code=401,
        ...     error_code=ERROR_CODE_UNAUTHORIZED,
        ...     detail="無效的身份驗證憑證",
        ... )
    """

    def __init__(
        self,
        status_code: int,
        error_code: str,
        detail: str,
    ) -> None:
        """Initialise the AppException.

        Args:
            status_code: The HTTP status code (e.g. 400, 401, 403, 404, 409, 422, 500).
            error_code: A machine-readable error code constant (e.g. ``ERROR_CODE_NOT_FOUND``).
            detail: A human-readable message describing the error condition.
        """
        super().__init__(status_code=status_code, detail=detail)
        self.error_code: str = error_code
        self.status_code: int = status_code
        self.detail: str = detail

    def __repr__(self) -> str:
        """Return a developer-friendly string representation.

        Returns:
            A string showing the class name, status code, error code, and detail.
        """
        return (
            f"AppException("
            f"status_code={self.status_code!r}, "
            f"error_code={self.error_code!r}, "
            f"detail={self.detail!r})"
        )
