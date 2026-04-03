"""
Event-related Pydantic schemas.

事件相關的驗證模型。
"""

from typing import Optional

from pydantic import Field

from .common import IdSchema


class EventTypeCreate(IdSchema):
    """
    Schema for creating a new event type.
    
    創建新事件類型的驗證模型。
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Event type name"
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Description of this event type"
    )
    attributes: str = Field(
        default="{}",
        description="JSON schema for event attributes"
    )


class EventTypeRead(IdSchema):
    """
    Schema for reading event type data.
    
    讀取事件類型數據的驗證模型。
    """

    id: int = Field(
        ...,
        description="Event type ID"
    )
    name: str = Field(
        ...,
        description="Event type name"
    )
    description: str = Field(
        ...,
        description="Event type description"
    )
    attributes: str = Field(
        ...,
        description="Event attributes schema"
    )

    class Config:
        """Pydantic config."""

        from_attributes = True


class EventCreate(IdSchema):
    """
    Schema for creating a new event.
    
    創建新事件的驗證模型。
    """

    event_type_id: int = Field(
        ...,
        description="Reference to EventType"
    )
    source: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Event source identifier"
    )
    data: str = Field(
        default="{}",
        description="Event data as JSON string"
    )
    processed: bool = Field(
        default=False,
        description="Whether event has been processed"
    )


class EventRead(IdSchema):
    """
    Schema for reading event data.
    
    讀取事件數據的驗證模型。
    """

    id: int = Field(
        ...,
        description="Event ID"
    )
    event_type_id: int = Field(
        ...,
        description="Event type ID"
    )
    source: str = Field(
        ...,
        description="Event source"
    )
    data: str = Field(
        ...,
        description="Event data"
    )
    processed: bool = Field(
        ...,
        description="Processing status"
    )

    class Config:
        """Pydantic config."""

        from_attributes = True
