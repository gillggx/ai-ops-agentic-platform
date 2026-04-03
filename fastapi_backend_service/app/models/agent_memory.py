"""AgentMemory ORM model — long-term RAG memory for the agentic platform."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentMemoryModel(Base):
    """A single memory entry for the Agent's long-term RAG store.

    'embedding' stores a JSON-serialized float list (SQLite-compatible).
    In production, replace with pgvector column.
    """

    __tablename__ = "agent_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON float array — dev: stored as text; prod: replace with pgvector
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'diagnosis' | 'agent_request' | 'manual'
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Optional: links back to a skill/mcp id
    ref_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # v14.1: Metadata Indexing for pre-filtered search
    task_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    data_subject: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
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

    def __repr__(self) -> str:
        preview = self.content[:40] if self.content else ""
        return f"AgentMemoryModel(id={self.id}, user={self.user_id}, source={self.source!r}, content={preview!r})"
