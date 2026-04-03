"""
MCP (Measurement Collection Pipeline) models for the Ontology layer.

Define MCP and MCPDefinition entities.
定義 MCP 和 MCPDefinition 實體。
"""

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class MCPDefinition(BaseModel):
    """
    MCP (Measurement Collection Pipeline) definition.
    
    Represents a data processing pipeline configuration.
    代表一個數據處理流水線配置。
    
    Attributes:
        name: str - Unique MCP name (唯一 MCP 名稱)
        description: str - MCP description (MCP 描述)
        data_source_type: str - Type of data source (數據源類型)
        processing_intent: str - Intended processing logic (處理意圖)
        processing_script: str - Python script for processing (處理腳本)
        output_schema: str - Expected output schema (輸出 schema)
        ui_render_config: str - UI rendering configuration (UI 渲染配置)
    """

    __tablename__ = "mcp_definitions"

    name: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique MCP name"
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Description of this MCP pipeline"
    )

    data_source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Type of data source (e.g., API, Database, Sensor)"
    )

    processing_intent: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="User-written description of intended processing"
    )

    processing_script: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="LLM-generated or user-written Python processing script"
    )

    output_schema: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Expected output schema as JSON"
    )

    ui_render_config: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Plotly or UI rendering configuration"
    )

    sample_output: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Sample output from last execution"
    )

    # ── Ontology knowledge fields ─────────────────────────────────────────────
    # data_subject_id: which DataSubject this MCP operates on.
    data_subject_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("data_subjects.id", ondelete="SET NULL"), nullable=True,
        doc="DataSubject this MCP collects/processes data for"
    )
    visibility: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default="private")
    #
    # mcp_type: execution semantics differ:
    #   "system" — platform-built-in MCP. Fixed behavior implemented in Python code.
    #              Cannot be edited. Guaranteed available. The agent can always call these.
    #   "custom" — user-defined MCP. Behavior is in `processing_script` (sandboxed Python).
    #              May be private or shared. Identified by the user who created it.
    mcp_type: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True, default="custom",
        doc="'system' = platform built-in (fixed); 'custom' = user-defined script"
    )
    # api_config: JSON config for the data source this MCP calls.
    #   Overrides the parent DataSubject's api_config for this specific MCP.
    api_config: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        doc="JSON: data source config, overrides DataSubject.api_config for this MCP"
    )
    # input_schema: JSON Schema for the parameters callers must pass to this MCP.
    input_schema: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        doc="JSON Schema: parameters required when invoking this MCP"
    )
    # input_definition: human-readable parameter descriptions (shown in builder UI).
    input_definition: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        doc="Human-readable parameter definitions for builder UI"
    )
    # system_mcp_id: for custom MCPs, the platform system MCP this was derived from.
    #   Allows the platform to offer "upgrade" prompts when the base system MCP changes.
    system_mcp_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        doc="For custom MCPs: ID of the system MCP template this was derived from"
    )

    @property
    def is_system(self) -> bool:
        """True if this is a platform-built-in MCP (cannot be scripted or deleted)."""
        return self.mcp_type == "system"

    # Relationships
    mcps: Mapped[list["MCP"]] = relationship(
        "MCP",
        back_populates="mcp_definition",
        cascade="all, delete-orphan",
        doc="Individual MCP instances"
    )

    def __repr__(self) -> str:
        return f"MCPDefinition(id={self.id}, name={self.name!r})"

    def __str__(self) -> str:
        return self.name


class MCP(BaseModel):
    """
    Individual MCP (Measurement Collection Pipeline) instance.
    
    Represents a specific instantiation of an MCP definition.
    代表 MCP 定義的具體實例化。
    
    Attributes:
        mcp_definition_id: int - FK to MCPDefinition (MCP 定義外鍵)
        name: str - Instance name (實例名稱)
        config: str - Instance configuration (實例配置)
        is_active: bool - Whether this MCP instance is active (是否活躍)
        last_execution_at: datetime - When last executed (最後執行時間)
        last_status: str - Status of last execution (最後執行狀態)
    """

    __tablename__ = "mcps"

    mcp_definition_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to MCPDefinition"
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
        doc="Instance name"
    )

    config: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
        doc="Instance-specific configuration as JSON"
    )

    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        index=True,
        doc="Whether this MCP instance is active"
    )

    last_execution_at: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
        doc="ISO timestamp of last execution"
    )

    last_status: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        doc="Status of last execution (success, failed, running)"
    )

    # Relationships
    mcp_definition: Mapped[MCPDefinition] = relationship(
        "MCPDefinition",
        back_populates="mcps",
        doc="Reference to MCPDefinition"
    )

    def __repr__(self) -> str:
        return (
            f"MCP(id={self.id}, name={self.name!r}, "
            f"is_active={self.is_active})"
        )

    def __str__(self) -> str:
        return self.name
