"""
MCP (Measurement Collection Pipeline) Pydantic schemas.

MCP 相關的驗證模型。
"""

from typing import Optional

from pydantic import Field

from .common import IdSchema


class MCPDefinitionCreate(IdSchema):
    """
    Schema for creating an MCP definition.
    
    創建 MCP 定義的驗證模型。
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Unique MCP name"
    )
    description: str = Field(
        ...,
        min_length=1,
        description="MCP description"
    )
    data_source_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Type of data source (API, Database, Sensor, etc.)"
    )
    processing_intent: str = Field(
        ...,
        min_length=1,
        description="Intended processing logic"
    )
    processing_script: Optional[str] = Field(
        default=None,
        description="Python processing script"
    )
    output_schema: Optional[str] = Field(
        default=None,
        description="Expected output schema (JSON)"
    )
    ui_render_config: Optional[str] = Field(
        default=None,
        description="UI rendering configuration (Plotly)"
    )


class MCPDefinitionRead(IdSchema):
    """
    Schema for reading MCP definition data.
    
    讀取 MCP 定義數據的驗證模型。
    """

    id: int = Field(
        ...,
        description="MCP definition ID"
    )
    name: str = Field(
        ...,
        description="MCP name"
    )
    description: Optional[str] = Field(
        default=None,
        description="MCP description"
    )
    data_source_type: Optional[str] = Field(
        default=None,
        description="Data source type"
    )
    processing_intent: Optional[str] = Field(
        default=None,
        description="Processing intent"
    )
    processing_script: Optional[str] = Field(
        default=None,
        description="Processing script"
    )
    output_schema: Optional[str] = Field(
        default=None,
        description="Output schema"
    )
    ui_render_config: Optional[str] = Field(
        default=None,
        description="UI rendering config"
    )

    class Config:
        """Pydantic config."""

        from_attributes = True


class MCPCreate(IdSchema):
    """
    Schema for creating an MCP instance.
    
    創建 MCP 實例的驗證模型。
    """

    mcp_definition_id: int = Field(
        ...,
        description="Reference to MCPDefinition"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Instance name"
    )
    config: str = Field(
        default="{}",
        description="Instance configuration (JSON)"
    )
    is_active: bool = Field(
        default=True,
        description="Whether this MCP instance is active"
    )


class MCPRead(IdSchema):
    """
    Schema for reading MCP instance data.
    
    讀取 MCP 實例數據的驗證模型。
    """

    id: int = Field(
        ...,
        description="MCP instance ID"
    )
    mcp_definition_id: int = Field(
        ...,
        description="Reference to MCPDefinition"
    )
    name: str = Field(
        ...,
        description="Instance name"
    )
    config: str = Field(
        ...,
        description="Instance configuration"
    )
    is_active: bool = Field(
        ...,
        description="Whether instance is active"
    )
    last_execution_at: Optional[str] = Field(
        default=None,
        description="Last execution timestamp (ISO format)"
    )
    last_status: Optional[str] = Field(
        default=None,
        description="Last execution status (success/failed/running)"
    )

    class Config:
        """Pydantic config."""

        from_attributes = True
