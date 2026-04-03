"""
DataSubject-related Pydantic schemas.

DataSubject 相關的驗證模型。
"""

from typing import Optional

from pydantic import Field

from .common import IdSchema


class DataSubjectCreate(IdSchema):
    """
    Schema for creating a new data subject.
    
    創建新數據主體的驗證模型。
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Name of data subject"
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
        description="Category (e.g., equipment, process, customer)"
    )
    external_id: Optional[str] = Field(
        default=None,
        max_length=255,
        description="External system ID"
    )
    custom_metadata: Optional[dict] = Field(
        default=None,
        description="Additional metadata as JSON"
    )
    is_active: bool = Field(
        default=True,
        description="Whether this subject is active"
    )


class DataSubjectUpdate(IdSchema):
    """
    Schema for updating a data subject.
    
    更新數據主體的驗證模型。
    """

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
    external_id: Optional[str] = Field(
        default=None,
        max_length=255,
        description="New external ID"
    )
    custom_metadata: Optional[dict] = Field(
        default=None,
        description="New metadata"
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Whether to activate/deactivate"
    )


class DataSubjectRead(IdSchema):
    """
    Schema for reading/returning data subject.
    
    讀取/返回數據主體的驗證模型。
    """

    id: int = Field(
        ...,
        description="Data subject ID"
    )
    name: str = Field(
        ...,
        description="Name"
    )
    description: str = Field(
        ...,
        description="Description"
    )
    category: Optional[str] = Field(
        default=None,
        description="Category"
    )
    external_id: Optional[str] = Field(
        default=None,
        description="External ID"
    )
    custom_metadata: dict = Field(
        default_factory=dict,
        description="Metadata"
    )
    is_active: bool = Field(
        default=True,
        description="Active status"
    )

    class Config:
        """Pydantic config."""
        from_attributes = True
