"""Pydantic schemas for MockDataSource CRUD + run + generate-code."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MockDataSourceCreate(BaseModel):
    name: str = Field(..., max_length=200)
    description: str = Field(default="")
    input_schema: Optional[str] = None
    python_code: Optional[str] = None
    is_active: bool = True


class MockDataSourceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    input_schema: Optional[str] = None
    python_code: Optional[str] = None
    is_active: Optional[bool] = None


class MockDataSourceResponse(BaseModel):
    id: int
    name: str
    description: str
    input_schema: Optional[str] = None
    python_code: Optional[str] = None
    sample_output: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MockDataRunRequest(BaseModel):
    params: Dict[str, Any] = Field(default_factory=dict)


class MockDataRunResponse(BaseModel):
    mock_data_source_id: int
    name: str
    dataset: Any
    llm_readable_data: str
    ui_render_payload: Dict[str, Any]
    endpoint_url: str


class MockDataGenerateRequest(BaseModel):
    description: str = Field(..., description="What this mock data source should simulate")
    input_schema: Optional[str] = Field(default=None, description="JSON input schema (optional, auto-generates if omitted)")
    sample_params: Optional[Dict[str, Any]] = Field(default=None, description="Example params for the LLM to test with")
