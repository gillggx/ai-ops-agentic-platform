"""GeneratedEvent ORM model — aligned with original dev.db schema."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class GeneratedEvent(BaseModel):
    """Auto-generated alarm event created by LLM Skill-to-Event mapping engine."""

    __tablename__ = "generated_events"

    # Which EventType this alarm belongs to
    event_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("event_types.id", ondelete="RESTRICT"),
        nullable=False, index=True,
        doc="Reference to EventType"
    )
    # The Skill that triggered this alarm
    source_skill_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skill_definitions.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Skill that generated this event"
    )
    # The RoutineCheck job that triggered this alarm (null if triggered manually)
    source_routine_check_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("routine_checks.id", ondelete="SET NULL"),
        nullable=True, default=None,
        doc="RoutineCheck that triggered this (null if manual)"
    )
    # LLM-mapped event parameters: {"lot_id": "...", "tool_id": "...", ...}
    mapped_parameters: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}",
        doc="LLM-mapped event parameters as JSON"
    )
    # Skill result summary that triggered this alarm
    skill_conclusion: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        doc="Skill conclusion that triggered this event"
    )
    # "pending" | "acknowledged" | "resolved"
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        doc="Event status: pending | acknowledged | resolved"
    )

    def __repr__(self) -> str:
        return (
            f"GeneratedEvent(id={self.id!r}, event_type_id={self.event_type_id!r}, "
            f"status={self.status!r})"
        )
