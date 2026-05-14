-- V46 — 2026-05-14 (v18): panel blocks gain source-mode + colors + chart_name filter.
--
-- Background:
--   User requested block_spc_panel be self-contained: pass tool_id + step
--   + chart_name + time_range and get back the single SPC chart's trend.
--   Previous version required an upstream block_process_history (2 nodes).
--
--   Plus: orange UCL/LCL line color, green value line, and color_by
--   support to color series by toolID / lotID / fdc_classification.
--
-- This migration updates the description + param_schema + examples for
-- both block_spc_panel and block_apc_panel. The executor code already
-- supports these params (see _param_panel_base.py); this is the catalog
-- side so LLM and Block Advisor see the new capabilities.

UPDATE pb_blocks
SET description = $$== What ==
**SPC chart panel — 自給自足的 SPC chart 元件。**
🌟 **v18 升級**：給 `tool_id + step + chart_name` 我就自己撈資料畫圖，**完全不用上游**。
把 process_history 的 SPC 資料一次處理好：unnest spc_charts → (opt) filter chart_name → 依 event_filter 模式挑時段 → 出 line/bar chart + 橘色 UCL/LCL + 綠色 value line + OOC highlight。

🚨🚨🚨 **最佳用法 — 1 個 node 全包**:
  `block_spc_panel(tool_id='EQP-01', step='STEP_001', chart_name='xbar_chart', time_range='7d')`
🚨 不需要上游 process_history、不需要 unnest、不需要 filter — 我內建。
🚨 如果你已有 process_history 在 upstream，也可以接過來 — 我兩種 mode 都支援。
🚨 **不要**在我之前接 unnest / filter(is_ooc) / sort+limit / groupby — 那會把多 SPC 砍成 1 點。

== When to use ==
- ✅ user 說「看 SPC chart」「SPC 趨勢」「xbar_chart 過去 N 天」→ 用我
- ✅ user 說「機台最後一次 OOC 時的 SPC 狀況」→ 用我 + event_filter=latest_ooc
- ✅ 多機台對照 → 用我 + color_by='toolID'
- ✅ 多 lot 對照 → 用我 + color_by='lotID'
- ❌ 計算 Cpk/EWMA 等統計 → 我只畫圖，不算統計
- ❌ APC 參數 → 用 block_apc_panel

== event_filter 模式 ==
  latest_ooc    (default) — 找最後一個有 OOC 的 process event，秀那時刻所有 SPCs
  latest_event  — 最後一個 process event（不論 OOC），秀全部 SPCs
  all           — 全部時間範圍，多 series trend mode
  custom_time   — 配 event_time 指定 ISO timestamp

== Params ==
── source mode (不接上游時) ──
tool_id              (string, opt) — 機台 ID e.g. 'EQP-01'。給了我就自己撈
lot_id               (string, opt)
step                 (string, opt) — process step e.g. 'STEP_001'
time_range           (string, default '7d') — 撈多久
limit                (int, default 200) — 撈幾筆

── 篩選 ──
chart_name           (string, opt) — 只看單一 SPC，例 'xbar_chart' / 'r_chart'
event_filter         (string, default latest_ooc)
event_time           (string, opt) — event_filter=custom_time 時必填 ISO timestamp
show_only_violations (bool, default false) — true=只秀 is_ooc=true 的 charts

── 視覺化 ──
color_by             (string, opt) — 例 'toolID' / 'lotID' / 'fdc_classification'
                     — 多 series 依該欄分顏色（會 override chart_name 預設的分色）
value_color          (string, default '#16a34a' green) — value 線顏色
bound_color          (string, default '#f59e0b' orange) — UCL/LCL 線顏色
title                (string, opt) — 預設 'SPC Charts'

== Input / Output ==
port: data (dataframe, optional in source mode) — process_history nested 或長表
port: chart_spec (chart_spec) — line/bar chart with rules + highlight

== 典型 pipelines ==
(A) **1-block 看單一 SPC 趨勢（最常用！）**：
    block_spc_panel(tool_id='EQP-01', step='STEP_001', chart_name='xbar_chart', time_range='7d', event_filter='all')

(B) 1-block 看機台最後一次 OOC 那一刻全部 SPCs：
    block_spc_panel(tool_id='EQP-01', event_filter='latest_ooc')

(C) 多機台對照同一 SPC：
    block_spc_panel(step='STEP_001', chart_name='xbar_chart', time_range='7d', color_by='toolID')

(D) Lot 對照：
    block_spc_panel(tool_id='EQP-01', chart_name='xbar_chart', time_range='7d', color_by='lotID')

(E) Verdict + chart 雙終點：
    n1 process_history → fan-out:
      Branch 1: n1 → unnest → filter(is_ooc) → groupby → step_check
      Branch 2: n1 → spc_panel(event_filter='latest_ooc')

