-- V79: MCP capability exposure registry (Phase 1 of the MCP-registry feature).
--
-- An OVERLAY on the code-defined built-in tools (from the MCP server's
-- /capabilities manifest), DB domain skills (skills_v2), and external MCPs
-- (mcp_definitions). This table stores only the per-capability EXPOSURE
-- override that IT admin sets — a row means "admin decided this capability's
-- public/private". Absence of a row = default, which per spec decision 4 is
-- "current exposure stays open" → treated as public=true. So the catalog
-- enumerates all capabilities and LEFT JOINs this table; no row → public.
--
-- `kind` mirrors the registry taxonomy (spec decision 3): built-in agent tool,
-- domain analysis skill, or external-sourced. `is_write` is NOT stored here —
-- it is intrinsic to the capability (built-in: from the manifest; skill
-- lifecycle ops / proposals: derived) and drives the human-confirm requirement
-- (spec decision 5), which is orthogonal to exposure.

CREATE TABLE IF NOT EXISTS mcp_capability_settings (
    id             BIGSERIAL     PRIMARY KEY,
    capability_key VARCHAR(200)  NOT NULL UNIQUE,   -- tool name / skill slug / mcp name
    kind           VARCHAR(20)   NOT NULL,          -- 'builtin' | 'domain_skill' | 'external'
    is_public      BOOLEAN       NOT NULL DEFAULT TRUE,   -- exposed to external cowork
    updated_by     VARCHAR(120),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mcp_cap_kind ON mcp_capability_settings(kind);

COMMENT ON TABLE mcp_capability_settings IS
  'Per-capability public/private exposure override for the MCP capability '
  'registry. Absence of a row = default public (current exposure preserved). '
  'IT-admin toggles create/update rows.';
