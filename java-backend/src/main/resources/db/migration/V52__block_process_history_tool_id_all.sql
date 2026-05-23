-- V52 — 2026-05-23: document tool_id='ALL' sentinel on block_process_history.
--
-- Background:
--   Agent's spc-ooc trace showed correct mental model "leave tool_id empty
--   = all equipment" — but MCP /api/v1/process/info rejects when all three
--   of tool/lot/step are missing. Agent then defaulted to step='STEP_001'
--   which silently narrowed the "top 5 OOC tools" query to STEP_001 only.
--
--   Z-lite fix (ontology_simulator route change, same commit): tool_id
--   accepts literal 'ALL' as wildcard sentinel. Validation still counts it
--   as "provided" (satisfies the at-least-one rule), but the filter is
--   skipped so query returns all-tool events for the time window.
--
--   Only tool_id has this sentinel — lot_id / step keep literal-only
--   semantics (per user spec 2026-05-23). Specific multi-tool queries
--   (e.g. EQP-01,02,03) should pass tool_id='ALL' upstream then chain
--   block_filter(column='toolID', operator='in', value=[...]) downstream.
--
-- Idempotent via NOT LIKE.

UPDATE block_docs
SET markdown = replace(
        markdown,
        '| `tool_id` | string | 三選一必填 | - | - | Single machine ID (e.g. ''EQP-01''). MCP accepts only single string, not comma list or array. For multi-tool queries, leave empty and filter downstream with block_filter(operator=''in''). |',
        '| `tool_id` | string | 三選一必填 | - | - | Single machine ID (e.g. ''EQP-01''). 特殊值 `''ALL''` = 全機台不過濾（仍算「三選一」之一，可單獨給）. MCP 單值字串、不接 comma list / array; 若要篩特定多台 → 傳 ''ALL'' + downstream `block_filter(column=''toolID'', operator=''in'', value=[...])`. |'
    ),
    updated_at = now()
WHERE block_id = 'block_process_history'
  AND markdown NOT LIKE '%特殊值 `''ALL''` = 全機台不過濾%';
