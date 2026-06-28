-- V67: let skill_runs trace skills_v2 runs (not just legacy skill_documents).
--
-- Phase A of wiring cron/event scheduling to the skills_v2 model. skill_runs
-- was hard-FK'd to skill_documents(id); add a parallel nullable FK to
-- skills_v2(id) so a run row references exactly one of the two registries.
--
-- A run is legacy iff skill_id IS NOT NULL; v2 iff skill_v2_id IS NOT NULL.
-- The existing patrol-activity funnel queries on skill_id keep working for
-- legacy; v2 runs are queried via skill_v2_id.
--
-- Flyway is DISABLED in prod — apply manually:  psql -f V67__skill_runs_v2.sql

ALTER TABLE skill_runs
  ADD COLUMN IF NOT EXISTS skill_v2_id BIGINT
    REFERENCES skills_v2(id) ON DELETE CASCADE;

-- skill_id was NOT NULL (legacy-only world). v2 runs leave it NULL, so relax it.
ALTER TABLE skill_runs
  ALTER COLUMN skill_id DROP NOT NULL;

-- Exactly one of the two skill references must be set.
ALTER TABLE skill_runs
  DROP CONSTRAINT IF EXISTS ck_skill_runs_one_owner;
ALTER TABLE skill_runs
  ADD CONSTRAINT ck_skill_runs_one_owner
    CHECK ((skill_id IS NOT NULL) <> (skill_v2_id IS NOT NULL));

CREATE INDEX IF NOT EXISTS ix_skill_runs_v2
  ON skill_runs (skill_v2_id, triggered_at DESC)
  WHERE skill_v2_id IS NOT NULL;

COMMENT ON COLUMN skill_runs.skill_v2_id IS
  'FK to skills_v2 for runs of the new Skill=1-pipeline model. Mutually '
  'exclusive with skill_id (legacy skill_documents). See V67.';
