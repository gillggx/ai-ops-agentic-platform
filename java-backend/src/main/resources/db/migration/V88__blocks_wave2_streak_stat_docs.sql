UPDATE pb_blocks SET description = '== What ==
計算多欄位 pairwise correlation matrix，輸出 **long format**（可直接餵 block_chart(heatmap)）。

== When to use ==
- ✅ 「SPC xbar 跟哪個 APC param 相關性最高」→ columns=[spc_xbar_chart_value, apc_rf_power_bias, ...]
- ✅ 「DC sensor 之間共線性分析」→ 多個 dc_* 欄位計算
- ✅ 直接接 heatmap：chart_type=heatmap, x=col_a, y=col_b, value_column=correlation
- ❌ 要單一 x,y 迴歸（含 R²、residual、CI band）→ 用 block_linear_regression
- ❌ 類別欄獨立性（chi-square）→ 用 block_hypothesis_test(test_type=''chi_square'')

== Params ==
columns (array, opt) 要納入的數值欄位 — **省略 = 全部數值欄**（逗號字串也接受）
method  (string, default ''pearson'') pearson | spearman | kendall
target  (string, opt) **排行模式**：「哪些欄位跟 X 最相關」— 給了 target 輸出改為
        每欄 vs target 一列：column / correlation / abs_corr / p_value / n（依 abs_corr 降冪）

== Output ==
port: matrix (dataframe, long) — 每 pair 一列：
  col_a       (string)  第一欄名
  col_b       (string)  第二欄名
  correlation (number)  相關係數 [-1, 1]
  p_value     (number)  顯著性
  n           (integer) 有效樣本數

== Common mistakes ==
⚠ 輸出是 long format（每 pair 一列），不是 wide matrix；heatmap 正好吃 long
⚠ columns 必須是**數值欄**；字串欄 pearson 會出錯（spearman/kendall 也要 rankable）
⚠ 欄位有 NaN 會被 pairwise drop；n 可能每 pair 不同
⚠ 輸出 port 叫 `matrix`，不是 `data`

== Errors ==
- COLUMN_NOT_FOUND  : columns 有欄位不存在
- INSUFFICIENT_DATA : pair 有效樣本 < 3
- INVALID_COL_TYPE  : 欄位非數值
', param_schema = '{"type": "object", "required": [], "properties": {"columns": {"type": "array", "items": {"type": "string"}, "title": "納入欄位（省略=全部數值欄）"}, "method": {"type": "string", "enum": ["pearson", "spearman", "kendall"], "default": "pearson"}, "target": {"type": "string", "title": "排行模式：每欄 vs 這個欄位的相關排行", "x-column-source": "input.data"}}}' WHERE name = 'block_correlation';
UPDATE pb_blocks SET description = '== What ==
把 upstream DataFrame 釘到 Pipeline Results 視圖區; 每 row 一個顯示 row,
欄位以原值呈現 (text / number / bool)。比 block_chart(chart_type=''table'')
輕量, 不需 chart_type/x/y 設定。

**呈現限制 (極重要)**: nested list / nested dict 欄位以 **raw JSON 字串**
顯示, **不會自動展開**。若想以多 row 形式呈現 nested 內容 (例如某 column
是 list of dicts, 你想每 dict 占一 row), 上游必須先 unnest / explode 該
column, 再接 data_view。

== When to use ==
- ✅ Diagnostic Rule 要把「最近 N 筆 process 資料」當輸出秀給工程師
- ✅ 想 audit 某個中間 node 的輸出（接一條邊過去即可，純顯示用）
- ✅ 比 block_chart(chart_type=''table'') **更輕量**：沒有 chart schema 的包袱
- ❌ 要視覺化（line/bar/heatmap 等）→ 用 block_chart
- ❌ 要發告警 record → 用 block_alert
- ❌ 純中間計算（沒要給人看）→ 不需要 data_view

== Multiple views ==
同一 pipeline 可以放多個 block_data_view（例如一個秀原始 5 筆 + 一個秀 Filter 後的 3 筆）。
用 `sequence` 參數控制呈現順序（ascending；未指定則以 canvas position.x 為 tiebreak）。

