-- V12 — Add deprecation hint to block_chart description.
--
-- 18 dedicated chart blocks landed in V10/V11. block_chart stays production
-- because of its `facet` feature (one input → N independent panels), but
-- we want the LLM to prefer dedicated blocks for everything else. Just
-- update the description text.

UPDATE pb_blocks
SET
  description = E'⚠ **建議改用 dedicated chart blocks**（PR-G/H/I 後 18 個）。\n'
    || E'本 block_chart 仍 production — 留作 multi-purpose fallback +\n'
    || E'保留 `facet` 功能（一個 input 出 N 張獨立 chart，dedicated 沒實作）。\n'
    || E'選 dedicated 對 LLM 較易選對工具：\n'
    || E'  - line/bar/scatter → block_line_chart / block_bar_chart / block_scatter_chart\n'
    || E'  - boxplot → block_box_plot          - distribution → block_histogram_chart\n'
    || E'  - SPC 嚴格 X̄/R + WECO → block_xbar_r / block_imr / block_ewma_cusum\n'
    || E'  - 排序 + 累計 % → block_pareto      - QQ → block_probability_plot\n'
    || E'  - wafer → block_wafer_heatmap / block_defect_stack / block_spatial_pareto\n'
    || E'**只有需要 facet（同 input 切 N panel）時才用本 block。**\n'
    || E'\n'
    || description,
  updated_at = now()
WHERE name = 'block_chart' AND version = '1.0.0'
  AND description NOT LIKE '⚠ **建議改用 dedicated chart blocks**%';
