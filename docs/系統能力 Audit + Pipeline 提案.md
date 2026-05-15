# 系統能力 Audit + Pipeline 提案

> 2026-05-15 — v23 後系統盤點，列出可組裝的 data pipeline，作為後續 macro_plan 教學 + skill library 設計依據。

## 🧱 可用 Block（53 個）按 category

| Category | Blocks |
|---|---|
| **Source** | `process_history`, `mcp_call`, `list_objects` |
| **Transform / Reshape** | `unnest`, `select`, `pluck`, `unpivot`, `union`, `join`, `filter`, `sort`, `groupby_agg`, `count_rows`, `compute`, `delta`, `shift_lag`, `rolling_window` |
| **Stats / SPC 規則** | `cpk`, `weco_rules`, `consecutive_rule`, `xbar_r`, `imr`, `ewma`, `ewma_cusum`, `linear_regression`, `correlation`, `hypothesis_test`, `histogram`, `probability_plot` |
| **Composite (1-step 自包)** | `spc_panel`, `apc_panel`, `spc_long_form`, `apc_long_form` |
| **Chart (15 種)** | `line_chart`, `bar_chart`, `scatter_chart`, `box_plot`, `histogram_chart`, `splom`, `pareto`, `variability_gauge`, `parallel_coords`, `heatmap_dendro`, `wafer_heatmap`, `defect_stack`, `spatial_pareto`, `trend_wafer_maps`, `chart` (legacy) |
| **Verdict / Alarm** | `step_check`, `threshold`, `alert`, `any_trigger` |
| **Other** | `data_view` (table), `mcp_foreach` |

## 📦 Simulator 提供的 raw data shape (per process event)

```
{eventTime, lotID, toolID, step, spc_status,
 SPC:    {chamberID, charts: [{name, value, ucl, lcl, is_ooc, status}], ...},
 APC:    {objectID, mode, parameters: {etch_time_offset, rf_power_bias, ... ~20 params}},
 DC:     {chamberID, parameters: {chamber_pressure, rf_forward_power, ... 70+ sensors}},
 RECIPE: {objectID, recipe_version, parameters: {etch_time_s, target_thickness_nm, ...}},
 FDC:    {classification, fault_code, confidence, contributing_sensors, description},
 EC:     {chamberID, constants: {rf_power_offset, calibrations, ...}}}
```

> 注意：`block_process_history` 把 simulator 的 `SPC.charts` 自動 normalize 成 top-level `spc_charts: list[{name, value, ucl, lcl, is_ooc, status}]`，並預算 `spc_summary: {ooc_count, total_charts, ooc_chart_names}`。  
> 下游用 `block_unnest(column='spc_charts')` 解開，leaf 欄位是 `name`/`value`/`ucl`/`lcl`/`is_ooc`/`status`（**不是** `spc_name`/`chart_name`）。

## 🎯 10 個建議 Data Pipeline (按複雜度 + 應用面)

| # | User Instruction | 主要 Blocks | Terminal |
|---|---|---|---|
| **1** | 看 EQP-01 STEP_001 xbar_chart 過去 7 天 | **spc_panel** (composite) | line_chart |
| **2** | 看 EQP-01 過去 24h APC etch_time_offset 趨勢 | **apc_panel** | line_chart |
| **3** | 機台最後一次 OOC 時，是否多張 SPC 同時 OOC ≥3 | process_history → unnest → filter → sort+limit=1 → 三 fan-out: step_check / data_view / line_chart | verdict + table + chart |
| **4** | 比較 EQP-01..05 過去 24h xbar 趨勢 (小倍數) | process_history → unnest → filter name=='xbar' → line_chart `facet='toolID'` | facet chart |
| **5** | 計算 EQP-01 STEP_001 過去 30 天 xbar 的 Cpk | process_history → unnest → filter → **cpk** (USL/LSL) → data_view | scalar cpk |
| **6** | 跑 WECO 8 條規則檢查 EQP-01 xbar 過去 100 lot | process_history → unnest → filter → **weco_rules** → step_check | verdict + alarm |
| **7** | RF forward power vs reflected power 散佈圖 (FDC root-cause hint) | process_history (object_name=DC) → select rf_forward + rf_reflected → **scatter_chart** + **linear_regression** | chart + regression |
| **8** | 各 toolID Past-week OOC 次數 Pareto 排名 | process_history → unnest → filter is_ooc → groupby_agg toolID count → **pareto** | pareto chart |
| **9** | DC 多參數對 SPC OOC vs PASS 比對 (parallel coords) | process_history → 拆 SPC 結果 → join DC params → **parallel_coords** color=spc_status | chart |
| **10** | EWMA-CUSUM detect drift on xbar 過去 200 lot | process_history → unnest → filter → **ewma_cusum** → data_view alarm rows | chart + alarm rows |

## 🔥 高難度 (跨 branch / 多 source) — 需 block_join 或 mcp_foreach

| # | User Instruction | 為何難 |
|---|---|---|
| **11** | 找最後 1 次 OOC 那一刻，列出該時刻**所有** SPC charts 7 天 trend | 跨 branch (last time → re-filter 全表) — 需 `block_join` (deps_on=[3, 5]) |
| **12** | 同 step 跨 5 台機台對比，各自 Cpk 排名 + 總 boxplot | mcp_foreach (per-tool fan-out) + groupby + box_plot |
| **13** | Recipe v1 vs v2 etch_rate hypothesis test (兩 source) | union 兩個 process_history (filter recipe_version) → hypothesis_test |

## 已驗證狀態 (v23, 2026-05-15)

- ✅ **#3 通過**：driver 5x 全 finish，3/3 chart 真 render
- ⚠ **#11 部分**：v23 trigger 後 LLM 改走 #3 的簡化路徑（直接 fan-out from filter），不主動用 join；單獨拿 #11 case 跑時 1/3 仍出新 bug `{last_ooc_time}` template syntax (待 v24 widening guard 修)
- 其他 8 個尚未自動測試