== Params ==
title       (string, opt, default ''Data View'') 標題
description (string, opt) 副標
columns     (array, opt) 要顯示的欄位清單；未給則全部
max_rows    (integer, opt, default 200, min 1) 最多顯示列數
sequence    (integer, opt) 多視圖時的排序（ascending）

== Output ==
port: data_view (dict) — Pipeline Results 自動收集到 result_summary.data_views；
前端以表格呈現（含 title + description + columns + rows）

== Common mistakes ==
⚠ columns 指定不存在的欄位會被忽略（不 fail）
⚠ max_rows 預設 200；大型 df 先 filter/limit 再接，避免 UI 卡頓
⚠ sequence 整數非連續也 OK；只看相對大小決定順序
⚠ 輸出 port 是 `data_view`（dict），不是 dataframe；不能當下游 dataframe 輸入

== Errors ==
（鮮少 fail，主要是上游無 data 才空表）
highlight_rules (array, opt) 條件格式化：[{column, operator, value, background?, text_color?}]
  例：spc_status == ''OOC'' 紅底 — 該欄 cell 命中即套色（operator 同 block_filter；表單有預設色可選）
', param_schema = '{"type": "object", "properties": {"title": {"type": "string", "title": "標題（預設 ''Data View''）"}, "description": {"type": "string", "title": "副標（選填）"}, "columns": {"type": "array", "items": {"type": "string"}, "title": "要顯示的欄位（未指定則全部）"}, "highlight_rules": {"type": "array", "title": "條件格式化 — 命中的 cell 套色"}, "max_rows": {"type": "integer", "minimum": 1, "default": 200, "title": "最多顯示列數（預設 200）"}, "sequence": {"type": "integer", "title": "多視圖時的排序（ascending）"}}}' WHERE name = 'block_data_view';
UPDATE pb_blocks SET description = '== What ==
Line / multi-line chart with optional control rules + highlight overlay.
Output `chart_spec` with type=''line'' that the SVG engine renders via
the dedicated LineChart component.

== When to use ==
- ✅ 純時序趨勢（thickness over time / count per hour / event_time vs value）
- ✅ 多條線疊圖（y 是 array，e.g. xbar + ucl + lcl 都當 y series）
- ✅ 雙 Y 軸（y_secondary 給第二軸 series，e.g. SPC 值 + APC 補償）
- ✅ 「同一張圖」按某欄位上多條彩色線：series_field=''toolID''
- ✅ 「拆成 N 張獨立小圖」按某欄位 group：facet=''chart_name''
       (e.g. SPC long-form 一次出 X̄/R/S/P/C 5 張**分開的** trend chart)
- ⚠ series_field vs facet 的選擇：
       使用者說「分開」「各自一張」「別放同張」→ 用 facet（產出多張 panel）
       使用者說「疊在一起比較」「不同顏色」「同張圖」→ 用 series_field
- ❌ 嚴格的 SPC X̄/R 控制圖（subgroup 算 σ + WECO） → 用 block_xbar_r
- ❌ 純值分佈 → 用 block_histogram_chart

== Params ==
x:                 string, opt — x 軸欄位（time / index / category）。**省略或填 ''sequence'' = 照資料順序 1..N 當 x**（資料沒有時間欄時用這個，不要硬湊）。給欄位名時必須是 input dataframe 真實欄位名
y:                 string | string[], required — y series 欄位。**必須是 input dataframe 真實欄位名**
y_secondary:       string[], opt — 右側 y 軸 series
style.dashed_series:  string[], opt — 指定哪幾條 series 虛線（名稱=圖例名）；style.line_style=''dash'' 是全部虛線
series_field:      string, opt — group rows 出多條 color trace。**必須是 input dataframe 真實欄位名**
                  常用範例：
                    - SPC unnest(''spc_charts'') 後想分顏色 → series_field=''name'' (chart 名稱 leaf)
                    - 多機台同圖比較 → series_field=''toolID''
                    - 多 lot → series_field=''lotID''
                  ⚠ 不要寫 ''spc_name''/''chart_name''/''spc_id'' — unnest spc_charts 的 leaf 叫 `name`
