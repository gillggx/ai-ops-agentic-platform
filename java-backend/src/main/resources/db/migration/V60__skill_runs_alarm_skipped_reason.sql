-- V60 — skill_runs: explain why no alarm was emitted.
--
-- Patrol Activity UI needs to surface "skill ran but no alarm — why?"
-- Without this column the UI can only show "alarms = 0" which forces
-- the oncall engineer to open the source code to learn the 4 guards
-- in SkillAlarmEmitter.emitIfTriggered.
--
-- Values written by SkillAlarmEmitter:
--   'test'              — Guard 1: run was a test, never alarms
--   'stage_not_patrol'  — Guard 2: skill.stage != 'patrol' (e.g. diagnose)
--   'confirm_failed'    — Guard 3: confirm step failed → checklist skipped
--   'no_step_passed'    — Guard 4: no step status='pass'
--   'dedup'             — active alarm for (skill, equipment) within 1h
--   NULL                — alarm emitted normally, OR row predates this column
--
-- Old rows stay NULL — UI renders '—' for them. No backfill needed.
--
-- Flyway disabled in prod — apply on EC2 with:
--   psql -h localhost -U aiops aiops_db -f V60__skill_runs_alarm_skipped_reason.sql

ALTER TABLE skill_runs
  ADD COLUMN IF NOT EXISTS alarm_skipped_reason TEXT;

COMMENT ON COLUMN skill_runs.alarm_skipped_reason IS
  'When no alarm was emitted, which guard rejected. NULL = alarm emitted OR pre-V60 row. See SkillAlarmEmitter for guard list.';

CREATE INDEX IF NOT EXISTS ix_skill_runs_alarm_skipped_reason
  ON skill_runs(alarm_skipped_reason)
  WHERE alarm_skipped_reason IS NOT NULL;

-- ── alarms.skill_run_id (provenance link, same feature) ──────────────
--
-- Why: Patrol Activity items are anchored on skill_runs; if an alarm fired
-- we want a "View alarm" link without a fuzzy time-window match. The
-- AlarmEmitter knows the SkillRunEntity at write time, so just record it.

ALTER TABLE alarms
  ADD COLUMN IF NOT EXISTS skill_run_id BIGINT;

COMMENT ON COLUMN alarms.skill_run_id IS
  'FK-like link to the skill_runs row that produced this alarm. NULL on pre-V60 rows and on legacy auto-patrol alarms that bypass the skill runner.';

CREATE INDEX IF NOT EXISTS ix_alarms_skill_run_id
  ON alarms(skill_run_id)
  WHERE skill_run_id IS NOT NULL;
