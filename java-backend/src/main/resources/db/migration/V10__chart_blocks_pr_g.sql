-- V10 — PR-G of the 18-block charting overhaul.
--
-- Six new chart blocks: 3 primitives (line / bar / scatter) + 3 EDA
-- (box_plot / splom / histogram_chart). Each emits a ChartDSL `chart_spec`
-- routed by the new SVG engine to a dedicated React component (Stage 4
-- dispatcher wires this).
--
-- Until the dispatcher lands, these chart_specs land on the legacy
-- ChartDSLRenderer which doesn't recognize the new types and shows the
-- empty placeholder — which is fine for Stage 2 (LLM agent learns the
-- catalog now; visuals come at Stage 4).
--
-- Block descriptions / param schemas mirror the sidecar seed.py exactly so
-- the boot invariant check passes (BUILTIN_EXECUTORS == DB rows).

-- ─── 1. block_line_chart ──────────────────────────────────────────────────
INSERT INTO pb_blocks
  (name, version, category, status, description,
   input_schema, output_schema, param_schema, implementation,
   examples, output_columns_hint, is_custom)
VALUES (
  'block_line_chart', '1.0.0', 'output', 'production',
$desc$== What ==
Line / multi-line chart with optional control rules + highlight overlay.
Output `chart_spec` with type='line' that the SVG engine renders via
the dedicated LineChart component.

== When to use ==
- ✅ 純時序趨勢（thickness over time / count per hour / event_time vs value）
- ✅ 多條線疊圖（y 是 array，e.g. xbar + ucl + lcl 都當 y series）
- ✅ 雙 Y 軸（y_secondary 給第二軸 series，e.g. SPC 值 + APC 補償）
- ✅ 一個欄位 group 出多條彩色線：series_field='toolID'
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
title:             string, opt

== Output ==
chart_spec (dict): type='line', data, x, y, [y_secondary, rules, highlight, series_field]
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "required": ["x", "y"], "properties": {"x": {"type": "string"}, "y": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}, "y_secondary": {"type": "array", "items": {"type": "string"}}, "series_field": {"type": "string"}, "rules": {"type": "array"}, "highlight_field": {"type": "string"}, "highlight_eq": {}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.line_chart:LineChartBlockExecutor"}',
  '[]',
  NULL,
  false
)
ON CONFLICT (name, version) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  output_schema = EXCLUDED.output_schema,
  param_schema = EXCLUDED.param_schema,
  implementation = EXCLUDED.implementation,
  status = EXCLUDED.status,
  category = EXCLUDED.category,
  updated_at = now();

-- ─── 2. block_bar_chart ───────────────────────────────────────────────────
INSERT INTO pb_blocks
  (name, version, category, status, description,
   input_schema, output_schema, param_schema, implementation,
   examples, output_columns_hint, is_custom)
VALUES (
  'block_bar_chart', '1.0.0', 'output', 'production',
$desc$== What ==
Categorical bar / grouped-bar chart. Multiple `y` columns produce side-by-
side grouped bars per category.

== When to use ==
- ✅ 「按 EQP 比較 OOC count」「每個 step 的 alarm 數」
- ❌ 排序 + 累計 % 的 80/20 分析 → 用 block_pareto（自動排序 + 累計線）
- ❌ 連續時間軸 → 用 block_line_chart

== Params ==
x:               string, required — 類別欄位
y:               string | string[], required — bar 高度欄位
rules:           array, opt — 水平 threshold 線
highlight_field/highlight_eq: 同 line_chart
title:           string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "required": ["x", "y"], "properties": {"x": {"type": "string"}, "y": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}, "rules": {"type": "array"}, "highlight_field": {"type": "string"}, "highlight_eq": {}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.bar_chart:BarChartBlockExecutor"}',
  '[]',
  NULL,
  false
)
ON CONFLICT (name, version) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  output_schema = EXCLUDED.output_schema,
  param_schema = EXCLUDED.param_schema,
  implementation = EXCLUDED.implementation,
  status = EXCLUDED.status,
  category = EXCLUDED.category,
  updated_at = now();

-- ─── 3. block_scatter_chart ───────────────────────────────────────────────
INSERT INTO pb_blocks
  (name, version, category, status, description,
   input_schema, output_schema, param_schema, implementation,
   examples, output_columns_hint, is_custom)
VALUES (
  'block_scatter_chart', '1.0.0', 'output', 'production',
$desc$== What ==
Scatter plot — markers only. Use for correlation / dispersion / x-vs-y.
`series_field` (single y) splits into one colored series per group.

== When to use ==
- ✅ 「RF Power vs Thickness 是否相關」「stage_time vs OOC%」
- ❌ 多參數矩陣相關 (5+ params) → 用 block_splom（更密集）
- ❌ 趨勢線 → 用 block_line_chart

== Params ==
同 block_line_chart 但無 y_secondary。
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "required": ["x", "y"], "properties": {"x": {"type": "string"}, "y": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}, "series_field": {"type": "string"}, "rules": {"type": "array"}, "highlight_field": {"type": "string"}, "highlight_eq": {}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.scatter_chart:ScatterChartBlockExecutor"}',
  '[]',
  NULL,
  false
)
ON CONFLICT (name, version) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  output_schema = EXCLUDED.output_schema,
  param_schema = EXCLUDED.param_schema,
  implementation = EXCLUDED.implementation,
  status = EXCLUDED.status,
  category = EXCLUDED.category,
  updated_at = now();

