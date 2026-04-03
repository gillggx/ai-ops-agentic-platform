## app/schemas/item.py
"""Item-related Pydantic schemas for the FastAPI Backend Service.

This module provides all Pydantic v2 schema classes for item-related
request validation and response serialization throughout the application.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    """Schema for creating a new item.

    Validates the incoming request body when creating a new item.
    Only the ``title`` field is required; ``description`` is optional.

    Attributes:
        title: The title of the item. Must be 1–255 characters long.
        description: An optional long-form description of the item.

    Examples:
        Minimal creation (title only)::

            item = ItemCreate(title="My First Item")

        Full creation::

            item = ItemCreate(
                title="My First Item",
                description="A detailed description of my item.",
            )
    """

    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Title of the item. Must be 1–255 characters long.",
        examples=["My First Item", "Shopping List"],
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional long-form description of the item.",
        examples=["A detailed description of my item.", None],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "title": "My First Item",
                    "description": "A detailed description of my item.",
                }
            ]
        }
    }


class ItemUpdate(BaseModel):
    """Schema for updating an existing item.

    All fields are optional; only the provided fields will be updated.
    Inherits the same validation constraints as ``ItemCreate`` for
    fields that are supplied.

    Attributes:
        title: New title of the item. Optional; must be 1–255 characters if provided.
        description: New description of the item. Optional.
        is_active: Whether the item should be active/visible. Optional.

    Examples:
        Partial update (title only)::

            update = ItemUpdate(title="Updated Title")

        Full update::

            update = ItemUpdate(
                title="Updated Title",
                description="Updated description.",
                is_active=False,
            )
    """

    title: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New title of the item. Must be 1–255 characters if provided.",
        examples=["Updated Title"],
    )
    description: Optional[str] = Field(
        default=None,
        description="New description of the item.",
        examples=["Updated description."],
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Whether the item should be active/visible.",
        examples=[True, False],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "title": "Updated Title",
                    "description": "Updated description.",
                    "is_active": True,
                }
            ]
        }
    }


class ItemResponse(BaseModel):
    """Schema for serializing item data in API responses.

    Used as the response model for item-related endpoints. Configured
    with ``from_attributes=True`` to support direct ORM model serialization.

    Attributes:
        id: The unique identifier of the item.
        title: The title of the item.
        description: An optional long-form description of the item.
        is_active: Whether the item is currently active/visible.
        owner_id: The unique identifier of the user who owns this item.
        created_at: UTC timestamp of when the item was created.

    Examples:
        >>> from datetime import datetime, timezone
        >>> response = ItemResponse(
        ...     id=1,
        ...     title="My First Item",
        ...     description="A detailed description.",
        ...     is_active=True,
        ...     owner_id=42,
        ...     created_at=datetime.now(timezone.utc),
        ... )
    """

    id: int = Field(
        ...,
        description="Unique identifier of the item.",
        examples=[1, 42],
    )
    title: str = Field(
        ...,
        description="The title of the item.",
        examples=["My First Item"],
    )
    description: Optional[str] = Field(
        default=None,
        description="An optional long-form description of the item.",
        examples=["A detailed description of my item.", None],
    )
    is_active: bool = Field(
        ...,
        description="Whether the item is currently active/visible.",
        examples=[True],
    )
    owner_id: int = Field(
        ...,
        description="Unique identifier of the user who owns this item.",
        examples=[1, 42],
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp of when the item was created.",
    )

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "title": "My First Item",
                    "description": "A detailed description of my item.",
                    "is_active": True,
                    "owner_id": 1,
                    "created_at": "2024-01-01T00:00:00Z",
                }
            ]
        },
    }
