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

/** AlarmEmitter guard codes (wire values) with a user-facing label in the
 *  patrol catalog (i18n P3: code on the wire, translate at the edge).
 *  Unknown codes fall back to the raw wire value. */
export const ALARM_SKIPPED_CODES = new Set([
  "test", "stage_not_patrol", "confirm_failed", "no_step_passed", "dedup",
]);

export function formatAlarmSkipped(
  reason: string | null,
  t: (key: string) => string,
): string {
  if (!reason) return "—";
  return ALARM_SKIPPED_CODES.has(reason) ? t(`alarmSkipped.${reason}`) : reason;
}
