-- V75 — 記憶治理 (W2 波, 2026-07-06): C1 索引 + C2 生命週期 + 提案案情敘事。
--
-- ⚠ Flyway is DISABLED in prod — apply manually:
--   psql aiops_db -f V75__memory_governance.sql
--
-- Policy constants live in code (SupervisorCurationService / sidecar):
--   preference 零召回 180d → PRUNE 提案; domain/procedure 年審 (review_at);
--   correction draft 30d 未轉正 → archived; episodic 90d → stale.

-- ── agent_knowledge: C1 subject index + C2 lifecycle ──────────────────
ALTER TABLE agent_knowledge ADD COLUMN IF NOT EXISTS status VARCHAR(12) NOT NULL DEFAULT 'active';
ALTER TABLE agent_knowledge DROP CONSTRAINT IF EXISTS agent_knowledge_status_chk;
ALTER TABLE agent_knowledge ADD CONSTRAINT agent_knowledge_status_chk
  CHECK (status IN ('draft','active','stale','archived'));

ALTER TABLE agent_knowledge ADD COLUMN IF NOT EXISTS subject_kind VARCHAR(16);
ALTER TABLE agent_knowledge DROP CONSTRAINT IF EXISTS agent_knowledge_subject_kind_chk;
ALTER TABLE agent_knowledge ADD CONSTRAINT agent_knowledge_subject_kind_chk
  CHECK (subject_kind IS NULL OR subject_kind IN ('block','tool','skill','request_class','general'));
ALTER TABLE agent_knowledge ADD COLUMN IF NOT EXISTS subject_id VARCHAR(80);

ALTER TABLE agent_knowledge ADD COLUMN IF NOT EXISTS review_at   TIMESTAMPTZ;
ALTER TABLE agent_knowledge ADD COLUMN IF NOT EXISTS expires_at  TIMESTAMPTZ;
ALTER TABLE agent_knowledge ADD COLUMN IF NOT EXISTS superseded_by BIGINT;

-- Backfill: W3 drafts today are stored as active=false + written_by='repair'
-- + memo_class='correction'; everything else inactive was a human disable.
UPDATE agent_knowledge SET status = 'draft'
 WHERE active = false AND written_by = 'repair' AND memo_class = 'correction'
   AND status = 'active';
UPDATE agent_knowledge SET status = 'archived'
 WHERE active = false AND status = 'active';

CREATE INDEX IF NOT EXISTS idx_ak_status  ON agent_knowledge(status);
CREATE INDEX IF NOT EXISTS idx_ak_subject ON agent_knowledge(subject_kind, subject_id);

-- ── supervisor_actions: cfg/issue 型 + 案情敘事 + 簽核/落地/驗證生命週期 ──
ALTER TABLE supervisor_actions DROP CONSTRAINT IF EXISTS supervisor_actions_action_type_check;
ALTER TABLE supervisor_actions ADD CONSTRAINT supervisor_actions_action_type_check
  CHECK (action_type IN ('MERGE','CORRECT','PRUNE','PROMOTE','DOC_REVISE','CFG','ISSUE'));

-- 案情四段 {happened, observed, subject:{kind,id,label}, action} — 舊列為 NULL,
-- 前端 fallback 舊三段式渲染。
ALTER TABLE supervisor_actions ADD COLUMN IF NOT EXISTS narrative     JSONB;
ALTER TABLE supervisor_actions ADD COLUMN IF NOT EXISTS reject_reason TEXT;
ALTER TABLE supervisor_actions ADD COLUMN IF NOT EXISTS landed_at     TIMESTAMPTZ;
ALTER TABLE supervisor_actions ADD COLUMN IF NOT EXISTS landed_by     VARCHAR(80);
ALTER TABLE supervisor_actions ADD COLUMN IF NOT EXISTS verify_result TEXT;
ALTER TABLE supervisor_actions ADD COLUMN IF NOT EXISTS verify_at     TIMESTAMPTZ;
ALTER TABLE supervisor_actions ADD COLUMN IF NOT EXISTS superseded_by BIGINT;

-- ── S3: LLM provider 品質 daily rollup（空回應率）────────────────────
CREATE TABLE IF NOT EXISTS llm_provider_daily (
  day           DATE NOT NULL,
  model         VARCHAR(80) NOT NULL,
  calls         INT NOT NULL DEFAULT 0,
  empty_calls   INT NOT NULL DEFAULT 0,   -- finish=stop 且 content 全空
  error_calls   INT NOT NULL DEFAULT 0,   -- finish_reason='error' / exception
  input_tokens  BIGINT NOT NULL DEFAULT 0,
  output_tokens BIGINT NOT NULL DEFAULT 0,
  cache_read    BIGINT NOT NULL DEFAULT 0,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (day, model)
);
