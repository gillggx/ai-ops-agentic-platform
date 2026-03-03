"""Pydantic schemas for GeneratedEvent (auto-alarm, Phase 11)."""

from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

EventAlarmStatus = Literal["pending", "acknowledged", "resolved"]


class GeneratedEventResponse(BaseModel):
    id: int
    event_type_id: int
    source_skill_id: int
    source_routine_check_id: Optional[int]
    mapped_parameters: Dict[str, Any]
    skill_conclusion: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GeneratedEventStatusUpdate(BaseModel):
    status: EventAlarmStatus = Field(..., description="New status: acknowledged | resolved")
