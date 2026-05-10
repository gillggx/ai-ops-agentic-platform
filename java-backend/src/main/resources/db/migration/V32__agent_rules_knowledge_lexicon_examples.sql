-- V32 — Agent Rules & Knowledge surface (4 user-owned tables)
--
-- Background (2026-05-11):
--   User wanted a maintenance UI to teach the agent "this domain's iron
--   rules / domain facts / jargon / style examples". Mockup at
--   /Users/gill/Downloads/agent-rules-standalone shows 4 tabs (Rules,
--   Knowledge, Lexicon, Examples).
--
-- Naming choice: existing /api/v1/rules + auto_patrols already use the
-- word "rules" for scheduled-pipeline rules. To avoid clash we use
-- "directives" for the prompt-injection version + new namespace
-- /api/v1/agent-{directives,knowledge,lexicon,examples}.
--
-- Embedding dim = 1024 to match existing agent_experience_memory.

-- ── Directives — always-on prompt rules (Phase 1) ────────────────────
CREATE TABLE agent_directives (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- scope: global = applies always; skill:<slug> = only when user is
    -- using that skill; tool:<id> = only when message mentions that tool;
    -- recipe:<id> = only when message mentions that recipe.
    scope_type    VARCHAR(20) NOT NULL CHECK (scope_type IN ('global','skill','tool','recipe')),
    scope_value   VARCHAR(120),
    title         VARCHAR(200) NOT NULL,
    body          TEXT NOT NULL,
    priority      VARCHAR(10) NOT NULL DEFAULT 'med' CHECK (priority IN ('high','med','low')),
    active        BOOLEAN NOT NULL DEFAULT true,
    source        VARCHAR(20) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','auto-promoted')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_agent_directives_user_scope ON agent_directives(user_id, scope_type, scope_value, active);

-- Audit log for "directive fired in conversation X" — drives the
-- "Recent triggers" UI panel + uses count.
CREATE TABLE agent_directive_fires (
    id            BIGSERIAL PRIMARY KEY,
    directive_id  BIGINT NOT NULL REFERENCES agent_directives(id) ON DELETE CASCADE,
    fired_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_id    VARCHAR(64),
    context       VARCHAR(200)
);
CREATE INDEX ix_directive_fires_directive ON agent_directive_fires(directive_id, fired_at DESC);

-- ── Lexicon — jargon → standard term (Phase 1) ───────────────────────
CREATE TABLE agent_lexicon (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    term         VARCHAR(80)  NOT NULL,
    standard     VARCHAR(120) NOT NULL,
    note         TEXT,
    uses         INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, term)
);
CREATE INDEX ix_agent_lexicon_user ON agent_lexicon(user_id);

-- ── Knowledge — RAG-retrievable domain facts (Phase 2) ───────────────
CREATE TABLE agent_knowledge (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope_type    VARCHAR(20) NOT NULL CHECK (scope_type IN ('global','skill','tool','recipe')),
    scope_value   VARCHAR(120),
    title         VARCHAR(200) NOT NULL,
    body          TEXT NOT NULL,
    priority      VARCHAR(10) NOT NULL DEFAULT 'med' CHECK (priority IN ('high','med','low')),
    active        BOOLEAN NOT NULL DEFAULT true,
    source        VARCHAR(20) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','auto-promoted')),
    embedding     vector(1024),
    uses          INT NOT NULL DEFAULT 0,
    last_used_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_agent_knowledge_user_scope ON agent_knowledge(user_id, scope_type, scope_value, active);
-- ivfflat index needs at least 1 row before it works well, but creating it
-- early is fine — pgvector handles empty tables.
CREATE INDEX ix_agent_knowledge_embedding ON agent_knowledge USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ── Examples — few-shot pairs (Phase 2) ──────────────────────────────
CREATE TABLE agent_examples (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope_type    VARCHAR(20) NOT NULL CHECK (scope_type IN ('global','skill','tool','recipe')),
    scope_value   VARCHAR(120),
    title         VARCHAR(200) NOT NULL,
    input_text    TEXT NOT NULL,
    output_text   TEXT NOT NULL,
    embedding     vector(1024),
    uses          INT NOT NULL DEFAULT 0,
    last_used_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_agent_examples_user_scope ON agent_examples(user_id, scope_type, scope_value);
CREATE INDEX ix_agent_examples_embedding ON agent_examples USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
