-- V22 — Phase 11: Skill as Knowledge Document
--
-- Introduces the unifying `skill_documents` concept that wraps the existing
-- four trigger paths (auto_patrols / pipeline_auto_check_triggers /
-- personal-rule kind / chat-invokable skill_definitions). A skill carries:
--   - lifecycle stage (patrol | diagnose)
--   - trigger_config (jsonb) — discriminated union: system | user | schedule
--   - steps (jsonb) — ordered list of {text, pipeline_id, suggested_actions}
--
-- Per E8 (user decision 2026-05-09 開始開發): no migration of existing
-- trigger rows; clear non-shared-alarm patrols and ALL auto-check triggers
-- so users rebuild via the new Skill Library UI from scratch.

-- ── 1. Skill documents (the knowledge asset itself) ───────────────────
CREATE TABLE skill_documents (
  id              BIGSERIAL PRIMARY KEY,
  slug            VARCHAR(120) NOT NULL UNIQUE,
  title           VARCHAR(200) NOT NULL,
  version         VARCHAR(20)  NOT NULL DEFAULT '0.1',
  stage           VARCHAR(20)  NOT NULL,                  -- patrol | diagnose
  domain          VARCHAR(80)  NOT NULL DEFAULT '',
  description     TEXT         NOT NULL DEFAULT '',
  author_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  certified_by    VARCHAR(120),
  status          VARCHAR(20)  NOT NULL DEFAULT 'draft',  -- draft | stable

  -- JSON: discriminated union — see Phase 11 spec §2-1
  -- {"type":"system",   "event_type":"OCAP_TRIGGERED", "match_filter":{...}, "scope":"..."}
  -- {"type":"user",     "name":"CD_BIAS_DRIFT", "source":"...", "metric":"...", ...}
  -- {"type":"schedule", "cron":"0 */4 * * *", "timezone":"...", "skip":[...]}
  trigger_config  TEXT NOT NULL DEFAULT '{}',

  -- JSON array — ordered steps:
  -- [{ "id":"s1", "order":1, "text":"...", "ai_summary":"...",
  --    "pipeline_id":42, "confirmed":true,
  --    "suggested_actions":[{"id":"a1","title":"...","detail":"...",
  --                          "rationale":"...","confidence":"high"}] }]
  steps           TEXT NOT NULL DEFAULT '[]',

  -- JSON array — Phase 11-E (deferred); empty in 11-A
  test_cases      TEXT NOT NULL DEFAULT '[]',

  -- JSON — denormalized counters refreshed by SkillRunner / nightly job
  -- {"rating_avg":4.9, "runs_total":120, "runs_30d":47, "last_run_at":"..."}
  stats           TEXT NOT NULL DEFAULT '{}',

  created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
  updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX ix_skill_documents_stage  ON skill_documents(stage);
CREATE INDEX ix_skill_documents_status ON skill_documents(status);
CREATE INDEX ix_skill_documents_author ON skill_documents(author_user_id);

COMMENT ON COLUMN skill_documents.stage          IS 'Lifecycle: patrol (continuous watch) | diagnose (root-cause when triggered)';
COMMENT ON COLUMN skill_documents.trigger_config IS 'JSON discriminated union — system event / user-defined / cron schedule';
COMMENT ON COLUMN skill_documents.steps          IS 'JSON ordered array — each step has plain-language text + pipeline_id + author-written suggested_actions';

-- ── 2. Skill runs (per execution; sandbox flag distinguishes test from live) ─
CREATE TABLE skill_runs (
  id              BIGSERIAL PRIMARY KEY,
  skill_id        BIGINT NOT NULL REFERENCES skill_documents(id) ON DELETE CASCADE,
  triggered_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
  triggered_by    VARCHAR(40)  NOT NULL,                    -- event:OCAP_TRIGGERED | cron | user_test
  trigger_payload TEXT         NOT NULL DEFAULT '{}',
  is_test         BOOLEAN      NOT NULL DEFAULT FALSE,      -- sandbox: no notify, no stats
  status          VARCHAR(20)  NOT NULL DEFAULT 'running',  -- running | completed | failed | cancelled
  -- JSON: [{"step_id":"s1","pipeline_run_id":int,"status":"pass|fail",
  --         "value":"...","note":"...","duration_ms":int}]
  step_results    TEXT         NOT NULL DEFAULT '[]',
  duration_ms     INTEGER,
  finished_at     TIMESTAMP WITH TIME ZONE
);
CREATE INDEX ix_skill_runs_skill ON skill_runs(skill_id, triggered_at DESC);
CREATE INDEX ix_skill_runs_test  ON skill_runs(skill_id, is_test, triggered_at DESC);

COMMENT ON TABLE  skill_runs            IS 'One row = one execution of a skill (all N steps). is_test=true rows are sandbox dry-runs and excluded from stats.';

-- ── 3. Personal-rule fire audit (for "Test from past event" tab) ──────
-- Phase 9 didn't record per-fire history; Phase 11 adds it so the test
-- modal can replay past trigger payloads for trigger.type=user.
CREATE TABLE personal_rule_fires (
  id          BIGSERIAL PRIMARY KEY,
  patrol_id   BIGINT NOT NULL REFERENCES auto_patrols(id) ON DELETE CASCADE,
  fired_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
  payload     TEXT   NOT NULL DEFAULT '{}',   -- snapshot of metric value at fire time
  inbox_id    BIGINT REFERENCES notification_inbox(id) ON DELETE SET NULL
);
CREATE INDEX ix_personal_rule_fires_rule ON personal_rule_fires(patrol_id, fired_at DESC);

COMMENT ON TABLE personal_rule_fires IS 'Per-fire audit for personal/user-defined rules. Used by Phase 11 Skill test modal Past Event tab.';

-- ── 4. Skill ownership of triggers (skill is source of truth) ─────────
-- New `skill_doc_id` column distinct from the existing legacy `skill_id`
-- (which references skill_definitions). When set, the trigger row belongs
-- to a Skill Document; SkillRunner takes over from PipelineRunner for
-- those rows.
ALTER TABLE auto_patrols
  ADD COLUMN skill_doc_id BIGINT REFERENCES skill_documents(id) ON DELETE SET NULL;
CREATE INDEX ix_auto_patrols_skill_doc ON auto_patrols(skill_doc_id);

ALTER TABLE pipeline_auto_check_triggers
  ADD COLUMN skill_doc_id BIGINT REFERENCES skill_documents(id) ON DELETE SET NULL;
CREATE INDEX ix_auto_check_skill_doc ON pipeline_auto_check_triggers(skill_doc_id);

COMMENT ON COLUMN auto_patrols.skill_doc_id              IS 'Phase 11: when set, this patrol row was materialized from skill_documents.trigger_config (type=schedule|user); SkillRunner handles execution.';
COMMENT ON COLUMN pipeline_auto_check_triggers.skill_doc_id IS 'Phase 11: when set, this auto-check row was materialized from skill_documents.trigger_config (type=system).';

-- ── 5. Per E8: truncate existing trigger rows for clean rebuild ───────
-- shared_alarm auto_patrols (the alarm-generating patrol — pre-Phase-9
-- bread-and-butter) are KEPT IN PLACE — they're a different concept than
-- the new Skill abstraction (they GENERATE alarms; skills CONSUME them).
-- Personal/briefing/saved_query rules + all auto_check rows are cleared
-- per the "我想都重建" decision.
DELETE FROM auto_patrols WHERE kind != 'shared_alarm';
DELETE FROM pipeline_auto_check_triggers;
