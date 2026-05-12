-- V38 — 2026-05-13 Object-native pipeline (Phase 1):
--   1. Add 3 path navigation blocks (block_pluck, block_unnest, block_select)
--   2. Update block_filter operator enum to accept '=' alongside '=='
--   3. Mark block_count_rows as deprecated (replaced by block_compute / step_check.count)
--
-- Background: previous flat-table model forced LLM into JOIN + GROUP BY for
-- naturally hierarchical questions like "this process has N SPC charts, count
-- OOC". We now treat the pipeline data type as `list of arbitrarily nested
-- objects`, with path syntax `a.b` / `a[].b` everywhere a column ref is
-- accepted. These three blocks let the LLM extract, explode, or reshape
-- nested objects without resorting to JOIN gymnastics.

-- ── 1. block_pluck ────────────────────────────────────────────────────
DELETE FROM pb_blocks WHERE name = 'block_pluck';
INSERT INTO pb_blocks (
  name, category, version, status, description,
  input_schema, output_schema, param_schema,
  implementation, examples, output_columns_hint, is_custom
) VALUES (
  'block_pluck',
  'transform',
  '1.0.0',
  'production',
  $$== What ==
Extract a (possibly nested) field from each record into a single-column DataFrame.
Path syntax supports dot + array brackets — works on object-native data.

== When to use ==
- ✅ 「我只要 spc_summary.ooc_count 這欄」→ path='spc_summary.ooc_count'
- ✅ 「每張 process 的所有 chart 名稱」→ path='spc_charts[].name' (column 變 list-of-strings)
- ✅ 想把寬表瘦身（只留一欄）給下游 chart / 計算用
- ❌ 想要多個欄位 → 用 block_select
- ❌ 想要把 array 展平成多筆 record → 用 block_unnest（pluck 保留 list 在 cell 內）

== Params ==
path        (string, required) 例 'tool_id' / 'spc_summary.ooc_count' / 'spc_charts[].name'
as_column   (string, opt) 輸出欄位名稱（預設 = path 最後一段，e.g. 'ooc_count'）
keep_other  (boolean, default=false) 是否保留原本所有欄位（false=只剩 pluck 出的這一欄）

== Output ==
port: data (dataframe)

== Errors ==
- COLUMN_NOT_FOUND : path 第一段不在 input 欄位中$$,
  $$[{"port": "data", "type": "dataframe", "required": true}]$$,
  $$[{"port": "data", "type": "dataframe"}]$$,
  $${
    "type": "object",
    "required": ["path"],
    "properties": {
      "path": {"type": "string", "description": "Field path (dot syntax, [] for arrays)"},
      "as_column": {"type": "string"},
      "keep_other": {"type": "boolean", "default": false}
    }
  }$$,
  'native:block_pluck',
  $$[
    {"title": "Extract nested ooc_count", "params": {"path": "spc_summary.ooc_count"}},
    {"title": "Pluck chart names", "params": {"path": "spc_charts[].name", "as_column": "chart_names"}}
  ]$$,
  $$[
    {"name": "<as_column>", "type": "any", "description": "Plucked value(s)"}
  ]$$,
  FALSE
);

-- ── 2. block_unnest ───────────────────────────────────────────────────
DELETE FROM pb_blocks WHERE name = 'block_unnest';
INSERT INTO pb_blocks (
  name, category, version, status, description,
  input_schema, output_schema, param_schema,
  implementation, examples, output_columns_hint, is_custom
) VALUES (
  'block_unnest',
  'transform',
  '1.0.0',
  'production',
  $$== What ==
Explode an array-typed column into multiple rows. Sibling columns broadcast.
If array elements are dicts, their keys lift to top-level columns automatically —
so `[{tool: A, charts: [{name: X}, {name: Y}]}]` →
`[{tool: A, name: X}, {tool: A, name: Y}]`.

== When to use ==
- ✅ 「想 group by spc_charts[].name 算 OOC 次數」→ 先 unnest spc_charts，再 groupby_agg
- ✅ 「想 filter 哪些 chart 是 OOC」→ 先 unnest，再 filter status=='OOC'
- ✅ 任何 array field 想做 per-element analysis
- ❌ 只想拿 array 不展開 → 用 block_pluck
- ❌ 已經是扁平表 → 不用 unnest

== Params ==
column (string, required) array column 名稱（可以是 path：'spc_charts'、'spc_charts[]'、或 'obj.list_field'）

== Output ==
port: data (dataframe) — 多筆 rows，每個 array element 一筆。array 元素若是 object 則 keys 自動展為欄位。

== Errors ==
- COLUMN_NOT_FOUND : column 不在 input$$,
  $$[{"port": "data", "type": "dataframe", "required": true}]$$,
  $$[{"port": "data", "type": "dataframe"}]$$,
  $${
    "type": "object",
    "required": ["column"],
    "properties": {
      "column": {"type": "string", "description": "Array column or path to explode"}
    }
  }$$,
  'native:block_unnest',
  $$[
    {"title": "Explode spc_charts", "params": {"column": "spc_charts"}}
  ]$$,
  $$[]$$,
  FALSE
);

-- ── 3. block_select ───────────────────────────────────────────────────
DELETE FROM pb_blocks WHERE name = 'block_select';
INSERT INTO pb_blocks (
  name, category, version, status, description,
  input_schema, output_schema, param_schema,
  implementation, examples, output_columns_hint, is_custom
) VALUES (
  'block_select',
  'transform',
  '1.0.0',
  'production',
  $$== What ==
Project / rename fields — jq-lite for objects. Drops every column not listed.
Each field entry is {path, as?} — path supports dot + [] syntax.

== When to use ==
- ✅ 想瘦身一個寬表（35 欄變 3 欄）給下游 chart
- ✅ 想把 nested field 拉到 top-level + 改名 (e.g. spc_summary.ooc_count → ooc_count)
- ✅ 重組 shape 後丟給 block_mcp_call args
- ❌ 想保留所有欄位只新增一個 → 用 block_compute
- ❌ 只要一個欄位 → block_pluck 更輕

== Params ==
fields (array, required) [{path: 'x', as: 'y'}, ...] — 每個 entry 必填 path，as 預設 = path 最後一段

== Output ==
port: data (dataframe) — 只包含 selected fields，按 fields 順序排列

== Errors ==
- COLUMN_NOT_FOUND : 任一 path 不在 input
- INVALID_PARAM    : fields 不是 list 或 entry shape 錯$$,
  $$[{"port": "data", "type": "dataframe", "required": true}]$$,
  $$[{"port": "data", "type": "dataframe"}]$$,
  $${
    "type": "object",
    "required": ["fields"],
    "properties": {
      "fields": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["path"],
          "properties": {
            "path": {"type": "string"},
            "as": {"type": "string"}
          }
        },
        "minItems": 1
      }
    }
  }$$,
  'native:block_select',
  $$[
    {"title": "Flatten + rename", "params": {"fields": [{"path": "tool_id"}, {"path": "spc_summary.ooc_count", "as": "ooc_count"}]}}
  ]$$,
  $$[]$$,
  FALSE
);

-- ── 4. block_filter: accept '=' alongside '==' ────────────────────────
-- Q1 from architectural review: LLMs trained on SQL use '=' while ones
-- trained on Python use '=='. Same semantics — sidecar executor already
-- treats them as aliases (filter.py L21-22). Update DB description +
-- param_schema enum so the catalog displays both.
UPDATE pb_blocks
SET param_schema = jsonb_set(
      param_schema::jsonb,
      '{properties,operator,enum}',
      '["==", "=", "!=", ">", "<", ">=", "<=", "contains", "in"]'::jsonb,
      false
    )::text,
    updated_at = now()
WHERE name = 'block_filter';

UPDATE pb_blocks
SET description = REPLACE(description,
  'operator (string, required) ==, !=, >, <, >=, <=, contains, in',
  'operator (string, required) == (or =), !=, >, <, >=, <=, contains, in (`=` is alias for `==`)'
),
    updated_at = now()
WHERE name = 'block_filter'
  AND description LIKE '%operator (string, required) ==, !=, >, <, >=, <=, contains, in%';

-- ── 5. block_count_rows: deprecate ────────────────────────────────────
-- Q2 from architectural review: 同質功能太多會讓 LLM confused. Replaced
-- by block_step_check(aggregate='count') for verdict-emitting use, or
-- block_compute({"op": "length", ...}) for keeping the count as a column.
UPDATE pb_blocks
SET status = 'deprecated',
    description = '⚠ DEPRECATED — use block_step_check(aggregate=''count'') for ' ||
                  'verdict-emitting counters, or wrap an upstream + block_compute ' ||
                  'for keeping count as a column.' || E'\n\n' || description,
    updated_at = now()
WHERE name = 'block_count_rows' AND status != 'deprecated';
