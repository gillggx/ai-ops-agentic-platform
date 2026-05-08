-- V21 — Phase 9 Agent-Authored Rules: per-user notification inbox.
--
-- One row = one notification rendered for a specific user from a rule
-- firing. The bell-icon widget polls /api/v1/notifications/inbox and the
-- partial index keeps the unread query (the hot path) tiny regardless of
-- total inbox size.
--
-- payload shape (Phase 9-A baseline):
--   {
--     "title":   string,           // bell-tooltip preview
--     "body":    string,            // markdown allowed
--     "rule_id": int,               // back-link to auto_patrols
--     "run_id":  int,               // back-link to execution_logs
--     "chart_id": int | null        // optional embedded artifact
--   }
-- Future channel-specific fields (email subject, push deep-link, etc.)
-- can be added inside payload without schema migration.

CREATE TABLE notification_inbox (
  id          BIGSERIAL PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rule_id     INTEGER REFERENCES auto_patrols(id) ON DELETE SET NULL,
  payload     TEXT NOT NULL,                                       -- JSON; same convention as other Java jsonb-as-text columns
  read_at     TIMESTAMP WITH TIME ZONE,
  created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Hot path: bell-icon polls per-user unread. Partial index keeps it fast
-- as historical inbox grows.
CREATE INDEX ix_notification_inbox_user_unread
  ON notification_inbox (user_id, created_at DESC)
  WHERE read_at IS NULL;

-- General "show me recent 50" view for the dropdown.
CREATE INDEX ix_notification_inbox_user_recent
  ON notification_inbox (user_id, created_at DESC);

COMMENT ON TABLE notification_inbox IS
  'Phase 9 — per-user inbox written by NotificationDispatch when a personal-rule auto_patrols row fires. The bell-icon widget reads this; alarm-center reads alarm_definitions instead.';
