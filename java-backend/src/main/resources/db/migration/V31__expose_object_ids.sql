-- V31 — Expose APC / RECIPE / FDC objectID through MCP + flatten them as
--       apc_id / recipe_id / fdc_id columns in process_history wide format
--
-- Background (2026-05-11):
--   User showed simulator TRACE view containing APC-009, RCP-001 instance
--   names. But /api/v1/process/info endpoint was actively stripping
--   `objectID` before returning, so MCP description's claim "APC?: {objectID,
--   mode, parameters: ...}" was a lie — agent never saw the instance ID.
--
--   Two fixes deployed simultaneously:
--   1. ontology_simulator: removed `objectID` from the strip list at
--      routes.py:556. Now APC.objectID="APC-009" / RECIPE.objectID="RCP-001"
--      reach the response payload.
--   2. block_process_history: flattens X.objectID → x_id column so
--      downstream blocks can groupby by APC/RECIPE/DC instance.
--
-- This migration syncs the seed.py description changes into pb_blocks +
-- updates the get_process_info MCP description to advertise the new fields.

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
    ⚠ 此模式下每根 bar 高度可能相近 — 因為每個 OOC event 都帶全部 ~20 個
    APC params。要看「哪個 APC 模型 instance 觸發 OOC」改用 (D)。

(D) APC OOC count by APC instance（看哪台 APC 模型最常觸發 OOC）:
    process_history(object_name='APC')
      → filter(column='spc_status', operator='==', value='OOC')
      → groupby_agg(group_by='apc_id', agg_column='lotID', agg_func='count')
      → bar_chart(x='apc_id', y='lotID_count', title='APC instance OOC 次數')
    這條**不需要 apc_long_form**（不需要展開 params），直接用 process_history
    的 apc_id 欄位即可。apc_id 是 user 在 TRACE view 看到的 APC-001/APC-009 等
    instance name。

== Errors ==
- INVALID_INPUT  : data 不是 DataFrame
- NO_APC_COLUMNS : 上游沒 apc_<param> 欄位
$BD$,
    updated_at = now()
WHERE name = 'block_apc_long_form';

-- ── 2. get_process_info MCP description: advertise new objectID fields ─
-- The existing description says "APC?: {objectID, mode, parameters: ...}"
-- which was previously aspirational. Now actually true. Append a section
-- explaining the canonical pattern for "OOC count by APC instance".
UPDATE mcp_definitions
SET description = description || E'\n\n== ✨ Object instance IDs（V31，2026-05-11）==\n'
  || E'每個 nested object 都會回 `objectID`，user 在 TRACE view 看到的就是這個：\n'
  || E'  - APC.objectID    e.g. "APC-009" — APC 模型 instance（總共 ~20 個 instance）\n'
  || E'  - RECIPE.objectID e.g. "RCP-001" — recipe instance\n'
  || E'  - DC.chamberID    e.g. "CH-2"     — chamber instance（DC 用 chamberID 不是 objectID）\n'
  || E'  - FDC.objectID    e.g. "FDC-001"  — FDC 模型 instance\n'
  || E'\n'
  || E'要做「OOC count by APC instance」這種跨 instance 統計，直接 filter\n'
  || E'spc_status=OOC 後 groupby APC.objectID 即可，不需展開 parameters。\n',
    updated_at = now()
WHERE name = 'get_process_info'
  AND description NOT LIKE '%Object instance IDs（V31%';
