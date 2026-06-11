-- V55 — 2026-06-12: ship the SLASH-17 baseline knowledge patches.
--
-- Background:
--   The 2026-06-11 SLASH-17 audit applied 4 block_docs edits + 3
--   agent_knowledge entries directly to EC2's DB to bring KIMI K2.5
--   tool-use compliance up to 17/17 pass. Flyway is disabled in prod
--   (memory: feedback_flyway_disabled_in_prod) so this migration files
--   those changes into the repo so future deployments (POC branches,
--   fresh EC2, K8s) reproduce the same baseline.
--
-- Contents:
--   - block_docs (4 entries): block_find, block_process_history,
--     block_mcp_foreach, block_sort  — frontmatter / param-name fixes
--     that bind LLM block-pick decisions
--   - agent_knowledge (3 entries id=35/36/37): plan-time RAG hints
--     covering SPC history-cap, cross-tool aggregation, multi-tool
--     tool_id=ALL anti-pattern
--
-- Idempotent:
--   block_docs uses (block_id, block_version) unique key with
--   ON CONFLICT DO UPDATE. agent_knowledge guards each INSERT with
--   NOT EXISTS on title.
--
-- Embeddings (agent_knowledge.embedding): the dumped vector values are
--   stored as text literals here; sidecar's embedding_backfill task
--   regenerates them automatically if NULL. We deliberately ship the
--   exact vectors from the validated 2026-06-11 run so a fresh deploy
--   gets immediate semantic match without waiting for backfill.

-- block_docs (4 entries — upsert on (block_id, block_version))

