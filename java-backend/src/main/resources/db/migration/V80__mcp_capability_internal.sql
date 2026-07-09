-- V80: MCP capability — internal (Coordinator) exposure axis (Phase 6).
--
-- Phase 2 gave every capability a public/private toggle for EXTERNAL cowork.
-- Phase 6 adds a SECOND, independent axis: is_internal = "grant this capability
-- to OUR internal chat agent (the Coordinator)". Default FALSE — the Coordinator
-- keeps its curated core tools unless IT admin explicitly grants a registry
-- capability. Only Coordinator-appropriate capabilities are offerable 對內
-- (query / run-ready-made-skill); pipeline-construction primitives stay
-- Builder-only so the Coordinator can't bypass Planner & Builder. That
-- eligibility is computed in the service (not stored) from the capability's
-- nature, so it can't drift out of a DB column.

ALTER TABLE mcp_capability_settings
    ADD COLUMN IF NOT EXISTS is_internal BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN mcp_capability_settings.is_internal IS
  'Granted to the internal Coordinator agent (Phase 6). Default false; only '
  'coordinator-eligible capabilities may be set true (eligibility computed in '
  'McpCapabilityService, not stored).';
