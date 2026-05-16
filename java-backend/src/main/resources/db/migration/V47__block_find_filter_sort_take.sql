-- V47 — 2026-05-16: block_find — 1-block filter + (optional) sort + take.
--
-- Background:
--   EQP-08 lastooc trace showed LLM building "find latest OOC event" as
--   filter → sort(desc) → limit=1 — three nodes for one obvious task.
--   When the LLM dropped the sort or got order_dir wrong, the verifier
--   advanced on "last" semantics with 13/87 rows (B2 judge later caught
--   this, but the upstream cause was missing primitive).
--
--   block_find collapses the trio into one block with explicit `take`
--   semantics. Doc-only; backed by FindBlockExecutor in sidecar
--   pipeline_builder/blocks/find.py.
--
-- Usage examples:
--   "找最後一次 OOC 事件" → block_find(column='spc_status', operator='==',
--      value='OOC', order_by='eventTime', order_dir='desc', take='last')
--   "找全部 PASS events"  → block_find(column='spc_status', operator='==',
--      value='PASS', take='all')   # equivalent to block_filter
--   "top 5 by score"      → block_find(column='status', operator='==',
--      value='OK', order_by='score', order_dir='desc', take=5)

DELETE FROM pb_blocks WHERE name = 'block_find';
INSERT INTO pb_blocks (
  name, category, version, status, description,
  input_schema, output_schema, param_schema,
  implementation, examples, output_columns_hint, is_custom
) VALUES (
  'block_find',
  'transform',
  '1.0.0',
  'production',
  $$== What ==
**1-block find specific rows** — filter by condition + optional sort + take first/last/all/N，取代 filter+sort+limit 3 步常見組合。

== Params ==
column     (string, required) 要比較的欄位 (支援 nested path e.g. 'spc_summary.ooc_count')
operator   (string, required) ==, =, !=, >, <, >=, <=, contains, in
value      (any, required) 比較值；operator='in' 時是 list；boolean 欄位請給 True/False
order_by   (string, optional) 排序欄位；省略 = 不排序 (input 順序)
order_dir  (enum 'asc'|'desc', default 'desc') 排序方向；常見 'desc' 取最新
take       (enum 'first'|'last'|'all' | int N, default 'all')
             - 'all' = 等價於 block_filter
             - 'first' = 取 1 row (sort 後的第一筆)
             - 'last'  = 取 1 row (sort 後的最後一筆)
             - int N   = 取 top N rows

== When to use ==
- [best] 「找最後一次 OOC」「找最新一筆違規」「找第一個 alarm」→ 我（filter+sort+take 1 步搞定）
- [best] 「top N by score」「最近 5 筆 events」→ 我 + take=N
- [ok]   全部符合條件的 rows (不排序、不取 N) → 用我 take='all' 或更輕量的 block_filter
- [no]   多欄複合排序（先 A asc 再 B desc） → 用 block_sort，本 block 只支援單欄
- [no]   要 evidence + triggered 雙 port → block_threshold
- [no]   多條件 AND/OR 組合 → 多個 block_filter 串接

== Output ==
port: data (dataframe) — 過濾後 (可選排序、可選取 N) 的 rows

== Errors ==
- COLUMN_NOT_FOUND  : column / order_by 名稱錯
- INVALID_PARAM     : take 不是 'first'/'last'/'all'/int N，或 order_dir 不是 'asc'/'desc'$$,
  $$[{"port": "data", "type": "dataframe", "required": true}]$$,
  $$[{"port": "data", "type": "dataframe"}]$$,
  $${
    "type": "object",
    "required": ["column", "operator"],
    "properties": {
      "column":    {"type": "string", "x-column-source": "input.data", "title": "欄位"},
      "operator":  {
        "type": "string",
        "enum": ["==", "=", "!=", ">", "<", ">=", "<=", "contains", "in"],
        "title": "比較運算"
      },
      "value":     {"title": "比較值"},
      "order_by":  {"type": "string", "title": "排序欄位 (選填)"},
      "order_dir": {
        "type": "string",
        "enum": ["asc", "desc"],
        "default": "desc",
        "title": "排序方向"
      },
      "take": {
        "anyOf": [
          {"type": "string", "enum": ["first", "last", "all"]},
          {"type": "integer", "minimum": 1}
        ],
        "default": "all",
        "title": "取多少 (first/last/all/N)"
      }
    }
  }$$,
  $${"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.find:FindBlockExecutor"}$$,
  $$[
    {"label": "找最後一次 OOC SPC event",
     "params": {"column": "spc_status", "operator": "==", "value": "OOC",
                "order_by": "eventTime", "order_dir": "desc", "take": "last"}},
    {"label": "找最早一筆違規 lot",
     "params": {"column": "violated", "operator": "==", "value": true,
                "order_by": "eventTime", "order_dir": "asc", "take": "first"}},
    {"label": "全部 PASS events (等價 block_filter)",
     "params": {"column": "spc_status", "operator": "==", "value": "PASS",
                "take": "all"}},
    {"label": "top 5 by score",
     "params": {"column": "status", "operator": "==", "value": "OK",
                "order_by": "score", "order_dir": "desc", "take": 5}}
  ]$$,
  '[]',
  false
);
