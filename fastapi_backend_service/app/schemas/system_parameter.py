"""Pydantic schemas for SystemParameter."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SystemParameterResponse(BaseModel):
    key: str
    value: Optional[str]
    description: Optional[str]
    updated_at: datetime

    model_config = {"from_attributes": True}


class SystemParameterUpdate(BaseModel):
    value: str = Field(..., min_length=1)
