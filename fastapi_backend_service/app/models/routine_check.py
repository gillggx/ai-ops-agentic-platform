"""RoutineCheck ORM model — scheduled proactive inspection job (Phase 11)."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from app.database import Base


class RoutineCheckModel(Base):
    """A periodic inspection job: bridge between Skill and EventType.

    skill_id       → which Skill to run
    skill_input    → mandatory JSON params fed into the Skill (mapped to DB column 'preset_parameters')
    trigger_event_id → which EventType to create when Skill returns ABNORMAL
    """

    __tablename__ = "routine_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    skill_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skill_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # JSON: {"lot_id": "...", "tool_id": "...", ...} — mandatory Skill execution parameters
    # NOTE: mapped to legacy DB column 'preset_parameters' for backward compatibility
    skill_input: Mapped[str] = mapped_column("preset_parameters", Text, nullable=False, default="{}")
    # EventType to fire via LLM mapping when Skill returns ABNORMAL
    trigger_event_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("event_types.id", ondelete="SET NULL"), nullable=True, default=None
    )
    # JSON: [{"event_field": "lot_id", "mcp_field": "lot_id"}] — pre-configured event param mappings
    # If set, scheduler uses these directly; otherwise falls back to runtime LLM mapping
    event_param_mappings: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    # Enum: "30m" | "1h" | "4h" | "8h" | "12h" | "daily"
    schedule_interval: Mapped[str] = mapped_column(String(20), nullable=False, default="1h")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # ISO timestamp of the last successful run
    last_run_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    # "NORMAL" | "ABNORMAL" | "ERROR" | None (never ran)
    last_run_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default=None)
    # ISO date string (YYYY-MM-DD) after which this check is automatically deactivated
    expire_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    # "HH:MM" — only used when schedule_interval == "daily" to specify execution time
    schedule_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True, default=None)
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
        return f"RoutineCheckModel(id={self.id!r}, name={self.name!r}, interval={self.schedule_interval!r})"
