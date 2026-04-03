"""
MockData-related Pydantic schemas.

MockData 相關的驗證模型。
"""

from typing import Optional

from pydantic import Field

from .common import IdSchema


class MockDataCreate(IdSchema):
    """Schema for creating mock data."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Mock data name"
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Description"
    )
    category: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Data category (e.g., equipment, process, sensor)"
    )
    data_content: dict = Field(
        ...,
        description="Mock data content (JSON)"
    )
    is_featured: bool = Field(
        default=False,
        description="Whether to feature in UI"
    )
    source_url: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Original source URL"
    )


class MockDataUpdate(IdSchema):
    """Schema for updating mock data."""

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="New name"
    )
    description: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=5000,
        description="New description"
    )
    category: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="New category"
    )
    data_content: Optional[dict] = Field(
        default=None,
        description="New data content"
    )
    is_featured: Optional[bool] = Field(
        default=None,
        description="Update featured status"
    )
    source_url: Optional[str] = Field(
        default=None,
        max_length=500,
        description="New source URL"
    )


class MockDataRead(IdSchema):
    """Schema for reading mock data."""

    id: int
    name: str
    description: str
    category: str
    data_content: dict
    is_featured: bool = Field(default=False)
    source_url: Optional[str] = None

    class Config:
        from_attributes = True
