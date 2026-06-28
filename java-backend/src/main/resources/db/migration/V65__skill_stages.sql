-- V65 — skill_stages: per-stage trigger / prose / compiled-rules / pipeline
-- binding for the 3-stage Skill Studio (DETECT → DIAGNOSE → RECOVER).
--
-- New side-by-side table; skill_documents stays untouched. Migration of
-- existing skills' steps[] into a synthetic 'diagnose' row is deferred to
-- a one-off backfill script after Phase 2 ships.
--
-- Each row = one stage of one skill. Unique (skill_doc_id, kind) guarantees
-- exactly one detect / diagnose / recover per skill.
--
-- Why a new table (vs adding columns to skill_documents):
--   - 3-stage prose / compiled_rules / trigger_config triple every wide column
--   - per-stage versioning is cleaner with own activated_at / activated_by
--   - DIAGNOSE's pipeline_id FK was previously buried inside skill_documents.steps JSON
--
-- Flyway disabled in prod (per feedback_flyway_disabled_in_prod) — apply via:
--   psql -h localhost -U aiops aiops_db -f V65__skill_stages.sql

CREATE TABLE IF NOT EXISTS skill_stages (
  id              BIGSERIAL PRIMARY KEY,
  skill_doc_id    BIGINT NOT NULL REFERENCES skill_documents(id) ON DELETE CASCADE,
  kind            TEXT NOT NULL CHECK (kind IN ('detect', 'diagnose', 'recover')),
  trigger_config  TEXT NOT NULL DEFAULT '{}',
  prose           TEXT NOT NULL DEFAULT '',
  compiled_rules  TEXT NOT NULL DEFAULT '[]',
  pipeline_id     BIGINT REFERENCES pb_pipelines(id) ON DELETE SET NULL,
  status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'stable')),
  version         TEXT NOT NULL DEFAULT '0.1',
  activated_at    TIMESTAMP WITH TIME ZONE,
  activated_by    BIGINT,
  created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  UNIQUE (skill_doc_id, kind)
);

CREATE INDEX IF NOT EXISTS ix_skill_stages_skill_doc_id  ON skill_stages(skill_doc_id);
CREATE INDEX IF NOT EXISTS ix_skill_stages_pipeline_id   ON skill_stages(pipeline_id);
CREATE INDEX IF NOT EXISTS ix_skill_stages_kind_status   ON skill_stages(kind, status);

COMMENT ON TABLE  skill_stages IS
  '3-stage Skill Studio: per-skill, per-stage (detect/diagnose/recover) trigger + NL prose + AI-compiled rules + (diagnose only) pipeline binding.';
COMMENT ON COLUMN skill_stages.prose IS
  'User-authored natural-language description of this stage. Source of truth for the compile step.';
COMMENT ON COLUMN skill_stages.compiled_rules IS
  'JSON array: AI-compiled rules executed by code. Frozen on Activate. Shape varies per kind: detect = [{when,for,if,then}], diagnose = [{idx,dim,title,operator,threshold}], recover = [{id,pattern,action,safety}].';
COMMENT ON COLUMN skill_stages.pipeline_id IS
  'DIAGNOSE only: which pb_pipeline implements this stage. NULL for detect (no pipeline; scheduler runs it) and recover (action dispatcher, not a pipeline).';
COMMENT ON COLUMN skill_stages.status IS
  'draft = prose may be edited but rules are not executed by scheduler. stable = activated, frozen, rules dispatched by detect / diagnose / recover schedulers.';
