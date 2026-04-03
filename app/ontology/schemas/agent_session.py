"""
Agent session-related Pydantic schemas.

Agent Session/Memory/Tool/Preference 相關的驗證模型。
"""

from typing import Optional

from pydantic import Field

from .common import IdSchema


# ==================== AgentSession Schemas ====================

class AgentSessionCreate(IdSchema):
    """Schema for creating an agent session."""

    user_id: int = Field(
        ...,
        description="User ID"
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Session title"
    )
    system_prompt: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="System prompt for this session"
    )
    context_summary: Optional[str] = Field(
        default=None,
        max_length=10000,
        description="Initial context summary"
    )


class AgentSessionUpdate(IdSchema):
    """Schema for updating an agent session."""

    title: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New title"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=10000,
        description="New system prompt"
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Active status"
    )
    context_summary: Optional[str] = Field(
        default=None,
        max_length=10000,
        description="Updated context"
    )


class AgentSessionRead(IdSchema):
    """Schema for reading an agent session."""

    id: int
    user_id: int
    title: str
    system_prompt: str
    message_count: int = Field(default=0)
    is_active: bool = Field(default=True)
    context_summary: Optional[str] = None

    class Config:
        from_attributes = True


# ==================== AgentMemory Schemas ====================

class AgentMemoryCreate(IdSchema):
    """Schema for creating an agent memory."""

    session_id: int = Field(
        ...,
        description="Session ID"
    )
    memory_type: str = Field(
        ...,
        description="Memory type (fact, insight, context, learned_pattern)"
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Memory content"
    )
    embedding_key: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Embedding key for semantic search"
    )


class AgentMemoryUpdate(IdSchema):
    """Schema for updating an agent memory."""

    content: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=10000,
        description="New content"
    )
    memory_type: Optional[str] = Field(
        default=None,
        description="New memory type"
    )
    is_indexed: Optional[bool] = Field(
        default=None,
        description="Index status"
    )


class AgentMemoryRead(IdSchema):
    """Schema for reading an agent memory."""

    id: int
    session_id: int
    memory_type: str
    content: str
    embedding_key: Optional[str] = None
    is_indexed: bool = Field(default=False)

    class Config:
        from_attributes = True


# ==================== AgentTool Schemas ====================

class AgentToolCreate(IdSchema):
    """Schema for creating an agent tool."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Tool name"
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Tool description"
    )
    schema: dict = Field(
        ...,
        description="Tool parameter schema (JSON)"
    )
    handler_path: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Handler function path (e.g., app.services.sandbox.execute)"
    )
    category: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Tool category (execution, analysis, data)"
    )
    is_available: bool = Field(
        default=True,
        description="Whether tool is available"
    )


class AgentToolUpdate(IdSchema):
    """Schema for updating an agent tool."""

    description: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=10000,
        description="New description"
    )
    schema: Optional[dict] = Field(
        default=None,
        description="New schema"
    )
    handler_path: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New handler path"
    )
    is_available: Optional[bool] = Field(
        default=None,
        description="Availability status"
    )


class AgentToolRead(IdSchema):
    """Schema for reading an agent tool."""

    id: int
    name: str
    description: str
    schema: dict
    handler_path: str
    category: str
    is_available: bool = Field(default=True)

    class Config:
        from_attributes = True


# ==================== AgentPreference Schemas ====================

class AgentPreferenceCreate(IdSchema):
    """Schema for creating an agent preference."""

    user_id: int = Field(
        ...,
        description="User ID"
    )
    communication_style: str = Field(
        default="balanced",
        description="Communication style (direct, formal, casual, balanced)"
    )
    verbosity_level: str = Field(
        default="normal",
        description="Verbosity level (terse, normal, verbose, expert)"
    )
    preference_data: Optional[dict] = Field(
        default=None,
        description="Additional preferences (JSON)"
    )


class AgentPreferenceUpdate(IdSchema):
    """Schema for updating an agent preference."""

    communication_style: Optional[str] = Field(
        default=None,
        description="New communication style"
    )
    verbosity_level: Optional[str] = Field(
        default=None,
        description="New verbosity level"
    )
    preference_data: Optional[dict] = Field(
        default=None,
        description="New preferences"
    )


class AgentPreferenceRead(IdSchema):
    """Schema for reading an agent preference."""

    id: int
    user_id: int
    communication_style: str = Field(default="balanced")
    verbosity_level: str = Field(default="normal")
    preference_data: dict = Field(default_factory=dict)

    class Config:
        from_attributes = True
