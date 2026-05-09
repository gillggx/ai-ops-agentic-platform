-- V23 — Phase 12 Simulator Enhancement
--
-- Alarm disposition / ack history. Phase 11 Skill needs to query "OOC ack
-- rate" / "shifts with high hold rate" / "disposition latency" — none of
-- these were possible until alarms recorded who/when/what happened after
-- they fired. New columns are nullable; legacy alarms display "—" in the
-- UI for missing fields.
--
-- (parameter_audit_log lives in MongoDB on the simulator side — Phase 12
-- skills query it via the simulator API, not Postgres. See
-- ontology_simulator/app/services/audit_service.py.)

ALTER TABLE alarms
  ADD COLUMN acked_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN acked_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN disposition VARCHAR(20),                  -- release | hold | scrap | rerun
  ADD COLUMN disposition_reason TEXT,
  ADD COLUMN disposed_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN disposed_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX ix_alarms_acked_at ON alarms(acked_at) WHERE acked_at IS NOT NULL;
CREATE INDEX ix_alarms_disposition ON alarms(disposition) WHERE disposition IS NOT NULL;

COMMENT ON COLUMN alarms.disposition IS
  'Phase 12: end-state of the alarm — release | hold | scrap | rerun. NULL means open / not yet disposed.';
COMMENT ON COLUMN alarms.acked_at IS
  'Phase 12: when an engineer first acknowledged the alarm. NULL means not yet seen.';
