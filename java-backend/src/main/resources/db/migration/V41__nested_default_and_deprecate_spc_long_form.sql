-- V41 — 2026-05-13: Phase 1 object-native cleanup.
--
-- 1. Flip block_process_history.nested default to TRUE (was FALSE in V40).
--    The 5 SPC chart blocks (xbar_r / imr / ewma_cusum / weco_rules /
--    consecutive_rule) now call ensure_flat_spc() at their entry point and
--    transparently re-widen nested spc_charts back to flat spc_<chart>_<field>
--    columns. Path-aware blocks (filter / sort / step_check / compute /
--    groupby_agg / join + 25 chart blocks) read nested via path syntax.
--    So nested-by-default works for both old and new chart blocks.
--
-- 2. Mark block_spc_long_form as deprecated. Its purpose (wide → long pivot
--    of SPC charts) is now achieved with block_unnest(column='spc_charts')
--    when upstream is nested — a generic block replaces a specialised one,
--    per the "don't multiply same-purpose blocks; LLM gets confused"
--    principle (memory: feedback_graph_heavy_preference).

-- ── 1. block_process_history: flip nested default ────────────────────
UPDATE pb_blocks
SET param_schema = jsonb_set(
      param_schema::jsonb,
      '{properties,nested,default}',
      'true'::jsonb,
      false
    )::text,
    updated_at = now()
WHERE name = 'block_process_history';

-- Replace the description block we added in V40 (which said "nested=true
-- 改回傳") with the new doc that says nested is now default.
UPDATE pb_blocks
SET description = regexp_replace(
      description,
      E'\\n\\n== Nested mode \\(2026-05-13\\).*$',
      E'\n\n== Output shape — nested is DEFAULT (2026-05-13) ==\n' ||
      E'**預設 nested=true** — 每筆 record 是 hierarchical object：\n' ||
      E'  - spc_charts: list[{name, value, ucl, lcl, is_ooc, status}]\n' ||
      E'  - spc_summary: {ooc_count, total_charts, ooc_chart_names}\n' ||
      E'  - APC / DC / RECIPE / FDC / EC: 保留原 nested sub-object\n' ||
      E'下游用 path 文法直讀（e.g. block_step_check column=''spc_summary.ooc_count''）。\n' ||
      E'想對 SPC chart 做 long-form 分析就接 block_unnest(column=''spc_charts'') 就好。\n\n' ||
      E'**SPC chart blocks 自動相容**：block_xbar_r / block_imr / block_ewma_cusum / ' ||
      E'block_weco_rules / block_consecutive_rule 在入口會 ensure_flat_spc 把 nested ' ||
      E'spc_charts 還原為扁平 spc_<chart>_<field> 欄位，不用為它們設 nested=false。\n\n' ||
      E'**nested=false 只在這幾種情況使用**：legacy pipelines / 想看完整扁平寬表 / ' ||
      E'下游 block 明確不支援 nested（極少數）。',
      'n'
    ),
    updated_at = now()
WHERE name = 'block_process_history';

-- ── 2. block_spc_long_form: deprecate ────────────────────────────────
UPDATE pb_blocks
SET status = 'deprecated',
    description = '⚠ DEPRECATED (2026-05-13) — block_process_history 預設改為 nested=true，' ||
                  '下游想要 long-form 直接接 block_unnest(column=''spc_charts'')，shape 完全一樣。' ||
                  '保留是為了舊 pipeline 仍可載入；新建議全部改用 unnest。' || E'\n\n' ||
                  description,
    updated_at = now()
WHERE name = 'block_spc_long_form' AND status != 'deprecated';
