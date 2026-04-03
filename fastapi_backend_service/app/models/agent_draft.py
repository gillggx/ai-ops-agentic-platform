"""AgentDraft ORM model — staging area for agent-created drafts awaiting human review."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentDraftModel(Base):
    """An Agent Draft holds parameters proposed by the AI agent.

    Lifecycle: pending → (human reviews) → published
    On publish the payload is written to the real registry table.
    """

    __tablename__ = "agent_drafts"

    # UUID string as PK (client-friendly)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # mcp | skill | schedule | event
    draft_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # JSON payload — fields depend on draft_type
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # Owner user ID
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # pending | published
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(tz=timezone.utc), server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"AgentDraftModel(id={self.id!r}, draft_type={self.draft_type!r}, status={self.status!r})"
