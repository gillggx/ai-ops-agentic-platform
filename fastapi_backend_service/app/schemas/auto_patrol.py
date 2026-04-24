"""Pydantic schemas for Auto-Patrol v2.0.

Auto-Patrol orchestrates Skill execution and alarm decisions.
  trigger fires → run Skill → read findings.condition_met
  → if True: create Alarm + notify
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Target Scope ─────────────────────────────────────────────────────────────

class TargetScope(BaseModel):
    """Which equipment this patrol covers."""
    type: str = "event_driven"   # "all_equipment" | "equipment_list" | "event_driven"
    equipment_ids: List[str] = []


# ── Notify Config ─────────────────────────────────────────────────────────────

class NotifyConfig(BaseModel):
    channels: List[str] = []   # e.g. ["email", "slack"]
    users: List[str] = []       # user IDs or emails


# ── CRUD Schemas ──────────────────────────────────────────────────────────────

DATA_CONTEXT_VALUES = ("recent_ooc", "active_lots", "tool_status")


class AutoPatrolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    # Natural language description of what this patrol checks (fed to AI designer)
    auto_check_description: str = ""
    trigger_mode: str = Field("schedule", pattern="^(event|schedule|once)$")
    event_type_id: Optional[int] = None
    cron_expr: Optional[str] = None
    # P3: one-shot execution at scheduled_at (used when trigger_mode="once")
    scheduled_at: Optional[datetime] = None
    # schedule-triggered: which context to fetch and inject as {data}
    data_context: str = Field("recent_ooc", pattern="^(recent_ooc|active_lots|tool_status)$")
    target_scope: TargetScope = Field(default_factory=lambda: TargetScope())
    alarm_severity: Optional[str] = Field(None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    alarm_title: Optional[str] = Field(None, max_length=300)
    notify_config: Optional[NotifyConfig] = None
    is_active: bool = True
    # Embedded skill steps (auto-creates source='auto_patrol' skill on save)
    steps_mapping: List[Dict[str, Any]] = Field(default_factory=list)
    input_schema: List[Dict[str, Any]] = Field(default_factory=list)
    output_schema: List[Dict[str, Any]] = Field(default_factory=list)
    # Phase 4-B: alternative to embedded skill — bind directly to a pipeline
    pipeline_id: Optional[int] = None
    input_binding: Optional[Dict[str, Any]] = None


class AutoPatrolUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    auto_check_description: Optional[str] = None
    trigger_mode: Optional[str] = Field(None, pattern="^(event|schedule|once)$")
    event_type_id: Optional[int] = None
    cron_expr: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    data_context: Optional[str] = Field(None, pattern="^(recent_ooc|active_lots|tool_status)$")
    target_scope: Optional[TargetScope] = None
    alarm_severity: Optional[str] = Field(None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    alarm_title: Optional[str] = Field(None, max_length=300)
    notify_config: Optional[NotifyConfig] = None
    is_active: Optional[bool] = None
    # Updating steps also updates the embedded skill
    steps_mapping: Optional[List[Dict[str, Any]]] = None
    input_schema: Optional[List[Dict[str, Any]]] = None
    output_schema: Optional[List[Dict[str, Any]]] = None
    # Phase 4-B
    pipeline_id: Optional[int] = None
    input_binding: Optional[Dict[str, Any]] = None


class AutoPatrolResponse(BaseModel):
    id: int
    name: str
    description: str
    auto_check_description: str = ""
    # Phase 4-B: either skill_id (legacy) OR pipeline_id (new)
    skill_id: Optional[int] = None
    pipeline_id: Optional[int] = None
    input_binding: Optional[Dict[str, Any]] = None
    trigger_mode: str
    event_type_id: Optional[int]
    cron_expr: Optional[str]
    scheduled_at: Optional[datetime] = None
    data_context: str
    target_scope: Dict[str, Any]
    alarm_severity: Optional[str]
    alarm_title: Optional[str]
    notify_config: Optional[Dict[str, Any]]
    is_active: bool
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime


# ── Manual Trigger ─────────────────────────────────────────────────────────────

class AutoPatrolTriggerRequest(BaseModel):
    """Manually trigger a patrol with an optional event payload."""
    event_payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Event payload forwarded to the Skill (e.g. {equipment_id, lot_id, step})"
    )


class AutoPatrolTriggerResponse(BaseModel):
    patrol_id: int
    patrol_name: str
    # Phase 4-B: skill_id nullable — pipeline-based patrols use pipeline_id instead
    skill_id: Optional[int] = None
    pipeline_id: Optional[int] = None
    condition_met: bool
    alarm_created: bool
    alarm_id: Optional[int] = None
    findings: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
