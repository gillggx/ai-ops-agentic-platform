-- V72 — Supervisor curation (Phase 5): proposal queue + audit trail.
-- Spec: 2026-07-04 收尾 spec (Phase 5). Design: AGENT_HARNESS_DESIGN §11.
--
-- HARD RULE (pollution incident 2026-07-03): the Supervisor NEVER writes
-- memories directly. Every MERGE / CORRECT / PRUNE / PROMOTE / DOC_REVISE is a
-- PROPOSAL row here; a human approves in /supervisor before anything commits.
--
-- Flyway is disabled in prod — apply via:
--   psql aiops_db -f V72__supervisor_actions.sql

CREATE TABLE IF NOT EXISTS supervisor_actions (
  id           BIGSERIAL PRIMARY KEY,
  action_type  VARCHAR(16) NOT NULL
               CHECK (action_type IN ('MERGE','CORRECT','PRUNE','PROMOTE','DOC_REVISE')),
  -- what the action targets: agent_knowledge ids / block_doc_memo ids (JSON array)
  target_ids   TEXT,
  -- the full structured proposal (per-type shape, see SupervisorCurationService)
  proposal     TEXT NOT NULL,
  -- one-line human-readable rationale from the proposer LLM
  rationale    TEXT,
  status       VARCHAR(12) NOT NULL DEFAULT 'proposed'
               CHECK (status IN ('proposed','approved','rejected')),
  -- provenance of the proposing run (model, run id, counts)
  proposer_meta TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_by  BIGINT,
  reviewed_at  TIMESTAMPTZ,
  -- what actually happened on approve (created row id, etc.)
  commit_result TEXT
);

CREATE INDEX IF NOT EXISTS idx_sa_status ON supervisor_actions(status);
CREATE INDEX IF NOT EXISTS idx_sa_created ON supervisor_actions(created_at);

-- Supervisor becomes a legal writer + source once a human approves a PROMOTE.
ALTER TABLE agent_knowledge DROP CONSTRAINT IF EXISTS agent_knowledge_written_by_check;
ALTER TABLE agent_knowledge ADD CONSTRAINT agent_knowledge_written_by_check
  CHECK (written_by IN ('planner','builder','repair','human','supervisor'));

ALTER TABLE agent_knowledge DROP CONSTRAINT IF EXISTS agent_knowledge_source_check;
ALTER TABLE agent_knowledge ADD CONSTRAINT agent_knowledge_source_check
  CHECK (source IN ('manual','auto-promoted','agent_fast','supervisor'));

-- Manual-psql gotcha: applying as postgres superuser leaves the table owned by
-- postgres → the app role gets "permission denied" (42501). Match existing tables.
ALTER TABLE supervisor_actions OWNER TO aiops;
ALTER SEQUENCE supervisor_actions_id_seq OWNER TO aiops;
