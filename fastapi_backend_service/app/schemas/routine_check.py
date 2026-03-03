"""Pydantic schemas for RoutineCheck CRUD (Phase 11)."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ScheduleInterval = Literal["30m", "1h", "4h", "8h", "12h", "daily"]


class RoutineCheckCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    skill_id: int = Field(..., description="Skill to run on schedule")
    # Mandatory params fed directly into the Skill execution
    skill_input: Dict[str, Any] = Field(
        ...,
        description="Required Skill execution parameters, e.g. {'lot_id': 'N97A45.00', 'tool_id': 'TETCH01'}",
    )
    # Name for the EventType that will be auto-created from the Skill's output schema.
    # When Skill returns ABNORMAL the system fires a GeneratedEvent of this type.
    # Defaults to "{name} 異常警報" when omitted.
    generated_event_name: Optional[str] = Field(
        default=None,
        description="Name for the auto-created EventType (defaults to '{schedule_name} 異常警報')",
    )
    schedule_interval: ScheduleInterval = Field(default="1h")
    is_active: bool = Field(default=True)


class RoutineCheckUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    skill_input: Optional[Dict[str, Any]] = Field(default=None)
    trigger_event_id: Optional[int] = Field(default=None)
    event_param_mappings: Optional[List[Dict[str, Any]]] = Field(default=None)
    schedule_interval: Optional[ScheduleInterval] = None
    is_active: Optional[bool] = None


class RoutineCheckResponse(BaseModel):
    id: int
    name: str
    skill_id: int
    skill_input: Dict[str, Any]
    trigger_event_id: Optional[int]
    event_param_mappings: Optional[List[Dict[str, Any]]] = None
    schedule_interval: str
    is_active: bool
    last_run_at: Optional[str]
    last_run_status: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoutineCheckRunResponse(BaseModel):
    """Result of a manual run-now trigger."""
    routine_check_id: int
    skill_id: int
    status: str          # "NORMAL" | "ABNORMAL" | "ERROR"
    conclusion: str = ""
    generated_event_id: Optional[int] = None
    error: Optional[str] = None
