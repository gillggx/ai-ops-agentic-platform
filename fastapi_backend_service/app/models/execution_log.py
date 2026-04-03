"""ExecutionLog — runtime record of each Skill execution."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExecutionLogModel(Base):
    """Immutable record of one Skill run (cron / event / manual)."""

    __tablename__ = "execution_logs"

    id:                  Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id:            Mapped[int]            = mapped_column(Integer, ForeignKey("skill_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    auto_patrol_id:      Mapped[Optional[int]]  = mapped_column(Integer, ForeignKey("auto_patrols.id", ondelete="SET NULL"), nullable=True, index=True)
    script_version_id:   Mapped[Optional[int]]  = mapped_column(Integer, ForeignKey("script_versions.id", ondelete="SET NULL"), nullable=True)
    cron_job_id:         Mapped[Optional[int]]  = mapped_column(Integer, ForeignKey("cron_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    # cron | event | manual | agent | auto_patrol
    triggered_by:        Mapped[str]            = mapped_column(String(80), nullable=False, default="manual")
    event_context:       Mapped[Optional[str]]  = mapped_column(Text, nullable=True)   # JSON EventContext snapshot
    # success | error | timeout
    status:              Mapped[str]            = mapped_column(String(20), nullable=False, default="success", index=True)
    llm_readable_data:   Mapped[Optional[str]]  = mapped_column(Text, nullable=True)   # JSON diagnose() output
    action_dispatched:   Mapped[Optional[str]]  = mapped_column(String(50), nullable=True)  # action_type that was dispatched
    error_message:       Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
    started_at:          Mapped[datetime]       = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc), server_default=func.now(),
    )
    finished_at:         Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms:         Mapped[Optional[int]]  = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"ExecutionLogModel(id={self.id}, skill_id={self.skill_id}, status={self.status!r}, triggered_by={self.triggered_by!r})"
