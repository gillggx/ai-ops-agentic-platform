/**
 * Pipeline Builder — shared TypeScript types.
 * Mirrors app/schemas/pipeline.py and app/schemas/block.py on the backend.
 */

export type BlockCategory = "source" | "transform" | "logic" | "output" | "custom";
export type BlockStatus = "draft" | "pi_run" | "production" | "deprecated";
/** PR-B: 5-stage pipeline lifecycle. Backend maps legacy names on migration.
 *  Phase 11 v6 — "linked" added for skill-owned pipelines (parent_skill_doc_id
 *  IS NOT NULL). Lifecycle is driven by the parent Skill, not pb_pipelines.status. */
export type PipelineStatus = "draft" | "validating" | "locked" | "active" | "archived" | "linked";

export interface PortSpec {
  port: string;
  type: string;
  columns?: string[];
  description?: string;
}

export interface JsonSchemaProperty {
  type?: string;
  title?: string;
  enum?: Array<string | number>;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  items?: JsonSchemaProperty;
  /** Extension: fetch autocomplete values from /api/pipeline-builder/suggestions/{key} */
  "x-suggestions"?: string;
  /** Extension: column-picker source. e.g. "input.data" / "input.left" / "input.left+right".
   *  Value is the columns of the named input port(s) of the current node (from upstream preview). */
  "x-column-source"?: string;
}

export interface ParamSchema {
  type?: string;
  required?: string[];
  properties?: Record<string, JsonSchemaProperty>;
}

export interface BlockExample {
  name: string;
  summary: string;
  params: Record<string, unknown>;
  upstream_hint?: string | null;
}

export interface BlockSpec {
  id: number;
  name: string;
  category: BlockCategory;
  version: string;
  status: BlockStatus;
  description: string;
  input_schema: PortSpec[];
  output_schema: PortSpec[];
  param_schema: ParamSchema;
  examples?: BlockExample[];
  is_custom: boolean;
}

export interface NodePosition {
  x: number;
  y: number;
}

export interface PipelineNode {
  id: string;
  block_id: string;
  block_version: string;
  position: NodePosition;
  params: Record<string, unknown>;
  display_label?: string;
}

export interface EdgeEndpoint {
  node: string;
  port: string;
}

export interface PipelineEdge {
  id: string;
  from: EdgeEndpoint;
  to: EdgeEndpoint;
}

export type PipelineInputType = "string" | "integer" | "number" | "boolean";

export interface PipelineInput {
  name: string;
  type: PipelineInputType;
  required?: boolean;
  default?: unknown;
  description?: string;
  example?: unknown;
}

export interface PipelineJSON {
  version: string;
  name: string;
  metadata?: Record<string, unknown>;
  /** Phase 4-B0: pipeline-level input declarations. Node params can reference
   *  any declared input via `"$name"` string value. */
  inputs?: PipelineInput[];
  nodes: PipelineNode[];
  edges: PipelineEdge[];
}

export interface PipelineSummary {
  id: number;
  name: string;
  description: string;
  status: PipelineStatus;
  /** PR-B: auto_patrol | diagnostic — determines runtime routing + structural rules */
  pipeline_kind?: PipelineKind;
  version: string;
  parent_id?: number | null;
  created_at?: string;
  updated_at?: string;
  usage_stats?: {
    invoke_count?: number;
    last_invoked_at?: string | null;
    last_triggered_at?: string | null;
  };
}

// Phase 5-UX-7: 3-kind split. "diagnostic" retained as read-only legacy.
export type PipelineKind = "auto_patrol" | "auto_check" | "skill" | "diagnostic";

export interface PipelineRecord extends PipelineSummary {
  pipeline_json: PipelineJSON;
}

export interface ValidationErrorItem {
  rule: string;
  message: string;
  node_id?: string;
  edge_id?: string;
}

export interface NodeResultPreview {
  type: string;
  columns?: string[];
  rows?: Array<Record<string, unknown>>;
  total?: number;
  snapshot?: unknown;
  length?: number;
  sample?: unknown;
  value?: unknown;
}

export interface NodeResult {
  status: "success" | "failed" | "skipped";
  rows?: number | null;
  duration_ms?: number | null;
  error?: string | null;
  preview?: Record<string, NodeResultPreview> | null;
}

export interface PipelineChartSummary {
  node_id: string;
  sequence: number | null;
  title: string | null;
  chart_spec: unknown; // Vega-Lite spec
}

/** PR-E1: pinned tabular output from block_data_view. */
export interface PipelineDataView {
  node_id: string;
  sequence: number | null;
  title: string;
  description?: string | null;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  total_rows: number;
}

/** Pipeline-level verdict: terminal logic node's triggered+evidence, plus all charts. */
export interface PipelineResultSummary {
  triggered: boolean;
  evidence_node_id: string | null;
  evidence_rows: number;
  charts: PipelineChartSummary[];
  data_views?: PipelineDataView[];
}

export interface ExecuteResponse {
  run_id: number;
  status: "running" | "success" | "failed" | "validation_error";
  node_results: Record<string, NodeResult>;
  errors?: ValidationErrorItem[];
  error_message?: string | null;
  duration_ms?: number | null;
  result_summary?: PipelineResultSummary | null;
}
