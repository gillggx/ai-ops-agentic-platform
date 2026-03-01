"""Pydantic schemas for EventType CRUD."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EventAttribute(BaseModel):
    name: str = Field(..., description="Attribute name, e.g. lot_id")
    type: str = Field(default="string", description="string|number|boolean")
    description: str = Field(..., min_length=1, description="MANDATORY: semantic description for LLM mapping")
    required: bool = Field(default=True)


class EventTypeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="e.g. SPC_OOC_Etch")
    description: str = Field(..., min_length=1, description="What this event represents")
    attributes: List[EventAttribute] = Field(default_factory=list)
    spc_chart: Optional[str] = Field(default=None, max_length=100, description="SPC chart ID, e.g. 'CD'")


class EventTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    attributes: Optional[List[EventAttribute]] = None
    spc_chart: Optional[str] = Field(default=None, max_length=100)


class EventTypeResponse(BaseModel):
    id: int
    name: str
    description: str
    attributes: List[Dict[str, Any]]
    spc_chart: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
