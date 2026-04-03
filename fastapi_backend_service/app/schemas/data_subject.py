"""Pydantic schemas for DataSubject CRUD."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApiConfig(BaseModel):
    endpoint_url: str = Field(..., description="Full URL of the data API endpoint")
    method: str = Field(default="GET", description="HTTP method: GET or POST")
    headers: Dict[str, str] = Field(default_factory=dict, description="HTTP headers")


class SchemaField(BaseModel):
    name: str
    type: str = Field(default="string", description="string|number|boolean|array|object")
    description: str = Field(default="")
    required: bool = Field(default=False)


class DataSubjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    api_config: ApiConfig
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class DataSubjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    api_config: Optional[ApiConfig] = None
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None


class DataSubjectResponse(BaseModel):
    id: int
    name: str
    description: str
    api_config: Dict[str, Any]
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    is_builtin: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
