"""Pydantic schemas for EventType CRUD."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, computed_field


class EventAttribute(BaseModel):
    name: str = Field(..., description="Attribute name, e.g. lot_id")
    type: str = Field(default="string", description="string|number|boolean")
    description: str = Field(..., min_length=1, description="MANDATORY: semantic description for LLM mapping")
    required: bool = Field(default=True)


class ParamMapping(BaseModel):
    """Mapping from an EventType attribute → one MCP input parameter."""
    event_field: str
    mcp_id: int
    mcp_param: str
    confidence: str = Field(default="HIGH")
    reasoning: str = Field(default="")


class DiagnosisSkillBinding(BaseModel):
    """Associates a Skill with this EventType, storing the parameter mapping."""
    skill_id: int
    param_mappings: List[ParamMapping] = Field(default_factory=list)


class EventTypeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="e.g. SPC_OOC_Etch")
    description: str = Field(..., min_length=1, description="What this event represents")
    attributes: List[EventAttribute] = Field(default_factory=list)
    diagnosis_skills: List[DiagnosisSkillBinding] = Field(
        default_factory=list,
        description="Skills bound to this EventType with per-skill parameter mappings",
    )


class EventTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    attributes: Optional[List[EventAttribute]] = None
    diagnosis_skills: Optional[List[DiagnosisSkillBinding]] = Field(
        default=None,
        description="Skills bound to this EventType with per-skill parameter mappings",
    )


class EventTypeResponse(BaseModel):
    id: int
    name: str
    description: str
    attributes: List[Dict[str, Any]]
    diagnosis_skills: List[DiagnosisSkillBinding] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def diagnosis_skill_ids(self) -> List[int]:
        """Backward-compat: plain list of skill IDs derived from diagnosis_skills."""
        return [s.skill_id for s in self.diagnosis_skills]
