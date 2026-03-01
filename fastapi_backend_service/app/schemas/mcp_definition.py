"""Pydantic schemas for MCPDefinition CRUD and LLM builder endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MCPDefinitionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    data_subject_id: int = Field(..., description="ID of the DataSubject to process")
    processing_intent: str = Field(..., min_length=1, description="Natural language processing goal")


class MCPDefinitionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    processing_intent: Optional[str] = None
    processing_script: Optional[str] = None
    output_schema: Optional[Dict[str, Any]] = None
    ui_render_config: Optional[Dict[str, Any]] = None
    input_definition: Optional[Dict[str, Any]] = None
    sample_output: Optional[Dict[str, Any]] = None


class MCPDefinitionResponse(BaseModel):
    id: int
    name: str
    description: str
    data_subject_id: int
    processing_intent: str
    processing_script: Optional[str]
    output_schema: Optional[Dict[str, Any]]
    ui_render_config: Optional[Dict[str, Any]]
    input_definition: Optional[Dict[str, Any]]
    sample_output: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── LLM builder request/response schemas ───────────────────────

class MCPGenerateRequest(BaseModel):
    """Ask LLM to generate all 4 artefacts for an MCP."""
    mcp_id: int = Field(..., description="Existing MCPDefinition ID to enrich")


class MCPGenerateResponse(BaseModel):
    mcp_id: int
    processing_script: str
    output_schema: Dict[str, Any]
    ui_render_config: Dict[str, Any]
    input_definition: Dict[str, Any]
    summary: str


class MCPTryRunRequest(BaseModel):
    """Try-run: LLM generates script from intent, executes it in sandbox with sample_data."""
    processing_intent: str = Field(..., min_length=1)
    data_subject_id: int
    sample_data: Any = Field(..., description="Real data from the DataSubject API (dict or list)")


class MCPTryRunResponse(BaseModel):
    """Result of a try-run execution."""
    success: bool
    script: str = ""
    output_data: Dict[str, Any] = {}
    ui_render_config: Dict[str, Any] = {}
    output_schema: Dict[str, Any] = {}
    input_definition: Dict[str, Any] = {}
    summary: str = ""
    error: Optional[str] = None
    error_analysis: Optional[str] = None   # LLM explanation when success=False
    error_type: Optional[str] = None        # "User_Prompt_Issue" | "System_Issue"
    suggested_prompt: Optional[str] = None  # LLM-suggested improved prompt


class MCPCheckIntentRequest(BaseModel):
    """Ask LLM to check if processing intent is clear before generation."""
    processing_intent: str = Field(..., min_length=1)
    data_subject_id: int


class MCPCheckIntentResponse(BaseModel):
    """Result of the intent clarity check."""
    is_clear: bool
    questions: List[str] = []
    suggested_prompt: str = ""


class MCPRunWithDataRequest(BaseModel):
    """Execute an MCP's stored processing_script with provided raw data (no LLM generation).

    Used by Skill Builder's '▶️ 執行載入 MCP 數據' button to run the existing script
    against test data fetched from the DataSubject API.
    """
    raw_data: Any = Field(..., description="Raw data from DataSubject API (dict or list)")
