-- V26 — Phase 11 v6: Skill-only authoring cleanup.
--
-- The Skill Document is now the single authoring entry point. Direct
-- Pipeline Builder access is hidden in the UI; the legacy 3-step wizard
-- and Triggers Overview Create CTAs are gone (see project_v6_to_remove_list).
--
-- This migration deletes orphan rows that were created via the legacy
-- entry points and have no Skill owner. The intent is a clean slate so
-- the Skill Library lists exactly the playbooks each tool is responsible
-- for.
--
-- Idempotent — safe to re-run. Free-standing pipelines (parent_skill_doc_id
-- IS NULL) and orphan triggers (skill_doc_id IS NULL) get dropped.
--
-- skill_definitions / skill_runs / alarms are PRESERVED (chat-skill path
-- + run history + ack stats keep working).

-- ── Drop orphan auto_check triggers first (FK to pb_pipelines) ────────
DELETE FROM pipeline_auto_check_triggers WHERE skill_doc_id IS NULL;

-- ── Drop orphan auto_patrols ─────────────────────────────────────────
DELETE FROM auto_patrols WHERE skill_doc_id IS NULL;

-- ── Drop free-standing pipelines (no Skill owner) ────────────────────
-- Skill-bound pipelines (parent_skill_doc_id NOT NULL) survive.
DELETE FROM pb_pipelines WHERE parent_skill_doc_id IS NULL;

-- Sanity counters into Postgres NOTICE for migration log.
DO $$
DECLARE
  rem_pipes  INTEGER;
  rem_patrol INTEGER;
  rem_check  INTEGER;
BEGIN
  SELECT COUNT(*) INTO rem_pipes  FROM pb_pipelines;
  SELECT COUNT(*) INTO rem_patrol FROM auto_patrols;
  SELECT COUNT(*) INTO rem_check  FROM pipeline_auto_check_triggers;
  RAISE NOTICE 'V26 cleanup: % skill-bound pipelines, % patrols, % auto-check triggers remain',
    rem_pipes, rem_patrol, rem_check;
END
$$;
