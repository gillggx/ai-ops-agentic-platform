"""EventTypeModel — System Event Catalog (Admin-managed)."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EventTypeModel(Base):
    """Defines a System Event type in the catalog (e.g. SPC_OOC, ProcessEnd).

    v18: Admins define event types; Super Users use them to design Skills.
    source tells the system where events of this type originate.
    """

    __tablename__ = "event_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Where events of this type come from
    # "simulator" | "webhook" | "manual"
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="simulator", server_default="simulator"
    )

    # Admin can disable an event type without deleting it
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )

    # Legacy fields — kept for backward compatibility with existing data
    attributes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    diagnosis_skill_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc), server_default=func.now(),
        onupdate=lambda: datetime.now(tz=timezone.utc),
    )

    def __repr__(self) -> str:
        return f"EventTypeModel(id={self.id!r}, name={self.name!r})"
