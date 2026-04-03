"""Pydantic schemas for Diagnostic Rule — source='rule' skill wrappers."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── CRUD ──────────────────────────────────────────────────────────────────────

class DiagnosticRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    auto_check_description: str = Field(
        default="",
        description="自動檢查描述 — 用於 AI 設計診斷計畫的 NL prompt"
    )
    steps_mapping: List[Dict[str, Any]] = Field(default_factory=list)
    input_schema: List[Dict[str, Any]] = Field(default_factory=list)
    output_schema: List[Dict[str, Any]] = Field(default_factory=list)
    visibility: str = Field(default="private", pattern="^(private|public)$")
    trigger_patrol_id: Optional[int] = Field(
        default=None,
        description="Auto-Patrol whose alarm triggers this Diagnostic Rule"
    )


class DiagnosticRuleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    auto_check_description: Optional[str] = None
    steps_mapping: Optional[List[Dict[str, Any]]] = None
    input_schema: Optional[List[Dict[str, Any]]] = None
    output_schema: Optional[List[Dict[str, Any]]] = None
    visibility: Optional[str] = Field(default=None, pattern="^(private|public)$")
    is_active: Optional[bool] = None
    trigger_patrol_id: Optional[int] = None


class DiagnosticRuleResponse(BaseModel):
    id: int
    name: str
    description: str
    auto_check_description: str
    steps_mapping: List[Dict[str, Any]] = []
    input_schema: List[Dict[str, Any]] = []
    output_schema: List[Dict[str, Any]] = []
    visibility: str
    is_active: bool
    source: str
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    trigger_patrol_id: Optional[int] = None

    model_config = {"from_attributes": True}


# ── LLM Builder ───────────────────────────────────────────────────────────────

class GenerateRuleStepsRequest(BaseModel):
    """Ask LLM to generate steps_mapping + output_schema from auto_check_description."""
    auto_check_description: str = Field(..., min_length=5)


class GenerateRuleStepsResponse(BaseModel):
    success: bool
    proposal_steps: List[str] = []
    steps_mapping: List[Dict[str, Any]] = []
    input_schema: List[Dict[str, Any]] = []
    output_schema: List[Dict[str, Any]] = []
    error: Optional[str] = None


# ── Try-Run ───────────────────────────────────────────────────────────────────

class RuleTryRunRequest(BaseModel):
    mock_payload: Dict[str, Any] = Field(
        default_factory=lambda: {
            "event_type": "OOC",
            "equipment_id": "EQP-01",
            "lot_id": "LOT-0001",
            "step": "STEP_038",
            "event_time": "2026-01-01T00:00:00Z",
        }
    )


class RuleTryRunDraftRequest(BaseModel):
    steps_mapping: List[Dict[str, Any]] = Field(..., min_length=1)
    output_schema: List[Dict[str, Any]] = Field(default_factory=list)
    mock_payload: Dict[str, Any] = Field(
        default_factory=lambda: {
            "event_type": "OOC",
            "equipment_id": "EQP-01",
            "lot_id": "LOT-0001",
            "step": "STEP_038",
            "event_time": "2026-01-01T00:00:00Z",
        }
    )
