"""
SystemParameter-related Pydantic schemas.

SystemParameter 相關的驗證模型。
"""

from typing import Optional

from pydantic import Field

from .common import IdSchema


class SystemParameterCreate(IdSchema):
    """
    Schema for creating a system parameter.
    
    創建系統參數的驗證模型。
    """

    key: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Parameter key (e.g., DEFAULT_EVENT_TIMEOUT)"
    )
    value: str = Field(
        ...,
        min_length=0,
        max_length=10000,
        description="Parameter value"
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Parameter description"
    )
    category: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Category (e.g., timing, feature, llm)"
    )
    is_secret: bool = Field(
        default=False,
        description="Whether value is sensitive"
    )


class SystemParameterUpdate(IdSchema):
    """
    Schema for updating a system parameter.
    
    更新系統參數的驗證模型。
    """

    value: Optional[str] = Field(
        default=None,
        min_length=0,
        max_length=10000,
        description="New value"
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
    is_secret: Optional[bool] = Field(
        default=None,
        description="Update secret status"
    )


class SystemParameterRead(IdSchema):
    """
    Schema for reading system parameter.
    
    讀取系統參數的驗證模型。
    """

    id: int = Field(
        ...,
        description="Parameter ID"
    )
    key: str = Field(
        ...,
        description="Parameter key"
    )
    value: str = Field(
        ...,
        description="Parameter value"
    )
    description: str = Field(
        ...,
        description="Description"
    )
    category: str = Field(
        ...,
        description="Category"
    )
    is_secret: bool = Field(
        default=False,
        description="Is secret"
    )

    class Config:
        """Pydantic config."""
        from_attributes = True


class SystemParameterReadWithoutSecret(IdSchema):
    """
    Schema for reading parameter without secret values.
    
    讀取參數而不顯示機密值的驗證模型。
    """

    id: int
    key: str
    value: Optional[str] = Field(
        default="***",
        description="Value (masked if secret)"
    )
    description: str
    category: str
    is_secret: bool

    class Config:
        from_attributes = True
