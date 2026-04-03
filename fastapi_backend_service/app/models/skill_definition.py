"""SkillDefinitionModel v2.0 — Diagnostic-First Skill Architecture."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SkillDefinitionModel(Base):
    """A Skill defines monitoring/diagnostic logic as Python steps.

    v2.0 redesign:
    - Skill is a pure diagnostic function: returns SkillFindings, no alarms
    - output_schema declares what fields the Skill returns in evidence
    - trigger_alarm() removed; alarm decisions delegated to Auto-Patrol
    - trigger_event_id links to the System Event Catalog (event_types table)
    """

    __tablename__ = "skill_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # System Event that triggers this Skill (NULL = schedule-only)
    trigger_event_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("event_types.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # "schedule" | "event" | "both"
    trigger_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="both", server_default="both"
    )

    # JSON: [{step_id, nl_segment, python_code}]
    steps_mapping: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # JSON: [{key, type, label, unit?, columns?, description?}]
    # Declares what parameters this Skill needs as input
    input_schema: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="[]")

    # JSON: [{key, type, label, unit?, columns?, description?}]
    # Declares what fields this Skill returns in _findings.outputs (render spec)
    output_schema: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="[]")

    # "legacy" | "rule" | "auto_patrol"
    # legacy   = old skill records (hidden from new UIs)
    # rule     = Diagnostic Rule (visible in /admin/skills)
    # auto_patrol = embedded skill owned by an Auto-Patrol (hidden)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="legacy", server_default="legacy"
    )

    # For source="rule": what this rule automatically checks (used as LLM prompt)
    auto_check_description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )

    # "private" | "public"
    visibility: Mapped[str] = mapped_column(
        String(10), nullable=False, default="private", server_default="private"
    )

    # Alarm-triggered DR: which Auto-Patrol's alarm triggers this Diagnostic Rule
    trigger_patrol_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("auto_patrols.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Who created this skill
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )

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
        return f"SkillDefinitionModel(id={self.id!r}, name={self.name!r})"
