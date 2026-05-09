-- V24 — Phase 11 follow-up: unified TRIGGER → CONFIRM → CHECKLIST shape.
--
-- Per user decision 2026-05-09: auto_patrol and auto_check share the same
-- Skill data model. The flow is:
--
--   [STEP 0]   TRIGGER     when does the skill run? (event / cron / user metric)
--   [STEP 0.5] CONFIRM     optional gating pipeline → pass / fail
--                          fail = "false alarm, do not proceed" (no alarm row)
--   [STEP 1..N] CHECKLIST  diagnose pipelines, each pass/fail + suggested action
--
-- This migration:
--   1. Adds skill_documents.confirm_check (JSON) — nullable; null = no gate.
--   2. Seeds event_types catalog with the actual events the simulator + Java
--      backend emit, replacing the prototype's hardcoded fake list in
--      TriggerConfig.tsx (OCAP_TRIGGERED / FDC_VIOLATION / CHAMBER_MATCH_FAIL
--      / PM_DUE were placeholders, never registered anywhere).

-- ── 1. confirm_check column ─────────────────────────────────────────────
ALTER TABLE skill_documents
  ADD COLUMN confirm_check TEXT;     -- TEXT to match the existing TEXT-stored
                                     -- JSON convention on this table; nullable

COMMENT ON COLUMN skill_documents.confirm_check IS
  'Phase 11 v2: optional gating step. JSON shape: {"description":"...", "pipeline_id":<int>, "ai_summary":"...", "must_pass":true}. NULL = no confirmation required, run goes straight to checklist.';

-- ── 2. Event-type catalog seed (idempotent) ─────────────────────────────
-- These are the events actually produced by the simulator + Java backend.
-- IT_ADMIN can add more via /api/v1/event-types POST; this seed is the
-- safe baseline so the Skill author UI never shows an empty dropdown.
INSERT INTO event_types (name, description, source, is_active, attributes, diagnosis_skill_ids)
VALUES
  ('FDC_FAULT',
   'Fault Detection & Classification 判定 FAULT — SPC OOC 同時 ≥1 個 DC sensor 落在 warning band 外',
   'simulator', TRUE, '[]', '[]'),
  ('FDC_WARNING',
   'FDC 早期警告 — APC model 退化 OR ≥2 DC sensor 落在 early-warn band 外',
   'simulator', TRUE, '[]', '[]'),
  ('PM_START',
   '機台開始 Preventive Maintenance — tool_events.eventType=''PM_START''',
   'simulator', TRUE, '[]', '[]'),
  ('PM_DONE',
   '機台 PM 完成、DC drift / EC 重新校準完畢',
   'simulator', TRUE, '[]', '[]'),
  ('EQUIPMENT_HOLD',
   'MES 對某台機台發出 HOLD（process 中暫停，等工程師 ack）',
   'simulator', TRUE, '[]', '[]'),
  ('RECIPE_VERSION_BUMP',
   '某 recipe 自動 bump version + 微調 key params — parameter_audit_log source=''recipe_version_bump''',
   'simulator', TRUE, '[]', '[]'),
  ('APC_AUTO_CORRECT',
   'APC 自動把 active param 校正回 target — parameter_audit_log source=''apc_auto_correct''',
   'simulator', TRUE, '[]', '[]'),
  ('ENGINEER_OVERRIDE',
   '工程師手動改 APC 或 recipe 參數 — parameter_audit_log source LIKE ''engineer:*''',
   'simulator', TRUE, '[]', '[]'),
  ('MONITOR_LOT_RUN',
   'Monitor lot 跑完一個 step（每 ~20 production lots 插一個 monitor）— events.lot_type=''monitor''',
   'simulator', TRUE, '[]', '[]'),
  ('ALARM_RAISED',
   '系統升出一筆 alarm（auto_patrol 條件成立、或 force-event 觸發）',
   'simulator', TRUE, '[]', '[]')
ON CONFLICT (name) DO NOTHING;
