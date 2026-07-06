-- V76 (2026-07-06): agent-activity case metadata — 觸發來源。
-- ⚠ Flyway disabled in prod — apply via manual psql -f.
-- chat / builder / skill / schedule；NULL = 舊 episode（未記錄）。
ALTER TABLE agent_episodes ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(16);