rules:             array, opt — [{value, label, style?, color?}] 水平參考線
highlight_field:   string, opt — bool 欄位（matched rows 紅圈 overlay）
highlight_eq:      any, opt — match 條件值，預設 true
ucl_column:        string, opt — 取 column 第一筆當 UCL rule 線（SPC 簡寫）
lcl_column:        string, opt — 同上，LCL
center_column:     string, opt — 同上，Center
highlight_column:  string, opt — 同 highlight_field（block_chart 舊名）
facet:             string, opt — 按此欄位 group → 一個 group 一張獨立小圖
                  （e.g. SPC long-form 用 facet=''chart_name'' 一次出 X̄/R/S/P/C 5 張）
title:             string, opt

== Style（外觀由參數控制） ==
style:             object, opt — 圖表外觀：
  spc_zones:      bool — σ 區帶 Zone A/B/C 上色。有管制線時預設 true
                  （標準 SPC 管制圖慣例）；使用者要「簡潔/不要區帶」→ 設 false
  line_style:     ''solid''|''dash''|''step'' — 主線線型
  show_markers:   bool；marker_size: ''small''|''medium''|''large''
  x_label / y_label: string — 軸標題（含單位，e.g. ''xbar (nm)''）
tooltip_fields:    string[], opt, max 5 — 滑鼠提示額外顯示的欄位
                  （e.g. [''lotID'',''recipe'']）。必須是資料真實欄位名，
                  錯欄位會回報可用欄位清單
weco_annotate:     bool, opt — 違規點的提示顯示違規說明
                  （「違反 R1：單點超出 UCL」）

== Output ==
chart_spec (dict | dict[]): type=''line'', data, x, y, …
  facet 啟用時 chart_spec 是 list；frontend 攤平成多張 panel

== Keywords ==
time series 时序 時序, trend 趋势 趨勢, line chart 折线图 折線圖, multi-line, dual-axis 双轴 雙軸, facet small multiples 小倍数 小倍數
', param_schema = '{"type": "object", "required": ["y"], "properties": {"x": {"type": "string", "title": "x 欄位；省略或填 ''sequence'' = 照資料順序 1..N（不需要時間欄）"}, "y": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}, "y_secondary": {"type": "array", "items": {"type": "string"}}, "series_field": {"type": "string"}, "rules": {"type": "array"}, "highlight_field": {"type": "string"}, "highlight_eq": {}, "ucl_column": {"type": "string", "x-column-source": "input.data"}, "lcl_column": {"type": "string", "x-column-source": "input.data"}, "center_column": {"type": "string", "x-column-source": "input.data"}, "highlight_column": {"type": "string", "x-column-source": "input.data"}, "facet": {"type": "string", "title": "facet — split into N panels by column"}, "title": {"type": "string"}, "style": {"type": "object", "properties": {"spc_zones": {"type": "boolean"}, "line_style": {"type": "string", "enum": ["solid", "dash", "step"]}, "show_markers": {"type": "boolean"}, "marker_size": {"type": "string", "enum": ["small", "medium", "large"]}, "show_values": {"type": "boolean"}, "x_label": {"type": "string"}, "y_label": {"type": "string"}}}, "tooltip_fields": {"type": "array", "items": {"type": "string"}, "maxItems": 5}, "weco_annotate": {"type": "boolean"}}}' WHERE name = 'block_line_chart';
UPDATE pb_blocks SET description = '== What ==
對上游 dataframe **加一個衍生 column**，值由 expression tree 算出。
這是「純值運算」的 primitive — 給下游 rolling_window / threshold / groupby
一個明確的 numeric / boolean 欄位可吃。

