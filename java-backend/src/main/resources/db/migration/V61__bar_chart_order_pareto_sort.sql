-- AUTO-GENERATED from seed.py (hardening #1, 2026-06-25).
-- block_bar_chart: add `order` param (in-block ranking) + description teaching;
-- block_pareto: description note that it self-sorts. UPDATE only (Flyway
-- disabled in prod -> apply manually via psql on EC2). Agent reads
-- description/param_schema from pb_blocks, so this is what makes it take effect.
BEGIN;
UPDATE pb_blocks SET description = $DESC$== What ==
Categorical bar / grouped-bar chart. Multiple `y` columns produce side-by-
side grouped bars per category.

== When to use ==
- ✅ 「按 EQP 比較 OOC count」「每個 step 的 alarm 數」
- ✅ 「OOC 最多的機台 由多到少」「top-N 排名」「ranking」→ 設 order='desc'，
     **本 block 自己排序，不需要另接 block_sort**
- ❌ 排序 + 累計 % 的 80/20 分析 → 用 block_pareto（自動排序 + 累計線）
- ❌ 連續時間軸 → 用 block_line_chart

== Params ==
x:               string, required — 類別欄位。**必須是 input dataframe 真實欄位名**
y:               string | string[], required — bar 高度欄位。**必須是 input dataframe 真實欄位名**
order:           'none'|'asc'|'desc', default 'none' — 依第一個 y 值排序 bars。
                 「由多到少 / 最多 / 排名 / top-N」→ desc；**設了就不必另接 block_sort**
rules:           array, opt — 水平 threshold 線
highlight_field/highlight_eq: 同 line_chart
title:           string, opt

⚠ column ref 一律從 UPSTREAM TRACE 取真實欄位名，不要從 macro_plan.expected_cols 取

== Keywords ==
bar chart 长条图 長條圖 柱状图 柱狀圖, comparison 比较 比較, count 计数 計數, ranking 排名, categorical 类别 類別
$DESC$,
    param_schema = $PS${"type": "object", "required": ["x", "y"], "properties": {"x": {"type": "string"}, "y": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}, "order": {"type": "string", "enum": ["none", "asc", "desc"], "default": "none"}, "rules": {"type": "array"}, "highlight_field": {"type": "string"}, "highlight_eq": {}, "title": {"type": "string"}}}$PS$
  WHERE name = 'block_bar_chart' AND version = '1.0.0';
UPDATE pb_blocks SET description = $DESC$== What ==
Pareto chart — 遞減排序 bars + 累計 % line + 80% 參考線。「找最大貢獻者」場景必備。
（本 block 自己依 value 由大到小排序，**上游不需要另接 block_sort**。）

== When to use ==
- ✅ 「最常見的缺陷類型」「哪幾台機台貢獻 80% OOC」「lot 失敗 root cause」
- ❌ 順序固定的類別（時間 / step) → 用 block_bar_chart

== Params ==
category_column:        string, required — 類別欄位
value_column:           string, required — 計數欄位
cumulative_threshold:   number, default 80 — 紅色參考線（80/20 rule）
title:                  string, opt

== Keywords ==
Pareto, 80/20, top-N, ranking 排序, cumulative 累计 累計, root cause 主要原因 主要因素, contributor 贡献 貢獻, frequency analysis 频率分析 頻率分析
$DESC$,
    param_schema = $PS${"type": "object", "required": ["category_column", "value_column"], "properties": {"category_column": {"type": "string"}, "value_column": {"type": "string"}, "cumulative_threshold": {"type": "number", "minimum": 0, "maximum": 100, "default": 80}, "title": {"type": "string"}}}$PS$
  WHERE name = 'block_pareto' AND version = '1.0.0';
COMMIT;
