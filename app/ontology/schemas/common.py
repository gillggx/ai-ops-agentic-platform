"""
Common Pydantic schemas used across all layers.

基礎和通用驗證模型。
"""

from datetime import datetime
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class BaseSchema(BaseModel):
    """
    Base Pydantic schema with common configuration.
    
    所有 schema 的基類，提供通用配置。
    
    Config:
    - populate_by_name: Allow population by field name or alias
    - from_attributes: Support ORM model conversion
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        json_schema_extra={
            "example": "See specific schema for example"
        }
    )


class TimestampedSchema(BaseSchema):
    """
    Schema with timestamp fields.
    
    包含時間戳字段的 schema。
    """

    created_at: Optional[datetime] = Field(
        default=None,
        description="Creation timestamp (UTC)"
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Last update timestamp (UTC)"
    )


class IdSchema(TimestampedSchema):
    """
    Schema with ID field.
    
    包含 ID 字段的 schema。
    """

    id: Optional[int] = Field(
        default=None,
        description="Primary key"
    )


class SuccessResponse(BaseSchema, Generic[T]):
    """
    Standard success response wrapper.
    
    標準成功響應包裝器。
    
    Used for consistent API responses.
    用於一致的 API 響應。
    
    Example:
        {
            "success": true,
            "message": "Operation completed",
            "data": { ... }
        }
    """

    success: bool = Field(
        default=True,
        description="Whether operation was successful"
    )
    message: str = Field(
        ...,
        description="Response message"
    )
    data: Optional[T] = Field(
        default=None,
        description="Response data"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Response timestamp (UTC)"
    )


class ErrorResponse(BaseSchema):
    """
    Standard error response wrapper.
    
    標準錯誤響應包裝器。
    
    Example:
        {
            "success": false,
            "error": "not_found",
            "message": "Resource not found",
            "details": {...}
        }
    """

    success: bool = Field(
        default=False,
        description="Always false for errors"
    )
    error: str = Field(
        ...,
        description="Error code"
    )
    message: str = Field(
        ...,
        description="Error message"
    )
    details: Optional[dict[str, Any]] = Field(
        default=None,
        description="Additional error details"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Error timestamp (UTC)"
    )


class PagedResponse(BaseSchema, Generic[T]):
    """
    Paginated response wrapper.
    
    分頁響應包裝器。
    
    Example:
        {
            "success": true,
            "data": [...],
            "total": 100,
            "page": 1,
            "page_size": 20,
            "total_pages": 5
        }
    """

    success: bool = Field(
        default=True,
        description="Whether operation was successful"
    )
    data: List[T] = Field(
        default_factory=list,
        description="Page data"
    )
    total: int = Field(
        default=0,
        description="Total number of items"
    )
    page: int = Field(
        default=1,
        description="Current page number (1-indexed)"
    )
    page_size: int = Field(
        default=20,
        description="Number of items per page"
    )
    total_pages: int = Field(
        default=0,
        description="Total number of pages"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Response timestamp (UTC)"
    )

    def calculate_total_pages(self) -> None:
        """
        Calculate total pages based on total and page_size.
        
        根據 total 和 page_size 計算總頁數。
        """
        if self.page_size > 0:
            self.total_pages = (self.total + self.page_size - 1) // self.page_size
        else:
            self.total_pages = 0


class ListResponse(BaseSchema, Generic[T]):
    """
    List response with pagination info.
    
    帶分頁信息的列表響應。
    
    Example:
        {
            "items": [...],
            "total": 100,
            "skip": 0,
            "limit": 20
        }
    """

    items: List[T] = Field(
        default_factory=list,
        description="List of items"
    )
    total: int = Field(
        default=0,
        description="Total number of items"
    )
    skip: int = Field(
        default=0,
        description="Number of items skipped"
    )
    limit: int = Field(
        default=100,
        description="Max items returned"
    )


class PaginationParams(BaseSchema):
    """
    Common pagination parameters.
    
    通用分頁參數。
    """

    skip: int = Field(
        default=0,
        ge=0,
        description="Number of records to skip"
    )
    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Max records to return"
    )
