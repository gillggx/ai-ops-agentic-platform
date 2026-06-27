/**
 * Shared types for the Patrol Activity surface.
 *
 * Mirrors Java {@code PatrolActivityService.Funnel} and {@code .Item}.
 * Wire format is snake_case (Jackson default) — these interfaces match
 * the on-wire shape exactly; no client-side renaming.
 */

export interface PatrolFunnel {
  events: number;
  skillRuns: number;
  stepPassed: number;
  alarms: number;
  dedupSuppressed: number;
}

export interface PatrolItem {
  skillRunId: number;
  skillId: number;
  skillSlug: string | null;
  skillTitle: string | null;
  skillStage: string | null;
  triggeredAt: string;          // ISO 8601
  triggeredBy: string | null;
  durationMs: number | null;
  status: string;                // running | completed | failed | skipped_by_confirm
  stepsTotal: number;
  stepsPassed: number;

  eventType: string | null;
  eventTime: string | null;
  equipmentId: string | null;
  lotId: string | null;
  stepId: string | null;

  alarmId: number | null;
  alarmSkippedReason: string | null;  // test | stage_not_patrol | confirm_failed | no_step_passed | dedup | null
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
