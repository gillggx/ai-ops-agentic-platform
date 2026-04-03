"""AgentMemory ORM model — long-term RAG memory for the agentic platform."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.ontology.models.base import BaseModel


class AgentMemoryModel(BaseModel):
    """A single memory entry for the Agent's long-term RAG store.

    'embedding' stores a JSON-serialized float list (SQLite-compatible).
    In production, replace with pgvector column.
    """

    __tablename__ = "agent_memories"
    __table_args__ = {"extend_existing": True}

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    data_subject: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        preview = self.content[:40] if self.content else ""
        return f"AgentMemoryModel(id={self.id}, user={self.user_id}, source={self.source!r}, content={preview!r})"


__all__ = ["AgentMemoryModel"]
