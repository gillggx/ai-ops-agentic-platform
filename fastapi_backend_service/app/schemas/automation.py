"""Automation schemas: EventContext, ActionReport, Script Registry, Cron Jobs."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Core runtime types
# ---------------------------------------------------------------------------

class EventContext(BaseModel):
    """Structured input passed to every Skill execution."""
    event_type:  str             = Field(..., description="spc_ooc | fdc_fault | equipment_hold | lot_delayed | cron | manual")
    toolID:      Optional[str]   = None
    lotID:       Optional[str]   = None
    step:        Optional[str]   = None
    eventTime:   str             = Field(..., description="ISO 8601 timestamp")
    severity:    str             = Field(default="info", description="critical | high | warning | info")
    payload:     Dict[str, Any]  = Field(default_factory=dict, description="Original event raw data")


class ActionReport(BaseModel):
    """Structured output from a Skill's diagnose() execution."""
    action:     str              = Field(..., description="hold_equipment | notify_engineer | escalate | create_ocap | monitor")
    severity:   str              = Field(default="info")
    target_id:  Optional[str]    = None
    message:    str              = Field(default="")
    evidence:   Dict[str, Any]   = Field(default_factory=dict)
    next_skill: Optional[str]    = None   # chain to another skill


# ---------------------------------------------------------------------------
# Script Registry schemas
# ---------------------------------------------------------------------------

class ScriptVersionResponse(BaseModel):
    id:           int
    skill_id:     int
    version:      int
    status:       str
    code:         str
    change_note:  Optional[str]
    reviewed_by:  Optional[str]
    approved_at:  Optional[datetime]
    generated_at: datetime

    class Config:
        from_attributes = True


class ScriptVersionCreate(BaseModel):
    code:        str
    change_note: Optional[str] = None


class ScriptTestRunRequest(BaseModel):
    event_context: EventContext
    version:       Optional[int] = None   # None → use latest draft or active


class ScriptTestRunResponse(BaseModel):
    status:            str          # success | error | timeout
    diag_status:       Optional[str] = None   # NORMAL | ABNORMAL
    diagnosis_message: Optional[str] = None
    problem_object:    Optional[Dict[str, Any]] = None
    error:             Optional[str] = None
    duration_ms:       int


# ---------------------------------------------------------------------------
# Cron Job schemas
# ---------------------------------------------------------------------------

class CronJobCreate(BaseModel):
    skill_id:  int
    schedule:  str  = Field(..., description="cron expression e.g. '0 8 * * *'")
    timezone:  str  = Field(default="Asia/Taipei")
    label:     str  = Field(default="")


class CronJobUpdate(BaseModel):
    schedule:  Optional[str] = None
    timezone:  Optional[str] = None
    label:     Optional[str] = None


class CronJobResponse(BaseModel):
    id:          int
    skill_id:    int
    schedule:    str
    timezone:    str
    label:       str
    status:      str
    created_by:  Optional[str]
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at:  datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Action Dispatch schemas
# ---------------------------------------------------------------------------

class DispatchActionRequest(BaseModel):
    action_type:  str            = Field(..., description="hold_equipment | notify_engineer | escalate | create_ocap | monitor")
    target_id:    str
    severity:     str            = Field(default="warning")
    message:      str            = Field(default="")
    evidence:     Dict[str, Any] = Field(default_factory=dict)
    auto_execute: bool           = Field(default=False, description="Skip confirmation for non-critical actions")


class DispatchActionResponse(BaseModel):
    dispatched:  bool
    action_type: str
    target_id:   str
    message:     str
    requires_confirm: bool       # True → frontend should show confirm dialog


# ---------------------------------------------------------------------------
# Execution Log schemas
# ---------------------------------------------------------------------------

class ExecutionLogResponse(BaseModel):
    id:                 int
    skill_id:           int
    script_version_id:  Optional[int]
    cron_job_id:        Optional[int]
    triggered_by:       str
    event_context:      Optional[Dict[str, Any]]
    status:             str
    llm_readable_data:  Optional[Dict[str, Any]]
    action_dispatched:  Optional[str]
    error_message:      Optional[str]
    started_at:         datetime
    finished_at:        Optional[datetime]
    duration_ms:        Optional[int]

    class Config:
        from_attributes = True
