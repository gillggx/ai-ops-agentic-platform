-- V30 — APC OOC count semantics: it's spc_status, not is_ooc
--
-- Background (2026-05-11):
--   User: 「為什麼我在MCP 查詢後看不到APC name? 每次process 的OOC 是看
--    spc_status, 所以只要把APC, SPC 同時都查詢出來，依據spc_status 是OOC 的
--    去統計APC 的OOC count 就可以得解」
--
--   Two missteps the agent kept making:
--   1. Tried to derive APC OOC from `value != null` (APC has no is_ooc;
--      spc_status is the process-level OOC marker shared by APC + SPC).
--   2. _TRANSFORM_OUT_RULES["block_apc_long_form"] in plan.py had wrong
--      schema (said "parameter", omitted spc_status) → LLM didn't see
--      spc_status was available downstream and synthesised wrong logic.
--
-- This migration syncs the corrected description into pb_blocks so the
-- BlockDocsDrawer + Java catalog readers + agent prompt all align with
-- the seed.py canonical text. plan.py change to _TRANSFORM_OUT_RULES is
-- a code-only deploy.
--
-- Also strengthen get_process_info MCP description so chat agent (which
-- reads MCP descriptions) understands spc_status semantics before deciding
-- which long-form block to use.

-- ── 1. block_apc_long_form description sync ───────────────────────────
UPDATE pb_blocks
SET description = $BD$== What ==
Process-History wide → APC long format reshape (purpose-built).
把 process_history 直出的 apc_<param> 欄位攤平成長表，downstream 用
group_by=param_name 一次處理所有 APC 參數。

== When to use ==
- ✅ 「任一 APC 參數連 N 次超過 X」→ apc_long_form → threshold → consecutive_rule
- ✅ 「對每個 APC 參數做 boxplot / histogram」→ groupby param_name
- ✅ 「APC OOC count by parameter」→ filter spc_status=OOC → groupby_agg(group_by=param_name, count)
- ❌ 只看 1 個指定參數 → 直接用該欄位即可
- ❌ SPC chart → 用 block_spc_long_form

== Output columns（固定）==
Passthrough (從 process_history 直接帶下來):
  eventTime, toolID, lotID, step, spc_status, fdc_classification, apc_id
Reshape 結果:
  param_name (string, 已剝 apc_ 前綴), value (該 param 的測量值)
⚠ 欄位**固定叫 param_name**，不是 parameter / metric / apc_param。

== ⚠ 重要：APC 沒有 is_ooc 欄位 ==
APC long_form 的 `value` 是 raw measurement，**不是** OOC 標記。
OOC 是 process 級的概念，看 `spc_status` 欄位（'OOC' / 'PASS'）— 這欄位
由 process_history 決定該 process 整體是否 OOC，APC + SPC 都共用。

❌ 錯誤示範：用 `value != null` 當 OOC marker → 那只是 measurement 計數
✅ 正確：filter `spc_status == 'OOC'` 取出 OOC 過的 process，再 groupby param_name

== 經典 pipeline ==
(A) APC threshold-based 連續觸發告警:
    process_history(step=$step) → apc_long_form
      → threshold(value_column=value, op='>', threshold=100)
      → consecutive_rule(flag_column=triggered_row, count=3,
                         sort_by=eventTime, group_by=param_name)
      → alert(severity=HIGH)

(B) APC OOC count by parameter（看哪個 APC 參數常出問題）:
    process_history(...) → apc_long_form
      → filter(column='spc_status', operator='==', value='OOC')
      → groupby_agg(group_by='param_name', agg_column='value', agg_func='count')
      → bar_chart(x='param_name', y='value_count')
    要看跨機台分佈：process_history 別 filter $tool_id（撈全廠），
    要看單機分佈：process_history 用 tool_id=$tool_id。

== Errors ==
- INVALID_INPUT  : data 不是 DataFrame
- NO_APC_COLUMNS : 上游沒 apc_<param> 欄位
$BD$,
    updated_at = now()
WHERE name = 'block_apc_long_form';

-- ── 2. get_process_info MCP description: spell out spc_status semantics ─
-- Existing tail line says:「spc_status 值是 'PASS'|'OOC'。」 We append a
-- dedicated section explaining it's the *process-level* OOC marker shared
-- by APC + SPC, so chat agent doesn't try to find OOC info inside APC.* sub-objects.
UPDATE mcp_definitions
SET description = description || E'\n\n== ⚠ OOC 判定一律看 spc_status ==\n'
  || E'`spc_status` 是 process 級的 OOC 標記，APC / SPC / FDC 都共用同一欄位：\n'
  || E'  - PASS = 該 process 整體合格\n'
  || E'  - OOC  = 該 process 任一指標超出管制 → 整筆 process 算 OOC\n'
  || E'\n'
  || E'**APC 沒有獨立的 is_ooc 欄位**（不像 SPC charts.is_ooc）。\n'
  || E'要算「APC OOC count by parameter」就是 filter spc_status=OOC → groupby APC param。\n'
  || E'要算「SPC OOC by chart」用 SPC.charts.<chart>.is_ooc 細分到 chart 層級。\n'
  || E'\n'
  || E'⚠ 不要把 APC.parameters 的 value 拿來當 OOC marker — 那是 raw measurement。\n',
    updated_at = now()
WHERE name = 'get_process_info'
  AND description NOT LIKE '%OOC 判定一律看 spc_status%';
