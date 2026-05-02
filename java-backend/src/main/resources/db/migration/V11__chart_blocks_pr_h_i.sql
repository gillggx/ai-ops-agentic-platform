-- V11 — PR-H + PR-I of the 18-block charting overhaul (Stage 2 parts 2 + 3).
--
-- Twelve new chart blocks: 3 SPC (xbar_r / imr / ewma_cusum) + 5 Diagnostic
-- (pareto / variability_gauge / parallel_coords / probability_plot /
-- heatmap_dendro) + 4 Wafer (wafer_heatmap / defect_stack / spatial_pareto /
-- trend_wafer_maps).
--
-- Block descriptions / param schemas mirror the sidecar seed.py exactly so
-- the boot invariant check passes (BUILTIN_EXECUTORS == DB rows).

-- ─── 1. block_xbar_r ──────────────────────────────────────────────────────
INSERT INTO pb_blocks
  (name, version, category, status, description,
   input_schema, output_schema, param_schema, implementation,
   examples, output_columns_hint, is_custom)
VALUES (
  'block_xbar_r', '1.0.0', 'output', 'production',
$desc$== What ==
Proper X̄/R control chart with full WECO R1-R8 highlighting.

== When to use ==
- ✅ subgroup-size SPC monitoring（每批 5 個 wafer 量量算 X̄/R）
- ✅ 想要 WECO R2/R3/R4/R6/R7/R8 自動偵測（不只 OOC）
- ❌ 單測量（n=1）→ 用 block_imr
- ❌ small-shift 偵測 → 用 block_ewma_cusum

== Params ==
subgroups:        number[][], opt — 預先 aggregated subgroup arrays
value_column:     string — 數值欄位（與 subgroup_column 配合 raw rows path）
subgroup_column:  string, opt — group 欄位（lot_id, wafer_id 等）
subgroup_size:    int, opt — 估 σ 用的 n（預設取出現最多的 group size）
weco_rules:       string[], opt — 例 ['R1','R2','R5']，預設 R1-R8 全開
title:            string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "properties": {"subgroups": {"type": "array"}, "value_column": {"type": "string"}, "subgroup_column": {"type": "string"}, "subgroup_size": {"type": "integer", "minimum": 2, "maximum": 10}, "weco_rules": {"type": "array", "items": {"type": "string"}}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.xbar_r:XbarRBlockExecutor"}',
  '[]', '[]', false
)
ON CONFLICT (name, version) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  output_schema = EXCLUDED.output_schema,
  param_schema = EXCLUDED.param_schema,
  implementation = EXCLUDED.implementation,
  status = EXCLUDED.status, category = EXCLUDED.category, updated_at = now();

-- ─── 2. block_imr ─────────────────────────────────────────────────────────
INSERT INTO pb_blocks (name, version, category, status, description, input_schema, output_schema, param_schema, implementation, examples, output_columns_hint, is_custom)
VALUES (
  'block_imr', '1.0.0', 'output', 'production',
$desc$== What ==
Individual + Moving Range chart for un-subgrouped (n=1) data with WECO R1-R8.

== When to use ==
- ✅ 每筆只一個量測值（destructive test, single-shot endpoint）
- ❌ subgroup data → 用 block_xbar_r（更敏感）

== Params ==
values:        number[], opt — 預先 aggregated values
value_column:  string — 與 values 二擇一
weco_rules:    string[], opt
title:         string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "properties": {"values": {"type": "array"}, "value_column": {"type": "string"}, "weco_rules": {"type": "array", "items": {"type": "string"}}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.imr:IMRBlockExecutor"}',
  '[]', '[]', false
)
ON CONFLICT (name, version) DO UPDATE SET description = EXCLUDED.description, input_schema = EXCLUDED.input_schema, output_schema = EXCLUDED.output_schema, param_schema = EXCLUDED.param_schema, implementation = EXCLUDED.implementation, status = EXCLUDED.status, category = EXCLUDED.category, updated_at = now();

-- ─── 3. block_ewma_cusum ──────────────────────────────────────────────────
INSERT INTO pb_blocks (name, version, category, status, description, input_schema, output_schema, param_schema, implementation, examples, output_columns_hint, is_custom)
VALUES (
  'block_ewma_cusum', '1.0.0', 'output', 'production',
$desc$== What ==
EWMA + CUSUM small-shift detector. Distinct from `block_ewma` (transform).
Two modes: 'ewma' (time-varying limits) or 'cusum' (SH/SL paths with H+/H− interval).

== When to use ==
- ✅ 製程小偏移偵測（< 1σ shift）— 比 X̄/R 更敏感
- ✅ EWMA λ=0.2 是工廠常用值；CUSUM k=0.5 + h=4 是 1σ shift 的 ARL=10 配置
- ❌ 單純 smoothing（不需要 chart） → 用 block_ewma

== Params ==
values:        number[], opt — 與 value_column 二擇一
value_column:  string
mode:          'ewma' | 'cusum'，default 'ewma'
lambda:        number, default 0.2 — EWMA smoothing
k:             number, default 0.5 — CUSUM reference (σ units)
h:             number, default 4 — CUSUM decision interval (σ units)
target:        number, opt — 覆寫 μ
title:         string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "properties": {"values": {"type": "array"}, "value_column": {"type": "string"}, "mode": {"type": "string", "enum": ["ewma", "cusum"], "default": "ewma"}, "lambda": {"type": "number", "minimum": 0.05, "maximum": 1, "default": 0.2}, "k": {"type": "number", "default": 0.5}, "h": {"type": "number", "default": 4}, "target": {"type": "number"}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.ewma_cusum:EwmaCusumBlockExecutor"}',
  '[]', '[]', false
)
ON CONFLICT (name, version) DO UPDATE SET description = EXCLUDED.description, input_schema = EXCLUDED.input_schema, output_schema = EXCLUDED.output_schema, param_schema = EXCLUDED.param_schema, implementation = EXCLUDED.implementation, status = EXCLUDED.status, category = EXCLUDED.category, updated_at = now();

-- ─── 4. block_pareto ──────────────────────────────────────────────────────
INSERT INTO pb_blocks (name, version, category, status, description, input_schema, output_schema, param_schema, implementation, examples, output_columns_hint, is_custom)
VALUES (
  'block_pareto', '1.0.0', 'output', 'production',
$desc$== What ==
Pareto chart — 遞減排序 bars + 累計 % line + 80% 參考線。「找最大貢獻者」場景必備。

== When to use ==
- ✅ 「最常見的缺陷類型」「哪幾台機台貢獻 80% OOC」「lot 失敗 root cause」
- ❌ 順序固定的類別（時間 / step) → 用 block_bar_chart

== Params ==
category_column:        string, required — 類別欄位
value_column:           string, required — 計數欄位
cumulative_threshold:   number, default 80 — 紅色參考線（80/20 rule）
title:                  string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "required": ["category_column", "value_column"], "properties": {"category_column": {"type": "string"}, "value_column": {"type": "string"}, "cumulative_threshold": {"type": "number", "minimum": 0, "maximum": 100, "default": 80}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.pareto:ParetoBlockExecutor"}',
  '[]', '[]', false
)
ON CONFLICT (name, version) DO UPDATE SET description = EXCLUDED.description, input_schema = EXCLUDED.input_schema, output_schema = EXCLUDED.output_schema, param_schema = EXCLUDED.param_schema, implementation = EXCLUDED.implementation, status = EXCLUDED.status, category = EXCLUDED.category, updated_at = now();

-- ─── 5. block_variability_gauge ───────────────────────────────────────────
INSERT INTO pb_blocks (name, version, category, status, description, input_schema, output_schema, param_schema, implementation, examples, output_columns_hint, is_custom)
VALUES (
  'block_variability_gauge', '1.0.0', 'output', 'production',
$desc$== What ==
多階分組變異分解 — jittered points + 每組均值粗線 + 連線顯示 lot/wafer/tool 階層 shifts。

== When to use ==
- ✅ 「不同 lot 之間有沒有 shift」「同 lot 不同 wafer 變異多大」「tool-to-tool」
- ❌ 純看分佈 → 用 block_box_plot 或 block_histogram_chart

== Params ==
value_column:  string, required
levels:        string[], required — 由外到內，e.g. ['lot','wafer','tool']
title:         string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "required": ["value_column", "levels"], "properties": {"value_column": {"type": "string"}, "levels": {"type": "array", "items": {"type": "string"}, "minItems": 1}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.variability_gauge:VariabilityGaugeBlockExecutor"}',
  '[]', '[]', false
)
ON CONFLICT (name, version) DO UPDATE SET description = EXCLUDED.description, input_schema = EXCLUDED.input_schema, output_schema = EXCLUDED.output_schema, param_schema = EXCLUDED.param_schema, implementation = EXCLUDED.implementation, status = EXCLUDED.status, category = EXCLUDED.category, updated_at = now();

-- ─── 6. block_parallel_coords ─────────────────────────────────────────────
INSERT INTO pb_blocks (name, version, category, status, description, input_schema, output_schema, param_schema, implementation, examples, output_columns_hint, is_custom)
VALUES (
  'block_parallel_coords', '1.0.0', 'output', 'production',
$desc$== What ==
Parallel coordinates — N axes 並列，每筆 row 一條多段折線。互動：drag axis 設 brush 範圍，dblclick 清除。

== When to use ==
- ✅ 「Recipe 5+ params 探索 yield 為何低」（color_by='Yield%' + alert_below=92）
- ✅ 多維 outlier 找：先 brush 已知異常範圍，看其他維度是否同步
- ❌ 只 2 維 → 用 block_scatter_chart

== Params ==
dimensions:    string[], required, length >= 2 — 軸的欄位
color_by:      string, opt — 上色欄位（通常是 yield 或 quality）
alert_below:   number, opt — < threshold 的 row 改紅色
title:         string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "required": ["dimensions"], "properties": {"dimensions": {"type": "array", "items": {"type": "string"}, "minItems": 2}, "color_by": {"type": "string"}, "alert_below": {"type": "number"}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.parallel_coords:ParallelCoordsBlockExecutor"}',
  '[]', '[]', false
)
ON CONFLICT (name, version) DO UPDATE SET description = EXCLUDED.description, input_schema = EXCLUDED.input_schema, output_schema = EXCLUDED.output_schema, param_schema = EXCLUDED.param_schema, implementation = EXCLUDED.implementation, status = EXCLUDED.status, category = EXCLUDED.category, updated_at = now();

-- ─── 7. block_probability_plot ────────────────────────────────────────────
INSERT INTO pb_blocks (name, version, category, status, description, input_schema, output_schema, param_schema, implementation, examples, output_columns_hint, is_custom)
VALUES (
  'block_probability_plot', '1.0.0', 'output', 'production',
$desc$== What ==
Normal Q-Q plot + Anderson-Darling p-value annotation. 用於檢定資料是否常態分佈。

== When to use ==
- ✅ 「Cpk 算前先確認常態性」「outlier 是真離群還是分佈本身偏」
- ✅ AD p ≥ 0.05 → 常態 ✓；否則 ⚠ non-normal
- ❌ 純看 distribution shape → 用 block_histogram_chart（更直覺）

== Params ==
values:        number[], opt — 二擇一
value_column:  string
title:         string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "properties": {"values": {"type": "array"}, "value_column": {"type": "string"}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.probability_plot:ProbabilityPlotBlockExecutor"}',
  '[]', '[]', false
)
ON CONFLICT (name, version) DO UPDATE SET description = EXCLUDED.description, input_schema = EXCLUDED.input_schema, output_schema = EXCLUDED.output_schema, param_schema = EXCLUDED.param_schema, implementation = EXCLUDED.implementation, status = EXCLUDED.status, category = EXCLUDED.category, updated_at = now();

-- ─── 8. block_heatmap_dendro ──────────────────────────────────────────────
INSERT INTO pb_blocks (name, version, category, status, description, input_schema, output_schema, param_schema, implementation, examples, output_columns_hint, is_custom)
VALUES (
  'block_heatmap_dendro', '1.0.0', 'output', 'production',
$desc$== What ==
Clustered heatmap — single-linkage agglomerative clustering on (1-|value|)
distance；row + col 重排，附 top + right dendrograms。

== When to use ==
- ✅ 「FDC 哪幾組 params 強相關」（matrix 模式：先跑 block_correlation 拿到 matrix）
- ✅ 「哪幾個 step × tool 同步異常」（long-form 模式）
- ❌ 不需 cluster → 用 block_chart(heatmap)（更輕）

== Params ==
matrix:           number[][], opt — N×N 矩陣（與 dim_labels 配對）
dim_labels:       string[], opt — matrix 的 row/col 標籤
x_column / y_column / value_column: long-form mode（與 matrix 二擇一）
cluster:          bool, default true
title:            string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "properties": {"matrix": {"type": "array"}, "dim_labels": {"type": "array", "items": {"type": "string"}}, "x_column": {"type": "string"}, "y_column": {"type": "string"}, "value_column": {"type": "string"}, "cluster": {"type": "boolean", "default": true}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.heatmap_dendro:HeatmapDendroBlockExecutor"}',
  '[]', '[]', false
)
ON CONFLICT (name, version) DO UPDATE SET description = EXCLUDED.description, input_schema = EXCLUDED.input_schema, output_schema = EXCLUDED.output_schema, param_schema = EXCLUDED.param_schema, implementation = EXCLUDED.implementation, status = EXCLUDED.status, category = EXCLUDED.category, updated_at = now();

-- ─── 9. block_wafer_heatmap ───────────────────────────────────────────────
INSERT INTO pb_blocks (name, version, category, status, description, input_schema, output_schema, param_schema, implementation, examples, output_columns_hint, is_custom)
VALUES (
  'block_wafer_heatmap', '1.0.0', 'output', 'production',
$desc$== What ==
Circle wafer outline + IDW interpolated value field over (x,y) measurement
sites + optional measurement-point overlay. Uniformity stats (μ/σ/range/±%).

== When to use ==
- ✅ 「49-site thickness 空間分佈」「edge ring drift」「center-to-edge slope」
- ❌ defect 類別空間分佈 → 用 block_defect_stack

== Params ==
x_column / y_column:  座標欄位（mm 單位，center 為原點）— default 'x' / 'y'
value_column:         required — measurement 值
wafer_radius_mm:      default 150（300mm wafer）
notch:                'top' | 'bottom' | 'left' | 'right'，default 'bottom'
unit:                 string, opt — legend / tooltip 單位（'Å', 'nm'）
color_mode:           'viridis' | 'diverging'，default 'viridis'
show_points:          bool, default true
grid_n:               int, default 60 — 插值解析度
title:                string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "required": ["value_column"], "properties": {"x_column": {"type": "string", "default": "x"}, "y_column": {"type": "string", "default": "y"}, "value_column": {"type": "string"}, "wafer_radius_mm": {"type": "number", "default": 150}, "notch": {"type": "string", "enum": ["top", "bottom", "left", "right"], "default": "bottom"}, "unit": {"type": "string"}, "color_mode": {"type": "string", "enum": ["viridis", "diverging"], "default": "viridis"}, "show_points": {"type": "boolean", "default": true}, "grid_n": {"type": "integer", "minimum": 10, "maximum": 200, "default": 60}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.wafer_heatmap:WaferHeatmapBlockExecutor"}',
  '[]', '[]', false
)
ON CONFLICT (name, version) DO UPDATE SET description = EXCLUDED.description, input_schema = EXCLUDED.input_schema, output_schema = EXCLUDED.output_schema, param_schema = EXCLUDED.param_schema, implementation = EXCLUDED.implementation, status = EXCLUDED.status, category = EXCLUDED.category, updated_at = now();

-- ─── 10. block_defect_stack ───────────────────────────────────────────────
INSERT INTO pb_blocks (name, version, category, status, description, input_schema, output_schema, param_schema, implementation, examples, output_columns_hint, is_custom)
VALUES (
  'block_defect_stack', '1.0.0', 'output', 'production',
$desc$== What ==
Wafer outline + 缺陷點按 defect_code 著色 + clickable legend toggle 顯示。

== When to use ==
- ✅ 「最近 N wafer 的 defect 空間分佈」「Particle 是否聚集在 edge」
- ❌ 連續變數 → 用 block_wafer_heatmap

== Params ==
x_column / y_column:  座標欄位 — default 'x' / 'y'
defect_column:        缺陷類型欄位 — default 'defect_code'
codes:                string[], opt — 限制顯示哪些 codes（預設 auto）
wafer_radius_mm:      default 150
notch:                default 'bottom'
title:                string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "properties": {"x_column": {"type": "string", "default": "x"}, "y_column": {"type": "string", "default": "y"}, "defect_column": {"type": "string", "default": "defect_code"}, "codes": {"type": "array", "items": {"type": "string"}}, "wafer_radius_mm": {"type": "number", "default": 150}, "notch": {"type": "string", "enum": ["top", "bottom", "left", "right"], "default": "bottom"}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.defect_stack:DefectStackBlockExecutor"}',
  '[]', '[]', false
)
ON CONFLICT (name, version) DO UPDATE SET description = EXCLUDED.description, input_schema = EXCLUDED.input_schema, output_schema = EXCLUDED.output_schema, param_schema = EXCLUDED.param_schema, implementation = EXCLUDED.implementation, status = EXCLUDED.status, category = EXCLUDED.category, updated_at = now();

-- ─── 11. block_spatial_pareto ─────────────────────────────────────────────
INSERT INTO pb_blocks (name, version, category, status, description, input_schema, output_schema, param_schema, implementation, examples, output_columns_hint, is_custom)
VALUES (
  'block_spatial_pareto', '1.0.0', 'output', 'production',
$desc$== What ==
Yield (or any value) binned 到 wafer grid，diverging palette 著色，**worst cell 黑框 highlight**。

== When to use ==
- ✅ 「yield 哪一區最差」「edge yield drop 嚴重程度」
- ❌ 連續 thickness 分佈 → 用 block_wafer_heatmap

== Params ==
x_column / y_column:  default 'x' / 'y'
value_column:         required — yield_pct 或類似
wafer_radius_mm:      default 150
grid_n:               int, default 12 — 切格數
notch:                default 'bottom'
unit:                 string, opt — '%' 等
title:                string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "required": ["value_column"], "properties": {"x_column": {"type": "string", "default": "x"}, "y_column": {"type": "string", "default": "y"}, "value_column": {"type": "string"}, "wafer_radius_mm": {"type": "number", "default": 150}, "grid_n": {"type": "integer", "minimum": 4, "maximum": 50, "default": 12}, "notch": {"type": "string", "enum": ["top", "bottom", "left", "right"], "default": "bottom"}, "unit": {"type": "string"}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.spatial_pareto:SpatialParetoBlockExecutor"}',
  '[]', '[]', false
)
ON CONFLICT (name, version) DO UPDATE SET description = EXCLUDED.description, input_schema = EXCLUDED.input_schema, output_schema = EXCLUDED.output_schema, param_schema = EXCLUDED.param_schema, implementation = EXCLUDED.implementation, status = EXCLUDED.status, category = EXCLUDED.category, updated_at = now();

-- ─── 12. block_trend_wafer_maps ───────────────────────────────────────────
INSERT INTO pb_blocks (name, version, category, status, description, input_schema, output_schema, param_schema, implementation, examples, output_columns_hint, is_custom)
VALUES (
  'block_trend_wafer_maps', '1.0.0', 'output', 'production',
$desc$== What ==
Small-multiples grid of mini wafer heatmaps over time. Shared color domain.
PM days (`pm_column`=true) 框紅虛線。

== When to use ==
- ✅ 「pre/post PM 空間分佈變化」「過去 7 天 wafer drift」「lot-to-lot 重複性」
- ❌ 單一 wafer 細看 → 用 block_wafer_heatmap

== Params ==
maps:           list, opt — pre-aggregated [{date, points:[{x,y,v}], is_pm}, ...]
x_column / y_column / value_column / time_column: long-form mode
pm_column:      string, opt — bool 欄位標 PM 日
wafer_radius_mm: default 150
cols:           int, opt — grid 欄數（預設 = maps 數）
grid_n:         int, default 28
notch:          default 'bottom'
title:          string, opt
$desc$,
  '[{"port": "data", "type": "dataframe"}]',
  '[{"port": "chart_spec", "type": "dict"}]',
  '{"type": "object", "properties": {"maps": {"type": "array"}, "x_column": {"type": "string", "default": "x"}, "y_column": {"type": "string", "default": "y"}, "value_column": {"type": "string"}, "time_column": {"type": "string"}, "pm_column": {"type": "string"}, "wafer_radius_mm": {"type": "number", "default": 150}, "cols": {"type": "integer", "minimum": 1}, "grid_n": {"type": "integer", "minimum": 10, "maximum": 100, "default": 28}, "notch": {"type": "string", "enum": ["top", "bottom", "left", "right"], "default": "bottom"}, "title": {"type": "string"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.trend_wafer_maps:TrendWaferMapsBlockExecutor"}',
  '[]', '[]', false
)
ON CONFLICT (name, version) DO UPDATE SET description = EXCLUDED.description, input_schema = EXCLUDED.input_schema, output_schema = EXCLUDED.output_schema, param_schema = EXCLUDED.param_schema, implementation = EXCLUDED.implementation, status = EXCLUDED.status, category = EXCLUDED.category, updated_at = now();
