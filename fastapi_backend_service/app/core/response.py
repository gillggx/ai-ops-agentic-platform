## app/core/response.py
"""Standardized API response formatting module for the FastAPI Backend Service.

This module provides a unified response structure for all API endpoints,
ensuring consistent JSON response format across the entire application.
All responses follow the structure: {status, message, data, error_code}.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class StandardResponse(BaseModel):
    """Unified API response schema for all endpoints.

    Provides a consistent response envelope with ``status``, ``message``,
    and ``data`` fields. Use the ``success`` and ``error`` class methods
    as factories to construct well-formed responses without manually
    setting each field.

    Attributes:
        status: A short string indicating the outcome, e.g. ``"success"`` or ``"error"``.
        message: A human-readable description of the outcome.
        data: The payload of the response. ``None`` for error responses or
              operations that return no data (e.g. DELETE).

    Examples:
        Creating a success response with data::

            response = StandardResponse.success(
                data={"id": 1, "username": "alice"},
                message="使用者取得成功",
            )
            # StandardResponse(status='success', message='使用者取得成功', data={'id': 1, ...})

        Creating a success response without data::

            response = StandardResponse.success(message="使用者已刪除")
            # StandardResponse(status='success', message='使用者已刪除', data=None)

        Creating an error response::

            response = StandardResponse.error(
                message="使用者不存在",
                error_code="NOT_FOUND",
            )
            # StandardResponse(status='error', message='NOT_FOUND: 使用者不存在', data=None)
    """

    status: str = Field(
        default="success",
        description="Response status indicator: 'success' or 'error'.",
        examples=["success", "error"],
    )
    message: str = Field(
        default="操作成功",
        description="Human-readable description of the response outcome.",
        examples=["操作成功", "使用者不存在"],
    )
    data: Optional[Any] = Field(
        default=None,
        description="Response payload. None when there is no data to return.",
    )
    error_code: Optional[str] = Field(
        default=None,
        description="Machine-readable error code. Present only in error responses.",
        examples=["NOT_FOUND", "UNAUTHORIZED", "CONFLICT"],
    )

    @classmethod
    def success(
        cls,
        data: Optional[Any] = None,
        message: str = "操作成功",
    ) -> "StandardResponse":
        """Construct a successful standard response.

        Args:
            data: The payload to include in the response. Defaults to ``None``
                  for operations that produce no output (e.g. DELETE).
            message: A human-readable success message. Defaults to ``"操作成功"``.

        Returns:
            A ``StandardResponse`` instance with ``status`` set to ``"success"``.

        Examples:
            >>> resp = StandardResponse.success(data={"id": 1}, message="查詢成功")
            >>> resp.status
            'success'
            >>> resp.data
            {'id': 1}
        """
        return cls(
            status="success",
            message=message,
            data=data,
        )

    @classmethod
    def error(
        cls,
        message: str = "操作失敗",
        error_code: Optional[str] = None,
    ) -> "StandardResponse":
        """Construct an error standard response.

        Combines the ``error_code`` and ``message`` into the ``message`` field
        so that clients can easily identify the error type alongside its
        human-readable description. The ``data`` field is always ``None`` for
        error responses.

        Args:
            message: A human-readable description of the error. Defaults to ``"操作失敗"``.
            error_code: A machine-readable error code constant (e.g. ``"NOT_FOUND"``).
                        When provided, it is prepended to the message as
                        ``"<error_code>: <message>"``. Defaults to ``None``.

        Returns:
            A ``StandardResponse`` instance with ``status`` set to ``"error"``
            and ``data`` set to ``None``.

        Examples:
            >>> resp = StandardResponse.error(message="使用者不存在", error_code="NOT_FOUND")
            >>> resp.status
            'error'
            >>> resp.message
            '使用者不存在'
            >>> resp.error_code
            'NOT_FOUND'
            >>> resp.data is None
            True
        """
        return cls(
            status="error",
            message=message,
            data=None,
            error_code=error_code,
        )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "success",
                    "message": "操作成功",
                    "data": None,
                    "error_code": None,
                },
                {
                    "status": "error",
                    "message": "使用者不存在",
                    "data": None,
                    "error_code": "NOT_FOUND",
                },
            ]
        }
    }


class HealthResponse(BaseModel):
    """Response schema for the GET /health endpoint.

    Attributes:
        status: Service health status, e.g. ``"ok"`` or ``"degraded"``.
        version: Application version string from ``Config.APP_VERSION``.
        database: Database connectivity status, e.g. ``"connected"`` or ``"unavailable"``.
        timestamp: ISO-8601 UTC timestamp of when the health check was performed.

    Examples:
        >>> resp = HealthResponse(
        ...     status="ok",
        ...     version="1.0.0",
        ...     database="connected",
        ...     timestamp=datetime.now(timezone.utc),
        ... )
    """

    status: str = Field(
        description="Service health status.",
        examples=["ok", "degraded"],
    )
    version: str = Field(
        description="Application version string.",
        examples=["1.0.0"],
    )
    database: str = Field(
        description="Database connectivity status.",
        examples=["connected", "unavailable"],
    )
    timestamp: datetime = Field(
        description="UTC timestamp of the health check.",
    )
