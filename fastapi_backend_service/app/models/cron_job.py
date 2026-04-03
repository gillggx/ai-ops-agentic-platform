"""CronJob — scheduled Skill execution definition."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CronJobModel(Base):
    """A Cron Job schedules a Skill to run automatically."""

    __tablename__ = "cron_jobs"

    id:           Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id:     Mapped[int]            = mapped_column(Integer, ForeignKey("skill_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule:     Mapped[str]            = mapped_column(String(100), nullable=False)   # cron expression e.g. "0 8 * * *"
    timezone:     Mapped[str]            = mapped_column(String(50), nullable=False, default="Asia/Taipei")
    label:        Mapped[str]            = mapped_column(String(200), nullable=False, default="")
    # active | paused | deleted
    status:       Mapped[str]            = mapped_column(String(20), nullable=False, default="active", index=True)
    created_by:   Mapped[Optional[str]]  = mapped_column(String(100), nullable=True)
    last_run_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:   Mapped[datetime]       = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc), server_default=func.now(),
    )
    updated_at:   Mapped[datetime]       = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc), server_default=func.now(),
        onupdate=lambda: datetime.now(tz=timezone.utc),
    )

    def __repr__(self) -> str:
        return f"CronJobModel(id={self.id}, skill_id={self.skill_id}, schedule={self.schedule!r}, status={self.status!r})"
