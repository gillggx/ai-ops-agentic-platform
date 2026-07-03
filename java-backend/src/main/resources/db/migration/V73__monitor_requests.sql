-- V73 — Monitor requesters (Phase 6, option A: system self-health).
-- Spec: 2026-07-04 收尾 spec. The monitor watches OUR agents' own episode
-- metrics (doc gaps, divergence, repair handovers) — NOT fab data (that is
-- auto-patrol's job) — and files improvement REQUESTS. Human approves before
-- anything drives the Planner (same human-in-the-loop as supervisor curation).
--
-- Flyway is disabled in prod — apply via:
--   psql aiops_db -f V73__monitor_requests.sql

CREATE TABLE IF NOT EXISTS monitor_requests (
  id                    BIGSERIAL PRIMARY KEY,
  kind                  VARCHAR(20) NOT NULL
                        CHECK (kind IN ('DOC_GAP','DIVERGENCE','REPAIR_HANDOVER')),
  -- what the finding is about (block id for DOC_GAP, metric key otherwise)
  subject               VARCHAR(120) NOT NULL,
  -- measured evidence JSON: {metric, value, threshold, window_days, samples[]}
  evidence              TEXT NOT NULL,
  -- the prepared instruction a human can launch at the Planner after approval
  suggested_instruction TEXT,
  status                VARCHAR(12) NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open','approved','dismissed')),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_by           BIGINT,
  reviewed_at           TIMESTAMPTZ
);

-- Dedup guard: one OPEN request per (kind, subject).
CREATE UNIQUE INDEX IF NOT EXISTS uq_mr_open
  ON monitor_requests(kind, subject) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_mr_status ON monitor_requests(status);
