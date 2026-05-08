-- V20 — Phase 9 Agent-Authored Rules: extend auto_patrols for personal rules.
--
-- The existing schema covers the shared "alarm-generating patrol" model.
-- Phase 9 adds a per-user "rule" model (briefings / weekly reports / saved
-- queries) that reuses the same scheduler + executor stack but dispatches
-- to a per-user notification inbox instead of generating an alarm row.
--
-- Design choice: extend `auto_patrols` rather than creating a new table.
-- Owner is the existing `created_by` column. Discrimination is via the
-- new `kind` column. Defaulting `kind='shared_alarm'` keeps existing rows
-- behaving exactly as before.

ALTER TABLE auto_patrols
  ADD COLUMN kind VARCHAR(40) NOT NULL DEFAULT 'shared_alarm',
  ADD COLUMN notification_channels TEXT,            -- JSON: [{"type":"in_app"}]
  ADD COLUMN notification_template TEXT,            -- "上週 OOC top-5: {top_tools}"
  ADD COLUMN last_dispatched_at TIMESTAMP WITH TIME ZONE;

-- Index for the scheduler's "active personal rules to fire" lookup.
CREATE INDEX ix_auto_patrols_owner_active
  ON auto_patrols (created_by, is_active)
  WHERE kind != 'shared_alarm';

COMMENT ON COLUMN auto_patrols.kind IS
  'shared_alarm (existing) | personal_briefing | weekly_report | saved_query | watch_rule';
COMMENT ON COLUMN auto_patrols.notification_channels IS
  'JSON array — Phase 9-A only honours [{"type":"in_app"}]; email/push/slack come in 9-D.';
COMMENT ON COLUMN auto_patrols.notification_template IS
  'Template with {placeholders} resolved against pipeline run output before dispatch.';
COMMENT ON COLUMN auto_patrols.last_dispatched_at IS
  'Updated by NotificationDispatch service after a successful inbox write. Used for dedupe + UI staleness display.';
