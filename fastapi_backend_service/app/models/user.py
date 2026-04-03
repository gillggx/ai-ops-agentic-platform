## app/models/user.py
"""User ORM model module for the FastAPI Backend Service.

This module defines the ``UserModel`` SQLAlchemy ORM class, which maps to the
``users`` table in the database. It includes all user-related fields and
establishes a one-to-many relationship with ``ItemModel``.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.item import ItemModel


class UserModel(Base):
    """SQLAlchemy ORM model representing a user in the system.

    Maps to the ``users`` database table and stores authentication credentials,
    profile information, and account status flags. Establishes a one-to-many
    relationship with ``ItemModel`` via the ``items`` back-reference.

    Attributes:
        id: Auto-incremented primary key.
        username: Unique username string, indexed for fast lookup.
        email: Unique email address, indexed for fast lookup.
        hashed_password: Bcrypt-hashed password string; never stores plain text.
        is_active: Flag indicating whether the user account is active.
        is_superuser: Flag indicating whether the user has superuser privileges.
        created_at: Timestamp of when the record was created (UTC).
        updated_at: Timestamp of the last update to the record (UTC).
        items: One-to-many relationship to :class:`~app.models.item.ItemModel`.

    Examples:
        Creating a new user model instance::

            user = UserModel(
                username="alice",
                email="alice@example.com",
                hashed_password="$2b$12$...",
                is_active=True,
                is_superuser=False,
            )
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
        comment="Auto-incremented primary key",
    )
    username: Mapped[str] = mapped_column(
        String(150),
        unique=True,
        index=True,
        nullable=False,
        comment="Unique username for the user",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        comment="Unique email address for the user",
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Bcrypt-hashed password; plain-text passwords are never stored",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
        comment="Whether the user account is active",
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        comment="Whether the user has superuser (admin) privileges",
    )
    roles: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        server_default="'[]'",
        comment="JSON-encoded list of roles: it_admin, expert_pe, general_user",
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

    items: Mapped[List["ItemModel"]] = relationship(
        "ItemModel",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # ---------------------------------------------------------------------------
    # Dunder Methods
    # ---------------------------------------------------------------------------

    def __repr__(self) -> str:
        """Return a developer-friendly string representation of the user.

        Returns:
            A string showing the class name, id, username, and email.
        """
        return (
            f"UserModel("
            f"id={self.id!r}, "
            f"username={self.username!r}, "
            f"email={self.email!r}, "
            f"is_active={self.is_active!r}, "
            f"is_superuser={self.is_superuser!r})"
        )

    def __str__(self) -> str:
        """Return a user-friendly string representation.

        Returns:
            A string in the format ``username <email>``.
        """
        return f"{self.username} <{self.email}>"
