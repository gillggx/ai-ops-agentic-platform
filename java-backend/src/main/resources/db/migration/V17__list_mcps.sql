-- 2026-05-06: register 4 list-type system MCPs so chat agent can answer
-- "what APCs / SPCs / steps / active lots exist". list_tools already exists
-- and is unchanged. Each row points at a simulator endpoint (port 8012)
-- via api_config; sidecar dispatches by name → simulator HTTP call.
--
-- Idempotent via ON CONFLICT (name) DO NOTHING — re-running on a DB that
-- already has these rows is a no-op.

INSERT INTO mcp_definitions
  (name, mcp_type, visibility, description, processing_intent, api_config, input_schema)
VALUES
  (
    'list_active_lots', 'system', 'public',
       E'== What ==\n'
    || E'列出目前還在跑的 lot — Waiting + Processing 狀態的 lot 都算 active。\n\n'
    || E'== Use when ==\n'
    || E'- 「現在有哪些 lot 還沒跑完」\n'
    || E'- 「哪些 lot 卡在哪一站」（看 current_step）\n'
    || E'- 跟 list_steps 對照看 lot 走到哪了\n\n'
    || E'== Returns ==\n'
    || E'[{lot_id, current_step, status, cycle}, ...]  // 通常 ~20 筆\n'
    || E'  status: ''Waiting'' (排隊) / ''Processing'' (機台正在跑) — Finished 不會列\n\n'
    || E'== Common mistakes ==\n'
    || E'⚠ 想看完成過的 lot 請用 process_info 查歷史 events，不是這個 MCP\n',
    '',
    '{"endpoint_url": "http://localhost:8012/api/v1/lots?status=active", "method": "GET", "headers": {}}',
    '{"fields": []}'
  ),
  (
    'list_steps', 'system', 'public',
       E'== What ==\n'
    || E'列出系統定義的全部 process steps（STEP_001 ~ STEP_NNN）。\n\n'
    || E'== Use when ==\n'
    || E'- 「系統有哪些 step」「總共幾站」\n'
    || E'- 跟 list_active_lots 對照看 lot 還剩多少步沒跑\n\n'
    || E'== Returns ==\n'
    || E'{total: int, steps: [{name: ''STEP_001'', description}, ...]}\n',
    '',
    '{"endpoint_url": "http://localhost:8012/api/v1/list-steps", "method": "GET", "headers": {}}',
    '{"fields": []}'
  ),
  (
    'list_apcs', 'system', 'public',
       E'== What ==\n'
    || E'列出系統有哪些 APC config object（從 object_snapshots 拉 distinct apcID）。\n\n'
    || E'== Use when ==\n'
    || E'- 「系統現在有幾個 APC」「APC 名單」\n'
    || E'- 想看某個 APC 的歷史時，先用這個確認 ID\n\n'
    || E'== Returns ==\n'
    || E'{total: int, apcs: [{apcID: ''APC-003''}, ...]}\n\n'
    || E'== Common mistakes ==\n'
    || E'⚠ 這只列 APC config object（可重用、跨 lot 共享）。要看某筆 process 的\n'
    || E'  APC parameter 數值請用 get_process_info（events[].APC.parameters）\n',
    '',
    '{"endpoint_url": "http://localhost:8012/api/v1/list-apcs", "method": "GET", "headers": {}}',
    '{"fields": []}'
  ),
  (
    'list_spcs', 'system', 'public',
       E'== What ==\n'
    || E'列出系統支援的 SPC chart 種類。每筆 process event 的 SPC.charts 物件\n'
    || E'會帶這幾種 chart 的 value / ucl / lcl / is_ooc。\n\n'
    || E'== Use when ==\n'
    || E'- 「SPC 有哪幾種 chart」「除了 xbar 還有什麼可看」\n'
    || E'- 寫 pipeline 前確認可用的 SPC 欄位\n\n'
    || E'== Returns ==\n'
    || E'{total: int, charts: [{chart: ''xbar_chart'', description}, ...]}\n'
    || E'  目前 5 種：xbar / r / s / p / c\n\n'
    || E'== Common mistakes ==\n'
    || E'⚠ chart 名是 ''xbar_chart''（含 _chart 後綴），不是單純 ''xbar''\n'
    || E'⚠ 要看實際數值請用 get_process_info — 這個 MCP 只列種類\n',
    '',
    '{"endpoint_url": "http://localhost:8012/api/v1/list-spcs", "method": "GET", "headers": {}}',
    '{"fields": []}'
  )
ON CONFLICT (name) DO NOTHING;
