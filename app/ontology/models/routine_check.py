"""RoutineCheck ORM model — aligned with original dev.db schema.

skill_id FK → skill_definitions (original style).
Extra refactored fields are nullable for forward compat.
"""

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.ontology.models.base import BaseModel


class RoutineCheckModel(BaseModel):
    """A periodic inspection job linked to a SkillDefinition."""

    __tablename__ = "routine_checks"
    __table_args__ = {"extend_existing": True}

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    # Original FK: skill_definitions (not skills instance table)
    skill_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skill_definitions.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    skill_input: Mapped[str] = mapped_column("preset_parameters", Text, nullable=False, default="{}")
    trigger_event_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("event_types.id", ondelete="SET NULL"), nullable=True
    )
    event_param_mappings: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    schedule_interval: Mapped[str] = mapped_column(String(20), nullable=False, default="1h")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_run_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    expire_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    schedule_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)

    # Refactored extra fields — nullable for forward compat
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cron_expression: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_enabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"RoutineCheckModel(id={self.id}, name={self.name!r}, skill_id={self.skill_id})"
