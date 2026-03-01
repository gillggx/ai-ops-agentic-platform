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
    event_type_id: int
    mcp_id: Optional[int] = None
    param_mappings: Optional[List[ParamMapping]] = None
    diagnostic_prompt: Optional[str] = None
    human_recommendation: Optional[str] = None


class SkillDefinitionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    mcp_id: Optional[int] = None
    param_mappings: Optional[List[ParamMapping]] = None
    diagnostic_prompt: Optional[str] = None
    human_recommendation: Optional[str] = None


class SkillDefinitionResponse(BaseModel):
    id: int
    name: str
    description: str
    event_type_id: int
    mcp_id: Optional[int]
    param_mappings: Optional[List[Dict[str, Any]]]
    diagnostic_prompt: Optional[str]
    human_recommendation: Optional[str]
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