-- ─── 4. block_box_plot ────────────────────────────────────────────────────
INSERT INTO pb_blocks
  (name, version, category, status, description,
   input_schema, output_schema, param_schema, implementation,
   examples, output_columns_hint, is_custom)
VALUES (
  'block_box_plot', '1.0.0', 'output', 'production',
$desc$== What ==
Box plot — IQR + whiskers + outlier dots, with optional nested grouping
bracket (e.g. inner=Chamber, outer=Tool).

== When to use ==
- ✅ 「比較不同 chamber 的 thickness 分散」「per-tool 數值差異」
- ✅ 嵌套分群（tool > chamber）→ 設 group_by_secondary
- ❌ 只想看分佈不分組 → 用 block_histogram_chart
- ❌ 純看 raw 數值列表 → 用 block_data_view

== Params ==
x:                  string, required — 內層分組欄位（e.g. chamber）
y:                  string, required — 數值欄位（要算 quartiles 的）
group_by_secondary: string, opt — 外層 bracket 欄位（e.g. tool）
show_outliers:      bool, default true
expanded:           bool, default true（按 outer label 可展開/收合）
y_label:            string, opt — y 軸標題（預設 = y 欄位名）
title:              string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "required": ["x", "y"], "properties": {"x": {"type": "string"}, "y": {"type": "string"}, "group_by_secondary": {"type": "string"}, "show_outliers": {"type": "boolean", "default": true}, "expanded": {"type": "boolean", "default": true}, "y_label": {"type": "string"}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.box_plot:BoxPlotBlockExecutor"}',
  '[]',
  NULL,
  false
)
ON CONFLICT (name, version) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  output_schema = EXCLUDED.output_schema,
  param_schema = EXCLUDED.param_schema,
  implementation = EXCLUDED.implementation,
  status = EXCLUDED.status,
  category = EXCLUDED.category,
  updated_at = now();

-- ─── 5. block_splom ───────────────────────────────────────────────────────
INSERT INTO pb_blocks
  (name, version, category, status, description,
   input_schema, output_schema, param_schema, implementation,
   examples, output_columns_hint, is_custom)
VALUES (
  'block_splom', '1.0.0', 'output', 'production',
$desc$== What ==
Scatter Plot Matrix — N × N grid for FDC parameter exploration.
  - Diagonal: density curves
  - Lower triangle: scatter
  - Upper triangle: |Pearson r| heatmap

== When to use ==
- ✅ 「5+ FDC params 之間哪幾個有相關」「對照 outlier 在哪幾個 dim 異常」
- ❌ 只看 2 個變數 → 用 block_scatter_chart
- ❌ 純 correlation matrix（不看 raw scatter） → 用 block_heatmap_dendro

== Params ==
dimensions:     string[], required, length >= 2
outlier_field:  string, opt — bool 欄位，true 的 row scatter 會用 alert 色
title:          string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "required": ["dimensions"], "properties": {"dimensions": {"type": "array", "items": {"type": "string"}, "minItems": 2}, "outlier_field": {"type": "string"}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.splom:SplomBlockExecutor"}',
  '[]',
  NULL,
  false
)
ON CONFLICT (name, version) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  output_schema = EXCLUDED.output_schema,
  param_schema = EXCLUDED.param_schema,
  implementation = EXCLUDED.implementation,
  status = EXCLUDED.status,
  category = EXCLUDED.category,
  updated_at = now();

-- ─── 6. block_histogram_chart ─────────────────────────────────────────────
INSERT INTO pb_blocks
  (name, version, category, status, description,
   input_schema, output_schema, param_schema, implementation,
   examples, output_columns_hint, is_custom)
VALUES (
  'block_histogram_chart', '1.0.0', 'output', 'production',
$desc$== What ==
Distribution histogram with optional USL/LSL/target spec lines + normal-fit
curve + auto Cpk/Cp/ppm annotation.

⚠ NAMING — 注意跟 `block_histogram` (transform, 算 bin counts) 區分。
本 block 是 chart 輸出，可以吃 raw values（自動 binning）或預先 binned 的
data（含 bin_center + count 欄位）。

== When to use ==
- ✅ 「CD 分佈 + spec window」「thickness 落在 USL/LSL 之間多少 ppm」
- ✅ 想看 Cpk → 給 USL + LSL 即可，自動算
- ❌ 只想要 bin counts（給後續 pipeline 用） → 用 block_histogram

== Params ==
value_column:   string, required (raw mode) — 數值欄位
                若 data 已是 pre-binned (bin_center + count)，可省略
usl, lsl:       number, opt — spec 上下限（兩者都給才算 Cpk）
target:         number, opt — 目標值（綠色虛線）
bins:           int, opt, default 28（raw mode 才用到）
show_normal:    bool, default true
unit:           string, opt — x 軸標題後綴（'nm', 'Å', etc.）
title:          string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "properties": {"value_column": {"type": "string"}, "usl": {"type": "number"}, "lsl": {"type": "number"}, "target": {"type": "number"}, "bins": {"type": "integer", "minimum": 4, "maximum": 200}, "show_normal": {"type": "boolean", "default": true}, "unit": {"type": "string"}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.histogram_chart:HistogramChartBlockExecutor"}',
  '[]',
  NULL,
  false
)
ON CONFLICT (name, version) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  output_schema = EXCLUDED.output_schema,
  param_schema = EXCLUDED.param_schema,
  implementation = EXCLUDED.implementation,
  status = EXCLUDED.status,
  category = EXCLUDED.category,
  updated_at = now();
