"""EventType ORM model — defines an alarm/anomaly event and its attributes."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EventTypeModel(Base):
    """Defines an event type (e.g. SPC_OOC_Etch) with structured attributes."""

    __tablename__ = "event_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON: [{"name": str, "type": "string|number|boolean", "description": str, "required": bool}]
    # NOTE: description on each attribute is MANDATORY (LLM mapping relies on it)
    attributes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON list of Skill IDs to run when this event type is diagnosed: [1, 2, 3]
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
