"""AlarmModel — alarm created by a Skill when it detects an ABNORMAL condition."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AlarmModel(Base):
    """An alarm created by a Skill execution when trigger_alarm() is called.

    Replaces GeneratedEventModel. Separates 'system events' (from OntologySimulator)
    from 'alarms' (human-actionable notifications with lifecycle).
    """

    __tablename__ = "alarms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Which Skill triggered this alarm
    skill_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skill_definitions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Which system event type triggered the skill (denormalised for fast query)
    trigger_event: Mapped[str] = mapped_column(String(100), nullable=False, default="", index=True)

    # Ontology context — all 5 fields needed to trace any object via MCP
    equipment_id: Mapped[str] = mapped_column(String(100), nullable=False, default="", index=True)
    lot_id: Mapped[str] = mapped_column(String(100), nullable=False, default="", index=True)
    step: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    event_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Alarm content (set by trigger_alarm() call inside Skill Python code)
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="MEDIUM"
    )  # LOW / MEDIUM / HIGH / CRITICAL
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )  # active / acknowledged / resolved
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Execution log of the Auto-Patrol run that created this alarm
    execution_log_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("execution_logs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Execution log of the Diagnostic Rule triggered by this alarm (deep investigation)
    diagnostic_log_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("execution_logs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc), server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"AlarmModel(id={self.id!r}, severity={self.severity!r}, "
            f"title={self.title!r}, status={self.status!r})"
        )
