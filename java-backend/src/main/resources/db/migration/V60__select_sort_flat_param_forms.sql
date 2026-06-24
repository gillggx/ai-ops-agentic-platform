-- AUTO-GENERATED from seed.py (tools/gen_block_seed_sql.py sibling).
-- Sync block_select.fields + block_sort.columns to the flat-string-OR-object
-- form (2026-06-24). UPDATE only — canonical seed is insert-only and won't
-- refresh existing rows; the agent reads description/param_schema from pb_blocks.
BEGIN;
UPDATE pb_blocks SET description = $BLKUPD$== What ==
Project / rename fields — jq-lite for objects. Drops every column not listed.
fields is a flat list of path strings, e.g. ["RECIPE.objectID", "etch_time_offset"].
Path supports dot + [] syntax. To RENAME a field, use the object form
{path, as} for just that one (mix freely): ["tool_id", {"path": "spc_summary.ooc_count", "as": "ooc_count"}].

== When to use ==
- ✅ 想瘦身一個寬表（35 欄變 3 欄）給下游 chart
- ✅ 想把 nested field 拉到 top-level + 改名 (e.g. spc_summary.ooc_count → ooc_count)
- ✅ 重組 shape 後丟給 block_mcp_call args
- ❌ 想保留所有欄位只新增一個 → 用 block_compute
- ❌ 只要一個欄位 → block_pluck 更輕

== Params ==
fields (array, required) — 扁平字串清單即可，例 ["RECIPE.objectID", "etch_time_offset"]。
  要改名才用物件形 {path, as}（可與字串混用）；as 預設 = path 最後一段。

== Output ==
port: data (dataframe) — 只包含 selected fields，按 fields 順序排列
⚠ **被丟掉的欄位下游就拿不到了**。如果下游 chart 需要 'value' / 'ucl' / 'lcl' 之類欄位，select 的 fields 一定要把這些欄位都列進來，否則 chart 會 'COLUMN_NOT_FOUND'。
👉 多數情況**不需要 block_select**（block_chart 自己會挑欄位）；只在你**真的**要刪欄位 （瘦身 / 重組 shape 給 mcp_call）才用。

== Errors ==
- COLUMN_NOT_FOUND : 任一 path 不在 input
- INVALID_PARAM    : fields 不是 list 或 entry shape 錯
$BLKUPD$,
  param_schema = $BLKUPD${"type": "object", "required": ["fields"], "properties": {"fields": {"type": "array", "x-fields-editor": true, "items": {"oneOf": [{"type": "string"}, {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}, "as": {"type": "string"}}}]}, "minItems": 1}}}$BLKUPD$,
  examples = $BLKUPD$[{"label": "Pick fields (flat — the common case)", "params": {"fields": ["RECIPE.objectID", "etch_time_offset"]}}, {"label": "Rename a nested field (object form for `as`)", "params": {"fields": ["tool_id", {"path": "spc_summary.ooc_count", "as": "ooc_count"}]}}]$BLKUPD$
WHERE name = 'block_select';
UPDATE pb_blocks SET description = $BLKUPD$== What ==
多欄排序 + optional top-N cap。用於 ranking / leaderboard 場景。

== When to use ==
- ✅ 多欄排序：先按 toolID asc 再按 eventTime desc → 必須用我（block_find 只支援單欄）
- ✅ 「按 eventTime asc 重排整張表」(不過濾、不取 N) → 用我
- ✅ 「OOC 最多的 3 台機台」→ groupby_agg count → 我 sort(desc) + limit=3
- ❌ 「找最後一次 OOC / 最早一筆違規 / top N by X」(filter+sort+取 1 row) → 用 block_find，一步搞定
- ❌ 需要 is_rising / lag / delta → 用 block_delta / block_shift_lag（那些內含 sort）
- ❌ 過濾 rows（非排序取 top） → 用 block_filter

== Params ==
columns (array, required) — 預設 asc 時用扁平字串清單即可，例 ['ooc_count'] 或 ['toolID','eventTime']。
  要指定方向才用物件形 {column, order='asc'|'desc'}（可與字串混用）：
  e.g. ['ooc_count'] (asc) ；e.g. [{'column':'ooc_count','order':'desc'}] (desc)
  e.g. ['toolID', {'column':'eventTime','order':'desc'}]
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
⚠ **必填 param 叫 `columns` (複數，list)，不是 `column`**。寫 `column='eventTime'` 會 INVALID_SORT_SPEC
⚠ columns 是 list（字串 ['x'] 預設 asc，或物件 [{'column':'x','order':'desc'}]）
⚠ order 拼錯（'descending' / 'DESC'）會被預設成 'asc'
⚠ limit 不是 top；是 head(N) — 要 top 請先 desc 排序再 limit
⚠ 「找最後一次 X」這種 1-row 需求**不要用我**，請改 block_find（避免 LLM 漏寫 limit=1 拿到全表）
⚠ NaN 預設排到最後（pandas 行為）

== Errors ==
- COLUMN_NOT_FOUND : columns 有欄位不存在
- INVALID_SORT_SPEC: columns 結構不對（缺 column key）
$BLKUPD$,
  param_schema = $BLKUPD${"type": "object", "required": ["columns"], "properties": {"columns": {"type": "array", "title": "排序欄位 (字串清單，或 {column, order})", "items": {"oneOf": [{"type": "string"}, {"type": "object", "properties": {"column": {"type": "string"}, "order": {"type": "string", "enum": ["asc", "desc"], "default": "asc"}}}]}}, "limit": {"type": "integer", "minimum": 1, "title": "Top-N (選填)"}}}$BLKUPD$,
  examples = $BLKUPD$[{"title": "asc 排序 (扁平字串 — 最常見)", "params": {"columns": ["eventTime"]}}, {"title": "排序 by 單欄 desc + top-N (要方向用物件形)", "params": {"columns": [{"column": "ooc_count", "order": "desc"}], "limit": 3}}, {"title": "多欄混用 (toolID asc 字串, eventTime desc 物件)", "params": {"columns": ["toolID", {"column": "eventTime", "order": "desc"}]}}]$BLKUPD$
WHERE name = 'block_sort';
COMMIT;
