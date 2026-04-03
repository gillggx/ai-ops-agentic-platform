"""GeneratedEvent Pydantic schemas — aligned with actual DB columns."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GeneratedEventCreate(BaseModel):
    event_type_id: int
    source_skill_id: int
    source_routine_check_id: Optional[int] = None
    mapped_parameters: str = Field(default="{}")
    skill_conclusion: Optional[str] = None
    status: str = Field(default="pending")


class GeneratedEventRead(BaseModel):
    id: int
    event_type_id: int
    source_skill_id: int
    source_routine_check_id: Optional[int] = None
    mapped_parameters: str = "{}"
    skill_conclusion: Optional[str] = None
    status: str = "pending"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GeneratedEventStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|acknowledged|resolved)$")
