## app/models/item.py
"""Item ORM model module for the FastAPI Backend Service.

This module defines the ``ItemModel`` SQLAlchemy ORM class, which maps to the
``items`` table in the database. It includes all item-related fields and
establishes a many-to-one relationship with ``UserModel``.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import UserModel


class ItemModel(Base):
    """SQLAlchemy ORM model representing an item in the system.

    Maps to the ``items`` database table and stores item content, status flags,
    and ownership information. Establishes a many-to-one relationship with
    ``UserModel`` via the ``owner`` back-reference.

    Attributes:
        id: Auto-incremented primary key.
        title: The title of the item; required and non-nullable.
        description: An optional long-form description of the item.
        is_active: Flag indicating whether the item is active/visible.
        owner_id: Foreign key referencing the owning user's ``id``.
        created_at: Timestamp of when the record was created (UTC).
        updated_at: Timestamp of the last update to the record (UTC).
        owner: Many-to-one relationship to :class:`~app.models.user.UserModel`.

    Examples:
        Creating a new item model instance::

            item = ItemModel(
                title="My First Item",
                description="A detailed description of my item.",
                is_active=True,
                owner_id=1,
            )
    """

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
        comment="Auto-incremented primary key",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Title of the item",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="Optional long-form description of the item",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
        comment="Whether the item is active/visible",
    )
    owner_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Foreign key referencing the owning user",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=timezone.utc),
        server_default=func.now(),
        comment="UTC timestamp of when this record was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(tz=timezone.utc),
        comment="UTC timestamp of the last update to this record",
    )

    # ---------------------------------------------------------------------------
    # Relationships
    # ---------------------------------------------------------------------------

    owner: Mapped["UserModel"] = relationship(
        "UserModel",
        back_populates="items",
        lazy="select",
    )

    # ---------------------------------------------------------------------------
    # Dunder Methods
    # ---------------------------------------------------------------------------

    def __repr__(self) -> str:
        """Return a developer-friendly string representation of the item.

        Returns:
            A string showing the class name, id, title, is_active, and owner_id.
        """
        return (
            f"ItemModel("
            f"id={self.id!r}, "
            f"title={self.title!r}, "
            f"is_active={self.is_active!r}, "
            f"owner_id={self.owner_id!r})"
        )

    def __str__(self) -> str:
        """Return a user-friendly string representation.

        Returns:
            A string in the format ``title (owner_id=<owner_id>)``.
        """
        return f"{self.title} (owner_id={self.owner_id})"
