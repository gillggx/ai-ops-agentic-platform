"""AgentDraft ORM model — MCP/Skill builder intermediate state."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.ontology.models.base import Base


class AgentDraft(Base):
    """Stores in-progress MCP or Skill drafts from the builder UI."""

    __tablename__ = "agent_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    draft_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'mcp' | 'skill'
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"AgentDraft(id={self.id!r}, type={self.draft_type!r}, user_id={self.user_id})"