== Errors ==
- INVALID_INPUT: 沒上游 data 又沒 tool_id source 參數$$,
    param_schema = $${
      "type": "object",
      "properties": {
        "tool_id": {"type": "string", "title": "機台 ID (source mode)"},
        "lot_id": {"type": "string", "title": "批次 ID (source mode)"},
        "step": {"type": "string", "title": "Process step (source mode)"},
        "time_range": {"type": "string", "default": "7d", "title": "撈多久 (source mode)"},
        "limit": {"type": "integer", "default": 200, "title": "撈幾筆 (source mode)"},
        "chart_name": {"type": "string", "title": "SPC chart 名稱 (filter)"},
        "event_filter": {
          "type": "string",
          "enum": ["latest_ooc", "latest_event", "all", "custom_time"],
          "default": "latest_ooc",
          "title": "事件範圍"
        },
        "event_time": {"type": "string", "title": "指定 timestamp (ISO)"},
        "show_only_violations": {"type": "boolean", "default": false, "title": "只秀 OOC 的 charts"},
        "color_by": {"type": "string", "title": "依此欄分色 (e.g. toolID / lotID)"},
        "value_color": {"type": "string", "default": "#16a34a", "title": "Value 線顏色"},
        "bound_color": {"type": "string", "default": "#f59e0b", "title": "UCL/LCL 線顏色"},
        "title": {"type": "string", "default": "SPC Charts", "title": "圖表標題"}
      }
    }$$,
    examples = $$[
      {"label": "1-block 看 EQP-01 STEP_001 xbar 過去 7 天",
       "params": {"tool_id": "EQP-01", "step": "STEP_001", "chart_name": "xbar_chart",
                  "time_range": "7d", "event_filter": "all"}},
      {"label": "機台最後一次 OOC 的所有 SPC charts",
       "params": {"tool_id": "EQP-01", "event_filter": "latest_ooc"}},
      {"label": "多機台對照 xbar trend (依 toolID 分色)",
       "params": {"step": "STEP_001", "chart_name": "xbar_chart",
                  "time_range": "7d", "color_by": "toolID", "event_filter": "all"}}
    ]$$,
    updated_at = now()
WHERE name = 'block_spc_panel';

UPDATE pb_blocks
SET description = $$== What ==
**APC parameter panel — 自給自足的 APC 元件。**
🌟 **v18 升級**：給 `tool_id + step + chart_name` 我就自己撈 APC 資料畫圖，**不用上游**。
把 process_history 的 APC 資料一次處理好：unnest apc_params → (opt) filter param_name → 依 event_filter 模式挑時段 → 出多 series line chart（無 bound，APC 原始資料沒帶上下界）。

🚨 1-block 用法：`block_apc_panel(tool_id='EQP-01', step='STEP_001', chart_name='temperature', time_range='7d')`
   （chart_name 就是 APC 參數名，e.g. 'temperature' / 'pressure' / 'flow_rate'）

== When to use ==
- ✅ user 說「看 APC 參數」「APC 趨勢」「APC temperature 過去 N 天」→ 用我
- ✅ user 說「最近 N 天 APC 各參數變化」→ 用我 + event_filter=all
- ❌ SPC chart → 用 block_spc_panel
- ❌ APC drift 偵測（連 N 次超過 X）→ block_apc_long_form + block_threshold + block_consecutive_rule

== event_filter 模式 ==
  latest_drift  (default)
  latest_event
  all
  custom_time

== Params ==
── source mode ──
tool_id, lot_id, step, time_range (default '7d'), limit (default 200)

── 篩選 ──
chart_name           (string, opt) — APC 參數名 e.g. 'temperature'
event_filter         (string, default latest_drift)
event_time, show_only_violations

── 視覺化 ──
color_by             (string, opt) — e.g. 'toolID'
value_color          (string, default '#16a34a' green)
bound_color          (string, default '#f59e0b' orange)
title                (string, opt)

== Errors ==
- INVALID_INPUT: 沒上游 data 又沒 tool_id$$,
    param_schema = $${
      "type": "object",
      "properties": {
        "tool_id": {"type": "string", "title": "機台 ID (source mode)"},
        "lot_id": {"type": "string", "title": "批次 ID (source mode)"},
        "step": {"type": "string", "title": "Process step (source mode)"},
        "time_range": {"type": "string", "default": "7d", "title": "撈多久"},
        "limit": {"type": "integer", "default": 200, "title": "撈幾筆"},
        "chart_name": {"type": "string", "title": "APC 參數名 (filter)"},
        "event_filter": {
          "type": "string",
          "enum": ["latest_drift", "latest_event", "all", "custom_time"],
          "default": "latest_drift",
          "title": "事件範圍"
        },
        "event_time": {"type": "string", "title": "指定 timestamp (ISO)"},
        "show_only_violations": {"type": "boolean", "default": false, "title": "只秀 drift 的參數"},
        "color_by": {"type": "string", "title": "依此欄分色"},
        "value_color": {"type": "string", "default": "#16a34a", "title": "Value 線顏色"},
        "bound_color": {"type": "string", "default": "#f59e0b", "title": "Bound 線顏色"},
        "title": {"type": "string", "default": "APC Parameters", "title": "圖表標題"}
      }
    }$$,
    examples = $$[
      {"label": "1-block 看 EQP-01 STEP_001 temperature 過去 7 天",
       "params": {"tool_id": "EQP-01", "step": "STEP_001", "chart_name": "temperature",
                  "time_range": "7d", "event_filter": "all"}},
      {"label": "最近一次 drift 的 APC 參數",
       "params": {"tool_id": "EQP-01", "event_filter": "latest_drift"}},
      {"label": "過去 24 小時 APC 趨勢",
       "params": {"tool_id": "EQP-01", "event_filter": "all"}}
    ]$$,
    updated_at = now()
WHERE name = 'block_apc_panel';