== When to use ==
- ✅ 從 `spc_status` 衍生 `spc_is_any_ooc = (spc_status != ''PASS'') as int` 讓 rolling_sum 可用
- ✅ 合併多個 boolean column：`is_any_spc_ooc = xbar_ooc OR r_ooc OR s_ooc`
- ✅ 將字串 cast 成數值 / 反之：`v_num = as_float(v_str)`
- ❌ 做 group 統計 → 用 block_groupby_agg
- ❌ 複雜 regex / apply → 超出本 block 能力

== Params ==
column      (string, 必填) **產出的新欄位名稱**（不是來源欄位；來源寫在 expression 的 {column} 節點）
expression  (object, 必填) expression tree，節點三種：
  literal            42, ''PASS'', true, null, [..]
  column ref         {column: ''spc_status''}
  op node            {op: ''<name>'', operands: [...]}

== Ops ==
Comparison: eq ne gt gte lt lte
Logical:    and or not
Set:        in not_in     (第二參數為 list)
Arithmetic: add sub mul div abs（abs 單一 operand）
Cast:       as_int as_float as_str as_bool
Null:       coalesce is_null is_not_null
String:     concat（operands 逐個轉字串相接，例 {op:''concat'', operands:[{column:''toolID''}, ''-'', {column:''step''}]}）
Cond:       if（3 個 operands：[條件, 成立值, 不成立值]，例 {op:''if'', operands:[{op:''eq'',operands:[{column:''spc_status''},''OOC'']}, 1, 0]}）

== Output ==
port: data (dataframe)    原 df + 一個新 column

== Example ==
加 `spc_is_any_ooc`：
  {
    "column": "spc_is_any_ooc",
    "expression": {
      "op": "as_int",
      "operands": [{
        "op": "ne",
        "operands": [{"column": "spc_status"}, "PASS"]
      }]
    }
  }
', param_schema = '{"type": "object", "required": ["column", "expression"], "properties": {"column": {"type": "string", "title": "新欄位名稱"}, "expression": {"type": "object", "title": "Expression tree"}}}' WHERE name = 'block_compute';
INSERT INTO pb_blocks (name, category, version, status, description, input_schema, output_schema, param_schema, implementation, examples, output_columns_hint)
SELECT 'block_streak', 'transform', '1.0.0', 'production', '== What ==
連續上升/下降偵測（run length）— 每列輸出「目前同方向連續了幾步」。

== When to use ==
- ✅ 「連續 5 筆上升就告警」→ 我 + block_filter(<col>_streak_len >= 5 且 dir==''up'')
- ✅ 「找連跌最久的機台」→ group_by=''toolID'' + sort/find max streak_len
- ❌ 只要單點漲跌旗標 → 用 block_delta（is_rising/is_falling）
- ❌ 「**最近** N 筆連續 X 就告警」（tail 型、要 triggered bool）→ 用 block_consecutive_rule；我是**歷史全掃** run length（每列都有 streak_len）
- ❌ SPC 圖上的趨勢視覺警示 → xbar_r / imr 內建 WECO trend rule

== Params ==
value_column (string, required) 數值欄
sort_by      (string, required) 排序欄（時間或序號；嚴禁隱式預設）
group_by     (string | list, opt) 各組內獨立計算（例：每台機台）

== Output ==
port: data (dataframe) — 原欄 + 2 欄：
  <col>_streak_dir (string)  ''up'' | ''down'' | ''flat''（跟前一筆比）
  <col>_streak_len (integer) 目前同方向連續步數（首筆/flat = 0）
  例：值 1,2,3,3,2 → dir flat,up,up,flat,down；len 0,1,2,0,1

== Keywords ==
連續上升 連續下降 consecutive rising falling streak run trend 連漲 連跌
', '[{"port": "data", "type": "dataframe"}]', '[{"port": "data", "type": "dataframe"}]', '{"type": "object", "required": ["value_column", "sort_by"], "properties": {"value_column": {"type": "string", "x-column-source": "input.data"}, "sort_by": {"type": "string", "x-column-source": "input.data"}, "group_by": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}}}', '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.streak:StreakBlockExecutor"}', '[]', '[]'
WHERE NOT EXISTS (SELECT 1 FROM pb_blocks WHERE name = 'block_streak');
