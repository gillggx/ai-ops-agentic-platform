"""AutoPatrolModel — event/schedule-driven skill execution with alarm decisions."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AutoPatrolModel(Base):
    """Auto-Patrol: ties a Skill to a trigger (event or schedule) and alarm config.

    Execution flow:
      trigger fires → run Skill → read findings.condition_met
      → if True: create Alarm + notify according to alarm_severity / notify_config
    """

    __tablename__ = "auto_patrols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    skill_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skill_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # "event" | "schedule"
    trigger_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="schedule", server_default="schedule"
    )

    # For trigger_mode="event"
    event_type_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("event_types.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # For trigger_mode="schedule" (cron expression)
    cron_expr: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Natural language description of what this patrol automatically checks
    auto_check_description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )

    # For trigger_mode="schedule": how to build input context
    # e.g. "recent_ooc" | "active_lots" | "tool_status"
    data_context: Mapped[str] = mapped_column(
        String(100), nullable=False, default="recent_ooc", server_default="recent_ooc"
    )

    # JSON: {type: "all_equipment"|"equipment_list"|"event_driven", equipment_ids: [...]}
    target_scope: Mapped[str] = mapped_column(
        Text, nullable=False, default='{"type":"event_driven"}',
        server_default='{"type":"event_driven"}'
    )

    # Alarm config (applied when condition_met == True)
    alarm_severity: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    alarm_title: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    # JSON: {channels: ["email","slack"], users: [...]}
    notify_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )

    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
        return f"AutoPatrolModel(id={self.id!r}, name={self.name!r})"
