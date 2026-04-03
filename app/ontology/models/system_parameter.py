"""
SystemParameter model for the Ontology layer.

Define the SystemParameter entity for storing system-wide configuration.
定義 SystemParameter 實體，用於存儲系統級配置。
"""

from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class SystemParameter(BaseModel):
    """
    System-wide configuration parameter.

    Stores configuration values that are globally applicable across
    the system (e.g., default timeouts, feature flags, LLM settings).

    存儲系統級配置值，例如默認超時、功能開關、LLM 設置等。

    Attributes:
        key: str - Unique parameter key (唯一參數鍵)
        value: str - Parameter value as string (參數值)
        description: str - Parameter description (參數描述)
        category: str - Parameter category (參數分類)
        is_secret: bool - Whether value is sensitive (值是否敏感)

    Well-known keys (use these constants to avoid typos):
        KEY_AGENT_SOUL      — The agent's core identity prompt (replaces hardcoded soul).
                              Loaded by ContextLoader at the start of every conversation.
        KEY_DEFAULT_LLM     — Default LLM model identifier (overrides .env at runtime).
        KEY_MAX_TOOL_LOOPS  — Safety cap on tool-call iterations per agent turn.
        KEY_MCP_TIMEOUT     — Default MCP execution timeout in seconds.

    Example:
        >>> param = SystemParameter(
        ...     key=SystemParameter.KEY_AGENT_SOUL,
        ...     value="# AI Ops Agent\\nYou are...",
        ...     description="Agent core identity prompt",
        ...     category="agent"
        ... )
    """

    # ── Well-known parameter key constants ────────────────────────────────────
    # Agent soul / identity
    KEY_AGENT_SOUL: str = "AGENT_SOUL_PROMPT"
    KEY_DEFAULT_LLM: str = "DEFAULT_LLM_MODEL"
    KEY_MAX_TOOL_LOOPS: str = "MAX_TOOL_LOOPS"
    KEY_MCP_TIMEOUT: str = "MCP_EXECUTION_TIMEOUT"

    # MCPBuilderService prompt overrides (see mcp_builder_service._DEFAULT_*)
    # When present, these replace the hardcoded Chinese prompts — editable without deploy.
    KEY_PROMPT_MCP_GENERATE: str = "PROMPT_MCP_GENERATE"      # MCP script generation
    KEY_PROMPT_MCP_TRY_RUN: str = "PROMPT_MCP_TRY_RUN"        # MCP try-run guardrails
    KEY_PROMPT_SKILL_DIAGNOSIS: str = "PROMPT_SKILL_DIAGNOSIS" # LLM-based diagnosis judge
    KEY_PROMPT_SKILL_DIAG_CODE: str = "PROMPT_SKILL_DIAG_CODE" # Python diagnose() generator

    __tablename__ = "system_parameters"

    key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique parameter key (e.g., DEFAULT_EVENT_TIMEOUT)"
    )

    value: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Parameter value (as string)"
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Description of what this parameter controls"
    )

    category: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        doc="Parameter category (e.g., timing, feature, llm)"
    )

    is_secret: Mapped[Optional[bool]] = mapped_column(
        default=False,
        nullable=True,
        doc="Whether value should be treated as secret (not logged)"
    )

    def __repr__(self) -> str:
        """Return detailed representation."""
        safe_value = "***" if self.is_secret else self.value[:50]
        return (
            f"SystemParameter(id={self.id}, key={self.key!r}, "
            f"value={safe_value!r}, category={self.category!r})"
        )

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"{self.key}={self.value if not self.is_secret else '***'}"
