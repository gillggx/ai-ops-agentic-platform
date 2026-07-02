-- V69 — Agent observability: episode + behavioural step records.
--
-- Spec: docs/MULTI_AGENT_OBSERVABILITY_SPEC.md §4.1.
-- One agent_episodes row per build (keyed by sidecar session_id); agent_steps
-- is the structured behavioural event stream (14-event taxonomy, emitted by
-- deterministic graph code — never by the LLM). The Supervisor tuning loop
-- queries these across builds; raw /tmp llm_calls traces stay as the debug
-- drill-down layer (trace_file cross-ref).
--
-- Retention (G4): steps 90 days, episodes kept (pruned by a later job; no
-- TTL enforced in schema).
--
-- Flyway is disabled in prod — apply via:
--   psql -h localhost -U aiops aiops_db -f V69__agent_episodes.sql

CREATE TABLE IF NOT EXISTS agent_episodes (
  id              BIGSERIAL PRIMARY KEY,
  episode_key     VARCHAR(64) UNIQUE NOT NULL,     -- sidecar session_id
  user_id         BIGINT,
  instruction     TEXT NOT NULL DEFAULT '',
  plan_json       TEXT,                            -- final phases (post user edits)
  self_assessment TEXT,                            -- JSON {ok, verifier_passed, ...}
  user_feedback   TEXT,                            -- JSON list [{stage, sentiment, text, ts}]
  divergence      BOOLEAN NOT NULL DEFAULT FALSE,  -- self ok BUT user reject (derived)
  cost_json       TEXT,                            -- per-agent token/cache/latency rollup
  status          VARCHAR(24) NOT NULL DEFAULT 'running',
  trace_file      TEXT,                            -- raw trace path (debug drill-down)
  started_at      TIMESTAMPTZ NOT NULL,
  finished_at     TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_steps (
  id            BIGSERIAL PRIMARY KEY,
  episode_id    BIGINT NOT NULL REFERENCES agent_episodes(id) ON DELETE CASCADE,
  agent         VARCHAR(16) NOT NULL,              -- planner|builder|repair|system
  phase_id      VARCHAR(16),
  event_type    VARCHAR(40) NOT NULL,              -- taxonomy, spec §4.2
  payload       TEXT,                              -- JSON, shape per event_type
  input_tokens  INT,
  output_tokens INT,
  cache_read    INT,
  latency_ms    INT,
  ts            TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_steps_episode ON agent_steps(episode_id);
CREATE INDEX IF NOT EXISTS idx_agent_steps_event   ON agent_steps(event_type, ts);
CREATE INDEX IF NOT EXISTS idx_agent_steps_agent   ON agent_steps(agent, ts);
CREATE INDEX IF NOT EXISTS idx_agent_episodes_started ON agent_episodes(started_at);
