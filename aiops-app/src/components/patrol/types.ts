/**
 * Shared types for the Patrol Activity surface.
 *
 * Mirrors Java {@code PatrolActivityService.Funnel} and {@code .Item}.
 * Wire format is snake_case (Jackson SNAKE_CASE naming strategy — see
 * feedback_jackson_snake_case_wire) — these interfaces match the on-wire
 * shape exactly; no client-side renaming.
 */

export interface PatrolFunnel {
  events: number;
  skill_runs: number;
  step_passed: number;
  alarms: number;
  dedup_suppressed: number;
}

export interface PatrolItem {
  skill_run_id: number;
  skill_id: number;
  skill_slug: string | null;
  skill_title: string | null;
  skill_stage: string | null;
  triggered_at: string;          // ISO 8601
  triggered_by: string | null;
  duration_ms: number | null;
  status: string;                // running | completed | failed | skipped_by_confirm
  steps_total: number;
  steps_passed: number;

  event_type: string | null;
  event_time: string | null;
  equipment_id: string | null;
  lot_id: string | null;
  step_id: string | null;

  alarm_id: number | null;
  alarm_skipped_reason: string | null;  // test | stage_not_patrol | confirm_failed | no_step_passed | dedup | null
}

/** Maps AlarmEmitter guard names to short user-facing labels. */
export const ALARM_SKIPPED_LABELS: Record<string, string> = {
  test: "test run",
  stage_not_patrol: "diagnose 階段（不 alarm）",
  confirm_failed: "confirm 沒過",
  no_step_passed: "無 step pass",
  dedup: "1h 內已 alarm",
};

export function formatAlarmSkipped(reason: string | null): string {
  if (!reason) return "—";
  return ALARM_SKIPPED_LABELS[reason] ?? reason;
}
