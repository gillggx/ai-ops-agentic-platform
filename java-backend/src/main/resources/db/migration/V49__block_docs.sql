-- V49 — 2026-05-19: Block docs as DB-stored Markdown + admin maintenance
--
-- Migrates per-block descriptions from baked seed.py literals to a real
-- DB table (block_docs) so admins can edit via UI and an auto-gen script
-- can populate first versions via LLM.
--
-- Format: YAML frontmatter (name + description) + Markdown body following
-- the skill SKILL.md convention.
--   ---
--   name: block_xxx
--   description: <1-line headline used for catalog brief>
--   ---
--   # block_xxx
--   ## When to invoke
--   ## Inputs
--   ## Outputs
--   ## Parameters
--   ## Examples
--
-- Per CLAUDE.md core principle #1 (MCP/Block description = single source
-- of truth): sidecar reads block_docs.markdown for catalog brief +
-- inspect_block_doc. seed.py description becomes legacy / migration source.

CREATE TABLE block_docs (
    id              BIGSERIAL PRIMARY KEY,
    block_id        VARCHAR(100) NOT NULL,
    block_version   VARCHAR(20)  NOT NULL DEFAULT '1.0.0',

    -- Full markdown (YAML frontmatter + body)
    markdown        TEXT         NOT NULL,

    -- Parsed sections cache (avoid re-parsing on every read).
    -- Shape: {"description": "...", "when_to_invoke": "...",
    --         "inputs": "...", "outputs": "...",
    --         "parameters": "...", "examples": "..."}
    sections        JSONB,

    -- Provenance:
    --   true  = LLM-generated first version, has NOT been admin-reviewed
    --   false = admin manually edited (skip re-generation by default)
    auto_generated  BOOLEAN      NOT NULL DEFAULT TRUE,

    last_edited_by  VARCHAR(120),                         -- user email/login
    last_edited_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT block_docs_uniq UNIQUE (block_id, block_version)
);

CREATE INDEX idx_block_docs_block_id ON block_docs (block_id);
CREATE INDEX idx_block_docs_auto_generated ON block_docs (auto_generated);

COMMENT ON TABLE block_docs IS
  'Rich Markdown documentation per pipeline-builder block. Single source of '
  'truth for catalog brief + inspect_block_doc + admin-facing BlockDocsDrawer.';
COMMENT ON COLUMN block_docs.markdown IS
  'YAML frontmatter (name + description) + Markdown body. See V49 migration header.';
COMMENT ON COLUMN block_docs.sections IS
  'Parsed sections cache, populated by service on write. Read path uses this when present.';
COMMENT ON COLUMN block_docs.auto_generated IS
  'TRUE = LLM-generated initial, NOT admin-reviewed. FALSE = admin manual edit. '
  'Regenerate script skips auto_generated=FALSE rows by default.';
