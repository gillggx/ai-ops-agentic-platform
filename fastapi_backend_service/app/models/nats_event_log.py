"""NatsEventLogModel — records every NATS OOC event received by the subscriber."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_MAX_LOG_ROWS = 500  # keep only the most recent N rows per event_type_name


class NatsEventLogModel(Base):
    __tablename__ = "nats_event_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    equipment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lot_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)  # full JSON
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
