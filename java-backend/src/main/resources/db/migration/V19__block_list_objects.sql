-- V19 — Single dispatch block for the 5 list-type system MCPs.
--
-- Why: agents and users were going through block_mcp_call with mcp_name=
-- 'list_tools' / 'list_lots' / etc. for ontology master lookups. Hard to
-- discover from the BlockDocsDrawer (no dedicated entry) and the MCP name
-- string is an avoidable failure mode (typos, version drift). One typed
-- block with a kind enum keeps maintenance low (one row, one executor)
-- while improving discoverability.

-- ─── 1. INSERT block_list_objects ────────────────────────────────────────
INSERT INTO pb_blocks
  (name, version, category, status, description,
   input_schema, output_schema, param_schema, implementation,
   examples, output_columns_hint, is_custom)
VALUES (
  'block_list_objects', '1.0.0', 'source', 'production',
$desc$== What ==
列出 ontology master 物件清單（機台 / 批次 / 站點 / APC 參數 / SPC chart）。
用 `kind` enum 一次選一種，內部 dispatch 到對應 system MCP 並回傳 DataFrame。

== When to use ==
- ✅ 「列出所有機台」「目前有哪些 active lot」「這 20 站的清單」→ kind=tool/lot/step
- ✅ 「APC 參數有哪些」「SPC chart 類型」→ kind=apc/spc
- ✅ 想做 enrichment（每個 tool 跑一次某查詢）→ 接 block_mcp_foreach
- ❌ 查 process 歷史 / 趨勢 → 用 block_process_history
- ❌ 查告警 / 摘要 / 沒在 5 種 kind 內的 list MCP → 用 block_mcp_call

== kind → MCP 對應 ==
- kind='tool' → list_tools  （回傳每台機台 + status / busy_lot）
- kind='lot'  → list_lots   （回傳 active lot + current_step / cycle）
- kind='step' → list_steps  （回傳 process flow 的 step 清單）
- kind='apc'  → list_apcs   （回傳 APC 參數 master）
- kind='spc'  → list_spcs   （回傳 SPC chart 類型 master）

== Params ==
kind (string, required) 五擇一: 'tool' | 'lot' | 'step' | 'apc' | 'spc'
args (object, optional)  forward 給對應 MCP 的 query params；多數 list MCP 不需要參數

== Output ==
port: data (dataframe) — 欄位由對應 MCP 的回傳結構決定（每個 object 的 key 變一個 column）。
查欄位細節請看對應 MCP 的 description（從 mcp_definitions 動態讀）。

== Common mistakes ==
⚠ 跟 block_mcp_call 的差異：本 block 只服務 5 種 list 類；其他 MCP 仍走 block_mcp_call
⚠ kind 是 enum 字串（'tool' / 'lot' / ...），不是 MCP 名（'list_tools'）；寫錯 → INVALID_PARAM
⚠ args 是 object（dict），不是 string

== Errors ==
- INVALID_PARAM      : kind 不在 5 種 enum 內，或 args 型別不對
- MCP_NOT_FOUND      : 對應 MCP 沒註冊（需檢查 system MCP seed）
- INVALID_MCP_CONFIG : MCP api_config 缺 endpoint_url
- MCP_HTTP_ERROR     : MCP 回 4xx/5xx
- MCP_UNREACHABLE    : 網路不通
$desc$,
  '[]',
  '[{"port": "data", "type": "dataframe"}]',
  '{"type": "object", "required": ["kind"], "properties": {"kind": {"type": "string", "enum": ["tool", "lot", "step", "apc", "spc"], "title": "物件類別"}, "args": {"type": "object", "title": "MCP 參數 (object)"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.list_objects:ListObjectsBlockExecutor"}',
  '[{"name": "列機台清單", "summary": "kind=tool → list_tools；回傳所有機台 + status / busy_lot", "params": {"kind": "tool", "args": {}}}, {"name": "列 active 批次", "summary": "kind=lot → list_lots；回傳 active lot + current_step / cycle", "params": {"kind": "lot", "args": {}}}, {"name": "列 process flow 站點", "summary": "kind=step → list_steps；回傳所有 STEP_xxx 清單", "params": {"kind": "step", "args": {}}}, {"name": "列 APC 參數 master", "summary": "kind=apc → list_apcs；回傳 APC 參數定義", "params": {"kind": "apc", "args": {}}}, {"name": "列 SPC chart 類型", "summary": "kind=spc → list_spcs；回傳 SPC chart 類型 master", "params": {"kind": "spc", "args": {}}}]',
  '[]',
  false
)
ON CONFLICT (name, version) DO UPDATE SET
  description = EXCLUDED.description,
  input_schema = EXCLUDED.input_schema,
  output_schema = EXCLUDED.output_schema,
  param_schema = EXCLUDED.param_schema,
  implementation = EXCLUDED.implementation,
  examples = EXCLUDED.examples,
  output_columns_hint = EXCLUDED.output_columns_hint,
  status = EXCLUDED.status,
  category = EXCLUDED.category,
  updated_at = now();

-- ─── 2. UPDATE block_mcp_call.description — redirect list-type MCPs ─────
-- The agent should reach for block_list_objects when it wants list_tools /
-- list_lots / etc., not the generic dispatcher. Patch the existing block
-- description so the LLM sees the redirect every time it inspects the
-- block. (Static seed.py SSOT also updated to keep both surfaces aligned.)
UPDATE pb_blocks
SET description = replace(
      description,
      '- ✅ 呼叫**沒有專用 block** 的 MCP：list_tools / get_alarm_list / get_tool_status / get_process_summary',
      E'- ✅ 呼叫**沒有專用 block** 的 MCP：get_alarm_list / get_tool_status / get_process_summary\n'
      || '- ❌ list_tools / list_lots / list_steps / list_apcs / list_spcs → 用 block_list_objects(kind=...)'
    ),
    updated_at = now()
WHERE name = 'block_mcp_call'
  AND description LIKE '%list_tools / get_alarm_list%';

-- ─── 3. UPDATE block_process_history.description — point list at new block ─
UPDATE pb_blocks
SET description = replace(
      description,
      '- ❌ 「現在哪些機台在跑 / 機台清單」→ 用 block_mcp_call(list_tools)',
      '- ❌ 「現在哪些機台在跑 / 機台 / 批次 / 站點清單」→ 用 block_list_objects(kind=...)'
    ),
    updated_at = now()
WHERE name = 'block_process_history'
  AND description LIKE '%block_mcp_call(list_tools)%';
