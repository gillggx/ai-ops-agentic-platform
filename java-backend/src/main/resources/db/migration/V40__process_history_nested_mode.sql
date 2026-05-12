-- V40 — block_process_history: opt-in `nested` mode (2026-05-13).
--
-- Background: Phase 1 object-native refactor. Adding a `nested=true` param
-- that skips the SPC/APC/DC/RECIPE/FDC/EC flattening and instead returns
-- hierarchical records with a precomputed spc_summary. Existing pipelines
-- (default nested=false) keep working unchanged — this is purely additive.
--
-- Sync param_schema + description to pb_blocks so the Java catalog readers
-- (BlockDocsDrawer, build agent catalog) match seed.py / sidecar executor.

UPDATE pb_blocks
SET param_schema = jsonb_set(
      param_schema::jsonb,
      '{properties,nested}',
      $${"type": "boolean", "default": false, "title": "回傳 hierarchical shape", "description": "true 改回傳 nested record + spc_summary 預算值；false（預設）展平成寬表"}$$::jsonb,
      true
    )::text,
    updated_at = now()
WHERE name = 'block_process_history';

-- Append nested-mode docs to description (idempotent guard via LIKE).
UPDATE pb_blocks
SET description = description || E'\n\n== Nested mode (2026-05-13) ==\n' ||
                  E'nested=true 改回傳 hierarchical record — spc_charts (array) + spc_summary ' ||
                  E'{ooc_count, total_charts, ooc_chart_names} + APC/DC/RECIPE/FDC/EC 保留 nested。\n' ||
                  E'下游用 path 文法直讀（e.g. step_check column=''spc_summary.ooc_count''）。\n' ||
                  E'適用「最後一次 process 有幾張 chart OOC」「該 lot 的所有 APC 補償」這類 hierarchical 提問。',
    updated_at = now()
WHERE name = 'block_process_history'
  AND description NOT LIKE '%Nested mode (2026-05-13)%';
