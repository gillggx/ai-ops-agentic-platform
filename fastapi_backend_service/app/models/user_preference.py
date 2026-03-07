"""UserPreference ORM model — per-user AI agent preferences."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserPreferenceModel(Base):
    """Stores a user's personal preferences for the AI Agent.

    'preferences' is free-text, LLM-sanitized before write.
    'soul_override' is Admin-only, overrides the global Soul prompt for this user.
    """

    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    # Free-text preferences (e.g. "回答用繁體中文", "報告結尾附上資料表格")
    preferences: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Admin-only: overrides global Soul for this user
    soul_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc),
        onupdate=lambda: datetime.now(tz=timezone.utc),
        server_default=func.now(),
    )
