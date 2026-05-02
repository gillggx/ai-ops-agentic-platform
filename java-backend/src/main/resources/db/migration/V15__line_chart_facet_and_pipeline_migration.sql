-- V15 — Add facet param to block_line_chart + migrate active pipelines off
-- block_chart, then mark block_chart deprecated.
--
-- Background (2026-05-02):
--   Stage 5 of the 18-block charting overhaul was originally skipped because
--   2 active SPC pipelines depended on block_chart's `facet` feature
--   (one node → N panels). We now lifted facet into the dedicated chart blocks
--   via `_chart_facet.maybe_facet()` so block_line_chart can replace
--   block_chart(chart_type='line', facet=...) directly.
--
-- This migration:
--   1. UPDATE block_line_chart description + param_schema to include facet
--   2. UPDATE pipelines 34 + 39 — swap their block_chart node for block_line_chart
--   3. UPDATE block_chart status → 'deprecated' so it disappears from the
--      sidebar block library (frontend filters by status='production')
--
-- Audit (Issue #1 long-term scope):
--   total active pipelines      : 5
--   using block_chart           : 1 (id=39, single node 'n3')
--   using facet                 : 2 (ids 34 + 39, both block_chart with facet=chart_name)
--   using chart_type='area'     : 0   ← no replacement needed, kill area outright
--
-- After this migration:
--   - 2/2 active pipelines still using block_chart should be 0 (expect: prod
--     audit re-runs as 0 after this).
--   - block_chart row stays in pb_blocks but with status='deprecated' so any
--     legacy pipeline_runs reference still resolves.

-- ── 1. Add facet + SPC shorthand params to block_line_chart ──────────────
UPDATE pb_blocks
SET param_schema = $ps${
  "type": "object",
  "required": ["x", "y"],
  "properties": {
    "x": {"type": "string"},
    "y": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
    "y_secondary": {"type": "array", "items": {"type": "string"}},
    "series_field": {"type": "string"},
    "rules": {"type": "array"},
    "highlight_field": {"type": "string"},
    "highlight_eq": {},
    "ucl_column": {"type": "string", "x-column-source": "input.data"},
    "lcl_column": {"type": "string", "x-column-source": "input.data"},
    "center_column": {"type": "string", "x-column-source": "input.data"},
    "highlight_column": {"type": "string", "x-column-source": "input.data"},
    "facet": {"type": "string", "title": "facet — split into N panels by column"},
    "title": {"type": "string"}
  }
}$ps$,
    description = description || E'\n\n[2026-05-02] facet + SPC shorthand (ucl_column / lcl_column / center_column / highlight_column) added — replaces block_chart(chart_type=line, …).',
    updated_at = now()
WHERE name = 'block_line_chart' AND description NOT LIKE '%facet + SPC shorthand%';

-- ── 2. Migrate pipeline 34 (SPC charts 連續OOC 的檢查) ────────────────────
-- Original: n3 = block_chart with chart_type=line + facet=chart_name + ...
-- Target  : n3 = block_line_chart with same params (facet/x/y/rules etc.)
UPDATE pb_pipelines
SET pipeline_json = jsonb_set(
        pipeline_json,
        '{nodes}',
        (
            SELECT jsonb_agg(
                CASE
                    WHEN n->>'block_id' = 'block_chart'
                         AND n->'params'->>'chart_type' = 'line'
                    THEN jsonb_set(
                            jsonb_set(n, '{block_id}', '"block_line_chart"'),
                            '{params}',
                            (n->'params') - 'chart_type'  -- drop chart_type, dedicated block doesn't need it
                         )
                    ELSE n
                END
            )
            FROM jsonb_array_elements(pipeline_json->'nodes') AS n
        )
    ),
    updated_at = now()
WHERE id IN (34, 39)
  AND pipeline_json::text LIKE '%"block_id": "block_chart"%';

-- ── 3. Mark block_chart deprecated (won't appear in BlockLibrary) ─────────
UPDATE pb_blocks
SET status = 'deprecated',
    description = description || E'\n\n⚠ DEPRECATED 2026-05-02 — use dedicated chart blocks (block_line_chart / block_bar_chart / block_xbar_r / etc.). All 8 chart_type variants have replacements; facet support lifted into the dedicated blocks via _chart_facet.maybe_facet.',
    updated_at = now()
WHERE name = 'block_chart' AND status = 'production';
