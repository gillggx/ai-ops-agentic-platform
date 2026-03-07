"""AgentSession ORM model — short-term conversation cache (24h TTL)."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentSessionModel(Base):
    """Stores the message history for an ongoing agent conversation.

    Expires after 24 hours (enforced in service layer, not DB).
    'messages' is a JSON-serialized list of {role, content} dicts.
    """

    __tablename__ = "agent_sessions"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # JSON: [{role: "user"|"assistant", content: "..."}]
    messages: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc), server_default=func.now(),
    )
    # 24h TTL — service layer checks this and auto-clears
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