INSERT INTO public.block_docs (id, block_id, block_version, markdown, sections, auto_generated, last_edited_by, last_edited_at, created_at, updated_at) VALUES (29, 'block_sort', '1.0.0', '---
name: block_sort
description: Multi-column sorting with optional top-N cap. **Param `columns` MUST be a list of `{column, order}` dicts** — e.g. `columns=[{"column": "spc_status_count", "order": "desc"}]`. ⛔ 不要用 `sort_by=` / `order_dir=` / `column=` (singular) — 這些不是合法 param key，verifier 會 reject。 Invoke to rank aggregation results (e.g., OOC最多的3台機台), sort full tables by composite keys (e.g., toolID asc then eventTime desc), or reorder datasets without filtering. Do not invoke for single-row extraction (找最後一次/最早一筆)—use block_find instead; for lag/delta calculations—use block_shift_lag/block_delta; or for pure filtering—use block_filter.
---

# block_sort

Transform block that reorders upstream DataFrame by one or more columns in ascending or descending order, with optional row limit (head-N). Does not filter rows — simply rearranges and optionally truncates. Essential for ranking queries, leaderboard aggregation, and time-series reordering.

## When to invoke

- Multi-column sort: reorder by toolID (asc) then eventTime (desc) — `block_find` only supports single-column
- Reorder entire table by timestamp/sequence without filtering
- Rank aggregation: after `block_groupby_agg(agg_func=''count'')`, sort descending and limit to top-3 tools
- Terminal sort step in ranking/leaderboard pipelines

不適用情境:
- Single row retrieval (last event, earliest violation, top-1 by X) → use `block_find` instead
- Lag/delta/rising detection → use `block_delta` or `block_shift_lag` (they include sort)
- Row filtering (non-ranking) → use `block_filter`

## Inputs

### port: `data`
- type: dataframe
- required: yes
- 期望狀態: complete row set to be sorted. Block does not filter; all rows are retained unless `limit` is specified.
- 必要欄位: all columns referenced in `columns[].column` must exist in upstream output
- 不接受: empty dataframe is acceptable (0 rows pass through); nested list/dict columns not recommended

upstream sample:
```json
[
  {"toolID": "EQP-02", "eventTime": "2026-05-19T10:05", "ooc_count": 5},
  {"toolID": "EQP-01", "eventTime": "2026-05-19T10:10", "ooc_count": 3},
  {"toolID": "EQP-01", "eventTime": "2026-05-19T10:00", "ooc_count": 3}
]
```

## Outputs

### port: `data`
- type: dataframe
- shape: (≤ limit rows) × (same columns as upstream)
- 產出欄位: all upstream columns preserved; row order changed per `columns` spec; if `limit` set, only first N rows retained
- 下游 hint:
  - `block_data_view`: display sorted leaderboard/ranking table
  - `block_threshold`: check sorted value at head
  - chart blocks: plot sorted sequence

output sample:
```json
[
  {"toolID": "EQP-01", "eventTime": "2026-05-19T10:10", "ooc_count": 3},
  {"toolID": "EQP-01", "eventTime": "2026-05-19T10:00", "ooc_count": 3},
  {"toolID": "EQP-02", "eventTime": "2026-05-19T10:05", "ooc_count": 5}
]
```

## Parameters

| name | type | required | default | enum | 用途 |
|---|---|---|---|---|---|
| `columns` | array of {column, order} | yes | - | - | Sort key list: `[{column: "fieldname", order: "asc"\|"desc"}, ...]` Primary sort first, secondary follows. |
| `limit` | integer | no | - | ≥ 1 | Retain only top-N rows after sorting (head-N). Omit to return all sorted rows. |

常見錯誤:
- `column` (singular) instead of `columns` (plural) → INVALID_SORT_SPEC
- `columns: "eventTime"` (string) instead of `[{column: "eventTime"}]` (array of objects) → type mismatch error
- `order: "DESC"` or `order: "descending"` → defaults silently to ''asc'' (case/spelling sensitive)
- `limit` confused with ranking threshold — limit is head-N, not "top N by value"
- Column name typo (e.g., `"ooc_count"` vs upstream actual `"spc_status_count"` from `block_groupby_agg`) → COLUMN_NOT_FOUND
- Using block_sort to find "last event" / "earliest violation" — should use `block_find` (1-step, avoids missed `limit=1`)

## Examples

### Single-column ranking with top-3 cap
```
block_groupby_agg(group_by=''toolID'', agg_column=''spc_status'', agg_func=''count'')
  → block_sort(columns=[{column: ''spc_status_count'', order: ''desc''}], limit=3)
  → block_data_view()
```
意圖: Count OOC per tool → rank by count descending → show top-3 tools. 
注意: upstream 的 count column 叫 `spc_status_count` (不是 ''count'')；使用者必須檢查 upstream 實際欄位名再填 `columns[].column`。

### Multi-column sort: tool asc, time desc
```
block_process_history(tool_id=''%'', limit=100)
  → block_sort(columns=[{column: ''toolID'', order: ''asc''}, {column: ''eventTime'', order: ''desc''}])
  → block_data_view()
```
意圖: 撈全廠最近 100 筆 process event → 按機台編號升序、同機內按時間降序排列 → 視覺檢查。
注意: 無 `limit` 保留全部 100 列；無 filter，只重排。', NULL, true, 'auto-gen', '2026-05-19 05:57:04.76099+00', '2026-05-19 05:57:04.761577+00', '2026-06-11 14:37:15.309867+00') ON CONFLICT (block_id, block_version) DO UPDATE SET markdown = EXCLUDED.markdown, updated_at = now();

INSERT INTO public.block_docs (id, block_id, block_version, markdown, sections, auto_generated, last_edited_by, last_edited_at, created_at, updated_at) VALUES (4, 'block_find', '1.0.0', '---
name: block_find
description: Filter rows by single condition with optional sorting, returning first, last, all, or top N results; condenses filter+sort+limit into one step. Use to locate the last OOC, latest 違規, first alarm, or top N events by score. Not for multi-column composite sorting (use block_sort), dual-port threshold checks (use block_threshold), or complex AND/OR conditions requiring multiple block_filter.
---

# block_find

Transform block for finding specific rows in a DataFrame. Applies a filter condition on a column, optionally sorts by another column, and limits the result set to first/last/all/N rows. Consolidates the common 3-step pattern (filter → sort → take) into one block.

## When to invoke

- Need to find "the most recent event where X=Y" (filter + sort desc + take first)
- Extract "top N rows by metric after filtering" (filter + sort + limit)
- Search for rows matching a condition with optional ranking (single-pass alternative to filter+sort+limit chain)
- Diagnostic rules that need "find latest anomaly" or "find max/min value row"

不適用情境:
- Want multiple independent filters on different columns → use `block_filter` with complex conditions
- Want to group and aggregate per group → use `block_groupby_agg`
- Want to keep all matching rows unsorted → use `block_filter` (simpler, no sort overhead)
- ⚠ 視覺化 SPC chart 趨勢時禁用 take=''first'': 若 user 問「SPC chart」「SPC 趨勢」「OOC 前後 SPC」，通常意指**整個 trend history**(多點折線)，不是單一 event 的瞬時值。block_find + take=''first'' 會把上游砍成 1 row，下游 line_chart 變空圖。SPC 視覺化應留 process_history 全部 events 給 chart node，用 highlight_field 標出 OOC 點。
- Want to output both filtered subset AND aggregated metric → use `block_filter` + `block_step_check` separately

## Inputs

### port: `data`
- type: dataframe
- required: yes
- 期望狀態: Any tabular data. Column names may use dot notation for nested access (e.g. `spc_summary.ooc_count`).
- 必要欄位: `column` and `order_by` (if specified) must exist in upstream dataframe.
- 不接受: Nested list/dict columns when using them as filter/sort keys. Empty dataframe passes through (returns 0 rows).

upstream sample:
```json
[
  {"eventTime": "2026-05-19T10:15", "toolID": "EQP-01", "status": "IDLE"},
  {"eventTime": "2026-05-19T10:10", "toolID": "EQP-01", "status": "RUN"},
  {"eventTime": "2026-05-19T10:05", "toolID": "EQP-02", "status": "RUN"},
  {"eventTime": "2026-05-19T10:00", "toolID": "EQP-01", "status": "RUN"}
]
```

## Outputs

### port: `data`
- type: dataframe
- shape: rows = min(matching_count, take), columns = same as input
- 下游 hint: Any block accepting dataframe (block_step_check, block_alert, block_data_view, chart blocks)

output sample:
```json
[
  {"eventTime": "2026-05-19T10:15", "toolID": "EQP-01", "status": "IDLE"}
]
```

## Parameters

| name | type | required | default | enum | 用途 |
|---|---|---|---|---|---|
| `column` | string | yes | - | - | 被過濾的欄位名 (支援 nested path e.g. `spc_summary.ooc_count`) |
| `operator` | string | yes | - | `==`/`=`/`!=`/`>`/`<`/`>=`/`<=`/`contains`/`in` | 比較運算子 |
| `value` | any | yes | - | - | 比較值；`operator=''in''` 時必須是 list；boolean 欄位用 True/False |
| `order_by` | string | no | - | - | 排序欄位；省略 = 保持 input 順序 (無排序開銷) |
| `order_dir` | string | no | `desc` | `asc`/`desc` | 排序方向 (`desc` 多用於取最新) |
| `take` | string \| integer | no | `all` | `first`/`last`/`all` 或正整數 N | 取多少 row: `all` = 全部; `first` = 1 row (排序後第一筆); `last` = 1 row (排序後最後一筆); N = top N |

常見錯誤:
- `column` 拼錯或不存在 → COLUMN_NOT_FOUND
- `order_by` 拼錯 → COLUMN_NOT_FOUND
- `take=''top5''` 而非整數 5 → INVALID_PARAM
- `order_dir=''newest''` 而非 `desc` → INVALID_PARAM
- `operator=''in''` 但 `value` 不是 list → INVALID_PARAM
- `operator=''contains''` 用於 numeric 欄位 → type mismatch error

## Examples

### Find most recent RUN event for EQP-01
```
block_process_history(tool_id=''EQP-01'', limit=50)
  → block_find(column=''status'', operator=''=='', value=''RUN'',
               order_by=''eventTime'', order_dir=''desc'', take=''first'')
```
意圖: 撈 50 筆歷史 → 篩 RUN 狀態 → 按時間倒序 → 取最新 1 筆。
注意: `order_by=''eventTime''` 假設上游有此欄位；若無須排序改 `take=''first''` 保留 input 順序。

### Find top 5 highest pressure readings
```
block_process_history(recipe=''ETCH_001'', step=''STEP_02'', limit=100)
  → block_find(column=''pressure_kpa'', operator=''>'', value=950,
               order_by=''pressure_kpa'', order_dir=''desc'', take=5)
```
意圖: 100 筆壓力記錄 → 篩 >950kpa → 按壓力倒序 → 取前 5 筆 (最高壓力)。
注意: `take` 為整數時自動排序後截斷，比 filter+sort+limit 更高效。', NULL, true, 'auto-gen', '2026-05-19 05:49:34.298287+00', '2026-05-19 05:49:34.299185+00', '2026-06-11 05:33:16.332306+00') ON CONFLICT (block_id, block_version) DO UPDATE SET markdown = EXCLUDED.markdown, updated_at = now();

INSERT INTO public.block_docs (id, block_id, block_version, markdown, sections, auto_generated, last_edited_by, last_edited_at, created_at, updated_at) VALUES (3, 'block_process_history', '1.0.0', '---
name: block_process_history
description: 從 data source MCP 擷取指定機台、批次或站點的 process events，自動整合 SPC/APC/DC/RECIPE/FDC/EC 多維度為單一寬表或巢狀結構，每筆 record 對應一個 process event。用於分析特定機台 SPC 趨勢、指定 Lot-Step 的 APC 補償值、或篩選時段內 OOC 事件等數值型查詢。tool_id / lot_id / step 至少需提供一個（runtime enforced，無法省略全部）。 ⛔ tool_id / lot_id / step **不接受 ''ALL'' / ''*'' / ''all'' / ''_all_'' 等 magic value** — MCP 雖然偶爾容錯回 data，仍是 undefined behavior，可能拿到錯誤或不完整結果。查多機台請走 fan-out（block_list_objects + block_mcp_foreach）或聚合 MCP （block_mcp_call get_process_summary）。跨多機台查詢需走 fan-out（block_list_objects → block_mcp_foreach）或聚合 MCP（block_mcp_call mcp_name=''get_process_summary''）。請勿用於查詢「現在哪些機台在跑」等即時清單（用 block_list_objects）。
---
```markdown
---
name: block_process_history
description: Query process events by tool/lot/step from ontology MCP; returns nested DataFrame with SPC charts, APC/DC/RECIPE/FDC/EC sub-objects. Unnest + filter downstream for single-chart trend analysis.
---

# block_process_history

Source block that retrieves historical process events from ontology MCP `get_process_info` API based on machine, lot, or step criteria. Returns a nested DataFrame where each row represents one process event with embedded `spc_charts` list, `spc_summary` object, and dimensional attributes (APC/DC/RECIPE/FDC/EC). To analyze a single SPC chart trend, you must downstream unnest + filter by chart name.

## When to invoke

- Historical process queries: "EQP-01 last 50 SPC xbar values", "LOT-123 APC etch_time_offset at STEP_004"
- Time-windowed OOC event detection: "all OOC events past 24 hours"
- **跨機台 / 跨 lot / 跨 step 查詢** — 本 block tool_id/lot_id/step 三擇一必填。想看「N 機台」「全廠」「哪些 X」時，**改走兩條 path 之一**：
    Pattern A (fan-out): block_list_objects(kind=''tool'') → block_mcp_foreach(mcp_name=''get_process_info'', args_template={''tool_id'': ''$tool_id'', ...}) → block_union (合併結果) → 下游聚合
    Pattern B (聚合 MCP): block_mcp_call(mcp_name=''get_process_summary'', args={''time_range'': ''24h'', ''aggregate_by'': ''tool''}) — 跳過 process_history，直接拿全廠 OOC 統計。
- Diagnostic rule backfill: "retrieve baseline for drift comparison"

不適用情境:
- Equipment/lot/step enumeration → use `block_list_objects(kind=...)`
- Real-time process summary (aggregate counts) → use `block_mcp_call(get_process_summary)`
- Multi-tool queries — 本 block 三擇一必填，無法用 tool_id=None 或 ''ALL'' 拉全廠。改走 Pattern A (fan-out) 或 Pattern B (聚合 MCP)，見上方 When to invoke。

## Inputs

### port: (none)
This is a source block; no upstream input required.

## Outputs

### port: `data`
- type: dataframe (nested by default)
- shape: rows = process events; columns listed below
- 產出欄位 + type + 描述:
  - `eventTime` (string, ISO8601): timestamp of process event
  - `toolID` (string): machine identifier
  - `lotID` (string|null): batch identifier
  - `step` (string): process step name
  - `spc_status` (string): enum {NORMAL, OOC, ALERT, ...}
  - `spc_charts` (list of objects): [{name (string), value (number), ucl (number), lcl (number), mean (number), sd (number), is_ooc (bool), status (string)}, ...]
    - **chart names are full keys**: ''xbar_chart'', ''r_chart'', ''s_chart'', ''p_chart'', ''c_chart'', ''imr_pressure'', ''cusum_temp'', ''ewma_bias'', ''cpk_etch'', ''oes_endpoint'', ''rga_h2o_chart'', ''match_tune_chart'' (NOT bare ''xbar'')
  - `spc_summary` (object): {ooc_count (int), total_charts (int), ooc_chart_names (list)}
  - `fdc_classification` (string|null): defect class
  - `apc` (object|null): nested APC parameters (if object_name=APC or empty)
  - `dc` (object|null): nested DC readings
  - `recipe` (object|null): recipe metadata
  - `fdc` (object|null): FDC events
  - `ec` (object|null): equipment context
- 下游 hint:
  - **SPC chart analysis**: unnest(spc_charts) → filter(name=''xbar_chart'') → block_xbar_r or block_chart_trend (value_column=''value'')
  - **Path notation in step_check**: column=''spc_summary.ooc_count'' to read nested scalar
  - **Legacy flat naming**: user says "spc_xbar_chart_value" → translate to unnest + filter name=''xbar_chart'' + use ''value'' field

output sample:
```json
[
  {
    "eventTime": "2026-05-19T10:00:00Z",
    "toolID": "EQP-01",
    "lotID": "LOT-0234",
    "step": "STEP_013",
    "spc_status": "OOC",
    "spc_charts": [
      {
        "name": "xbar_chart",
        "value": 125.4,
        "ucl": 130.0,
        "lcl": 120.0,
        "mean": 125.0,
        "sd": 2.1,
        "is_ooc": false,
        "status": "NORMAL"
      },
      {
        "name": "r_chart",
        "value": 8.5,
        "ucl": 10.0,
        "lcl": 0.0,
        "mean": 5.0,
        "sd": 1.8,
        "is_ooc": true,
        "status": "OOC"
      }
    ],
    "spc_summary": {
      "ooc_count": 1,
      "total_charts": 2,
      "ooc_chart_names": ["r_chart"]
    },
    "fdc_classification": "particle",
    "apc": {"etch_time_offset": -0.5, "bias_offset": 0.2},
    "dc": null,
    "recipe": {"version": "R001"},
    "fdc": null,
    "ec": null
  }
]
```

## Parameters

| name | type | required | default | enum | 用途 |
|---|---|---|---|---|---|
| `tool_id` | string | 三選一必填 | - | - | Single machine ID (e.g. ''EQP-01''). 特殊值 `''ALL''` = 全機台不過濾（仍算「三選一」之一，可單獨給）. MCP 單值字串、不接 comma list / array; 若要篩特定多台 → 傳 ''ALL'' + downstream `block_filter(column=''toolID'', operator=''in'', value=[...])`. |
| `lot_id` | string | 三選一必填 | - | - | Single batch ID (e.g. ''LOT-0234''). Same single-value constraint as tool_id. |
| `step` | string | 三選一必填 | - | - | Single step name (e.g. ''STEP_013''). Same constraint. |
| `object_name` | string | no | (empty) | "" / "SPC" / "APC" / "DC" / "RECIPE" / "FDC" / "EC" | Data dimension to include. Empty = all dimensions (nested wide shape). Single value = that dimension only. |
| `time_range` | string | no | "24h" | pattern `^[0-9]+[hd]$` | Time window: Nh or Nd format (e.g. 1h, 24h, 48h, 72h, 7d, 30d). User says "past N days" → convert to `{N*24}h`. |
| `event_time` | string | no | - | - | Exact timestamp (ISO8601) to query around. Precise moment queries. |
| `limit` | integer | no | 100 | 1–200 | Row count limit. MCP default 100, absolute max 200. |
| `nested` | boolean | no | true | true / false | Return hierarchical shape (true) preserving spc_charts[], spc_summary, and nested dimensions; or flatten to legacy wide columns (false, spc_<chart>_<field>). SPC analysis blocks auto-unnest, so true is recommended. |

常見錯誤:
- Passing comma-separated tool_id=''EQP-01,EQP-02'' or array → MCP rejects; use downstream filter
- Confusing spc_xbar_chart_value (flat legacy name) with nested spc_charts[{name=''xbar_chart'', value=...}] → must unnest first
- time_range=''2 days'' → invalid format; use ''48h'' instead
- Requesting multi-step without 三選一 parameter → returns empty; exactly one of tool_id / lot_id / step required
- Not unnesting before SPC chart block → path errors or unexpected aggregation

## Examples

### Standard SPC xbar trend analysis (nested mode)
```
block_process_history(tool_id=''EQP-01'', time_range=''7d'', limit=200)
  → block_unnest(column=''spc_charts'')
  → block_filter(column=''name'', operator=''=='', value=''xbar_chart'')
  → block_chart_trend(x_column=''eventTime'', y_column=''value'', title=''EQP-01 Xbar 7d'')
```
意圖: Fetch 7-day xbar history for EQP-01 → unnest spc_charts list → filter to xbar_chart only → plot trend.
注意: nested=true (default) returns spc_charts as list; unnest is mandatory. chart name is ''xbar_chart'' not ''xbar''.

### Diagnostic rule: OOC threshold with nested spc_summary
```
block_process_history(tool_id=''EQP-01'', time_range=''24h'')
  → block_filter(column=''spc_status'', operator=''=='', value=''OOC'')
  → block_step_check(aggregate=''count'', operator=''>='', threshold=3)
  → block_alert(severity=''HIGH'')
```
意圖: Get past 24h events → filter to OOC status → count rows → alert if ≥3.
注意: This pattern works without unnesting (spc_status is top-level). For chart-specific counts, use column=''spc_summary.ooc_count'' in step_check.

### Multi-step APC drift comparison (legacy flat mode)
```
block_process_history(lot_id=''LOT-0234'', step=''STEP_004'', nested=false)
  → block_step_check(aggregate=''mean'', column=''apc_etch_time_offset'',
                     operator=''drift'', baseline=0.0, threshold=1.5)
```
意圖: Lot 123 at step 004 → flatten APC nested object to apc_etch_time_offset column → compute mean → detect drift.
注意: nested=false transforms apc={...} into apc_<param> columns. For trend chart, still prefer nested=true + downstream transformation.

```', NULL, true, 'auto-gen', '2026-05-19 05:49:04.709328+00', '2026-05-19 05:49:04.709845+00', '2026-06-11 08:30:54.840372+00') ON CONFLICT (block_id, block_version) DO UPDATE SET markdown = EXCLUDED.markdown, updated_at = now();

INSERT INTO public.block_docs (id, block_id, block_version, markdown, sections, auto_generated, last_edited_by, last_edited_at, created_at, updated_at) VALUES (7, 'block_mcp_foreach', '1.0.0', '---
name: block_mcp_foreach
description: 對上游 DataFrame 的每一筆 row 非同步呼叫指定 MCP，將回傳結果合併為新欄位，支援並發控制以避免打爆下游服務。Params: `mcp_name` (string, registered MCP), `args_template` (object, values 用 $columnName 引用 upstream 欄位)。⛔ 不要寫 `mcp_key` / `args_map` — 這兩個不是合法 param key。適用於逐筆 enrichment，例如針對每個 OOC process 查詢 fault context，或針對每個 lot 查詢 recipe 詳細參數。不適用於單次 MCP 呼叫（無需逐 row 觸發）、兩個 DataFrame join、上游大於 500 列，或無法容許單點失敗導致整體中斷的場景。
---
```markdown
---
name: block_mcp_foreach
description: Call registered MCP for each upstream row with templated args, merge responses as new columns. Async concurrent up to max_concurrency limit.
---

# block_mcp_foreach

Transform block that invokes a registered MCP endpoint once per upstream DataFrame row, passing templated arguments derived from each row''s fields. Responses (dict/list) are merged as new columns with optional prefix. Executes concurrently (async) with configurable concurrency limit to balance throughput and MCP server load.

## When to invoke

- Each OOC process needs external fault context lookup → upstream filter(OOC) → mcp_foreach(get_fdc_context)
- Each lot ID requires recipe detail enrichment → upstream df → mcp_foreach(get_recipe_detail, args_template={''lotID'':''$lotID''})
- Row-wise enrichment: use upstream field values as MCP call parameters, expand result as new columns
- Per-process context gathering before diagnostic rule evaluation

不適用情境:
- Single MCP call independent of DataFrame → use `block_mcp_call` (no row iteration)
- Two-table join by key → use `block_join`
- Upstream > 500 rows → pre-filter or limit first; foreach scales linearly with row count
- MCP call fails on any single row → block stops (no per-row skip/fallback)

## Inputs

### port: `data`
- type: dataframe
- required: yes
- 期望狀態: Rows are the MCP call targets. Each row field can be referenced in `args_template` via `$fieldname` syntax.
- 必要欄位: Only columns referenced in `args_template` must exist (case-sensitive). No size constraints enforced at port level; TOO_MANY_ROWS error raised at execution if > 500 rows.
- 不接受: Nested list/dict columns in referenced fields; MCP args expect scalar or simple string values.

upstream sample:
```json
[
  {"lotID": "LOT-2026-001", "toolID": "EQP-01", "stepName": "ETCH"},
  {"lotID": "LOT-2026-002", "toolID": "EQP-02", "stepName": "IMPLANT"}
]
```

## Outputs

### port: `data`
- type: dataframe
- shape: same row count as upstream; new columns appended
- 產出欄位:
  - All upstream columns (unchanged)
  - If MCP returns dict: each key becomes column `<result_prefix><key>` (type inferred from value)
  - If MCP returns list[dict]: first element unpacked, keys prefixed
  - If MCP returns other (string/number/bool): stored as `<result_prefix>raw` (JSON)
  - On MCP failure: entire block fails (no partial row skip)
- 下游 hint:
  - `block_filter`, `block_groupby_agg`: consume enriched columns for further logic
  - `block_step_check`: use new columns in aggregate/threshold logic
  - Chart blocks: visualize new fields alongside original data

output sample:
```json
[
  {
    "lotID": "LOT-2026-001",
    "toolID": "EQP-01",
    "stepName": "ETCH",
    "recipe_name": "ETCH_STD_v3",
    "recipe_temp": 350,
    "recipe_duration": 45
  },
  {
    "lotID": "LOT-2026-002",
    "toolID": "EQP-02",
    "stepName": "IMPLANT",
    "recipe_name": "IMPLANT_HE_v2",
    "recipe_temp": 200,
    "recipe_duration": 120
  }
]
```

## Parameters

| name | type | required | default | enum | 用途 |
|---|---|---|---|---|---|
| `mcp_name` | string | yes | - | - | Registered MCP endpoint name (must exist in mcp_definitions table) |
| `args_template` | object | yes | - | - | Args passed to MCP; values can reference upstream columns via `$columnName` syntax (case-sensitive) |
| `result_prefix` | string | no | `` (empty) | - | Prefix for new columns merged from MCP response; prevents name collisions (e.g., `''apc_''` → `apc_param1`, `apc_param2`) |
| `max_concurrency` | integer | no | 5 | 1-20 | Max simultaneous in-flight HTTP requests to MCP; higher values (10-20) speed up but increase MCP server load |

常見錯誤:
- `$col_name` in `args_template` spelling mismatch → TEMPLATE_MISSING_COL (case-sensitive)
- Omitting `result_prefix` when MCP returns keys matching upstream columns → upstream values silently overwritten
- Upstream DataFrame > 500 rows → TOO_MANY_ROWS error; pre-filter or limit first
- Single MCP call failure → entire block fails (fail-fast, no per-row fallback)
- `mcp_name` not registered in system → MCP_NOT_FOUND

## Examples

### Lot-level recipe enrichment (OOC diagnostic)
```
block_process_history(tool_id=''EQP-01'', limit=50)
  → block_filter(column=''spc_status'', operator=''=='', value=''OOC'')
  → block_mcp_foreach(mcp_name=''get_recipe_detail'',
                      args_template={''lotID'': ''$lotID''},
                      result_prefix=''recipe_'')
  → block_filter(column=''recipe_temp'', operator=''>'', value=400)
  → block_step_check(aggregate=''count'', operator=''>='', threshold=5)
```
意圖: Get OOC process history, enrich each row with recipe details (temp, duration), filter high-temp recipes, check if >= 5 breaches.
注意: `args_template` references `$lotID` from upstream df; MCP returns dict with keys like `temp`, `duration` → stored as `recipe_temp`, `recipe_duration`. If upstream already has `recipe_temp`, it gets overwritten; use `result_prefix` to avoid collisions.

### Fault context lookup per OOC event
```
block_event_log(eventType=''OOC'', time_range=''24h'')
  → block_mcp_foreach(mcp_name=''get_fdc_context'',
                      args_template={''toolID'': ''$toolID'', ''timestamp'': ''$eventTime''},
                      result_prefix=''fdc_'',
                      max_concurrency=10)
  → block_data_view()
```
意圖: Retrieve recent OOC events, for each call FDC MCP with tool ID & timestamp, merge fault details as `fdc_*` columns, display enriched table.
注意: `max_concurrency=10` speeds up (default 5) for ~100s of rows; MCP must handle concurrent load. Response typically dict (fault_code, root_cause, recommendations) → each key prefixed `fdc_`.
```
</body>
```', NULL, true, 'auto-gen', '2026-05-19 05:50:23.50058+00', '2026-05-19 05:50:23.501066+00', '2026-06-11 14:37:15.309867+00') ON CONFLICT (block_id, block_version) DO UPDATE SET markdown = EXCLUDED.markdown, updated_at = now();

-- agent_knowledge (3 entries — id 35/36/37, idempotent on title)

INSERT INTO public.agent_knowledge (id, user_id, scope_type, scope_value, title, body, priority, active, source, embedding, uses, last_used_at, created_at, updated_at) SELECT 35, 1, 'global', NULL, 'SPC chart 看 trend / 看某 event 前後 — 不要砍 history', '
當 user 要看「SPC trend」「OOC 周邊 SPC chart」「某 event 前後 SPC charts」「最後一次 OOC 的 SPC charts」時，pipeline 設計鐵律：

1. block_process_history 用寬範圍 (time_range >= ''7d'')，留全部 events 給下游。

2. ⛔ 不要 在 chart 之前加 block_find + take=''first'' 或 take=1 — 會把上游砍成 1 row，下游 line_chart 變空圖（只有 1 點畫不出線）。

3. ✓ 正確 pattern：
     process_history(wide range)
       → block_unnest(column=''spc_charts'')
       → 每張 chart: block_filter(column=''name'', value=''<chart_name>'')
                    → block_line_chart(x=''eventTime'', y=''value'',
                                       ucl_column=''ucl'', lcl_column=''lcl'',
                                       highlight_field=''is_ooc'',
                                       highlight_eq=True)

4. highlight_field=''is_ooc'' 會把 OOC 點自動標紅 — user 看圖就知道「最後一次 OOC 在這、前後 trend 在這」，不需要先 query event time 再 query 第二次。

5. 「最後一次 OOC」「某 event」是 視覺化的注意力錨點，不是 query filter 的條件。
  ', 'high', true, 'manual', '[-0.001372,0.042603,-0.083618,0.022675,0.020966,-0.025101,0.01458,-0.05484,-0.060394,-0.033356,0.011169,0.060303,-0.022675,0.001839,0.002831,-0.04187,0.022354,0.01738,-0.017044,-0.045654,-0.029984,0.026947,0.056549,0.038116,0.022507,-0.029984,0.013214,0.030106,0.055786,0.018127,0.027649,-0.040955,0.018585,0.040802,0.002157,0.008682,0.020081,-0.015961,-0.003571,0.029175,-0.055084,-0.019791,-0.027054,0.036713,0.015511,-0.018463,0.023224,0.016937,0.055023,0.071716,-0.038086,0.011597,0.0177,-0.003304,0.003613,-0.029739,-0.012878,0.010971,0.012733,-0.019012,0.020874,0.038177,0.023422,0.038422,-0.001513,0.000817,-0.020309,0.052399,0.015747,0.038605,0.008087,0.00943,-0.00407,0.001292,-0.019287,-0.007385,-0.022049,-0.081848,-0.019806,-0.016693,-0.004375,0.016876,0.024429,0.011711,0.046295,-0.00795,-0.00872,0.027496,-0.041809,0.014748,-0.005394,-0.014091,-0.017868,0.03775,-0.028671,-0.001122,0.020645,-0.035004,0.044128,-0.008278,-0.000586,-0.027039,-0.022003,-0.003588,0.027725,0.009804,0.0513,0.020981,-0.013741,-0.013206,0.01178,-0.001008,-0.004623,-0.018997,-0.005199,0.015701,0.009659,-0.010216,0.006962,-0.027451,-0.035156,0.012367,0.003153,-0.007996,-0.013634,0.00137,0.028061,-0.010857,0.003889,-0.024734,-0.050873,0.019333,0.012215,0.014481,0.024429,0.025406,-0.029953,-0.010651,0.046112,0.020996,0.047668,0.032257,0.014008,0.056458,0.002211,-0.034393,-0.003893,0.002808,-0.040283,-0.025772,-0.013306,-0.041718,0.00507,-0.033569,0.045685,-0.009003,0.023468,-0.01683,0.018799,-0.005753,0.005524,-0.059967,0.012917,-0.020676,0.006145,-0.045807,0.056885,-0.011253,0.00238,0.033722,-0.01297,-0.010147,0.011757,-0.001289,0.001876,0.029968,0.019958,0.028366,-0.01223,0.019836,-0.019257,-0.009277,-0.031586,-0.087219,0.018402,0.008224,-0.015778,0.004864,0.022873,0.027435,0.002975,-0.040741,-0.063538,-0.033997,-0.034576,0.013626,0.012398,-0.034576,-0.003525,0.056671,0.039124,-0.039734,0.015045,-0.037048,-0.037201,-0.011581,0.012703,-0.017975,-0.051575,0.032501,-0.012985,-0.013519,-0.014023,0.011459,-0.011162,0.008865,0.013512,0.000151,0.021835,-0.015556,0.071045,-0.040863,0.036133,0.020081,-0.004295,-0.046387,0.030273,-0.021652,0.022308,-0.027481,-0.015038,-0.015266,0.024048,-0.026062,0.051605,0.018127,0.006863,-0.007744,-0.028534,-0.028076,-0.020767,0.017105,0.003103,-0.026566,0.018066,-0.027832,-0.002901,-0.013573,-0.01561,0.009117,0.011276,0.021347,-0.005516,-0.013908,0.018921,0.00626,-0.073914,0.002989,0.006718,0.017105,0.018158,-0.024811,0.040436,-0.001088,-0.03894,-0.026215,-0.000968,-0.001645,0.077515,0.036987,-0.007175,-0.010918,-0.00263,0.008469,-0.01049,0.011093,0.022888,-0.008446,0.037476,0.067627,-0.006741,0.036896,-0.009521,0.005863,-0.020981,0.053925,-0.080444,0.052826,-0.026031,0.024292,-0.034729,-0.024338,-0.03598,0.033295,-0.003902,-0.00758,0.031769,-0.024704,-0.035278,-0.002411,0.024338,-0.045868,-0.048676,-0.019394,0.057007,0.04126,-0.047821,0.012672,0.002649,0.001225,-0.008598,-0.004391,0.016251,0.05127,-0.081238,0.009499,-0.025711,-0.065186,-0.026627,0.045898,-0.004124,-0.03717,-0.034393,-0.01339,-0.028183,0.044678,-0.011208,0.003065,-0.010002,-0.030441,0.037415,-0.034607,0.045288,-0.025101,0.024139,0.006546,0.022171,-0.018387,-0.018738,0.033752,-0.052246,-0.016846,-0.07489,0.037262,0.010307,0.025375,-0.020309,-0.021957,0.020218,-0.019684,0.044159,0.014816,-0.025284,-0.029251,0.054382,-0.020142,0.008179,0.016861,-0.002836,-0.020996,0.023483,-0.044373,-0.01281,0.030853,-0.005768,0.023254,-0.010284,-0.000596,-0.005207,0.02655,0.003277,0.032074,0.059998,0.012718,-0.023941,0.01162,-0.027893,0.010643,0.022064,-0.016541,-0.007027,0.016144,-0.007553,0.049072,0.023453,0.04538,-0.015671,-0.023071,-0.013725,-0.009445,0.023193,0.027359,-0.026291,-0.037445,-0.004555,0.03772,-0.049377,0.014435,-0.095459,-0.017822,0.036407,-0.017883,6.8e-05,-0.001051,0.022781,-0.003386,0.011627,0.001072,0.022537,0.000542,-0.036102,0.03244,0.033295,-0.020889,-0.014145,-0.001052,0.016342,0.014114,-0.017258,-0.000722,0.001902,-0.031113,0.014954,0.03421,-0.030807,0.052887,0.007603,-0.105042,0.10022,0.032349,0.035004,0.019608,0.029343,-0.027252,0.0224,0.005245,0.012901,-0.03714,-0.003956,-0.026382,0.00782,0.028107,0.004829,0.011581,0.007092,0.044739,0.041779,0.049591,0.014244,0.024719,-0.008972,0.035797,-0.041229,-0.015617,-0.013496,-0.044434,-0.019608,-5e-06,0.041138,-0.011017,0.000301,-0.01741,-0.041382,-0.000558,0.044495,-0.072754,0.069946,0.011253,-0.012589,0.055176,-0.049622,0.057495,-0.019257,0.006321,0.008385,-0.058899,-0.033752,0.017517,-0.00856,-0.024445,0.005642,0.004841,-0.054932,0.003239,-0.077271,0.016342,0.024307,-0.004436,-0.013435,-0.045868,-0.039337,0.021027,-0.03479,0.024994,-0.041046,-0.02684,0.01088,-0.034882,-0.051117,-0.018005,0.007507,0.016174,-0.029556,0.06192,0.003159,0.013359,0.024139,-0.026993,-0.060242,-0.032837,-0.016998,0.034271,-0.015541,0.027512,0.021362,-0.047302,-0.008789,0.024078,0.016556,-0.03067,0.029007,0.106628,-0.049561,-0.007427,0.019379,0.015045,-0.07019,-0.015701,-0.081116,-0.011337,0.025406,0.022415,-0.021286,-0.001185,-0.050232,-0.068604,0.011841,0.023514,0.026276,-0.021927,-0.0084,-0.013901,-0.003181,0.002071,0.001486,-0.022461,0.023438,-0.018768,-0.052551,-0.001328,-0.023239,-0.010231,-0.006947,-0.021622,0.02533,0.063232,0.001582,0.005329,-0.009285,-0.080139,0.050934,-0.027023,0.002279,0.024536,0.01564,-0.029984,0.011963,-0.00079,-0.001332,0.032928,0.04837,-0.049927,-0.007168,0.010666,0.025238,-0.064026,0.038483,-0.026978,-0.017349,-0.023163,-0.043213,-0,0.011086,0.004234,-0.007935,-0.028198,-0.013649,-0.0051,0.032745,-0.003839,0.04126,-0.013435,-0.009872,0.034332,0.057373,0.023575,0.035706,0.013596,0.069275,0.033356,-0.050903,0.022827,0.004333,0.018768,0.029633,0.034241,0.01651,0.022812,-0.005402,-0.001665,0.029434,-0.011879,-0.034393,0.021332,-0.022049,-0.01532,-0.04245,-0.003733,-0.024902,-0.000307,-0.022827,-0.005402,-0.038208,-0.016251,0.004829,0.016296,0.013863,0.012779,-0.015602,0.008377,-0.050812,-0.038391,-0.025024,0.001943,0.018417,0.010277,-0.02504,-0.054718,-0.043915,0.031021,-0.005283,0.041077,-0.003777,0.00091,-0.015732,0.027603,0.023926,0.03476,0.01442,-0.029312,-0.000636,0.018143,0.058502,-0.010612,0.003031,-0.003248,0.027008,0.006405,-0.03949,0.038513,0.015823,0.018692,0.024963,0.047333,-0.01738,-0.015915,0.008568,0.060516,0.0271,-0.011513,0.020798,0.032959,0.036255,0.054138,0.066528,-0.059326,-0.048676,-0.048004,0.030762,-0.047455,-0.021317,-0.00853,-0.028549,-0.033539,-0.032928,0.025497,-0.1203,-0.019165,0.022156,-0.032562,0.005196,0.053619,-0.037109,0.018143,0.003832,-0.000884,0.031189,-0.001514,-0.030289,0.028915,0.000142,0.040558,0.017075,0.000799,-0.03009,-0.023193,0.054504,-0.048676,-0.004459,0.009621,0.020874,0.03302,-5.5e-05,0.010162,-0.02153,0.027786,0.010345,-0.01738,-0.025986,0.049408,0.0215,-0.01683,-0.015144,-0.026825,0.015038,0.001269,0.01516,0.003288,-0.013741,0.042725,0.04126,0.043182,0.034973,0.007408,-0.003269,0.008102,-0.029556,-0.039948,0.051392,-0.013863,0.025116,0.024338,-0.020447,-0.040985,0.009186,0.018204,-0.022217,0.01709,-0.026398,-0.002626,-0.036743,0.025131,-0.005703,0.000686,-0.01622,0.020081,-0.015282,0.052399,0.030457,-0.007278,-0.014046,0.019089,-0.046967,0.00555,-0.005894,0.001821,-0.024216,0.013618,0.00227,0.001465,0.00383,-0.008751,0.002882,0.003738,-0.018768,-0.008812,-0.051971,0.045685,0.000603,-0.057343,0.043732,0.030502,0.038208,0.04425,0.012802,0.020813,0.046875,0.016022,0.024734,0.033997,0.019958,-0.023895,0.031647,-0.0159,-0.016205,-0.001056,0.011566,-0.016052,0.017487,-0.059723,-0.043304,-0.024353,-0.009094,0.016052,-0.015373,-0.026443,-0.029663,0.022675,-0.029266,0.013779,0.009979,0.021286,-0.02623,0.028915,-0.013252,-0.028259,0.059235,0.040497,0.02153,0.012764,0.065674,-0.025711,-0.0131,0.000812,-0.031555,0.026443,0.010178,-0.018951,-0.015297,-0.02742,-0.037445,-0.010338,-0.024277,0.031921,0.037842,-0.000327,-0.028717,-0.021896,0.000848,-0.032928,0.008057,0.019928,0.013283,0.025757,0.012947,0.017853,-0.02565,0.046997,0.049286,0.036346,0.004448,0.052307,0.051361,-0.041992,-0.013496,-0.008286,0.034943,-0.003775,-0.009171,-0.023636,-0.011238,0.006721,-0.047119,0.053772,0.010887,0.007107,-0.023743,-0.000778,-0.019714,-0.036072,0.012787,-0.014717,-0.012871,0.002691,0.091736,0.006397,0.007778,0.000112,0.014656,0.016373,0.010544,-0.045776,-0.05249,0.046234,0.075989,-0.000317,0.01799,0.083313,-0.031708,0.017578,0.057068,0.036224,0.07251,0.008583,0.033569,-0.123413,0.044891,-0.003124,-0.056488,-0.017014,-0.014732,-0.018051,0.016571,0.030273,-0.048462,0.024979,0.019669,0.0112,0.008987,-0.037872,-0.052155,-0.00187,-0.018097,-0.0625,0.048981,-0.010712,0.030838,-0.072327,0.011955,0.035675,-0.031982,0.033813,-0.018784,-0.019104,-0.010399,-0.040192,0.056793,-0.023926,-0.045197,-0.007973,-0.055145,0.01532,0.031799,-0.017853,0.006313,0.014824,-0.01149,-0.034363,-0.065918,-0.034271,0.024734,-0.046753,0.044006,0.040192,0.027954,-0.017914,-0.03952,-0.007507,0.021591,-0.000943,0.01918,-0.008415,-0.009125,0.011642,-0.011467,-0.050232,-0.015427,-0.022079,0.05542,-0.037964,0.016495,0.007988,1.6e-05,0.014351,0.006672,-0.048004,-0.007702,-0.040771,0.008728,0.088623,0.076904,-0.060608,-0.099731,-0.031738,0.00134,-0.019043,-0.025879,0.019119,-0.008522,-0.02063,-0.002571,-0.026306,0.035675,-0.014259,0.005241,0.000978,0.000959,-0.005829,-0.019409,-0.01207,-0.059326,-0.010666,-0.024475,-0.074402,0.0383,0.041901,-0.060974,-0.004341,0.027573,0.069946,-0.024307,-0.059998,-0.006393,0.025848,-0.002932,-0.020203,0.018661,-0.041138,-0.005417,0.012054,-0.007401,-0.04364,0.02327,-0.015762,-0.021149,-0.018509,-0.010963,-0.002354,-0.00288,0.023087,0.017883,0.041443,-0.033752,-0.014931]', 0, NULL, '2026-06-11 06:03:19.988366+00', '2026-06-11 12:44:23.294527+00' WHERE NOT EXISTS (SELECT 1 FROM public.agent_knowledge WHERE title = 'SPC chart 看 trend / 看某 event 前後 — 不要砍 history');

INSERT INTO public.agent_knowledge (id, user_id, scope_type, scope_value, title, body, priority, active, source, embedding, uses, last_used_at, created_at, updated_at) SELECT 36, 1, 'global', NULL, '跨機台 / 跨站點聚合查詢 — 不要 hard-code 單一 tool_id', '
當 user 問「N 個機台今天 OOC」「全廠 OOC 排名」「各站點 OOC 分布」「比較多台機台的數據」「哪些機台...」「所有機台...」等**跨多 entity 的查詢 / 聚合**時：

⚠ 關鍵限制：`block_process_history` 的 tool_id / lot_id / step **三擇一必填**（runtime enforced）。無法用 tool_id=None / ''ALL'' / ''*'' 拉全廠。**plan 不能把「取得所有機台資料」當成一個 raw_data phase 用 process_history 解決**。

正確 plan 結構（任選一條 path）：

**Pattern A — fan-out（適用要看 detail events）**
1. raw_data phase 1: block_list_objects(kind=''tool'') 取機台清單
2. raw_data phase 2: block_mcp_foreach(mcp_name=''get_process_info'',
   args_template={''tool_id'': ''$tool_id'', ''time_range'': ''24h'', ''object_name'': ''SPC''}) 對每台跑
3. transform phase: block_union 合併 → block_filter(OOC) → block_groupby_agg(toolID, count) → block_sort(desc)
4. chart phase: block_bar_chart 顯示排名

**Pattern B — 聚合 MCP（適用要 count / summary，不需要 row level detail）**
1. raw_data phase: block_mcp_call(mcp_name=''get_process_summary'', args={''time_range'': ''24h'', ''aggregate_by'': ''tool''})
   — **這個輸出算 raw_data，不要 abandon 它**
2. transform phase: block_sort(desc) → block_filter(top N) 若需要
3. chart phase: block_bar_chart

⛔ 不要：
- 為了 plan「一個 raw_data phase」而 hard-code tool_id=''EQP-01'' 拉單台 — 偏離 user 多機台需求
- 用 tool_id={''tools'': ''*''} 或 tool_id=''ALL'' — 都會被 type / value 驗證拒
- 把對的 mcp_foreach / mcp_call 架構建好後又 remove — 看到 verifier reject 才砍，不要預期性砍

✓ plan 「raw_data」phase 的可接受輸出：process_history 結果、mcp_foreach 結果、mcp_call(get_process_summary) 結果 都算 raw_data。
', 'high', true, 'manual', '[-0.004295,0.014511,-0.016006,0.005997,0.007755,0.013199,0.011879,-0.039917,-0.006695,-0.041626,0.028397,0.054352,-0.021072,0.006924,-0.01535,0.002085,0.037445,-0.020721,0.003735,-0.044006,-0.029251,0.01358,0.090027,-0.034424,0.003933,-0.059113,0.004776,0.061646,-0.013786,0.007935,-0.014717,0.012772,-0.027298,0.032562,-0.014084,-0.012428,0.025879,-0.034058,-0.00321,0.028122,-0.038635,0.005589,-0.021149,0.034698,-0.002344,0.009766,0.007927,0.007507,0.077026,0.032257,-0.017609,-0.009193,0.020386,-0.02037,0.024429,-0.009216,-0.029205,-0.004047,0.052399,-0.021729,0.01281,0.036835,0.060883,0.015472,0.002439,-0.031052,-0.038971,0.097839,-0.014671,0.034546,0.037872,0.060852,0.046265,0.004509,0.010498,0.01384,0.023605,0.011429,0.043121,0.048004,-0.010887,0.007244,0.004829,0.012085,0.016037,-0.016876,-0.018753,0.014366,0.017838,-0.014114,0.018478,0.002935,-0.002502,0.038605,0.013916,-0.010841,0.048645,-0.036041,0.023056,-0.005108,0.00901,-0.015457,-0.036682,0.014183,0.001268,0.008316,-0.000607,0.006977,0.007523,0.010056,0.009468,0.020767,0.043793,-0.031494,-0.031052,0.003,-0.00626,-0.006733,-0.0578,-0.004814,0.010925,0.014351,-0.004478,0.01619,-0.008286,-0.068481,0.036163,-0.009201,0.022339,0.013947,-0.024872,0.046448,0.03595,-0.005302,0.018692,0.030457,-0.015015,-0.045685,0.020752,0.024796,0.047241,0.047272,0.020798,0.038147,0.01432,-0.015358,0.014801,0.03653,0.007019,-0.013924,-0.013504,0.028412,0.026031,-0.033569,0.049225,0.012154,0.053833,-0.043884,0.01088,0.020828,-0.024429,-0.07428,0.027222,-0.026947,0.015945,-0.039246,0.04184,-0.009964,-0.00351,0.001032,0.015518,-0.017029,0.019638,0.004543,-0.011047,0.008255,0.011086,0.015823,-0.002472,0.063354,0.003338,-0.043976,-0.023483,-0.090637,0.023117,-0.015106,-0.007572,0.036835,0.010666,-0.013367,-0.01252,-0.048157,-0.079224,0.001432,-0.04306,-0.000387,0.030731,-0.045013,0.032104,0.062866,0.015541,-0.032104,0.013794,-0.009193,-0.024368,0.000978,0.013519,0.001385,-0.045746,0.029251,-0.014008,-0.033875,-0.017075,0.011665,-0.029404,0.025284,0.055054,0.044617,-0.008919,-0.018356,0.065613,-0.029892,0.001089,-0.006767,0.02179,0.029755,-0.038025,-0.019775,0.028503,0.037354,0.007614,-0.020599,0.001862,-0.034454,0.068726,0.013138,0.015488,0.001842,-0.032135,-0.046936,0.005974,0.018326,0.014732,-0.01033,-0.01239,0.011925,-0.034851,-0.024353,-0.014038,0.016098,0.011482,0.007191,-0.0354,-0.004948,-0.019485,0.005981,-0.064575,0.025009,0.028015,0.007881,0.02124,0.00631,0.034668,-0.019135,0.003448,-0.011322,-0.002281,-0.013451,0.052429,0.006783,-0.010338,-0.022232,-0.013283,0.011879,-0.042297,-0.006893,-0.02034,-0.006844,0.02002,0.061401,-0.002384,0.008484,0.009659,-0.017853,-0.023697,0.047058,-0.062683,0.031708,-0.046112,0.01709,0.009483,-0.018158,-0.010681,0.00491,-0.019562,0.004879,0.035431,-0.034729,-0.032562,0.020584,-0.008095,0.003328,-0.006695,-0.009422,-0.011856,-0.010963,0.051331,-0.016113,0.047485,0.035767,0.002222,0.024216,-0.010811,0.025848,-0.072266,-0.009071,-0.032623,-0.046448,-0.016724,0.05011,-0.014992,-0.050568,-0.078796,-0.015091,-0.019058,0.051208,0.011467,0.006378,-0.011887,-0.015068,0.087952,-0.01236,0.016418,-0.057526,0.041962,0.00708,0.045349,0.044373,0.003269,-0.015839,-0.091064,-0.036743,-0.054932,0.032349,0.012779,-0.013206,-0.0168,-0.026596,0.00779,-0.040833,0.016083,0.014191,-0.003288,-0.024368,0.025208,-0.028214,0.045502,0.031235,-0.006332,-0.026398,0.018204,-0.030075,-0.048645,0.013512,-0.005108,0.01886,-0.00044,0.016541,-0.005119,0.013474,0.015083,0.071411,0.090759,0.054962,-0.047943,-0.011475,-0.023056,-0.003691,0.063599,-0.038025,0.003975,-0.030487,0.030609,0.007133,0.030502,0.033325,-0.023041,-0.015312,0.002689,-0.017578,0.029266,0.035065,0.027588,-0.049347,-0.016739,0.045135,-0.004307,0.028732,-0.087341,-0.019409,0.037842,-0.046234,-0.021347,-0.031891,-0.017838,0.054962,-0.004051,0.001296,0.019287,0.018646,-0.020813,0.018265,-0.013496,-0.012177,-0.029541,0.028336,-0.013382,0.030899,-0.017365,-0.017471,-0.006294,-0.019608,0.000518,0.016876,0.007568,0.063843,0.025955,-0.017609,0.066711,-0.009247,-0.036072,0.002596,-0.020325,0.021576,-0.00972,0.00176,-0.031097,0.010849,-0.008911,-0.013474,0.0177,-0.007767,0.015602,-0.003241,0.04007,0.045105,0.024399,0.046509,0.001857,0.010124,0.031769,0.03183,0.012802,-0.037048,-0.000296,-0.063171,-0.028915,0.0242,0.024338,0.011803,-6.6e-05,-0.007679,0.009003,-0.044952,0.042114,-0.020447,0.068848,0.036285,-0.008774,0.039032,-0.037689,0.063721,-0.021088,-0.016937,0.026047,0.014442,-0.048859,0.020554,0.003061,-0.008392,0.01059,0.023285,-0.053864,-0.017166,-0.093201,0.035156,0.030411,0.00827,0.02739,-0.063721,-0.076294,0.035156,-0.025986,0.013786,-0.004269,-0.004585,-0.015839,-0.037567,-0.137573,-0.055237,-0.015404,0.043518,-0.051422,0.045013,-0.007309,0.009743,0.027496,-0.016449,-0.031235,-0.01712,0.001228,-0.001541,-0.004951,0.042633,0.034637,-0.030273,0.029068,0.00486,0.029343,-0.042419,0.008492,0.076172,-0.030365,0.004089,0.021622,0.007324,-0.052002,-0.01281,-0.105774,-0.025894,0.034912,0.016144,0.016068,-0.002714,-0.045685,-0.060913,0.013458,0.015823,0.024719,0.002687,-0.020264,0.008659,-0.015793,0.03038,0.030975,-0.009521,-0.013039,-0.014732,-0.043549,-0.0186,-0.004692,0.009071,-0.010193,-0.012604,0.010818,0.025894,-0.013115,0.009109,0.015671,-0.042603,0.046936,-0.040375,-0.02388,0.053467,0.014923,-0.036316,0.028656,0.019379,-0.026367,-0.029861,0.031799,0.02623,0.014778,0.022903,-0.001284,-0.040802,0.016861,-0.002018,0.005695,-0.004753,-0.022537,0.008621,0.014572,-0.006622,-0.000125,-0.02832,-0.003061,-0.002851,0.03183,0.018997,0.033051,-0.002489,0.005657,0.005375,-0.000959,0.026962,0.005535,0.055267,0.074707,0.013268,-0.048218,0.010254,0.003124,-0.012634,0.034515,0.007015,0.018784,0.01709,0.018723,-0.021927,0.052032,-0.020569,-0.058929,0.03421,-0.018967,-0.040955,-0.044098,-0.031082,-0.017746,-0.000129,-0.018951,-0.020859,-0.00478,0.006481,-0.000175,0.012619,0.022202,0.023544,-0.04657,-0.016876,-0.045746,-0.043732,-0.028046,0.005447,-0.010384,0.001832,-0.023788,0.004944,-0.014877,-0.020065,-0.005276,0.039642,-0.003494,-0.00415,-0.015022,0.027893,0.028427,0.017807,0.031219,-0.02417,-0.023834,0.03653,0.062164,-0.019394,0.014847,-0.009995,0.007725,0.006474,-0.019699,0.058624,0.073669,0.015274,0.027252,0.053894,0.013329,-0.031525,0.008751,0.045776,0.016144,-0.024277,0.025787,-0.000647,0.081604,0.0672,0.104919,-0.079163,-0.071045,-0.020401,0.05777,-0.046692,0.010254,0.026611,-0.010895,-0.011917,0.003727,0.019974,-0.039917,0.008476,0.044098,-0.009384,0.023071,0.02507,-0.022079,0.004215,-0.012276,0.013992,0.035889,0.010475,-0.04361,-0.002987,0.010857,0.010529,-0.011581,0.009575,-0.028931,-0.050537,0.027649,-0.029999,0.051941,0.026932,0.042114,0.016266,0.009369,-0.029495,-0.00465,0.029251,0.002916,-0.010437,-0.034424,0.027451,0.036591,-0.038635,-0.046173,-0.033783,0.015617,0.002251,0.00526,-0.010941,-0.009262,0.032013,0.023224,0.024048,0.007355,0.02359,0.03421,-0.028076,-0.005901,-0.035248,0.012611,-0.000394,-0.00769,0.027267,-0.04422,-0.028458,0.029633,0.014908,-0.003614,-0.034546,0.010193,-0.034302,-0.005089,-0.016083,0.017914,0.007053,-0.004639,0.014854,-0.010681,-0.000652,0.008873,-0.02919,-0.021896,0.002129,0.01207,0.030853,0.033569,0.031433,-0.010391,-0.046906,0.014664,0.032379,0.007145,-0.002026,0.007595,0.004848,-0.013351,-0.003256,0.005081,-0.008995,0.035034,-0.072693,0.001669,-0.0042,0.035492,0.019516,-0.030457,0.009933,0.056213,-0.007275,0.015404,0.02478,-0.017654,-0.005096,0.014389,0.015594,0.033936,-0.024261,0.008713,-0.01738,-0.023636,-0.00539,-0.023895,-0.018967,0.010353,0.001369,-0.012436,-0.023605,-0.01239,-0.01268,-0.015808,0.043762,-0.019638,0.074341,-0.045837,-0.006374,0.01133,0.016022,0.066833,0.063354,0.022476,0.016281,0.006702,-0.005112,-0.009941,0.001184,-0.011253,0.033813,0.002279,0.00069,-0.022858,-0.04422,-0.048615,-0.018341,0.000416,0.01091,0.015198,-0.026733,-0.009079,0.031067,-0.002651,0.008911,0.025421,-0.000465,-0.004108,0.000577,0.012657,0.010712,0.005138,0.052094,0.04184,0.047089,-0.002872,0.061188,0.038574,-0.032745,-0.000548,-0.004425,0.026215,-0.006451,-0.033386,-0.02124,-0.058014,0.033112,-0.052734,0.017059,-0.016907,-0.024475,-0.017654,0.031708,0.025513,-0.008041,-0.056183,-0.016693,0.012062,-0.000987,0.079895,0.009621,0.012321,-0.003391,0.004528,0.009636,0.013794,-0.043518,-0.073669,0.03064,0.039703,0.015808,0.009613,0.093262,-0.073853,0.048492,0.011002,0.028259,0.041107,0.080261,0.054871,-0.03035,0.051605,8.7e-05,-0.059357,-0.009666,-0.008987,-0.004841,0.005302,0.037292,-0.045685,0.010223,-0.007103,-4.4e-05,0.001184,-0.038727,0.016006,-0.002954,-0.018417,-0.059448,0.037964,0.003874,0.07312,-0.05246,0.023529,0.033539,-0.036072,0.042908,0.010254,-0.008598,-0.039368,-0.024567,0.008942,0.025986,-0.043976,0.00618,-0.031219,-0.032837,0.027435,-0.011345,0.032562,-0.003656,0.018417,0.0186,-0.013489,0.035095,0.034058,-0.040039,0.066833,-0.00491,0.042419,-0.006214,0.039429,-0.007687,0.005901,0.007397,-0.029083,-0.012596,-0.016068,0.005878,0.009201,-0.017014,0.001509,-0.014267,0.021042,0.02449,0.005463,-0.011246,-0.0186,-0.005478,-0.006294,-0.045319,0.043365,-0.033844,0.003141,0.052856,0.066895,-0.076782,-0.069275,-0.040497,-0.010872,-0.022202,-0.018494,0.061218,0.006477,-0.016434,-0.019577,-0.038635,0.023178,0.00407,0.016022,-0.006226,0.045441,-0.006607,0.007469,-0.024734,-0.020096,-0.00526,-0.063843,-0.082092,0.018158,0.056732,-0.028717,-0.029205,0.033722,0.067322,0.014694,-0.049347,0.003038,0.02005,-0.043335,-0.043884,0.013374,-0.068604,-0.010422,-0.003536,-0.009186,-0.039551,0.008301,-0.016129,-0.027573,-0.01622,-0.000721,-0.020187,-0.024765,0.017517,-0.016937,0.071533,0.00988,-0.037201]', 0, NULL, '2026-06-11 07:22:16.538381+00', '2026-06-11 12:44:23.702855+00' WHERE NOT EXISTS (SELECT 1 FROM public.agent_knowledge WHERE title = '跨機台 / 跨站點聚合查詢 — 不要 hard-code 單一 tool_id');

INSERT INTO public.agent_knowledge (id, user_id, scope_type, scope_value, title, body, priority, active, source, embedding, uses, last_used_at, created_at, updated_at) SELECT 37, 1, 'global', NULL, 'multi-tool 查詢 (N 個具名機台) 的正確 path — 禁 ALL magic value', '
當 user 列出 N 個具名機台（例如「EQP-01 EQP-02 EQP-03」「比較 EQP-01 跟 EQP-02」）時，pipeline 設計：

⛔ **絕對禁止** tool_id=''ALL'' / ''all'' / ''*'' / ''\*'' / None — block_process_history runtime 雖然 simulator 可能容錯，但這是 undefined behavior，拿到的資料 row count 不固定、不是「真正 N 台的合集」。

✓ 兩條正確 path（看 user 是否要 row-level detail 來選）：

**Pattern A — N × process_history + block_union**（需要 row-level detail）
1. raw_data phase 1: block_process_history(tool_id=''EQP-01'', time_range=...) → df1
2. raw_data phase 2: block_process_history(tool_id=''EQP-02'', time_range=...) → df2
3. (再加一個 block_process_history per tool)
4. transform phase: block_union(on_schema_mismatch=''outer'') 合 N 個 df
5. 接下游 unnest / filter / groupby / sort / chart

**Pattern B — block_mcp_call get_process_summary**（只要 count / summary）
1. raw_data phase: block_mcp_call(mcp_name=''get_process_summary'', args={''time_range'': ''7d'', ''aggregate_by'': ''tool''})
2. transform phase: block_filter(toolID, op=''in'', value=[''EQP-01'',''EQP-02'',''EQP-03'']) → block_sort
3. chart phase: block_bar_chart

決策樹：
- N ≤ 5 且要看「每筆 event」→ Pattern A（明顯 row-level）
- N > 5 或只要排名 / count → Pattern B（避免 fan-out 爆量）

⚠ 補充：「**所有機台**」(N 不明) 不是這條 entry 的範圍（看 id=36）— 那條走 list_objects + mcp_foreach 或直接 mcp_call(get_process_summary)。
  ', 'high', true, 'manual', '[0.005043,0.010208,-0.047943,0.039429,0.021027,0.025162,0.038971,-0.031128,-0.01223,-0.02124,0.017822,0.038147,-0.007881,-0.012993,-9.6e-05,0.002838,0.033234,-0.013542,0.005505,-0.037109,-0.026367,0.021835,0.081787,-0.017639,0.019989,-0.06015,0.013657,0.050385,0.012619,0.033325,-0.001285,-0.004761,-0.027527,0.021347,0.006783,-0.001533,0.033081,-0.035828,-0.001883,0.043854,-0.039154,-0.016739,-0.038055,0.039734,0.018478,0.023605,-0.006481,-0.007973,0.067749,0.023041,0.02684,-0.049652,0.018539,0.014915,0.022873,-0.00363,-0.032349,-0.036682,0.044098,-0.02626,0.009186,0.034119,0.037079,0.023819,0.032715,-0.014702,-0.02298,0.077759,-0.013329,0.022949,0.04007,0.030716,0.027573,-0.004757,-0.039795,0.02774,0.033081,0.042664,0.044495,0.037292,-0.001345,0.026199,0.029526,0.041595,0.015289,-0.004524,-0.036377,0.04184,-0.009598,-0.017578,0.019394,-0.003099,-0.02713,0.035675,0.009857,-0.005402,0.042297,-0.014786,0.009941,0.001571,0.029312,0.013618,0.01265,0.017487,0.020508,0.016083,0.027054,0.020081,-0.014053,-0.021057,0.016663,-0.00898,0.008202,-0.020447,-0.051331,-0.010017,-0.002319,-0.025787,-0.03183,-0.045105,-0.0168,0.003298,0.006794,0.007881,-0.018387,-0.086609,0.02832,-0.00898,-0.003408,0.029083,-0.038422,0.034454,0.011108,-0.011635,0.046844,0.017319,0.005096,-0.032684,0.059845,0.041626,0.025558,0.036255,0.017899,0.030869,-0.011436,-0.020966,0.017181,0.02565,0.014038,-0.02449,-0.016129,0.037903,0.023987,-0.006367,0.045227,0.012764,0.031525,-0.041962,0.002972,0.01738,-0.021683,-0.049927,0.017624,-0.035217,-0.007645,-0.030411,0.025421,-0.005051,-0.017578,0.007797,0.005829,-0.033447,0.010468,-0.004623,-0.008202,0.041107,0.029541,0.022629,0.001343,0.050537,-0.004318,-0.016785,-0.031235,-0.088318,0.035187,0.009529,-0.015076,0.006584,0.002056,0.023071,-0.019287,-0.042328,-0.07489,-0.002031,-0.044983,0.018234,0.032562,-0.034668,0.02063,0.069458,0.000116,-0.030762,0.022186,0.000663,-0.03421,0.015083,0.02562,-0.015083,-0.05484,0.051575,-0.008766,-0.01545,0.005554,0.009338,-0.038116,0.005009,0.062805,0.051086,-0.025299,-0.032104,0.048859,-0.02858,-0.002665,-0.014435,-0.003611,-0.007366,-0.007629,-0.000328,-0.007298,0.002392,0.001275,-0.016464,0.042419,-0.021561,0.039215,-0.008736,0.012337,-0.024216,-0.008705,-0.015068,-0.002876,0.027893,0.03096,-0.003937,-0.02739,0.014328,-0.032867,-0.023178,-0.024658,0.007568,0.028839,0.005966,-0.033386,-0.001229,-0.019974,0.014587,-0.044342,0.00898,0.011093,-0.00234,0.009613,-0.011787,0.021408,-0.003704,-0.008049,-0.026184,-0.000207,0.002167,0.041992,0.005554,-0.017365,-0.004562,-0.013641,0.012291,-0.036011,0.011696,-0.023041,0.005199,0.017548,0.061401,-0.016769,0.001963,0.014923,-0.007179,-0.005478,0.052856,-0.084167,0.033203,-0.027359,0.002354,-0.037811,-0.015213,-0.013695,0.015213,-0.007439,-0.000291,0.052795,-0.034973,-0.056152,0.030746,-0.016739,-0.007629,-0.006256,0.003382,-0.011917,-0.027252,0.040649,-0.007549,0.061768,0.018387,0.009163,0.017853,-0.025879,0.018082,-0.057159,-0.022156,-0.01976,-0.057037,-0.009552,0.061584,-0.023666,-0.058502,-0.053162,-0.007759,-0.042053,0.062988,0.023895,-0.011383,-0.015945,-0.013718,0.099426,0.01944,0.014984,-0.034943,0.049835,0.000474,0.034943,0.032654,-0.03064,0.000914,-0.082031,-0.037476,-0.062805,0.036133,0.025681,0.00584,0.0042,-0.025497,-0.00824,-0.029678,0.012665,0.02449,0.016388,-0.02243,0.040802,-0.037567,0.049408,0.013992,-0.004227,-0.007729,0.006371,-0.03952,-0.045532,0.003696,-0.017578,0.041779,-0.019821,0.0233,-0.00914,0.001882,0.015808,0.059296,0.066406,0.059479,-0.049194,-0.018143,-0.01329,0.047607,0.069092,-0.03067,-0.031464,-0.02713,0.022003,-0.008995,0.009827,0.053802,-0.021973,-0.023026,0.003004,-0.044678,-0.002672,0.019119,0.032745,-0.043243,-0.010231,0.017197,-0.005898,0.021988,-0.061798,-0.028656,0.009148,-0.039673,-0.034882,-0.026978,-0.010056,0.015358,-0.001287,0.016205,0.052094,0.021866,-0.001102,0.00333,-0.016891,-0.03244,0.002808,0.0075,0.012314,0.024017,-0.025818,-0.007935,-0.01973,-0.041748,0.007763,0.029984,0.008942,0.044342,0.017426,-0.024841,0.049805,0.003265,-0.022141,0.028214,-0.015083,0.042267,-0.008034,0.002226,-0.049591,0.021866,-0.018372,-0.009689,0.013542,0.00375,0.007706,0.010002,0.025833,0.036774,0.016296,0.038361,0.010796,-0.008102,0.027298,0.035095,0.002468,-0.048248,0.005905,-0.03656,-0.045197,0.02005,0.009636,0.036835,0.008247,-0.00869,0.023773,-0.021973,0.033112,0.010406,0.030884,0.027695,-0.024979,0.046295,-0.031433,0.055725,-0.021255,-0.033997,0.031433,0.044525,-0.043152,0.022873,-0.000763,0.006916,0.001719,0.018982,-0.045593,-0.018082,-0.073914,0.025101,0.026443,0.005051,0.044586,-0.063354,-0.049988,0.03717,-0.041534,0.008934,-0.032013,-0.036865,-0.009605,-0.041199,-0.124451,-0.061768,0.011589,0.03595,-0.043976,0.036316,0.002735,0.004353,0.01545,-0.021011,-0.060028,-0.032135,-0.006142,0.007858,-0.000184,0.034546,0.016068,-0.010338,0.024536,-0.0159,0.040405,-0.039276,0.022446,0.096436,-0.025574,0.00272,0.013824,0.00972,-0.045929,-0.00491,-0.09613,-0.017792,0.024368,0.00959,0.013268,-0.004059,-0.045959,-0.064331,0.014557,0.0289,0.015099,0.008377,-0.007912,0.013481,0.002523,0.032135,0.01944,-0.017792,-0.005367,-0.013855,-0.043274,-0.005871,-0.016571,-0.004143,-0.024307,-0.022827,-2e-05,0.011177,-0.024963,-0.000528,0.014122,-0.035461,0.023331,-0.033142,-0.024689,0.053864,0.027496,-0.050842,-0.006104,0.004013,-0.029007,-0.022186,0.017395,0.038818,0.016037,0.026443,0.000677,-0.046539,0.042694,0.002193,-0.010246,0.011887,-0.01017,-0.006115,0.023956,-0.006058,-0.051971,-0.032593,0.020416,0.000835,0.061798,0.02948,0.039581,-0.013977,0.009407,0.013168,-0.015091,0.030228,0.010719,0.053955,0.049805,0.014648,-0.038391,0.012032,0.00544,-0.005592,0.026031,0.004013,0.017822,0.010941,-0.005096,-0.012978,0.040985,-0.011124,-0.053162,0.019547,-0.022415,-0.027557,-0.047577,-0.037903,-0.029282,-0.004971,-0.018982,-0.004784,0.018738,0.007229,0.006348,0.002108,0.001159,0.03833,-0.04306,-0.013542,-0.02832,-0.019699,-0.016342,-0.000978,-0.009796,-0.049896,-0.019501,-0.010773,-0.003782,-0.002375,-0.001119,0.005749,0.013359,-0.017761,0.002056,0.016861,0.024704,0.003241,0.049011,-0.033661,-0.060425,0.005199,0.075745,-0.018295,0.032166,-0.017166,0.007282,0.017365,-0.026993,0.058533,0.095581,0.028625,0.027008,0.072754,0.027252,-0.060608,0.022018,0.043701,0.019104,-0.014458,0.03476,0.005211,0.032104,0.072876,0.09668,-0.053345,-0.053619,0.01284,0.037201,-0.019531,0.001267,0.011536,-0.028061,-0.027695,-0.027679,0.032166,-0.075439,-0.015099,0.034882,-0.005306,0.01796,0.025513,-0.016373,0.006069,-0.002319,0.00423,0.030807,0.015221,-0.04007,0.011452,0.004566,0.021591,-0.013802,0.005421,-0.010887,-0.047974,0.016541,-0.030869,0.059326,0.038116,0.034729,0.019272,-0.012299,-0.009171,-0.011978,0.033936,0.008667,0.007568,-0.045044,0.04718,0.027283,-0.034271,-0.03775,-0.062164,0.036652,-0.002216,0.006134,0.001347,-0.003052,0.027695,0.018738,0.01387,0.00853,0.010788,0.017166,-0.026642,-0.010307,-0.070984,0.034302,-0.005051,-0.01236,0.014343,-0.054779,-0.019653,0.020996,0.034271,0.001673,-0.008888,0.005726,-0.033539,0.000538,-0.013695,0.005459,-0.009682,-0.013039,0.013054,-0.011101,0.016617,-0.01487,-0.000798,-0.012596,-0.001798,0.035522,-0.009438,0.023361,0.034576,0.030334,-0.036804,0.020645,0.015053,0.032776,-0.007236,0.024261,-0.016663,0.010803,-0.012466,-0.006466,-0.007076,0.037933,-0.072693,0.001026,0.009201,0.036224,0.022842,-0.033691,0.001896,0.040558,-0.011429,0.018738,0.006886,-0.03595,-0.006229,0.026932,0.004829,0.013512,-0.025055,0.008804,-0.014801,-0.017838,-0.022858,0.023605,-0.02182,-0.004425,0.004192,0.034241,-0.028183,-0.030945,0.010117,-0.035217,0.041748,0.000768,0.079346,-0.053284,0.015511,-0.015884,-0.011749,0.081604,0.083313,0.039886,-0.0015,-0.012039,-0.009567,-0.008881,-0.004673,-0.028976,0.029053,0.017944,-0.007988,-0.008583,-0.057709,-0.034393,-0.014351,0.010254,-0.011223,0.030792,-0.005424,0.005131,0.032288,0.013733,0.008095,0.021362,-0.008286,0.002909,0.003241,0.029739,0.020432,0.00452,0.059448,0.051086,0.071289,-0.012543,0.057983,0.047852,-0.040222,-0.000666,-0.007774,0.018738,-0.039734,-0.0354,-0.025742,-0.079224,0.034424,-0.041473,0.030212,0.009384,-0.009361,-0.009377,0.017227,0.029175,0.000278,-0.028198,-0.050873,0.001623,0.001776,0.116699,0.021347,0.013306,-0.000391,0.01532,0.011421,0.015701,-0.048065,-0.087219,-0.010399,0.036682,0.006817,0.014359,0.098145,-0.068542,0.021286,0.040009,0.052216,0.061981,0.085876,0.066223,-0.066589,0.017105,0.000473,-0.03421,-0.027771,-0.016113,-0.01355,-0.003883,0.036682,-0.036133,0.000824,0.0042,0.008087,0.000119,-0.019653,-0.002441,0.013107,-0.021896,-0.048706,0.030365,-0.005722,0.059448,-0.042206,0.034851,0.032837,-0.034515,0.05426,0.009041,-0.030685,-0.052063,-0.039551,0.023941,0.032318,-0.079651,0.008965,-0.013809,-0.04483,0.031677,-0.000423,0.006493,-0.010704,-0.000382,-0.016953,-0.031311,-0.018829,0.038177,-0.025024,0.031555,0.014038,0.018356,0.008636,0.002857,-0.011116,0.011673,0.002249,-0.000797,-0.000583,-0.020996,0.003075,0.019318,-0.045929,-0.000578,-0.017319,0.061096,-0.019333,-0.003244,-0.000682,-0.00176,-0.003847,-0.019562,-0.063782,0.035797,-0.030334,0.002199,0.043335,0.06543,-0.086853,-0.049103,-0.020615,-0.001017,-0.018097,-0.024673,0.044769,0.013115,-0.009155,-0.023254,-0.038696,0.014656,-0.003922,0.007942,0.014793,0.034515,-0.033936,0.000857,-0.024094,-0.032654,-0.010345,-0.014267,-0.088318,-0.001397,0.05481,-0.021027,-0.033508,0.003515,0.072388,0.002054,-0.031281,0.003162,0.015343,-0.012497,0.000626,0.029861,-0.024994,-0.004654,-0.001471,0.006493,-0.066406,0.01738,-0.02034,-0.039093,-0.016922,0.015388,-0.039795,-0.008469,0.015625,-0.028046,0.050049,0.025528,-0.025955]', 0, NULL, '2026-06-11 14:37:46.202387+00', '2026-06-11 14:37:51.251642+00' WHERE NOT EXISTS (SELECT 1 FROM public.agent_knowledge WHERE title = 'multi-tool 查詢 (N 個具名機台) 的正確 path — 禁 ALL magic value');
