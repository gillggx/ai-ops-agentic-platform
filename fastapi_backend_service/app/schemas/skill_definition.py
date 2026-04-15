"""Pydantic schemas for Skill Definition v2.0 — Diagnostic-First Architecture.

Skill = pure diagnostic function.
  Input:  event_payload (keys defined by input_schema)
  Output: SkillFindings { condition_met, summary, outputs, impacted_lots }

trigger_alarm() removed. Alarm decisions are delegated to Auto-Patrol.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Input Schema (declares what a Skill needs as input) ──────────────────────

class InputSchemaField(BaseModel):
    """One input parameter declared by a Skill."""
    key: str
    type: str = "string"            # "string" | "integer" | "boolean"
    required: bool = True
    default: Optional[Any] = None
    description: str = ""


# ── Output Schema / Render Spec (declares how results should be rendered) ────

class SchemaColumn(BaseModel):
    """Column definition for 'table' type output fields."""
    key: str
    label: str
    type: str = "str"               # "str" | "int" | "float" | "bool"


class OutputSchemaField(BaseModel):
    """One output render spec declared by a Skill.

    Supported render types:
      scalar       → number / string with optional unit
      table        → data table (requires 'columns')
      badge        → condition status label (ok / warning / error)
      line_chart   → line chart; requires x_key + y_keys; optional highlight_key
      bar_chart    → bar chart; requires x_key + y_keys
      scatter_chart→ scatter plot; requires x_key + y_keys
    """
    key: str
    type: str                       # "scalar"|"table"|"badge"|"line_chart"|"bar_chart"|"scatter_chart"
    label: str
    unit: Optional[str] = None      # for type='scalar'
    description: str = ""
    columns: Optional[List[SchemaColumn]] = None  # for type='table'
    # Chart fields
    x_key: Optional[str] = None          # x-axis field name
    y_keys: Optional[List[str]] = None   # y-axis series field names
    highlight_key: Optional[str] = None  # boolean field: true rows get red markers


# Keep backward-compat alias
SchemaField = OutputSchemaField


# ── Skill Findings (runtime output of every Skill execution) ─────────────────

class SkillFindings(BaseModel):
    """Structured result returned by every Skill execution.

    condition_met:   Auto-Patrol reads this to decide whether to create an alarm.
    summary:         Human-readable conclusion sentence (new format).
    outputs:         Keyed results matching output_schema keys (new format).
    evidence:        Legacy flat dict — kept for backward compat, new Skills use outputs.
    impacted_lots:   Lot IDs affected when condition is met.
    schema_warnings: Mismatch warnings between outputs and declared output_schema.
    """
    condition_met: bool = False
    summary: str = ""
    outputs: Dict[str, Any] = {}
    evidence: Dict[str, Any] = {}   # legacy — new Skills should use outputs
    impacted_lots: List[str] = []
    schema_warnings: List[str] = []


# ── Step Mapping ──────────────────────────────────────────────────────────────

class StepMapping(BaseModel):
    step_id: str = Field(..., description="Unique step identifier, e.g. 'step1'")
    nl_segment: str = Field(..., description="Natural language description of this step")
    python_code: str = Field(..., description="Python code (may use await execute_mcp)")


# ── Skill CRUD ────────────────────────────────────────────────────────────────

class SkillDefinitionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    trigger_event_id: Optional[int] = Field(
        default=None,
        description="System Event that triggers this skill (NULL = schedule-only)"
    )
    trigger_mode: str = Field(default="both", pattern="^(schedule|event|both)$")
    steps_mapping: List[StepMapping] = Field(default_factory=list)
    input_schema: List[InputSchemaField] = Field(
        default_factory=list,
        description="Declares what input parameters this Skill needs"
    )
    output_schema: List[OutputSchemaField] = Field(
        default_factory=list,
        description="Render spec: declares how this Skill's outputs should be displayed"
    )
    visibility: str = Field(default="private", pattern="^(private|public)$")
    trigger_patrol_id: Optional[int] = Field(
        default=None,
        description="Auto-Patrol whose alarm triggers this Diagnostic Rule"
    )


class SkillDefinitionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    trigger_event_id: Optional[int] = None
    trigger_mode: Optional[str] = Field(default=None, pattern="^(schedule|event|both)$")
    steps_mapping: Optional[List[StepMapping]] = None
    input_schema: Optional[List[InputSchemaField]] = None
    output_schema: Optional[List[OutputSchemaField]] = None
    visibility: Optional[str] = Field(default=None, pattern="^(private|public)$")
    is_active: Optional[bool] = None
    trigger_patrol_id: Optional[int] = None


class SkillDefinitionResponse(BaseModel):
    id: int
    name: str
    description: str
    trigger_event_id: Optional[int] = None
    trigger_event_name: Optional[str] = None
    trigger_mode: str
    steps_mapping: List[Dict[str, Any]] = []
    input_schema: List[Dict[str, Any]] = []
    output_schema: List[Dict[str, Any]] = []
    visibility: str
    is_active: bool
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    trigger_patrol_id: Optional[int] = None
    trigger_patrol_name: Optional[str] = None   # enriched at service layer

    model_config = {"from_attributes": True}


# ── LLM Builder ───────────────────────────────────────────────────────────────

class GenerateStepsRequest(BaseModel):
    """Ask LLM to generate steps_mapping + output_schema from natural language."""
    trigger_event_id: Optional[int] = Field(default=None)
    nl_description: str = Field(..., min_length=5)


class GenerateStepsResponse(BaseModel):
    success: bool
    proposal_steps: List[str] = []
    steps_mapping: List[Dict[str, Any]] = []
    input_schema: List[Dict[str, Any]] = []
    output_schema: List[Dict[str, Any]] = []
    error: Optional[str] = None


# ── Try-Run ───────────────────────────────────────────────────────────────────

class SkillTryRunRequest(BaseModel):
    """Sandbox try-run with mock event payload."""
    mock_payload: Dict[str, Any] = Field(
        default_factory=lambda: {
            "event_type": "OOC",
            "equipment_id": "EQP-01",
            "lot_id": "LOT-0001",
            "step": "STEP_038",
            "event_time": "2026-01-01T00:00:00Z",
        }
    )


class StepResult(BaseModel):
    step_id: str
    nl_segment: str
    status: str             # "ok" | "error"
    output: Optional[Any] = None
    error: Optional[str] = None


class SkillTryRunResponse(BaseModel):
    success: bool
    step_results: List[StepResult] = []
    findings: Optional[SkillFindings] = None
    charts: Optional[List[Dict[str, Any]]] = None  # Auto-generated by ChartMiddleware
    total_elapsed_ms: float = 0.0
    error: Optional[str] = None


class SkillTryRunDraftRequest(BaseModel):
    """Try-run without a saved skill — for testing before first save (v3.0 flow)."""
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


# ── Execute ───────────────────────────────────────────────────────────────────

class SkillExecuteRequest(BaseModel):
    """Execute skill with real event payload. Alarm decisions are made by caller."""
    event_payload: Dict[str, Any] = Field(
        ...,
        description="Must contain: event_type, equipment_id, lot_id, step, event_time"
    )
    triggered_by: str = Field(default="manual")


class SkillExecuteResponse(BaseModel):
    success: bool
    step_results: List[StepResult] = []
    findings: Optional[SkillFindings] = None
    charts: Optional[List[Dict[str, Any]]] = None  # _chart DSL output from skill steps
    pipeline_result: Optional[Dict[str, Any]] = None  # Pipeline Skill: full pipeline_executor result
    error: Optional[str] = None


# ── Compiler Mode ─────────────────────────────────────────────────────────────

class NlStep(BaseModel):
    step_id: str = Field(..., description="Unique step identifier")
    nl_segment: str = Field(..., description="Natural language description of this step")


class CompileStepsRequest(BaseModel):
    """Ask LLM to compile user-defined NL steps into Python code."""
    trigger_event_id: Optional[int] = Field(default=None)
    nl_steps: List[NlStep] = Field(..., min_length=1)


class CompileStepsResponse(BaseModel):
    success: bool
    steps_mapping: List[Dict[str, Any]] = []
    output_schema: List[Dict[str, Any]] = []
    validation_notes: str = ""
    has_issues: bool = False
    error: Optional[str] = None


# ── Agent-initiated build (backward compat) ───────────────────────────────────

class SkillAgentBuildRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    trigger_event_id: Optional[int] = None
    nl_description: str = Field(..., min_length=10)


class SkillAgentBuildResponse(BaseModel):
    success: bool
    skill_id: Optional[int] = None
    name: str = ""
    steps_mapping: List[Dict[str, Any]] = []
    output_schema: List[Dict[str, Any]] = []
    error: Optional[str] = None
