-- V29 — Improve block descriptions for chart facet vs series_field disambiguation
--
-- Background (2026-05-10):
--   User reported: "讓 SPC 各 chart 分開展示" 一直被 LLM 用 series_field 處理，
--   結果 5 張合成 1 張多色線。後來發現 plan.py 的 _format_catalog 把 chart blocks
--   description 砍到只剩第一行，facet 用法雖然有寫但 LLM 看不到。
--
-- This migration syncs the seed.py description updates into pb_blocks so that
-- BlockDocsDrawer and any DB-based catalog readers see the same text:
--   1. block_line_chart — adds explicit facet vs series_field guidance under
--      "When to use", with user-intent → param mapping.
--   2. block_spc_long_form — adds canonical pipeline (B) for "split into N
--      separate trend charts via facet=chart_name", with anti-pattern warning
--      against series_field=chart_name.
--
-- The sidecar reads seed.py directly (SeedlessBlockRegistry) so it picks up
-- the change on restart. This SQL keeps the DB in sync per CLAUDE.md §1+§4
-- (description is the single source of truth across all 3 surfaces).

-- ── 1. block_line_chart ─────────────────────────────────────────────────
UPDATE pb_blocks
SET description = $BD$== What ==
Line / multi-line chart with optional control rules + highlight overlay.
Output `chart_spec` with type='line' that the SVG engine renders via
the dedicated LineChart component.

== When to use ==
- ✅ 純時序趨勢（thickness over time / count per hour / event_time vs value）
- ✅ 多條線疊圖（y 是 array，e.g. xbar + ucl + lcl 都當 y series）
- ✅ 雙 Y 軸（y_secondary 給第二軸 series，e.g. SPC 值 + APC 補償）
- ✅ 「同一張圖」按某欄位上多條彩色線：series_field='toolID'
- ✅ 「拆成 N 張獨立小圖」按某欄位 group：facet='chart_name'
       (e.g. SPC long-form 一次出 X̄/R/S/P/C 5 張**分開的** trend chart)
- ⚠ series_field vs facet 的選擇：
       使用者說「分開」「各自一張」「別放同張」→ 用 facet（產出多張 panel）
       使用者說「疊在一起比較」「不同顏色」「同張圖」→ 用 series_field
- ❌ 嚴格的 SPC X̄/R 控制圖（subgroup 算 σ + WECO） → 用 block_xbar_r
- ❌ 純值分佈 → 用 block_histogram_chart

== Params ==
x:                 string, required — x 軸欄位（time / index / category）
y:                 string | string[], required — y series 欄位
y_secondary:       string[], opt — 右側 y 軸 series
series_field:      string, opt — group rows 出多條 color trace
rules:             array, opt — [{value, label, style?, color?}] 水平參考線
highlight_field:   string, opt — bool 欄位（matched rows 紅圈 overlay）
highlight_eq:      any, opt — match 條件值，預設 true
ucl_column:        string, opt — 取 column 第一筆當 UCL rule 線（SPC 簡寫）
lcl_column:        string, opt — 同上，LCL
center_column:     string, opt — 同上，Center
highlight_column:  string, opt — 同 highlight_field（block_chart 舊名）
facet:             string, opt — 按此欄位 group → 一個 group 一張獨立小圖
                  （e.g. SPC long-form 用 facet='chart_name' 一次出 X̄/R/S/P/C 5 張）
title:             string, opt

== Output ==
chart_spec (dict | dict[]): type='line', data, x, y, …
  facet 啟用時 chart_spec 是 list；frontend 攤平成多張 panel

== Keywords ==
time series 时序 時序, trend 趋势 趨勢, line chart 折线图 折線圖, multi-line, dual-axis 双轴 雙軸, facet small multiples 小倍数 小倍數
$BD$,
    updated_at = now()
WHERE name = 'block_line_chart';

-- ── 2. block_spc_long_form ───────────────────────────────────────────────
UPDATE pb_blocks
SET description = $BD$== What ==
Process-History wide → SPC long format reshape (purpose-built).
把 process_history 直出的 spc_<chart>_value/_ucl/_lcl/_is_ooc 欄位攤平成長表，
downstream 用 group_by=chart_name 一次掃所有 chart。

== When to use ==
- ✅ 「站點所有 SPC charts 任一連 N 次 OOC 就告警」→ 經典組合
- ✅ 「對每張 chart 各跑一次 regression / cpk」→ groupby chart_name
- ❌ 只處理 1 張特定 chart → 直接 filter 那張的欄位即可，不用 reshape
- ❌ APC 參數 → 用 block_apc_long_form

== Output columns（固定）==
eventTime, toolID, lotID, step, spc_status, fdc_classification (passthrough)
chart_name (string), value, ucl, lcl, is_ooc (bool)
⚠ 欄位**固定叫 chart_name**，不是 chart_type / chart / metric。

== 經典 pipeline ==
(A) OOC 連續觸發告警:
    process_history(step=$step) → spc_long_form
      → consecutive_rule(flag_column=is_ooc, count=2,
                         sort_by=eventTime, group_by=chart_name)
      → alert(severity=HIGH)

(B) 各 SPC chart **分開展示** trend chart（每張 chart_name 一張獨立 panel）:
    process_history(...) → spc_long_form
      → line_chart(x='eventTime', y=['value','ucl','lcl'],
                   facet='chart_name')   ← 關鍵：facet 按 chart_name 拆
    chart_name 欄位的值就是各 SPC chart 的種類（X̄/R/S/P/C 等），
    facet='chart_name' 會一次產出 N 張獨立的小圖。
    ⚠ 不要用 series_field='chart_name' — 那會把 5 張合併成 1 張多色線。

== Errors ==
- INVALID_INPUT  : data 不是 DataFrame
- NO_SPC_COLUMNS : 上游沒 spc_*_<field> 欄位
$BD$,
    updated_at = now()
WHERE name = 'block_spc_long_form';
