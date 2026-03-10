"""Pydantic schemas for SkillDefinition CRUD."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ParamMapping(BaseModel):
    event_field: str
    mcp_id: int
    mcp_param: str
    confidence: str = Field(default="HIGH", description="HIGH|MEDIUM|LOW")
    reasoning: str = Field(default="")


class SkillDefinitionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    problem_subject: Optional[str] = Field(default=None, max_length=300,
        description="有問題的項目或物件（e.g. TETCH01 蝕刻機台、SPC OOC 批次）")
    event_type_id: Optional[int] = None
    mcp_id: Optional[int] = None
    param_mappings: Optional[List[ParamMapping]] = None
    diagnostic_prompt: Optional[str] = None
    human_recommendation: Optional[str] = None
    last_diagnosis_result: Optional[Dict[str, Any]] = None


class SkillDefinitionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    problem_subject: Optional[str] = Field(default=None, max_length=300)
    mcp_id: Optional[int] = None
    param_mappings: Optional[List[ParamMapping]] = None
    diagnostic_prompt: Optional[str] = None
    human_recommendation: Optional[str] = None
    last_diagnosis_result: Optional[Dict[str, Any]] = None
    visibility: Optional[str] = Field(default=None, pattern="^(private|public)$")


class SkillDefinitionResponse(BaseModel):
    id: int
    name: str
    description: str
    problem_subject: Optional[str] = None
    event_type_id: Optional[int] = None
    mcp_id: Optional[int] = None
    mcp_ids: str = "[]"          # JSON text: "[1, 2, 3]"
    param_mappings: Optional[List[Dict[str, Any]]] = None
    diagnostic_prompt: Optional[str] = None
    human_recommendation: Optional[str] = None
    last_diagnosis_result: Optional[Dict[str, Any]] = None
    visibility: str = "private"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Skill Try Diagnosis request/response ──────────────────────────────────────

class SkillTryDiagnosisRequest(BaseModel):
    """Simulate diagnosis: send MCP sample_outputs + diagnostic_prompt to LLM."""
    diagnostic_prompt: str = Field(..., min_length=1)
    mcp_sample_outputs: Dict[str, Any] = Field(
        ..., description="Combined MCP sample outputs keyed by mcp_name"
    )


class SkillTryDiagnosisResponse(BaseModel):
    """Result of a simulated Skill diagnosis."""
    success: bool
    status: str = ""       # NORMAL | ABNORMAL
    conclusion: str = ""
    evidence: List[str] = []
    summary: str = ""
    error: Optional[str] = None


# ── Skill Auto-Map request/response ───────────────────────────────────────────

class SkillAutoMapRequest(BaseModel):
    """Ask LLM to semantically map DataSubject input fields to Event attributes."""
    mcp_id: int = Field(..., description="MCP whose DataSubject input_schema to use")
    event_type_id: int = Field(..., description="Event Type whose attributes to map from")


# ── Skill Check Diagnosis Intent request/response ─────────────────────────────

class SkillCheckDiagnosisIntentRequest(BaseModel):
    """Check if the diagnostic prompt is clear enough for LLM diagnosis."""
    diagnostic_prompt: str = Field(..., min_length=1)
    mcp_output_sample: Dict[str, Any] = Field(
        default_factory=dict, description="MCP sample output data for context"
    )


class SkillCheckDiagnosisIntentResponse(BaseModel):
    """Result of checking the diagnostic prompt clarity."""
    is_clear: bool
    questions: List[str] = []
    suggested_prompt: str = ""


# ── Skill Check Code Diagnosis Intent request/response ────────────────────────

class SkillCheckCodeDiagnosisIntentRequest(BaseModel):
    """Check if the diagnostic prompt + problem_subject are ready for code generation."""
    diagnostic_prompt: str = Field(..., min_length=1)
    problem_subject: Optional[str] = None
    mcp_output_sample: Dict[str, Any] = Field(default_factory=dict)
    event_attributes: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="EventType attributes that trigger this Skill (with name/type/description)",
    )


class SkillCheckCodeDiagnosisIntentResponse(BaseModel):
    """Result of checking the code-diagnosis configuration."""
    is_clear: bool
    questions: List[str] = []
    suggested_prompt: str = ""
    suggested_problem_subject: str = ""
    changes: str = ""


# ── Skill Generate Code Diagnosis request/response ────────────────────────────

class SkillGenerateCodeDiagnosisRequest(BaseModel):
    """LLM generates Python diagnostic code that returns diagnosis_message + problem_object."""
    diagnostic_prompt: str = Field(..., min_length=1)
    problem_subject: Optional[str] = None
    mcp_sample_outputs: Dict[str, Any] = Field(
        ..., description="MCP sample outputs keyed by mcp_name"
    )
    event_attributes: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="EventType attributes for code-generation context",
    )


class SkillGenerateCodeDiagnosisResponse(BaseModel):
    """Result of code-based Skill diagnosis generation."""
    success: bool
    generated_code: str = ""
    status: str = ""                   # "NORMAL" | "ABNORMAL"
    diagnosis_message: str = ""
    problem_object: Any = None
    check_output_schema: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    # Performance metrics
    llm_elapsed_s: float = 0.0
    exec_elapsed_s: float = 0.0
    input_records: int = 0
