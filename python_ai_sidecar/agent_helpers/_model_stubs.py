"""Stub SQLAlchemy entity classes referenced by the ported agent code.

The ported orchestrator/builder use these classes mostly for **type
annotations** (`session: AgentSessionModel`) — they don't actually run
``SELECT`` against them. By exposing empty Python classes here we keep
the imports green; if any code actually tries to call an instance method
that depends on real DB columns, it'll fail at runtime and we'll know to
rewire it through ``JavaAPIClient``.

Each stub mirrors the column attribute names the orchestrator reads, so
isinstance / hasattr checks still work at the shape level.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


class _BaseStub:
    """Common helpers — accept arbitrary kwargs without exploding."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"


class AgentSessionModel(_BaseStub):
    """Mirrors ``app.models.agent_session.AgentSessionModel``."""
    id: Optional[int] = None
    user_id: Optional[int] = None
    title: Optional[str] = None
    state: Optional[str] = None
    last_pipeline_json: Optional[str] = None
    last_pipeline_run_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MCPDefinitionModel(_BaseStub):
    id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    api_config: Optional[str] = None
    input_schema: Optional[str] = None
    output_schema: Optional[str] = None
    mcp_type: Optional[str] = None
    visibility: Optional[str] = None


class SkillDefinitionModel(_BaseStub):
    id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    pipeline_id: Optional[int] = None
    visibility: Optional[str] = None


class SystemParameterModel(_BaseStub):
    id: Optional[int] = None
    name: Optional[str] = None
    value: Optional[str] = None
    description: Optional[str] = None


class UserPreferenceModel(_BaseStub):
    id: Optional[int] = None
    user_id: Optional[int] = None
    key: Optional[str] = None
    value: Optional[str] = None


class AgentMemoryModel(_BaseStub):
    id: Optional[int] = None
    user_id: Optional[int] = None
    content: Optional[str] = None
    embedding: Optional[str] = None
    source: Optional[str] = None
    ref_id: Optional[str] = None
    task_type: Optional[str] = None
    data_subject: Optional[str] = None
    tool_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
