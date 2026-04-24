"""Pydantic schemas for Block (Pipeline Builder)."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


BlockCategory = Literal["source", "transform", "logic", "output", "custom"]
BlockStatus = Literal["draft", "pi_run", "production", "deprecated"]
ImplementationType = Literal["mcp", "tool", "skill", "python"]


class PortSpec(BaseModel):
    port: str = Field(..., description="Port name, e.g. 'data' or 'triggers'")
    type: str = Field(..., description="Data type, e.g. 'dataframe', 'records', 'ack'")
    columns: Optional[list[str]] = Field(default=None, description="Expected columns if dataframe")
    description: Optional[str] = None


class BlockImplementation(BaseModel):
    type: ImplementationType
    ref: str = Field(..., description="Reference key (MCP name / tool function / skill id / python module path)")


class BlockExample(BaseModel):
    """Concrete usage example surfaced in BlockDocsDrawer + injected into Agent prompt."""
    name: str = Field(..., description="Short label shown in UI, e.g. 'SPC xbar 標準控制圖'")
    summary: str = Field(..., description="1-sentence description of what this example does")
    params: dict[str, Any] = Field(default_factory=dict, description="Pre-filled params that 'Apply' will drop onto canvas")
    upstream_hint: Optional[str] = Field(
        default=None,
        description="Optional text — which block should connect upstream, e.g. 'feed from block_process_history(object_name=SPC)'",
    )


class OutputColumnHint(BaseModel):
    """Phase 5-UX-3b: declares an actual flat column the block produces at runtime.
    Injected into Agent system prompt so the LLM doesn't have to guess column names."""
    name: str = Field(..., description="Actual flat column name, e.g. 'spc_xbar_chart_value'")
    type: str = Field(..., description="Data type: number | string | datetime | boolean | object")
    description: Optional[str] = Field(default=None, description="Short human hint for this column")
    when_present: Optional[str] = Field(
        default=None,
        description="Condition for presence, e.g. 'when object_name=SPC + chart_type=xbar_chart'",
    )


class BlockCreate(BaseModel):
    name: str
    category: BlockCategory
    version: str = "1.0.0"
    status: BlockStatus = "draft"
    description: str = ""
    input_schema: list[PortSpec] = Field(default_factory=list)
    output_schema: list[PortSpec] = Field(default_factory=list)
    param_schema: dict[str, Any] = Field(default_factory=dict)
    implementation: BlockImplementation
    is_custom: bool = False
    output_columns_hint: list[OutputColumnHint] = Field(default_factory=list)


class BlockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: BlockCategory
    version: str
    status: BlockStatus
    description: str
    input_schema: list[PortSpec]
    output_schema: list[PortSpec]
    param_schema: dict[str, Any]
    implementation: BlockImplementation
    is_custom: bool
    examples: list[BlockExample] = Field(default_factory=list)
    output_columns_hint: list[OutputColumnHint] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
