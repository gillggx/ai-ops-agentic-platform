## app/schemas/common.py
"""Common shared Pydantic schemas for the FastAPI Backend Service.

This module provides reusable schema definitions used across multiple parts
of the application, including a standardized API response envelope,
pagination query parameter handling, and the health-check response schema.
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

        Creating a success response without data::

            response = StandardResponse.success(message="使用者已刪除")

        Creating an error response::

            response = StandardResponse.error(
                message="使用者不存在",
                error_code="NOT_FOUND",
            )
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
            'NOT_FOUND: 使用者不存在'
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
                },
                {
                    "status": "error",
                    "message": "NOT_FOUND: 使用者不存在",
                    "data": None,
                },
            ]
        }
    }


class PaginationParams(BaseModel):
    """Pagination query parameters schema.

    Provides standardized pagination parameters used across list endpoints.
    Both ``skip`` and ``limit`` have sensible defaults and validation
    constraints to prevent excessive data retrieval.

    Attributes:
        skip: The number of records to skip (offset). Must be non-negative.
        limit: The maximum number of records to return. Must be between 1 and 100.

    Examples:
        Using as a FastAPI dependency (via ``Depends``)::

            @router.get("/items")
            async def list_items(
                pagination: PaginationParams = Depends(),
                service: ItemService = Depends(get_item_service),
            ):
                return await service.get_items(
                    skip=pagination.skip,
                    limit=pagination.limit,
                )

        Direct instantiation with defaults::

            params = PaginationParams()
            # PaginationParams(skip=0, limit=10)

        Custom pagination::

            params = PaginationParams(skip=20, limit=5)
            # PaginationParams(skip=20, limit=5)
    """

    skip: int = Field(
        default=0,
        ge=0,
        description="Number of records to skip (offset). Must be non-negative.",
        examples=[0, 10, 20],
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of records to return. Must be between 1 and 100.",
        examples=[10, 25, 50],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "skip": 0,
                    "limit": 10,
                }
            ]
        }
    }


class HealthResponse(BaseModel):
    """Response schema for the GET /health endpoint.

    Attributes:
        status: Service health status, e.g. ``"ok"``.
        version: Application version string.
        database: Database connectivity status, e.g. ``"connected"``.
        timestamp: UTC timestamp of when the health check was performed.
    """

    status: str = Field(examples=["ok", "degraded"])
    version: str = Field(examples=["1.0.0"])
    database: str = Field(examples=["connected", "unavailable"])
    timestamp: datetime
