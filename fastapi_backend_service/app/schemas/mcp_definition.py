"""Pydantic schemas for MCPDefinition CRUD and LLM builder endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MCPDefinitionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    mcp_type: str = Field(default="custom", pattern="^(system|custom)$")
    # For custom MCPs: ID of the system MCP this wraps
    system_mcp_id: Optional[int] = Field(default=None, description="System MCP id (for custom MCPs)")
    # Legacy: kept for backward compat with existing API clients
    data_subject_id: Optional[int] = Field(default=None, description="Deprecated: use system_mcp_id")
    processing_intent: str = Field(default="", description="Natural language processing goal")
    # For system MCPs: API connection config
    api_config: Optional[Dict[str, Any]] = None
    input_schema: Optional[Dict[str, Any]] = None


class MCPDefinitionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    processing_intent: Optional[str] = None
    processing_script: Optional[str] = None
    output_schema: Optional[Dict[str, Any]] = None
    ui_render_config: Optional[Dict[str, Any]] = None
    input_definition: Optional[Dict[str, Any]] = None
    sample_output: Optional[Dict[str, Any]] = None
    visibility: Optional[str] = Field(default=None, pattern="^(private|public)$")
    api_config: Optional[Dict[str, Any]] = None
    input_schema: Optional[Dict[str, Any]] = None
    system_mcp_id: Optional[int] = None


class MCPDefinitionResponse(BaseModel):
    id: int
    name: str
    description: str
    mcp_type: str = "custom"
    data_subject_id: Optional[int] = None
    system_mcp_id: Optional[int] = None
    # Parsed dicts for system MCPs (mirrors DataSubjectResponse format)
    api_config: Optional[Dict[str, Any]] = None
    input_schema: Optional[Dict[str, Any]] = None
    processing_intent: str
    processing_script: Optional[str]
    output_schema: Optional[Dict[str, Any]]
    ui_render_config: Optional[Dict[str, Any]]
    input_definition: Optional[Dict[str, Any]]
    sample_output: Optional[Dict[str, Any]]
    visibility: str = "private"
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
    system_mcp_id: Optional[int] = Field(default=None, description="System MCP id (preferred)")
    data_subject_id: Optional[int] = Field(default=None, description="Deprecated: use system_mcp_id")
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
    # Performance metrics
    llm_elapsed_s: float = 0.0
    sandbox_elapsed_s: float = 0.0
    input_records: int = 0
    output_records: int = 0
    # Self-learning events (v14.2): schema guard retries, sandbox retries, error labels
    learning_events: List[str] = []


class MCPCheckIntentRequest(BaseModel):
    """Ask LLM to check if processing intent is clear before generation."""
    processing_intent: str = Field(..., min_length=1)
    system_mcp_id: Optional[int] = Field(default=None, description="System MCP id (preferred)")
    data_subject_id: Optional[int] = Field(default=None, description="Deprecated: use system_mcp_id")


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


class MCPRunWithFeedbackRequest(BaseModel):
    """Re-run MCP with user feedback → triggers LLM reflection + revised script + sandbox re-exec."""
    input_params: Any = Field(..., description="Form params used in the previous run (e.g. {lot_id, tool_id})")
    user_feedback: str = Field(..., min_length=1, description="User's description of what went wrong")
    previous_result_summary: Optional[str] = Field(
        default=None,
        description="Brief description of previous result (e.g. 'chart was empty, only 3 rows in dataset')"
    )
    force_regen: bool = Field(
        default=False,
        description="If True, discard current script and call full LLM re-generation (try_run) with feedback as extra context"
    )


class MCPRunWithFeedbackResponse(BaseModel):
    """Result of feedback-triggered re-run."""
    reflection: str = ""          # LLM's analysis of what went wrong
    revised_script: str = ""      # LLM's revised processing_script
    rerun_success: bool = False
    output_data: Dict[str, Any] = {}
    error: Optional[str] = None
    feedback_log_id: Optional[int] = None
