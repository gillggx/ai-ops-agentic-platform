-- V71 — Memory provenance: which agent wrote each knowledge row.
-- Spec: "要分是誰的 memory" (2026-07-03). Realizes the AGENT_HARNESS_DESIGN §9
-- 3-agent × 6-class matrix on the READ surface (/agent-knowledge).
--
-- Before this, Planner (W1) and Repair (W3) fast-path writes both landed in
-- agent_knowledge with source='agent_fast' and were indistinguishable — the
-- only proxy was the active flag (W3 draft) or the title prefix, both fragile.
-- written_by is the durable, queryable provenance (CLAUDE.md: schema, not
-- case-signal heuristics). Builder memories live in block_doc_memos and are
-- attributable by table.
--
-- Values: planner | builder | repair | human. NULL = legacy (pre-V71) — kept
-- NULL rather than guessed, so the UI shows "未分類/legacy" honestly.
--
-- Flyway is DISABLED in prod (see memory feedback_flyway_disabled_in_prod) —
-- apply this manually on EC2:  psql -f V71__knowledge_written_by.sql

ALTER TABLE agent_knowledge ADD COLUMN IF NOT EXISTS written_by VARCHAR(12)
  CHECK (written_by IN ('planner', 'builder', 'repair', 'human'));

-- Backfill: human-authored rows (manual CRUD) are attributable to 'human'.
-- agent_fast rows stay NULL (legacy) — we don't retro-guess planner vs repair.
UPDATE agent_knowledge SET written_by = 'human'
  WHERE written_by IS NULL AND source = 'manual';
