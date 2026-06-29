-- V68: drop the legacy skill_documents model (data + schema).
--
-- Final phase of the legacy-skill sunset (2026-06-29). The skill_documents
-- multi-step skill model is replaced entirely by skills_v2 (1 skill = 1
-- pipeline). All legacy CODE was removed first; this drops the schema.
--
-- ⚠️ IRREVERSIBLE. Flyway is DISABLED in prod — apply by hand:
--    psql -f V68__legacy_skill_documents_drop.sql
-- Deploy the code that removed SkillRunEntity.skillId + SkillDocumentEntity
-- FIRST; this migration drops the columns/tables they mapped.

-- 1. Delete legacy skill_runs history (per user: 砍, 歷史一樣砍). v2 runs
--    (skill_v2_id set) are kept.
DELETE FROM skill_runs WHERE skill_id IS NOT NULL;

-- 2. skill_runs: strip the legacy skill_id column + its constraints. The
--    remaining rows are all v2, so skill_v2_id becomes mandatory.
ALTER TABLE skill_runs DROP CONSTRAINT IF EXISTS ck_skill_runs_one_owner;
ALTER TABLE skill_runs DROP CONSTRAINT IF EXISTS skill_runs_skill_id_fkey;
ALTER TABLE skill_runs DROP COLUMN IF EXISTS skill_id;
ALTER TABLE skill_runs ALTER COLUMN skill_v2_id SET NOT NULL;

-- 3. Drop the FK references to skill_documents from tables we KEEP. The
--    columns are left in place (now vestigial, nullable) so the JPA entities
--    that still map them don't need a code change — only the FK goes, which
--    is what blocks DROP TABLE skill_documents.
--    auto_patrols is KEPT (separate, still-wired user-rules/patrol mechanism —
--    NOT part of this sunset); only its FK to skill_documents goes.
ALTER TABLE pb_pipelines
  DROP CONSTRAINT IF EXISTS pb_pipelines_parent_skill_doc_id_fkey;
ALTER TABLE pipeline_auto_check_triggers
  DROP CONSTRAINT IF EXISTS pipeline_auto_check_triggers_skill_doc_id_fkey;
ALTER TABLE auto_patrols
  DROP CONSTRAINT IF EXISTS auto_patrols_skill_doc_id_fkey;

-- 4. Drop the legacy skill_documents tables.
--    skill_stages = the legacy multi-step stage table (entity already gone in
--    the V65 sunset). skill_documents itself.
DROP TABLE IF EXISTS skill_stages CASCADE;
DROP TABLE IF EXISTS skill_documents CASCADE;

-- KEPT (NOT part of this sunset):
--   - auto_patrols — separate user-rules/patrol mechanism, still wired
--   - skill_definitions — separate registry (internal skill lookup + monitor)
