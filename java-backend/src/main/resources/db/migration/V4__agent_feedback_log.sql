-- Phase 8 v1.3 P0 — Agent Evaluation Log
-- Records user 👍 / 👎 ratings on agent synthesis messages so we can
-- measure where the chat orchestrator helps / misleads. Used both for
-- offline review (admin dashboard) and as ground truth when tuning
-- skill descriptions / system prompts.

CREATE TABLE IF NOT EXISTS agent_feedback_log (
	id                BIGSERIAL PRIMARY KEY,
	session_id        VARCHAR(100) NOT NULL,
	user_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
	-- Nth synthesis event in the session (multi-turn → multiple ratings).
	message_idx       INTEGER NOT NULL,
	-- 1 = thumbs-up, -1 = thumbs-down. SMALLINT keeps room for future
	-- weighting without breaking the column type.
	rating            SMALLINT NOT NULL,
	-- Reason chip selected on 👎. NULL on 👍.
	-- Allowed values (string match in controller):
	--     "data_wrong" | "logic_wrong" | "chart_unclear"
	reason            VARCHAR(40),
	free_text         VARCHAR(500),
	-- Snapshot of the agent answer at rating time so post-hoc review
	-- doesn't need to re-fetch the session.
	contract_summary  TEXT,
	-- JSON array of {tool, mcp_name?} the LLM invoked for this answer.
	tools_used        TEXT,
	created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

	-- Dedup per (session, message, user). The controller upserts so a
	-- user can flip 👍 → 👎 (or vice versa) without flooding the log.
	CONSTRAINT ux_agent_feedback_log_session_message_user
		UNIQUE (session_id, message_idx, user_id)
);

CREATE INDEX IF NOT EXISTS ix_agent_feedback_log_session
	ON agent_feedback_log (session_id);

CREATE INDEX IF NOT EXISTS ix_agent_feedback_log_created_at
	ON agent_feedback_log (created_at DESC);

CREATE INDEX IF NOT EXISTS ix_agent_feedback_log_rating
	ON agent_feedback_log (rating)
	WHERE rating = -1;
