"""Pydantic schemas for Pipeline (JSON + CRUD + run result)."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# PR-B (2026-04-19) — 5-stage lifecycle replaces old enum. Old values auto-mapped
# by _safe_add_columns migration (pi_run→validating, production→active, deprecated→archived).
PipelineStatus = Literal["draft", "validating", "locked", "active", "archived"]
# Phase 5-UX-7: 3-kind split. "diagnostic" retained for read back-compat on any
# legacy row that somehow escaped migration; new code should write only the 3
# canonical kinds. Validator + UI reject writing "diagnostic" going forward.
PipelineKind = Literal["auto_patrol", "auto_check", "skill", "diagnostic"]
TriggeredBy = Literal["user", "agent", "schedule", "event"]
RunStatus = Literal["running", "success", "failed", "validation_error"]


class NodePosition(BaseModel):
    # React Flow emits sub-pixel float positions during drag; accept both.
    x: float
    y: float


class PipelineNode(BaseModel):
    id: str = Field(..., description="Local node id within the pipeline (e.g. 'n1')")
    block_id: str = Field(..., description="Block.name — human-readable reference")
    block_version: str = "1.0.0"
    position: NodePosition = Field(default_factory=lambda: NodePosition(x=0, y=0))
    params: dict[str, Any] = Field(default_factory=dict)
    display_label: Optional[str] = Field(default=None, description="User-overriding label shown in canvas")


class EdgeEndpoint(BaseModel):
    node: str
    port: str


class PipelineEdge(BaseModel):
    id: str
    from_: EdgeEndpoint = Field(..., alias="from")
    to: EdgeEndpoint

    model_config = ConfigDict(populate_by_name=True)


PipelineInputType = Literal["string", "integer", "number", "boolean"]


class PipelineInput(BaseModel):
    """A pipeline-level input declaration (variable usable as `$name` in node params).

    Phase 4-B0 (2026-04-18) — lets pipelines be reusable templates (auto patrol /
    diagnostic rules / chat re-invocation pass values via the executor's `inputs`
    arg).
    """
    name: str = Field(..., min_length=1, description="Variable name (no '$' prefix)")
    type: PipelineInputType = "string"
    required: bool = False
    default: Optional[Any] = None
    description: Optional[str] = None
    example: Optional[Any] = Field(default=None, description="Used in preview + Inspector placeholder")


class PipelineJSON(BaseModel):
    """Canonical Pipeline JSON payload (§4 of SPEC)."""

    version: str = "1.0"
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Phase 4-B0: pipeline-level input declarations; empty = fully hardcoded (old behaviour).
    inputs: list[PipelineInput] = Field(default_factory=list)
    nodes: list[PipelineNode]
    edges: list[PipelineEdge]


class PipelineCreate(BaseModel):
    name: str
    description: str = ""
    status: PipelineStatus = "draft"
    # Phase 5-UX-3b: nullable — caller may defer kind choice to publish time
    pipeline_kind: Optional[PipelineKind] = None
    pipeline_json: PipelineJSON


class PipelineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    status: PipelineStatus
    pipeline_kind: Optional[PipelineKind] = None
    version: str
    pipeline_json: PipelineJSON
    created_at: datetime
    updated_at: datetime


class NodeResult(BaseModel):
    status: Literal["success", "failed", "skipped"]
    rows: Optional[int] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    preview: Optional[dict[str, Any]] = None  # {columns, rows_sample}


class ValidationError(BaseModel):
    rule: str
    message: str
    node_id: Optional[str] = None
    edge_id: Optional[str] = None


class ExecuteRequest(BaseModel):
    """Phase 1: ad-hoc execute — 傳入完整 Pipeline JSON 立即跑。"""

    pipeline_json: PipelineJSON
    triggered_by: TriggeredBy = "user"
    # Phase 4-B0: runtime values for pipeline.inputs (maps input.name → value).
    inputs: dict[str, Any] = Field(default_factory=dict)
    # PR-C telemetry: if UI is running a saved pipeline, pass its id so we can
    # bump usage_stats on success.
    pipeline_id: Optional[int] = None


class PipelineChartSummary(BaseModel):
    """One chart_spec entry aggregated at pipeline level."""

    node_id: str
    sequence: Optional[int] = None
    title: Optional[str] = None
    chart_spec: dict[str, Any]


class PipelineDataView(BaseModel):
    """PR-E1: a pinned DataFrame output (from block_data_view).

    Rendered by frontend as a plain table in Pipeline Results — distinct from
    chart_spec which goes through the chart renderer.
    """

    node_id: str
    sequence: Optional[int] = None
    title: str
    description: Optional[str] = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    total_rows: int = 0


class PipelineResultSummary(BaseModel):
    """Pipeline-level verdict: terminal logic node's triggered+evidence,
    plus all chart_spec outputs + data_view outputs (ordered by sequence).

    Populated when the pipeline has a logic node OR a chart OR a data_view;
    otherwise None.
    """

    triggered: bool
    evidence_node_id: Optional[str] = None
    evidence_rows: int = 0
    charts: list[PipelineChartSummary] = Field(default_factory=list)
    data_views: list[PipelineDataView] = Field(default_factory=list)


class ExecuteResponse(BaseModel):
    run_id: int
    status: RunStatus
    node_results: dict[str, NodeResult] = Field(default_factory=dict)
    errors: list[ValidationError] = Field(default_factory=list)
    error_message: Optional[str] = None
    duration_ms: Optional[float] = None
    result_summary: Optional[PipelineResultSummary] = None
