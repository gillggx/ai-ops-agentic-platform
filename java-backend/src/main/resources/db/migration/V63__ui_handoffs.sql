-- V63 — UI handoffs: cowork (MCP) proposes, the human reviews/confirms in the
-- real product GUI. A handoff is a short-lived record the MCP server creates; the
-- frontend resolves it (review a rule / confirm a dangerous action). The actual
-- mutation runs ONLY from the authenticated UI on resolve — the MCP layer never
-- executes delete/disable/activate itself.
--
-- kind:
--   review_rule       — launch the Rule Review page (whole-rule try-run) for target_ref(slug)
--   confirm_delete     — confirm + delete the skill-document target_ref(slug)
--   confirm_disable    — confirm + set status=draft (stop auto-running)
--   confirm_activate   — confirm + set status=stable (go live, materialize triggers)
--   view_detail        — open a read-only detail page (pipeline-view / rule page)
--
-- status: pending -> resolved | cancelled | expired   (TTL via expires_at)

CREATE TABLE ui_handoffs (
    id            VARCHAR(40)  PRIMARY KEY,                 -- non-guessable token, set by service
    kind          VARCHAR(40)  NOT NULL,
    target_ref    VARCHAR(180),                             -- skill slug or pipeline id
    action        VARCHAR(40),                              -- delete | disable | activate (confirm_* kinds)
    payload       TEXT,                                     -- JSON: impact/summary for the modal
    status        VARCHAR(20)  NOT NULL DEFAULT 'pending',
    requested_by  VARCHAR(80),                              -- service-principal hint (MCP/cowork)
    resolved_by   BIGINT,                                   -- users.id who resolved (no FK; audit-soft)
    resolved_at   timestamp with time zone,
    expires_at    timestamp with time zone NOT NULL,
    created_at    timestamp with time zone NOT NULL DEFAULT now(),
    updated_at    timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX ix_ui_handoffs_status     ON ui_handoffs(status);
CREATE INDEX ix_ui_handoffs_expires_at ON ui_handoffs(expires_at);
