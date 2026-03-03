"""GeneratedEvent ORM model — auto-alarm created by LLM mapping engine (Phase 11)."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from app.database import Base


class GeneratedEventModel(Base):
    """An auto-generated alarm event created by the LLM Skill-to-Event mapping engine."""

    __tablename__ = "generated_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Which EventType this alarm belongs to
    event_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("event_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # The Skill that triggered this alarm
    source_skill_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skill_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    # The RoutineCheck job that triggered this alarm (null if triggered manually)
    source_routine_check_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("routine_checks.id", ondelete="SET NULL"), nullable=True, default=None
    )
    # LLM-mapped event parameters: {"lot_id": "...", "tool_id": "...", ...}
    mapped_parameters: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # Skill result summary that triggered this alarm
    skill_conclusion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # "pending" | "acknowledged" | "resolved"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
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
        return (
            f"GeneratedEventModel(id={self.id!r}, event_type_id={self.event_type_id!r}, "
            f"status={self.status!r})"
        )
