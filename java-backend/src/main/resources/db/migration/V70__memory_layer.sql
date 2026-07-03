-- V70 — Memory layer: memo_class dimension + Builder doc-memo review queue.
--
-- Spec: docs/MULTI_AGENT_MEMORY_SPEC.md §3.1 (design: AGENT_HARNESS_DESIGN §9/§10).
--
-- (a) agent_knowledge.memo_class — the 6-class taxonomy. EXISTING rows stay
--     NULL = legacy-unclassified: retrieval behaviour is untouched (zero
--     regression); all NEW agent-written rows must set it.
-- (b) block_doc_memos — "sticky notes next to the doc": Builder's learning
--     lands here as a REVIEW QUEUE (pending → promoted|discarded). Memos are
--     candidates, never the doc itself (single-source-of-truth preserved).
--
-- Flyway is disabled in prod — apply via:
--   psql -h localhost -U aiops aiops_db -f V70__memory_layer.sql

-- Fast-path writes stamp source='agent_fast'; the original CHECK only knew
-- manual|auto-promoted → extend it (caught by e2e: INSERT 23514).
ALTER TABLE agent_knowledge DROP CONSTRAINT IF EXISTS agent_knowledge_source_check;
ALTER TABLE agent_knowledge ADD CONSTRAINT agent_knowledge_source_check
  CHECK (source IN ('manual', 'auto-promoted', 'agent_fast'));

ALTER TABLE agent_knowledge ADD COLUMN IF NOT EXISTS memo_class VARCHAR(16)
  CHECK (memo_class IN ('domain','preference','presentation',
                        'correction','episodic','procedure'));

CREATE TABLE IF NOT EXISTS block_doc_memos (
  id              BIGSERIAL PRIMARY KEY,
  block_id        VARCHAR(100) NOT NULL,
  param           VARCHAR(100),
  memo            TEXT NOT NULL,              -- deterministic summary (E1)
  verdict_context TEXT,                       -- reject payload(s) JSON
  from_episode    VARCHAR(64),                -- episode_key provenance
  status          VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending|promoted|discarded
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_by     BIGINT,
  reviewed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_bdm_block_status ON block_doc_memos(block_id, status);
CREATE INDEX IF NOT EXISTS idx_bdm_created ON block_doc_memos(created_at);
