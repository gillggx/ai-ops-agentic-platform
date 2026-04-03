"""
Agent session and memory models for the Ontology layer.

Schema aligned with original dev.db:
  - agent_sessions: session_id VARCHAR(36) PRIMARY KEY (original style)
  - agent_tools:    user_id + code + usage_count (original style)
  - AgentPreference: tablename=user_preferences, adds soul_override
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AgentSession(Base):
    """Stores message history for an ongoing agent conversation.

    PK is session_id (UUID string) — compatible with original dev.db.
    Extra refactored fields (title, system_prompt, etc.) are nullable.
    """

    __tablename__ = "agent_sessions"

    # Original PK style: UUID string
    session_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, doc="UUID session identifier"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    messages: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cumulative_tokens: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=0
    )
    workspace_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Refactored extra fields — nullable for backward compat
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    is_active: Mapped[Optional[bool]] = mapped_column(nullable=True, default=True)
    context_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"AgentSession(session_id={self.session_id!r}, user_id={self.user_id})"


# AgentMemory is defined in agent_memory.py (user_id-based RAG model)
from app.ontology.models.agent_memory import AgentMemoryModel as AgentMemory  # noqa: E402


class AgentTool(Base):
    """User-created Python code tools (original dev.db style).

    Original columns: user_id, name, code, description, usage_count.
    Refactored extra fields (schema, handler_path, etc.) are nullable.
    """

    __tablename__ = "agent_tools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Refactored extra fields — nullable for backward compat
    schema: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    handler_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_available: Mapped[Optional[bool]] = mapped_column(nullable=True, default=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:
        return f"AgentTool(id={self.id}, name={self.name!r}, user_id={self.user_id})"


class AgentPreference(Base):
    """User preference / soul override — maps to original user_preferences table."""

    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True
    )
    # Original column name
    preferences: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Original soul override field
    soul_override: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Refactored extra fields — nullable for backward compat
    communication_style: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    verbosity_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    preference_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"AgentPreference(id={self.id}, user_id={self.user_id})"
