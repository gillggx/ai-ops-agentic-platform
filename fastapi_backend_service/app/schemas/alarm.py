"""Pydantic schemas for Alarm CRUD and lifecycle management."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AlarmResponse(BaseModel):
    id: int
    skill_id: int
    trigger_event: str
    equipment_id: str
    lot_id: str
    step: Optional[str] = None
    event_time: Optional[datetime] = None
    severity: str  # LOW / MEDIUM / HIGH / CRITICAL
    title: str
    summary: Optional[str] = None
    status: str    # active / acknowledged / resolved
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    execution_log_id: Optional[int] = None
    diagnostic_log_id: Optional[int] = None
    # Enriched at API layer — Auto-Patrol findings (why alarm was triggered)
    findings: Optional[Dict[str, Any]] = None
    output_schema: Optional[List[Any]] = None
    # Enriched at API layer — Diagnostic Rule findings (deep investigation)
    diagnostic_findings: Optional[Dict[str, Any]] = None
    diagnostic_output_schema: Optional[List[Any]] = None

    model_config = {"from_attributes": True}


class AlarmAcknowledgeRequest(BaseModel):
    acknowledged_by: str = Field(..., min_length=1)


class AlarmResolveRequest(BaseModel):
    resolution_note: Optional[str] = None


class AlarmStatsResponse(BaseModel):
    """Severity counts for the homepage badge bar."""
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    total_active: int = 0


class AlarmListFilter(BaseModel):
    severity: Optional[str] = None       # LOW/MEDIUM/HIGH/CRITICAL
    status: Optional[str] = "active"     # active/acknowledged/resolved/all
    equipment_id: Optional[str] = None
    lot_id: Optional[str] = None
    trigger_event: Optional[str] = None
    days: int = Field(default=7, ge=1, le=90)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
