-- V48 — 2026-05-16: tighten block_filter / block_sort descriptions + add filter examples.
--
-- Background:
--   EQP-08 trace_replay showed LLM picking wrong shape:
--   - block_sort: writing singular `column='X'` instead of `columns=[{...}]`
--   - block_filter: guessing wrong value type per operator (e.g. 'in' with string)
--
--   V47 added block_find which collapses filter+sort+take(1) for the common
--   "find latest matching row" pattern. This V48 cross-references block_find
--   from filter/sort so LLM sees the right tool for 1-row needs.
--
--   block_filter additionally gets an `examples` array — same pattern that
--   solved block_sort's mistakes (V?? Phase 11 v15): catalog formatter
--   inlines examples so LLM learns shape from data, not prompt.
--
-- (block_count_rows.covers=[scalar,transform] is sidecar-only via produces
--  field; pb_blocks table has no `produces` column, so no DB UPDATE needed.)

-- ── 1. block_filter ────────────────────────────────────────────────────
UPDATE pb_blocks SET
  description = $$== What ==
根據 column/operator/value 過濾 DataFrame 列（單條件），保留符合條件的 rows。

== When to use ==
- ✅ 「只看 OOC events」→ column='spc_status', operator='==', value='OOC'
- ✅ 「只看特定 3 台機台」→ column='toolID', operator='in', value=['EQP-01','EQP-02','EQP-03']
- ✅ 「recipe 含 'ETCH' 字樣」→ operator='contains', value='ETCH'
- ✅ 「xbar 值超過 100」→ column='spc_xbar_chart_value', operator='>', value=100
- ❌ 多條件 AND/OR → 串多個 block_filter（目前不支援單一 block 內複合條件）
- ❌ 需要判斷 triggered (bool) + 輸出 evidence → 用 block_threshold，不是這個
- ❌ 「找最後一次 / 最早一筆 / top N by X」(filter + sort + 取 1 row) → 用 block_find 一步搞定

== Params ==
column   (string, required) 要比較的欄位
operator (string, required) == (or =), !=, >, <, >=, <=, contains, in (`=` is alias for `==`)
value    (any, required) 比較值；operator='in' 時必須是 list；'contains' 作 substring 比對（string only）

== Output ==
port: data (dataframe) — 只保留符合條件的 rows，欄位不變

== Choosing the right column ==
⚠ **column 必須是上游真正輸出的欄位名**。常見雷區：
  - 上游是 groupby_agg → 用 `<agg_column>_<agg_func>`（e.g. spc_status_count）
  - 上游是 count_rows → 'count'
  - 其它（source / pass-through transform）→ 用源頭欄位
  - 不確定 → 先 run_preview 上游 看 columns。
set_param 寫錯會丟 COLUMN_NOT_IN_UPSTREAM；hint 會列真實 columns。

== Common mistakes ==
⚠ 'in' 的 value 必須是 list（['a','b','c']），給 string 會出錯
⚠ column 名稱要完全一致（case-sensitive + snake_case）
⚠ 比較 boolean 欄位時 value 給 True/False（Python bool），不是字串 'True'
⚠ contains 只對 string column 有意義；數值欄位會出錯
⚠ **value 是 filter 專屬 param**；如果你要做的是「判斷有沒有違規 + 輸出 evidence」，不是過濾，請改用 block_threshold（threshold 用 'target' 或 'upper_bound'/'lower_bound'，不是 'value'）

== Errors ==
- COLUMN_NOT_FOUND : column 名稱打錯 / 上游沒這欄
- INVALID_OPERATOR : 用了 enum 外的 operator
- EMPTY_AFTER_FILTER : 過濾後 0 筆（放寬條件或檢查 value）$$,
  examples = $$[
    {"title": "等於 string (最常見)",
     "params": {"column": "spc_status", "operator": "==", "value": "OOC"}},
    {"title": "in: value 必須是 list",
     "params": {"column": "toolID", "operator": "in",
                "value": ["EQP-01", "EQP-02", "EQP-03"]}},
    {"title": "數值比較",
     "params": {"column": "score", "operator": ">", "value": 100}},
    {"title": "boolean 欄位 (給 True/False，不是 'True')",
     "params": {"column": "is_ooc", "operator": "==", "value": true}},
    {"title": "contains substring (僅 string 欄)",
     "params": {"column": "recipe", "operator": "contains", "value": "ETCH"}}
  ]$$
WHERE name = 'block_filter';

-- ── 2. block_sort ──────────────────────────────────────────────────────
UPDATE pb_blocks SET
  description = $$== What ==
多欄排序 + optional top-N cap。用於 ranking / leaderboard 場景。

== When to use ==
- ✅ 多欄排序：先按 toolID asc 再按 eventTime desc → 必須用我（block_find 只支援單欄）
- ✅ 「按 eventTime asc 重排整張表」(不過濾、不取 N) → 用我
- ✅ 「OOC 最多的 3 台機台」→ groupby_agg count → 我 sort(desc) + limit=3
- ❌ 「找最後一次 OOC / 最早一筆違規 / top N by X」(filter+sort+取 1 row) → 用 block_find，一步搞定
- ❌ 需要 is_rising / lag / delta → 用 block_delta / block_shift_lag（那些內含 sort）
- ❌ 過濾 rows（非排序取 top） → 用 block_filter

== Params ==
columns (array, required) list of {column, order='asc'|'desc'}
  e.g. [{'column':'ooc_count','order':'desc'}]
  e.g. [{'column':'toolID','order':'asc'}, {'column':'eventTime','order':'desc'}]
limit   (integer, opt, >= 1) 保留前 N 列

== Output ==
port: data (dataframe) — 排序後的 df；欄位不變，有 limit 則保留前 N 列

== Choosing the right column ==
⚠ **columns[].column 必須是上游真正輸出的欄位名**。寫錯就 auto-run
失敗。最常踩的雷：上游是 block_groupby_agg 時。
  - 上游 groupby_agg(agg_column='spc_status', agg_func='count')
    → output column 是 `spc_status_count`（NOT 'count'）
  - 上游 count_rows → column = 'count'（這個才是 'count'）
  - 上游 cpk → 'cpk' / 'cpu' / 'cpl' / 'mean' / 'std' / ...
  - 上游 source / filter / sort（pass-through）→ 用源頭 column
  - 不確定 → 先 run_preview 上游 node，看 columns 列表
set_param 會在你寫錯時丟 COLUMN_NOT_IN_UPSTREAM；hint 列出真實 columns。

== Common mistakes ==
⚠ **必填 param 叫 `columns` (複數，list of objects)，不是 `column`**。寫 `column='eventTime'` 會 INVALID_SORT_SPEC
⚠ columns 是 list of objects，不是 list of strings
⚠ order 拼錯（'descending' / 'DESC'）會被預設成 'asc'
⚠ limit 不是 top；是 head(N) — 要 top 請先 desc 排序再 limit
⚠ 「找最後一次 X」這種 1-row 需求**不要用我**，請改 block_find（避免 LLM 漏寫 limit=1 拿到全表）
⚠ NaN 預設排到最後（pandas 行為）

== Errors ==
- COLUMN_NOT_FOUND : columns 有欄位不存在
- INVALID_SORT_SPEC: columns 結構不對（缺 column key）$$
WHERE name = 'block_sort';
