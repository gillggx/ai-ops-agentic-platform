"""Seed block examples — concrete {name, summary, params, upstream_hint} per block.

Surfaced in BlockDocsDrawer (frontend) + injected into Agent system prompt
(backend). Keep `summary` short (< 80 chars) and `params` realistic.
"""

from __future__ import annotations

from typing import Any


def examples_by_name() -> dict[str, list[dict[str, Any]]]:
    """Return {block_name: [examples]} for the 23 standard blocks."""
    return {
        # ── Sources (2) ───────────────────────────────────────────────────
        "block_process_history": [
            {
                "name": "EQP-01 SPC 24h（點名單一機台）",
                "summary": "抓一台機台 24 小時的 SPC 寬表（含 xbar/R/S/P/C 所有 chart）",
                "params": {"tool_id": "EQP-01", "object_name": "SPC", "time_range": "24h", "limit": 100},
            },
            {
                "name": "所有機台 SPC 24h（宣告 $tool_id input）",
                "summary": (
                    "使用者說『所有機台』時：pipeline 宣告 input $tool_id，本 block tool_id 綁 $tool_id，"
                    "搭配 Auto-Patrol target_scope=all_equipment 做 runtime fan-out。"
                    "❌ 不要枚舉 EQP-01,EQP-02,...（新機台不會被包含）"
                ),
                "params": {"tool_id": "$tool_id", "object_name": "SPC", "time_range": "24h", "limit": 100},
                "upstream_hint": (
                    "Pipeline 必須先 declare_input {name: 'tool_id', type: 'string', required: true}；"
                    "Auto-Patrol 綁 target_scope={type:'all_equipment'}，runtime 為每台機台 fan-out 一次"
                ),
            },
            {
                "name": "單一 STEP 一週資料",
                "summary": "看某 step 最近 7 天全維度（不帶 object_name 則 flatten 所有）",
                "params": {"step": "STEP_002", "time_range": "7d", "limit": 200},
            },
            {
                "name": "批號精確追蹤",
                "summary": "依 lot_id 查 events（送料批追蹤 root cause）",
                "params": {"lot_id": "LOT-00123", "time_range": "24h"},
            },
            {
                "name": "所有機台最近 10 次 process 超過 3 次 OOC（端到端 Auto-Patrol 範本）",
                "summary": (
                    "典型 Auto-Patrol 使用情境。Pipeline 宣告 $tool_id input，block 鏈："
                    "process_history($tool_id) → filter(OOC) → count_rows → threshold(>=3) → alert。"
                    "Auto-Patrol 綁 schedule（每小時）+ target_scope=all_equipment 做 fan-out。"
                ),
                "params": {"tool_id": "$tool_id", "time_range": "7d", "limit": 10},
                "upstream_hint": (
                    "這是『所有機台』範圍語意的正確示範：tool_id 綁 $tool_id（不枚舉），"
                    "由 Auto-Patrol 的 target_scope 在 runtime 為每台機台跑一次"
                ),
            },
        ],
        "block_mcp_call": [
            {
                "name": "查告警清單",
                "summary": "呼叫 get_alarm_list，過濾 HIGH severity（list_tools 等請改用 block_list_objects）",
                "params": {"mcp_name": "get_alarm_list", "args": {"severity": "HIGH", "limit": 50}},
            },
            {
                "name": "OOC 摘要",
                "summary": "呼叫 get_process_summary 拿 24h aggregate",
                "params": {"mcp_name": "get_process_summary", "args": {"since": "24h"}},
            },
        ],
        "block_list_objects": [
            {
                "name": "列機台清單",
                "summary": "kind=tool → list_tools；回傳所有機台 + status / busy_lot",
                "params": {"kind": "tool", "args": {}},
            },
            {
                "name": "列 active 批次",
                "summary": "kind=lot → list_active_lots；回傳 active lot + current_step / cycle",
                "params": {"kind": "lot", "args": {}},
            },
            {
                "name": "列 process flow 站點",
                "summary": "kind=step → list_steps；回傳所有 STEP_xxx 清單",
                "params": {"kind": "step", "args": {}},
            },
            {
                "name": "列 APC 參數 master",
                "summary": "kind=apc → list_apcs；回傳 APC 參數定義（id / step / param 名）",
                "params": {"kind": "apc", "args": {}},
            },
            {
                "name": "列 SPC chart 類型",
                "summary": "kind=spc → list_spcs；回傳 SPC chart 類型 master（xbar/r/s/p/c）",
                "params": {"kind": "spc", "args": {}},
            },
        ],

        # ── Transforms (11) ───────────────────────────────────────────────
        "block_filter": [
            {
                "name": "只保留 OOC events",
                "summary": "SPC 異常偵測的首步：filter spc_status == 'OOC'",
                "params": {"column": "spc_status", "operator": "==", "value": "OOC"},
                "upstream_hint": "feed from block_process_history",
            },
            {
                "name": "特定 step",
                "summary": "把寬表限縮到 STEP_002",
                "params": {"column": "step", "operator": "==", "value": "STEP_002"},
            },
            {
                "name": "多機台 (in)",
                "summary": "只留 EQP-01 / EQP-02",
                "params": {"column": "toolID", "operator": "in", "value": ["EQP-01", "EQP-02"]},
            },
        ],
        "block_join": [
            {
                "name": "SPC × APC by eventTime",
                "summary": "兩張寬表 by eventTime 合併做相關分析",
                "params": {"key": "eventTime", "how": "inner"},
            },
        ],
        "block_groupby_agg": [
            {
                "name": "各機台 OOC 次數",
                "summary": "groupby toolID, count",
                "params": {"group_by": "toolID", "agg_column": "spc_status", "agg_func": "count"},
            },
            {
                "name": "各 step xbar 平均",
                "summary": "groupby step, mean(xbar)",
                "params": {"group_by": "step", "agg_column": "spc_xbar_chart_value", "agg_func": "mean"},
            },
        ],
        "block_shift_lag": [
            {
                "name": "相鄰批 APC drift",
                "summary": "計算 apc_rf_power_bias 相鄰批差異（offset=1）",
                "params": {"column": "apc_rf_power_bias", "offset": 1, "compute_delta": True, "sort_by": "eventTime"},
            },
        ],
        "block_rolling_window": [
            {
                "name": "xbar 5-pt 移動平均",
                "summary": "近 5 筆 xbar SMA，平滑短期波動",
                "params": {"column": "spc_xbar_chart_value", "window": 5, "func": "mean", "sort_by": "eventTime"},
            },
            {
                "name": "近 5 筆 OOC 數 (rolling count)",
                "summary": "5 點 2 OOC 規則預備：rolling sum of is_ooc bool 轉 int",
                "params": {"column": "spc_xbar_chart_is_ooc", "window": 5, "func": "sum", "sort_by": "eventTime"},
            },
        ],
        "block_delta": [
            {
                "name": "xbar 上升趨勢旗標",
                "summary": "算 delta + is_rising / is_falling，供 consecutive_rule 判連續 N 點上升",
                "params": {"value_column": "spc_xbar_chart_value", "sort_by": "eventTime"},
            },
        ],
        "block_sort": [
            {
                "name": "OOC 次數 top-3 機台",
                "summary": "依 count 遞減排序取前 3",
                "params": {"columns": [{"column": "count", "order": "desc"}], "limit": 3},
                "upstream_hint": "feed from block_groupby_agg",
            },
        ],
        "block_histogram": [
            {
                "name": "xbar 分布 20 bin",
                "summary": "標準 normal-test 直方圖；等寬 20 bins",
                "params": {"value_column": "spc_xbar_chart_value", "bins": 20},
            },
        ],
        "block_unpivot": [
            {
                "name": "SPC 寬表 → long (多 chart_type)",
                "summary": "wide → long；下游 group_by=chart_type 一次做 5 種分析",
                "params": {
                    "id_columns": ["eventTime", "toolID", "step"],
                    "value_columns": [
                        "spc_xbar_chart_value", "spc_r_chart_value",
                        "spc_s_chart_value", "spc_p_chart_value", "spc_c_chart_value",
                    ],
                    "variable_name": "chart_type",
                    "value_name": "spc_value",
                },
            },
        ],
        "block_union": [
            {
                "name": "兩機台合併 overlay 比較",
                "summary": "EQP-01 + EQP-02 縱向合併後 color=toolID 畫在同張圖",
                "params": {"on_schema_mismatch": "outer"},
            },
        ],
        "block_ewma": [
            {
                "name": "xbar EWMA 平滑 α=0.2",
                "summary": "近期權重大；α 愈大愈響應新資料",
                "params": {"value_column": "spc_xbar_chart_value", "alpha": 0.2, "sort_by": "eventTime"},
            },
        ],

        # ── Logic (8) ─────────────────────────────────────────────────────
        "block_threshold": [
            {
                "name": "xbar 超 UCL 檢查",
                "summary": "Mode A：UCL/LCL bound 判定（傳統 SPC）",
                "params": {"column": "spc_xbar_chart_value", "bound_type": "upper", "upper_bound": 150.0},
            },
            {
                "name": "Same-recipe 檢查 (row count == 1)",
                "summary": "Mode B：搭配 count_rows 做「只有 1 個 unique recipe」判定",
                "params": {"column": "count", "operator": "==", "target": 1},
                "upstream_hint": "feed from block_count_rows",
            },
        ],
        "block_count_rows": [
            {
                "name": "上游 DF 整體 row 數",
                "summary": "輸出 1-row DF 只含 count；通常接 block_threshold 做 row count 判定",
                "params": {},
            },
            {
                "name": "Per-group row 數",
                "summary": "分組後算每組有幾 row（e.g. unique recipe 數）",
                "params": {"group_by": "recipeID"},
            },
        ],
        "block_mcp_foreach": [
            {
                "name": "每 row 取 APC context",
                "summary": "process_history 每筆 → get_process_context → 合成 apc_ 前綴欄位",
                "params": {
                    "mcp_name": "get_process_context",
                    "args_template": {"targetID": "$lotID", "step": "$step"},
                    "result_prefix": "apc_",
                    "max_concurrency": 5,
                },
            },
        ],
        "block_consecutive_rule": [
            {
                "name": "連續 3 次 OOC (tail-based)",
                "summary": "最後 3 筆都 OOC 才觸發；按機台分組",
                "params": {
                    "flag_column": "spc_xbar_chart_is_ooc",
                    "count": 3,
                    "sort_by": "eventTime",
                    "group_by": "toolID",
                },
            },
            {
                "name": "連續 3 點上升",
                "summary": "搭配 block_delta 的 is_rising 欄位",
                "params": {"flag_column": "spc_xbar_chart_value_is_rising", "count": 3, "sort_by": "eventTime"},
                "upstream_hint": "feed from block_delta",
            },
        ],
        "block_weco_rules": [
            {
                "name": "Nelson 全 8 條",
                "summary": "R1..R8 同時掃，evidence 含 rule 欄位",
                "params": {
                    "value_column": "spc_xbar_chart_value",
                    "ucl_column": "spc_xbar_chart_ucl",
                    "sigma_source": "from_ucl_lcl",
                    "rules": ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"],
                    "sort_by": "eventTime",
                },
            },
            {
                "name": "預警 (R1 + R5)",
                "summary": "R1 即時 OOC + R5 早期趨勢；最常見組合",
                "params": {
                    "value_column": "spc_xbar_chart_value",
                    "ucl_column": "spc_xbar_chart_ucl",
                    "sigma_source": "from_ucl_lcl",
                    "rules": ["R1", "R5"],
                    "sort_by": "eventTime",
                },
            },
        ],
        "block_any_trigger": [
            {
                "name": "多 chart 聚合告警",
                "summary": "OR 5 個 WECO trigger；evidence 含 source_port 欄位做歸因",
                "params": {},
            },
        ],
        "block_linear_regression": [
            {
                "name": "SPC vs APC R² (含 CI)",
                "summary": "跑完有 stats / data(預測+殘差) / ci(95%) 三 port",
                "params": {"x_column": "apc_rf_power_bias", "y_column": "spc_xbar_chart_value", "confidence": 0.95},
            },
        ],
        "block_cpk": [
            {
                "name": "xbar Cpk (USL/LSL)",
                "summary": "雙邊規格；輸出 Cp/Cpu/Cpl/Cpk",
                "params": {"value_column": "spc_xbar_chart_value", "usl": 115.0, "lsl": 85.0},
            },
            {
                "name": "per-step Cpk",
                "summary": "每 step 獨立算 Cpk，用於站點能力比較",
                "params": {"value_column": "spc_xbar_chart_value", "usl": 115.0, "lsl": 85.0, "group_by": "step"},
            },
        ],
        "block_correlation": [
            {
                "name": "多 APC 相關矩陣",
                "summary": "輸出 long-format，直接餵 chart(heatmap)",
                "params": {
                    "columns": ["apc_rf_power_bias", "apc_gas_flow_comp", "apc_uniformity_pct"],
                    "method": "pearson",
                },
            },
        ],
        "block_hypothesis_test": [
            {
                "name": "兩機台 xbar 差異 (t-test)",
                "summary": "Welch t-test；p<alpha 視為顯著",
                "params": {"test_type": "t_test", "value_column": "spc_xbar_chart_value", "group_column": "toolID"},
            },
            {
                "name": "多 step xbar 差異 (ANOVA)",
                "summary": "3+ 組均值比較",
                "params": {"test_type": "anova", "value_column": "spc_xbar_chart_value", "group_column": "step"},
            },
            {
                "name": "OOC 是否與機台有關 (chi-square)",
                "summary": "類別獨立性檢定",
                "params": {"test_type": "chi_square", "group_column": "toolID", "target_column": "spc_status"},
            },
        ],

        # ── Outputs (2) ───────────────────────────────────────────────────
        "block_chart": [
            {
                "name": "SPC 標準 xbar 控制圖",
                "summary": "value line + UCL/LCL 紅虛線 + OOC 紅圈（Plotly）",
                "params": {
                    "chart_type": "line",
                    "x": "eventTime",
                    "y": "spc_xbar_chart_value",
                    "ucl_column": "spc_xbar_chart_ucl",
                    "lcl_column": "spc_xbar_chart_lcl",
                    "highlight_column": "spc_xbar_chart_is_ooc",
                    "title": "SPC xbar Chart",
                    "sequence": 1,
                },
            },
            {
                "name": "雙 Y 軸 (SPC + APC)",
                "summary": "左軸 SPC xbar、右軸 APC rf_power_bias",
                "params": {
                    "chart_type": "line",
                    "x": "eventTime",
                    "y": "spc_xbar_chart_value",
                    "y_secondary": ["apc_rf_power_bias"],
                    "title": "SPC vs APC Overlay",
                },
            },
            {
                "name": "Boxplot 分組比較",
                "summary": "各機台 xbar 分布箱型圖",
                "params": {"chart_type": "boxplot", "y": "spc_xbar_chart_value", "group_by": "toolID"},
            },
            {
                "name": "Heatmap 相關矩陣",
                "summary": "搭配 block_correlation long-format 輸出",
                "params": {"chart_type": "heatmap", "x": "col_a", "y": "col_b", "value_column": "correlation"},
                "upstream_hint": "feed from block_correlation",
            },
            {
                "name": "常態分布 + 1~4σ 標記 (TC20 解法)",
                "summary": "直接給 raw 數值欄；自動算 histogram + 擬合 normal 曲線 + μ/±σ 線 + USL/LSL",
                "params": {
                    "chart_type": "distribution",
                    "value_column": "spc_xbar_chart_value",
                    "bins": 30,
                    "show_sigma_lines": [1, 2, 3, 4],
                    "title": "xbar 常態分佈",
                },
            },
            {
                "name": "SPC 控制圖 + A/B/C zones (±1σ/±2σ)",
                "summary": "除 UCL/LCL 還加畫 ±1σ / ±2σ 細線，Nelson zone rules 視覺化",
                "params": {
                    "chart_type": "line",
                    "x": "eventTime",
                    "y": "spc_xbar_chart_value",
                    "ucl_column": "spc_xbar_chart_ucl",
                    "lcl_column": "spc_xbar_chart_lcl",
                    "highlight_column": "spc_xbar_chart_is_ooc",
                    "sigma_zones": [1, 2],
                    "title": "xbar 控制圖（含 A/B/C zones）",
                },
            },
            {
                "name": "Table — 最近 N 筆 process 原始資料 (分支顯示)",
                "summary": "chart.data 接自 MCP source（非 logic.evidence），顯示所有筆數而非僅觸發點",
                "params": {
                    "chart_type": "table",
                    "columns": ["eventTime", "toolID", "lotID", "step", "spc_status"],
                    "title": "最近 5 筆 Process",
                },
                "upstream_hint": "連接自 block_process_history 的 data port — 與 consecutive_rule→alert 是並行分支",
            },
            {
                "name": "Table — 僅顯示觸發的違規筆數 (串接 evidence)",
                "summary": "chart.data 接自 logic_node.evidence，僅呈現觸發該規則的那幾列",
                "params": {
                    "chart_type": "table",
                    "columns": ["eventTime", "toolID", "spc_xbar_chart_value", "spc_status"],
                    "title": "OOC 違規記錄",
                },
                "upstream_hint": "連接自 block_consecutive_rule 的 evidence port；只有觸發的 rows 會進來",
            },
        ],
        "block_alert": [
            {
                "name": "HIGH 級 OOC 告警",
                "summary": "上游 logic node triggered=true 時發一封；不負責呈現 evidence",
                "params": {
                    "severity": "HIGH",
                    "title_template": "EQP-{toolID} 連續 {evidence_count} 筆 OOC",
                    "message_template": "最後事件時間：{eventTime}，值 {spc_xbar_chart_value}",
                },
            },
        ],
        "block_data_view": [
            {
                "name": "最近 N 筆 Process 原始資料",
                "summary": "從 Sort/Source 拉邊進來；Pipeline Results 會顯示這份表格供人查閱",
                "params": {
                    "title": "最近 5 筆 Process",
                    "columns": ["eventTime", "toolID", "lotID", "step", "spc_status"],
                    "sequence": 1,
                },
                "upstream_hint": "拉自 block_sort.data 或 block_process_history.data — 不影響 alert 分支",
            },
            {
                "name": "Triggered rows only（搭 filter(triggered_row) 使用）",
                "summary": "上游先 block_filter(triggered_row==true)，只秀違規列",
                "params": {
                    "title": "OOC 違規筆數",
                    "sequence": 2,
                },
                "upstream_hint": "Logic 的 evidence → Filter(triggered_row=True) → 本節點",
            },
        ],
        # ── PR-G — 6 chart blocks (Stage 2 part 1/3) ─────────────────
        "block_line_chart": [
            {
                "name": "SPC X̄ trend with UCL/LCL",
                "summary": "Time-series xbar chart with control limits + OOC red ring overlay",
                "params": {
                    "x": "eventTime",
                    "y": "spc_xbar_chart_value",
                    "rules": [
                        {"value": 17.5, "label": "UCL", "style": "danger"},
                        {"value": 16.31, "label": "CL", "style": "center"},
                        {"value": 12.5, "label": "LCL", "style": "danger"},
                    ],
                    "highlight_field": "spc_xbar_chart_is_ooc",
                    "title": "EQP-01 SPC X̄ trend",
                },
                "upstream_hint": "block_process_history → 此處（保留 spc_xbar_chart_is_ooc bool 欄位）",
            },
            {
                "name": "Multi-tool overlay",
                "summary": "Group rows by tool → one colored line per tool",
                "params": {
                    "x": "eventTime",
                    "y": "value",
                    "series_field": "toolID",
                    "title": "Tool 對比 trend",
                },
                "upstream_hint": "資料含多個 toolID，series_field 自動拆分成多色 trace",
            },
        ],
        "block_bar_chart": [
            {
                "name": "OOC count per equipment",
                "summary": "每個 EQP 過去 24h 的 OOC 次數",
                "params": {
                    "x": "equipment_id",
                    "y": "ooc_count",
                    "rules": [{"value": 10, "label": "alert threshold", "style": "warning"}],
                    "title": "Equipment OOC count (24h)",
                },
                "upstream_hint": "block_groupby_agg(group_by=equipment_id, agg={ooc_count: sum})",
            },
        ],
        "block_scatter_chart": [
            {
                "name": "RF Power vs Thickness correlation",
                "summary": "兩個 FDC 變數散點，看是否有相關性",
                "params": {
                    "x": "rf_power",
                    "y": "thickness",
                    "series_field": "tool_id",
                    "title": "RF vs Thickness",
                },
                "upstream_hint": "block_filter(spc_status='PASS') → 此處看 in-control 樣本的相關",
            },
        ],
        "block_box_plot": [
            {
                "name": "Tool > Chamber thickness 分散",
                "summary": "嵌套分組 box plot — 每個 tool 內部 chamber 的差異",
                "params": {
                    "x": "chamber",
                    "y": "thickness",
                    "group_by_secondary": "tool",
                    "show_outliers": True,
                    "y_label": "Thickness (Å)",
                    "title": "Thickness by Tool / Chamber",
                },
                "upstream_hint": "block_process_history(metric='thickness') 直接接過來",
            },
        ],
        "block_splom": [
            {
                "name": "FDC parameter matrix",
                "summary": "5 個 FDC params 的 N×N scatter matrix",
                "params": {
                    "dimensions": ["rf_power", "pressure", "gas_flow", "temp", "endpoint"],
                    "outlier_field": "is_ooc",
                    "title": "FDC Parameter Matrix",
                },
                "upstream_hint": "block_filter / block_process_history → 含全部 dimensions 欄位 + 一個 bool outlier 欄位",
            },
        ],
        "block_histogram_chart": [
            {
                "name": "CD spec window with Cpk",
                "summary": "raw 值 distribution + USL/LSL/target + 自動 Cpk 註記",
                "params": {
                    "value_column": "cd_value",
                    "usl": 47.0,
                    "lsl": 43.0,
                    "target": 45.0,
                    "bins": 32,
                    "unit": "nm",
                    "title": "CD distribution",
                },
                "upstream_hint": "block_process_history(metric='cd_value') 直接接 — 給 USL+LSL 才會算 Cpk",
            },
        ],
        # ── PR-H — SPC + Diagnostic chart blocks ──────────────────────
        "block_xbar_r": [
            {
                "name": "Lot-level SPC X̄/R chart",
                "summary": "5-wafer subgroup per lot, full WECO R1-R8 detection",
                "params": {
                    "value_column": "thickness",
                    "subgroup_column": "lot_id",
                    "subgroup_size": 5,
                    "title": "Thickness X̄/R by lot",
                },
                "upstream_hint": "block_process_history(metric='thickness') → 此處（含 lot_id 分組欄位）",
            },
        ],
        "block_imr": [
            {
                "name": "Single-shot endpoint I-MR",
                "summary": "destructive test 的單值 SPC（無 subgroup）",
                "params": {"value_column": "endpoint_time", "title": "Endpoint time I-MR"},
                "upstream_hint": "raw 量測值欄位即可，自動算 moving range",
            },
        ],
        "block_ewma_cusum": [
            {
                "name": "EWMA λ=0.2 small-shift detector",
                "summary": "敏感度比 X̄/R 高，適合偵測 0.5σ shift",
                "params": {"value_column": "thickness", "mode": "ewma", "lambda": 0.2, "title": "Thickness EWMA"},
                "upstream_hint": "block_filter(spc_status='PASS') 看 in-control 樣本的 small drift",
            },
        ],
        "block_pareto": [
            {
                "name": "Defect type Pareto",
                "summary": "缺陷類型按 count 遞減 + 累計 % 線",
                "params": {"category_column": "defect_code", "value_column": "count", "cumulative_threshold": 80, "title": "Defect Pareto"},
                "upstream_hint": "block_groupby_agg(group_by=defect_code, agg={count: count})",
            },
        ],
        "block_variability_gauge": [
            {
                "name": "Lot › Wafer › Tool variability",
                "summary": "三層分組看 shift 來源（lot 之間？wafer 之間？tool？）",
                "params": {"value_column": "thickness", "levels": ["lot", "wafer", "tool"], "title": "Thickness variability"},
                "upstream_hint": "block_process_history → 此處（含 lot/wafer/tool 三個欄位）",
            },
        ],
        "block_parallel_coords": [
            {
                "name": "Recipe profile colored by yield",
                "summary": "5 個 recipe params 並列軸，yield<92 高亮紅色",
                "params": {
                    "dimensions": ["rf_power", "pressure", "gas_flow", "temp", "yield_pct"],
                    "color_by": "yield_pct",
                    "alert_below": 92,
                    "title": "Recipe profile",
                },
                "upstream_hint": "block_join recipe + yield 表 → 此處",
            },
        ],
        "block_probability_plot": [
            {
                "name": "Normality check before Cpk",
                "summary": "Q-Q plot + Anderson-Darling p-value 確認資料常態",
                "params": {"value_column": "thickness", "title": "Thickness normality"},
                "upstream_hint": "block_filter(spc_status='PASS') 排除 OOC 後檢測常態",
            },
        ],
        "block_heatmap_dendro": [
            {
                "name": "FDC correlation matrix (clustered)",
                "summary": "對 correlation matrix 做 hierarchical clustering 重排",
                "params": {
                    "matrix": [[1, 0.8, -0.3], [0.8, 1, -0.2], [-0.3, -0.2, 1]],
                    "dim_labels": ["RF", "Pressure", "Yield"],
                    "cluster": True,
                    "title": "FDC correlations",
                },
                "upstream_hint": "block_correlation 輸出 matrix + 此處視覺化（或 long-form mode）",
            },
        ],
        # ── PR-I — Wafer chart blocks ─────────────────────────────────
        "block_wafer_heatmap": [
            {
                "name": "49-site thickness wafer map",
                "summary": "IDW 插值 + edge ring drift 視覺化",
                "params": {
                    "x_column": "x",
                    "y_column": "y",
                    "value_column": "thickness",
                    "wafer_radius_mm": 150,
                    "unit": "Å",
                    "color_mode": "viridis",
                    "title": "Wafer thickness map",
                },
                "upstream_hint": "block_process_history(metric='thickness', include_xy=true) → 此處",
            },
        ],
        "block_defect_stack": [
            {
                "name": "Multi-wafer defect overlay",
                "summary": "最近 N wafer 的缺陷空間分佈，按 code 著色",
                "params": {
                    "x_column": "x",
                    "y_column": "y",
                    "defect_column": "defect_code",
                    "wafer_radius_mm": 150,
                    "title": "Defect stack (last 20 wafers)",
                },
                "upstream_hint": "block_filter(time>=last_24h) → 此處",
            },
        ],
        "block_spatial_pareto": [
            {
                "name": "Yield zone heatmap",
                "summary": "wafer 切方格，每格平均 yield，最差格框黑色",
                "params": {
                    "x_column": "x",
                    "y_column": "y",
                    "value_column": "yield_pct",
                    "grid_n": 12,
                    "wafer_radius_mm": 150,
                    "unit": "%",
                    "title": "Yield by zone",
                },
                "upstream_hint": "block_join(wafer_xy, yield_per_die) → 此處",
            },
        ],
        "block_trend_wafer_maps": [
            {
                "name": "Pre/post PM thickness drift",
                "summary": "7 天 wafer mini-maps，PM 日紅虛線框",
                "params": {
                    "x_column": "x",
                    "y_column": "y",
                    "value_column": "thickness",
                    "time_column": "wafer_date",
                    "pm_column": "is_pm_day",
                    "cols": 7,
                    "wafer_radius_mm": 150,
                    "title": "Thickness over time",
                },
                "upstream_hint": "block_process_history(since=7d, include_xy=true) + 標記 pm_day 欄位",
            },
        ],
    }
