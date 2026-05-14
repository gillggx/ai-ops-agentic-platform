-- V45 — 2026-05-14 (v18): domain-composite panel blocks.
--
-- Background:
--   2026-05-14 lastooc smoke ran 5x and 4/5 succeeded with the new
--   reject-and-ask + skill_terminal autofix, but inspecting trace shows
--   the final line_chart frequently had only **1 data point** because
--   the LLM composed `sort + limit=1` thinking "last OOC = 1 row".
--
--   Real semantic intent: "last OOC" = find the latest TIMESTAMP, then
--   show ALL SPCs at that timestamp (multi-series). User correctly
--   pointed out this is a domain-knowledge gap LLM can't reliably
--   infer from primitive block descriptions.
--
-- Fix: composite panel blocks that bake in the right semantics:
--   block_spc_panel — explode spc_charts → pick event window (latest_ooc /
--     latest_event / all / custom_time) → multi-series chart with UCL/LCL
--     bound rules + is_ooc highlight. One block instead of 4 primitives.
--   block_apc_panel — same shape for apc_params (no bounds, APC raw data
--     doesn't carry upper/lower limits).
--
-- LLM picks one of these when prompt mentions "SPC chart" / "APC 趨勢"
-- and skips the error-prone composition.

-- ── 1. block_spc_panel ─────────────────────────────────────────────────
DELETE FROM pb_blocks WHERE name = 'block_spc_panel';
INSERT INTO pb_blocks (
  name, category, version, status, description,
  input_schema, output_schema, param_schema,
  implementation, examples, output_columns_hint, is_custom
) VALUES (
  'block_spc_panel',
  'output',
  '1.0.0',
  'production',
  $$== What ==
**SPC chart panel — one block, right semantics.**
把 process_history 的 SPC 資料一次處理好：unnest spc_charts → 依 event_filter 模式挑時段 → 出多 series line chart + UCL/LCL bound + OOC highlight。

== When to use ==
- ✅ user 說「看 SPC chart」「SPC 趨勢」「OOC SPC chart」→ 用我
- ✅ user 說「機台最後一次 OOC 時的 SPC 狀況」→ 用我 + event_filter=latest_ooc
- ✅ user 說「過去 N 天 SPC 趨勢」→ 用我 + event_filter=all
- ✅ 取代繁瑣的 unnest+filter+sort+line_chart 4 步組合 — **這 4 步 LLM 常拼錯**
- ❌ user 要看「單一 SPC 的長期趨勢」(僅 r_chart) → 用 block_filter + block_line_chart 較彈性
- ❌ user 要計算 Cpk/EWMA 等統計 → 我只畫圖，不算統計
- ❌ APC 參數 → 用 block_apc_panel

== event_filter 模式 ==
  latest_ooc    (default) — 找最後一個有 OOC 的 process event，秀那時刻 **所有** SPCs
  latest_event  — 最後一個 process event（不論 OOC），秀全部 SPCs
  all           — 全部時間範圍，多 series trend mode
  custom_time   — 配 event_time 指定 ISO timestamp

== Params ==
event_filter         (string, default latest_ooc)
event_time           (string, opt) — event_filter=custom_time 時必填 ISO timestamp
show_only_violations (bool, default false) — true=只秀 is_ooc=true 的 charts
title                (string, opt) — chart 標題，預設 'SPC Charts'

== Input ==
port: data (dataframe) — process_history(nested=true) 的輸出，或已 unnest 的長表
**自動偵測**輸入 shape：有 spc_charts 欄就 explode；已長表就直接用

== Output ==
port: chart_spec (chart_spec) — 多 series line（trend mode）或 bar（single-event mode）
  自動帶 UCL/LCL bound rules + is_ooc highlight 紅圈
  meta 帶 {event_filter, n_rows, n_series} 給 admin trace 看

== 典型 pipelines ==
(A) 機台最後一次 OOC SPC chart：
    block_process_history(tool_id=$tool_id, nested=true)
      → block_spc_panel(event_filter=latest_ooc)
(B) 過去 7 天 SPC 趨勢：
    block_process_history(tool_id=$tool_id, time_range=7d, nested=true)
      → block_spc_panel(event_filter=all)
(C) OOC count >= 2 才觸發 + 同時展示 chart（skill_step_mode）：
    n1 process_history → fan-out:
      Branch 1 (verdict): n1 → block_unnest(spc_charts) → block_filter(is_ooc==true)
                          → block_groupby_agg(group_by=eventTime, agg_column=name, agg_func=count)
                          → block_step_check(operator='>=', threshold=2)
      Branch 2 (chart):   n1 → block_spc_panel(event_filter=latest_ooc)
    兩 branch 共用 n1，**不要**重做 process_history

== Common mistakes ==
⚠ 不要在我之前接 block_sort+limit=1 — 那會砍剩 1 row，我會接到只剩 1 個 SPC
⚠ event_filter=custom_time 但忘了給 event_time → 退回 all 模式 + 警告 note
⚠ 上游沒 spc_charts 欄又沒 SPC 長表 → empty chart + message

== Errors ==
- INVALID_INPUT: data 不是 DataFrame$$,
  $$[{"port": "data", "type": "dataframe", "required": true}]$$,
  $$[{"port": "chart_spec", "type": "chart_spec"}]$$,
  $${
    "type": "object",
    "properties": {
      "event_filter": {
        "type": "string",
        "enum": ["latest_ooc", "latest_event", "all", "custom_time"],
        "default": "latest_ooc",
        "title": "事件範圍"
      },
      "event_time": {"type": "string", "title": "指定 timestamp (ISO)"},
      "show_only_violations": {"type": "boolean", "default": false, "title": "只秀 OOC 的 charts"},
      "title": {"type": "string", "default": "SPC Charts", "title": "圖表標題"}
    }
  }$$,
  $${"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.spc_panel:SpcPanelBlockExecutor"}$$,
  $$[
    {"label": "機台最後一次 OOC 的所有 SPC charts",
     "params": {"event_filter": "latest_ooc", "title": "EQP-01 Last OOC Event"}},
    {"label": "過去 7 天 SPC 趨勢",
     "params": {"event_filter": "all"}},
    {"label": "指定時間點所有 SPC",
     "params": {"event_filter": "custom_time", "event_time": "2026-05-14T10:00:00"}}
  ]$$,
  NULL,
  false
);

-- ── 2. block_apc_panel ─────────────────────────────────────────────────
DELETE FROM pb_blocks WHERE name = 'block_apc_panel';
INSERT INTO pb_blocks (
  name, category, version, status, description,
  input_schema, output_schema, param_schema,
  implementation, examples, output_columns_hint, is_custom
) VALUES (
  'block_apc_panel',
  'output',
  '1.0.0',
  'production',
  $$== What ==
**APC parameter panel — one block, right semantics.**
把 process_history 的 APC 資料一次處理好：unnest apc_params → 依 event_filter 模式挑時段 → 出多 series line chart（無 bound，APC 原始資料沒帶上下界）。

== When to use ==
- ✅ user 說「看 APC 參數」「APC 趨勢」→ 用我
- ✅ user 說「最近 N 天 APC 各參數變化」→ 用我 + event_filter=all
- ✅ 取代 unnest+groupby+line_chart 組合
- ❌ SPC chart → 用 block_spc_panel
- ❌ APC drift 偵測（連 N 次超過 X）→ block_apc_long_form + block_threshold + block_consecutive_rule
- ❌ 比較單一 APC 參數的 box plot → block_apc_long_form + block_box_plot

== event_filter 模式 ==
  latest_drift  (default) — 找最後一個 drift event；上游沒提供 is_drift 欄則退回 latest_event
  latest_event  — 最後一個 process event
  all           — 全部時間範圍（trend）
  custom_time   — 配 event_time 指定 ISO timestamp

== Params ==
event_filter         (string, default latest_drift)
event_time           (string, opt) — custom_time 模式必填
show_only_violations (bool, default false) — true=只秀 is_drift=true
title                (string, opt) — 預設 'APC Parameters'

== Input ==
port: data (dataframe) — process_history(nested=true) 含 apc_params 陣列；或已 long-form 的 param_name/value 表

== Output ==
port: chart_spec — 多 series line（trend）或 bar（single-event），**無 UCL/LCL rules**（APC 原始資料沒帶）

== Common mistakes ==
⚠ 想要 drift 上下界 → 用 block_apc_long_form + block_threshold 算後再串其他 chart block
⚠ latest_drift 但上游沒 is_drift 欄 → 退 latest_event + note

== Errors ==
- INVALID_INPUT: data 不是 DataFrame$$,
  $$[{"port": "data", "type": "dataframe", "required": true}]$$,
  $$[{"port": "chart_spec", "type": "chart_spec"}]$$,
  $${
    "type": "object",
    "properties": {
      "event_filter": {
        "type": "string",
        "enum": ["latest_drift", "latest_event", "all", "custom_time"],
        "default": "latest_drift",
        "title": "事件範圍"
      },
      "event_time": {"type": "string", "title": "指定 timestamp (ISO)"},
      "show_only_violations": {"type": "boolean", "default": false, "title": "只秀 drift 的參數"},
      "title": {"type": "string", "default": "APC Parameters", "title": "圖表標題"}
    }
  }$$,
  $${"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.apc_panel:ApcPanelBlockExecutor"}$$,
  $$[
    {"label": "最近一次 drift 的 APC 參數",
     "params": {"event_filter": "latest_drift"}},
    {"label": "過去 24 小時 APC 趨勢",
     "params": {"event_filter": "all"}}
  ]$$,
  NULL,
  false
);
