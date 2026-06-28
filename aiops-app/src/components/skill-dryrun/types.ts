/**
 * Shared types for the Dry-run UI.
 *
 * Wire format from Java is snake_case (Jackson default — see
 * feedback_jackson_snake_case_wire); these mirror it.
 */

export interface SkillStep {
  id: string;
  text: string;
  order?: number;
  pipeline_id?: number | null;
  confirmed?: boolean;
  pending?: boolean;
  badge?: { label?: string; kind?: string } | null;
  // 2026-06-27 dry-run extension (not yet persisted): per-step threshold
  // override applied during dry-run only. Phase 2 will round-trip to backend.
  threshold?: number;
  operator?: string;
  dim?: string;
}

export interface SkillDocument {
  id: number;
  slug: string;
  title: string;
  stage: string;
  status: string;
  description: string;
  steps: SkillStep[];        // parsed from JSON-text on read
  test_cases: TestCase[];    // parsed from JSON-text on read
  trigger_config: Record<string, unknown>;
}

/**
 * A test case to dry-run against. Two shapes flow through this UI:
 *   (a) PastEvent — fetched from /past-events; payload is a past alarm.
 *   (b) SavedCase — appended via "Save as regression"; same shape.
 *   (c) ManualInput (Phase 2) — user-typed JSON.
 */
export interface TestCase {
  id: string;
  label?: string;             // human-readable e.g. "EQP-06"
  severity?: string | null;
  payload: Record<string, unknown>;
  // Pre-computed pass/fail values per step (only for legacy seed cases
  // matching the design prototype; real cases get values from SSE step_done).
  vals?: number[];
}

/** Per-step result the report renders, derived from SSE step_done or local calc. */
export interface StepResult {
  step_id: string;
  status: "pass" | "fail" | "skipped";
  value?: number | string;
  threshold?: number | string;
  operator?: string;
  note?: string;
  // 2026-06-28: SkillStepExecutor.parseRunResult forwards the full
  // pipeline result_summary so the dry-run report can render each step's
  // chart inline (not just the boolean verdict). Shape matches
  // PipelineResultSummary from @/lib/pipeline-builder/types but we keep it
  // loose here to avoid a circular module dep.
  result_summary?: {
    charts?: Array<{ node_id: string; title?: string | null; chart_spec: unknown }>;
    [k: string]: unknown;
  } | null;
}

export type DryRunView = "editor" | "picker" | "running" | "report";
