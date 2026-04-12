/**
 * AIOps Report Contract — TypeScript Type Definitions
 *
 * 共同語言：Agent 與 AIOps 之間的溝通標準。
 */

export const SCHEMA_VERSION = "aiops-report/v1" as const;

// ---------------------------------------------------------------------------
// Evidence Chain
// ---------------------------------------------------------------------------

export interface EvidenceItem {
  /** 執行順序（從 1 開始） */
  step: number;
  /** mcp_name 或 skill_id */
  tool: string;
  /** 一句話結論，給人類閱讀 */
  finding: string;
  /** 對應 visualization[].id，可 undefined */
  viz_ref?: string;
  // ── Extended (DR/AP-style execution detail) ────────────────────────────
  /** Skill step_id (e.g. "step1") — same as `tool` for execute_analysis */
  step_id?: string;
  /** Plain-language description of what this step does */
  nl_segment?: string;
  /** Python code that was executed for this step */
  python_code?: string;
  /** Step execution status */
  status?: "ok" | "error";
  /** Step output (any JSON-serialisable value) */
  output?: unknown;
  /** Error message if status === "error" */
  error?: string;
}

// ---------------------------------------------------------------------------
// Visualization
// ---------------------------------------------------------------------------

/**
 * 標準 visualization type 值。
 * 前端未認識的 type 顯示 UnsupportedPlaceholder，不 crash。
 */
export type VisualizationType =
  | "vega-lite"
  | "kpi-card"
  | "topology"
  | "gantt"
  | "table"
  | (string & {}); // 允許擴充的自訂 type

export interface VisualizationItem {
  /** 唯一識別，供 evidence_chain.viz_ref 引用 */
  id: string;
  /** renderer 類型 */
  type: VisualizationType;
  /**
   * 對應 type 的 spec。
   * - vega-lite：標準 Vega-Lite JSON spec
   * - 其他：自訂 schema，前端對應 component 負責解析
   */
  spec: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Suggested Actions
// ---------------------------------------------------------------------------

export interface AgentAction {
  label: string;
  trigger: "agent";
  /** 帶入 Agent 的 next message */
  message: string;
}

export interface HandoffAction {
  label: string;
  trigger: "aiops_handoff";
  /** AIOps Handoff MCP name */
  mcp: string;
  params?: Record<string, unknown>;
}

export type SuggestedAction = AgentAction | HandoffAction;

// ---------------------------------------------------------------------------
// Root Contract
// ---------------------------------------------------------------------------

/**
 * Findings produced by Skill / Diagnostic Rule execution.
 * Mirrors `app.schemas.skill_definition.SkillFindings`.
 */
export interface SkillFindings {
  condition_met: boolean;
  summary?: string;
  outputs?: Record<string, unknown>;
  evidence?: Record<string, unknown>;
  impacted_lots?: string[];
}

/**
 * Chart DSL produced by backend ChartMiddleware.
 * Frontend renders via <ChartListRenderer />.
 */
export interface ChartDSL {
  type: "line" | "bar" | "scatter";
  title: string;
  data: Record<string, unknown>[];
  x: string;
  y: string[];
  rules?: { value: number; label: string; style?: "danger" | "warning" | "center" }[];
  highlight?: { field: string; eq: unknown } | null;
}

export interface AIOpsReportContract {
  $schema: typeof SCHEMA_VERSION;
  /** 給人類閱讀的根因結論或回應摘要 */
  summary: string;
  /** 推理過程中每個工具呼叫的關鍵發現 */
  evidence_chain: EvidenceItem[];
  /** 視覺化區塊列表（legacy — 新格式請用 charts） */
  visualization: VisualizationItem[];
  /** 建議的後續動作，前端渲染為可點擊按鈕 */
  suggested_actions: SuggestedAction[];
  // ── Extended (DR/AP-style result, optional for back-compat) ────────────
  /** Full findings — enables RenderMiddleware to draw scalars/badges/tables */
  findings?: SkillFindings;
  /** Output schema for the steps — needed by RenderMiddleware */
  output_schema?: Array<Record<string, unknown>>;
  /** Chart DSL list from backend ChartMiddleware (preferred over visualization) */
  charts?: ChartDSL[];
}

// ---------------------------------------------------------------------------
// Type Guards
// ---------------------------------------------------------------------------

export function isAgentAction(action: SuggestedAction): action is AgentAction {
  return action.trigger === "agent";
}

export function isHandoffAction(action: SuggestedAction): action is HandoffAction {
  return action.trigger === "aiops_handoff";
}

export function isValidContract(value: unknown): value is AIOpsReportContract {
  if (typeof value !== "object" || value === null) return false;
  const obj = value as Record<string, unknown>;
  return (
    obj["$schema"] === SCHEMA_VERSION &&
    typeof obj["summary"] === "string" &&
    Array.isArray(obj["evidence_chain"]) &&
    Array.isArray(obj["visualization"]) &&
    Array.isArray(obj["suggested_actions"])
  );
}
