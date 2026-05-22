-- V51 — 2026-05-22: clarify block_xbar_r doc for process_history scenario.
--
-- Background (verify-build simulation 2026-05-22):
--   User reported t1 trace where prompt "EQP-01 STEP_001 X-bar/R + WECO 異常"
--   was built without WECO R2-R8 highlighting. Agent inspected block_xbar_r
--   but rejected it, falling back to block_line_chart with is_ooc highlight
--   (only R1 coverage). Root cause: xbar_r doc said "subgroup size ≥2 / need
--   value_column + subgroup_column" — agent looked at its
--   process_history.spc_charts.xbar_chart data (1 row per event with `value`
--   already = X̄ mean) and concluded xbar_r didn't fit.
--
--   In reality block_xbar_r DOES accept this shape — `value_column='value'`
--   on pre-aggregated subgroup means works. Doc just didn't say so.
--
--   Simulation with this note added: agent picked block_xbar_r correctly with
--   reasoning "文檔明確說明支援 process_history + unnest + filter 的預聚合資料模式".
--
-- Idempotent: WHERE NOT clause skips if note already present.

UPDATE block_docs
SET markdown = replace(
        markdown,
        E'\n## Inputs',
        E'\n⚡ Pre-aggregated 用法（process_history 場景）:\n'
        ||  '  上游若是 `block_process_history` + `block_unnest(spc_charts)` + `block_filter(name=xbar_chart)` 後' || E'\n'
        ||  '  的 row（每 row 的 `value` 已是 subgroup mean X̄），可直接設 `value_column=''value''`，' || E'\n'
        ||  '  不需要 `subgroup_column` 或 `subgroups`。block 自動視為已 aggregated，跳過內部 subgroup' || E'\n'
        ||  '  形成步驟直接 plot X̄ chart + 套 WECO R1-R8 規則 highlight。' || E'\n'
        ||  '  ⚠ 注意: 此模式下 R chart 因每 subgroup n=1 無法計算 within-subgroup range；' || E'\n'
        ||  '    若需 R chart 並列，請另外 `block_filter(name=r_chart)` 走 series；' || E'\n'
        ||  '    或用上游 raw measurements + `subgroup_column` 讓 block 自動 aggregate。' || E'\n'
        ||  E'\n## Inputs'
    ),
    updated_at = now()
WHERE block_id = 'block_xbar_r'
  AND markdown NOT LIKE '%Pre-aggregated 用法（process_history 場景）%';
