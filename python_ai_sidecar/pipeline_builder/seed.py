"""Seed 5 standard Phase-1 blocks into DB (idempotent).

Called from main.py lifespan. Uses BlockRepository.upsert to keep
(name, version) as the natural key.

All Phase-1 blocks are status='production' so Phase 1 pipelines can use them.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from python_ai_sidecar.pipeline_builder._sidecar_deps import BlockRepository

logger = logging.getLogger(__name__)


def _blocks() -> list[dict[str, Any]]:
    return [
        {
            "name": "block_process_history",
            "version": "1.0.0",
            "category": "source",
            "status": "production",
            "description": (
                "== What ==\n"
                "從 ontology MCP `get_process_info` 拉指定條件（機台 / 批次 / 站點）的 process events，\n"
                "自動 flatten 所有維度 (SPC/APC/DC/RECIPE/FDC/EC) 成單一寬表。每列 = 一筆 process event。\n"
                "\n"
                "== When to use ==\n"
                "你有確切的 tool_id / lot_id / step 要查歷史，且需要數值分析（畫圖、OOC 判斷、回歸）。\n"
                "- ✅ 「EQP-01 最近 50 次 SPC xbar 趨勢」→ tool_id=EQP-01\n"
                "- ✅ 「LOT-123 在 STEP_004 的 APC etch_time_offset」→ lot_id + step\n"
                "- ✅ 「最近 24 小時 OOC 事件」→ time_range=24h，下游 filter(spc_status=='OOC')\n"
                "- ❌ 「現在哪些機台在跑 / 機台清單」→ 用 block_mcp_call(list_tools)\n"
                "- ❌ 「今天總共幾個 OOC」→ 用 block_mcp_call(get_process_summary)，那是聚合端點，比這個快\n"
                "\n"
                "== Params ==\n"
                "tool_id     (string, 選填) 例 'EQP-01' — **單一字串，不接受逗號清單也不接受 list**\n"
                "lot_id      (string, 選填) 例 'LOT-0234' — 同上，單一字串\n"
                "step        (string, 選填) 例 'STEP_013' — 同上，單一字串\n"
                "object_name (string, 選填) '' | SPC | APC | DC | RECIPE | FDC | EC；留空=所有維度寬表\n"
                "time_range  (string, 預設 24h) 1h / 24h / 7d / 30d\n"
                "event_time  (string, 選填) 精確時間點 (ISO8601)\n"
                "limit       (integer, 預設 100, max 200)\n"
                "**tool_id / lot_id / step 三擇一必填**。\n"
                "需要查多機台 / 多 lot / 多 step：source 不要設這個欄位，下游接 block_filter\n"
                "operator='in' value=[...] 過濾。\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe)\n"
                "基礎欄位：eventTime, toolID, lotID, step, spc_status, fdc_classification\n"
                "SPC:    spc_<chart>_value / _ucl / _lcl / _is_ooc (chart: xbar/r/s/p/c)\n"
                "APC:    apc_<param_name> (~20 個 parameter)\n"
                "DC:     dc_<sensor_name> (~30 個 sensor)\n"
                "RECIPE: recipe_version + recipe_<param_name>\n"
                "FDC:    fdc_classification, fdc_fault_code, fdc_confidence, fdc_description\n"
                "EC:     ec_<const>_value / _nominal / _deviation_pct / _status\n"
                "\n"
                "== 範圍語意（重要）==\n"
                "當需求是「所有機台 / 全部機台 / every tool」：\n"
                "  ✅ 正確：pipeline 宣告 input `$tool_id`，本 block 的 tool_id 參數綁 `$tool_id`；\n"
                "     搭配 Auto-Patrol `target_scope={type:'all_equipment'}`，runtime 為每台機台 fan-out 一次\n"
                "  ❌ 錯誤：枚舉 'EQP-01,EQP-02,EQP-03,...' 寫死進 tool_id 參數\n"
                "     → 新機台上線時不會被自動包含，且違反 fan-out 語意\n"
                "\n"
                "當需求明確點名單一機台（如「EQP-03 的」）：\n"
                "  tool_id 直接寫 'EQP-03'\n"
                "\n"
                "當需求明確點名多台機台（如「EQP-01 跟 EQP-02 比較」/「EQP-01~EQP-05」）：\n"
                "  ✅ source 不設 tool_id（保留 step），下游 block_filter operator='in' value=['EQP-01','EQP-02']\n"
                "  ❌ tool_id='EQP-01,EQP-02' — MCP 只認單值，整段 string 進 Mongo 會 0 row\n"
                "\n"
                "當需求是條件式範圍（如「ABC recipe 的機台」）：\n"
                "  本 block 沒辦法直接表達；請建議使用者改為「所有機台」+ 後續接 block_filter 過濾 recipe\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 欄位名是 flat snake_case，不是巢狀路徑（e.g. spc_xbar_chart_value，不是 spc.xbar.value）\n"
                "⚠ 時間欄叫 eventTime（camelCase），不是 event_time\n"
                "⚠ spc_status 是 string ('PASS' | 'OOC')，不是 boolean，也不叫 status\n"
                "⚠ 三個 filter 都沒填會 NO_FILTER_GIVEN；全部空 events 會得 EMPTY_RESULT\n"
                "⚠ 「所有機台」請勿枚舉 EQP-ID，請用 `$tool_id` input + Auto-Patrol fan-out（見『範圍語意』段）\n"
                "\n"
                "== Errors ==\n"
                "- MCP_UNREACHABLE : ontology MCP 連不上（check simulator 是否在 8012）\n"
                "- NO_FILTER_GIVEN : 三擇一沒填\n"
                "- EMPTY_RESULT    : 條件太嚴回 0 筆（擴大 time_range 或放寬 filter）\n"
                "\n"
                "== Performance tips ==\n"
                "- limit 調小可加速下游；只要做趨勢通常 50~100 就夠\n"
                "- 已知分析維度時指定 object_name 可減少回傳 column 數\n"
            ),
            "input_schema": [],
            "output_schema": [
                {"port": "data", "type": "dataframe", "columns": ["eventTime", "toolID", "lotID", "step", "spc_status"]},
            ],
            "param_schema": {
                "type": "object",
                "properties": {
                    "tool_id":    {
                        "type": "string",
                        "title": "機台 ID (三擇一，單值)",
                        "x-suggestions": "tool_id",
                        "description": (
                            "**單一機台 ID**，例 'EQP-01'。MCP 只接受單值，不能傳逗號清單也不能傳 list。"
                            "需要多機台：source 留空，下游 block_filter operator='in' value=[...] 過濾。"
                            "需要『所有機台』runtime fan-out：綁 $tool_id pipeline input + Auto-Patrol "
                            "target_scope=all_equipment。"
                        ),
                    },
                    "lot_id":     {"type": "string", "title": "批次 ID (三擇一)"},
                    "step":       {"type": "string", "title": "站點 Step (三擇一)", "x-suggestions": "step"},
                    "object_name": {
                        "type": "string",
                        "title": "資料維度 (選填，留空=全部)",
                        "enum": ["", "SPC", "APC", "DC", "RECIPE", "FDC", "EC"],
                    },
                    "time_range": {"type": "string", "enum": ["1h", "24h", "7d", "30d"], "default": "24h", "title": "時間窗"},
                    "event_time": {"type": "string", "title": "精確時間 (ISO8601，選填)"},
                    "limit":      {"type": "integer", "default": 100, "minimum": 1, "maximum": 200, "title": "筆數上限"},
                },
            },
            "implementation": {
                "type": "python",
                "ref": "app.services.pipeline_builder.blocks.process_history:ProcessHistoryBlockExecutor",
            },
            "output_columns_hint": [
                # Base columns — always present
                {"name": "eventTime", "type": "datetime", "description": "事件時間 (ISO8601 字串，block_sort/block_linear_regression 會自動轉 epoch)"},
                {"name": "toolID", "type": "string", "description": "機台 ID，e.g. EQP-01"},
                {"name": "lotID", "type": "string", "description": "批次 ID"},
                {"name": "step", "type": "string", "description": "製程站點，e.g. STEP_013"},
                {"name": "spc_status", "type": "string", "description": "'PASS' | 'OOC' — SPC 總體判定（注意不是 status）"},
                {"name": "fdc_classification", "type": "string", "description": "FDC 分類，e.g. 'anomaly_detected'"},
                # SPC family — flat per chart_type
                {"name": "spc_xbar_chart_value", "type": "number", "when_present": "object_name=SPC + chart_type=xbar_chart"},
                {"name": "spc_xbar_chart_ucl", "type": "number", "when_present": "object_name=SPC + chart_type=xbar_chart"},
                {"name": "spc_xbar_chart_lcl", "type": "number", "when_present": "object_name=SPC + chart_type=xbar_chart"},
                {"name": "spc_xbar_chart_is_ooc", "type": "boolean", "when_present": "object_name=SPC + chart_type=xbar_chart"},
                {"name": "spc_r_chart_value", "type": "number", "when_present": "SPC + chart_type=r_chart"},
                {"name": "spc_r_chart_ucl", "type": "number", "when_present": "SPC + chart_type=r_chart"},
                {"name": "spc_r_chart_lcl", "type": "number", "when_present": "SPC + chart_type=r_chart"},
                {"name": "spc_s_chart_value", "type": "number", "when_present": "SPC + chart_type=s_chart"},
                {"name": "spc_p_chart_value", "type": "number", "when_present": "SPC + chart_type=p_chart"},
                {"name": "spc_c_chart_value", "type": "number", "when_present": "SPC + chart_type=c_chart"},
                # APC — dynamic per param_name
                {"name": "apc_<param_name>", "type": "number", "description": "APC 參數值，<param_name> 會展開，e.g. apc_etch_time_offset / apc_rf_power_bias / apc_chamber_pressure", "when_present": "object_name=APC"},
                # DC — dynamic per sensor
                {"name": "dc_<sensor_name>", "type": "number", "description": "DC sensor 讀值，e.g. dc_temperature / dc_gas_flow", "when_present": "object_name=DC"},
                # RECIPE
                {"name": "recipe_version", "type": "string", "when_present": "object_name=RECIPE"},
                {"name": "recipe_<param_name>", "type": "number", "description": "Recipe 參數設定值", "when_present": "object_name=RECIPE"},
                # FDC
                {"name": "fdc_fault_code", "type": "string", "when_present": "object_name=FDC"},
                {"name": "fdc_confidence", "type": "number", "when_present": "object_name=FDC"},
                {"name": "fdc_description", "type": "string", "when_present": "object_name=FDC"},
                # EC
                {"name": "ec_<const>_value", "type": "number", "when_present": "object_name=EC"},
                {"name": "ec_<const>_deviation_pct", "type": "number", "when_present": "object_name=EC"},
            ],
        },
        {
            "name": "block_filter",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "根據 column/operator/value 過濾 DataFrame 列（單條件），保留符合條件的 rows。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「只看 OOC events」→ column='spc_status', operator='==', value='OOC'\n"
                "- ✅ 「只看特定 3 台機台」→ column='toolID', operator='in', value=['EQP-01','EQP-02','EQP-03']\n"
                "- ✅ 「recipe 含 'ETCH' 字樣」→ operator='contains', value='ETCH'\n"
                "- ✅ 「xbar 值超過 100」→ column='spc_xbar_chart_value', operator='>', value=100\n"
                "- ❌ 多條件 AND/OR → 串多個 block_filter（目前不支援單一 block 內複合條件）\n"
                "- ❌ 需要判斷 triggered (bool) + 輸出 evidence → 用 block_threshold，不是這個\n"
                "\n"
                "== Params ==\n"
                "column   (string, required) 要比較的欄位\n"
                "operator (string, required) ==, !=, >, <, >=, <=, contains, in\n"
                "value    (any, required) 比較值；operator='in' 時必須是 list；'contains' 作 substring 比對（string only）\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe) — 只保留符合條件的 rows，欄位不變\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 'in' 的 value 必須是 list（['a','b','c']），給 string 會出錯\n"
                "⚠ column 名稱要完全一致（case-sensitive + snake_case）\n"
                "⚠ 比較 boolean 欄位時 value 給 True/False（Python bool），不是字串 'True'\n"
                "⚠ contains 只對 string column 有意義；數值欄位會出錯\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND : column 名稱打錯 / 上游沒這欄\n"
                "- INVALID_OPERATOR : 用了 enum 外的 operator\n"
                "- EMPTY_AFTER_FILTER : 過濾後 0 筆（放寬條件或檢查 value）\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["column", "operator"],
                "properties": {
                    "column":   {"type": "string", "x-column-source": "input.data"},
                    "operator": {
                        "type": "string",
                        "enum": ["==", "!=", ">", "<", ">=", "<=", "contains", "in"],
                    },
                    "value":    {},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.filter:FilterBlockExecutor"},
        },
        {
            "name": "block_threshold",
            "version": "1.0.0",
            "category": "logic",
            "status": "production",
            "description": (
                "== What ==\n"
                "對 column 做閾值判斷，輸出 triggered (bool) + evidence (dataframe) — Logic Node。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「xbar 值超過 UCL / 低於 LCL」→ Mode A，bound_type='both'\n"
                "- ✅ 「row count == 1（全部 OOC 來自同一 recipe 嗎）」→ Mode B，operator='==', target=1\n"
                "- ✅ 「p_value < 0.05 代表顯著」→ Mode B，operator='<', target=0.05\n"
                "- ✅ 要告警（接 block_alert）或要 evidence 表 → 用這個（它輸出 triggered + evidence 雙 port）\n"
                "- ❌ 純過濾 rows（不需要 triggered / evidence 欄位）→ 用 block_filter，比較輕量\n"
                "- ❌ SPC Nelson 多規則（連 9 點同側 / 6 點趨勢）→ 用 block_weco_rules\n"
                "- ❌ 連續 N 次 True 偵測 → 用 block_consecutive_rule\n"
                "\n"
                "== Two modes ==\n"
                "Mode A — UCL/LCL bound（傳統 SPC）：\n"
                "  bound_type='upper' → violates if value > upper_bound\n"
                "  bound_type='lower' → violates if value < lower_bound\n"
                "  bound_type='both'  → 任一違反\n"
                "Mode B — generic operator：\n"
                "  operator ∈ {==, !=, >=, <=, >, <} + target；非數值 column 僅支援 ==/!=\n"
                "\n"
                "== Params ==\n"
                "column      (string, required) 要判斷的欄位\n"
                "# Mode A\n"
                "bound_type  (string, opt) 'upper' | 'lower' | 'both'\n"
                "upper_bound (number, opt) bound_type 含 upper 時 required\n"
                "lower_bound (number, opt) bound_type 含 lower 時 required\n"
                "# Mode B\n"
                "operator    (string, opt) ==, !=, >=, <=, >, <\n"
                "target      (any, opt) 比較目標（數字或字串）\n"
                "\n"
                "== Output (PR-A evidence semantics) ==\n"
                "port: triggered (bool) — 是否有任一 row 違反\n"
                "port: evidence (dataframe) — **全部被評估的 rows（完整 audit trail）**，加欄：\n"
                "  triggered_row  (bool)  — 該筆是否違規\n"
                "  violation_side (str)   — 'above' / 'below' / None\n"
                "  violated_bound (float) — 比較的 bound 值\n"
                "  explanation    (str)   — 違規描述\n"
                "👉 Chart 接 evidence 看全部 + highlight_column='triggered_row' 可紅圈標記違規點\n"
                "👉 只看違規列 → chart 前加 filter(triggered_row==true)\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 別以為 evidence 只含違規列 — 它是 **全部 rows**，triggered_row 欄位才是違規旗標\n"
                "⚠ Mode A / Mode B 擇一：同時給 bound_type + operator 時 Mode A 優先\n"
                "⚠ column 要是數值型（除非用 ==/!=）；string 欄 + > / < 會出錯\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND : column 不在上游 df\n"
                "- MISSING_BOUND    : Mode A 沒給對應 bound\n"
                "- INVALID_MODE     : 兩 mode 的參數都沒給完整\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [
                {"port": "triggered", "type": "bool"},
                {"port": "evidence", "type": "dataframe"},
            ],
            "param_schema": {
                "type": "object",
                "required": ["column"],
                "properties": {
                    "column":      {"type": "string", "x-column-source": "input.data"},
                    # Mode A (legacy)
                    "bound_type":  {"type": "string", "enum": ["upper", "lower", "both"], "title": "Mode A: UCL/LCL 模式"},
                    "upper_bound": {"type": "number"},
                    "lower_bound": {"type": "number"},
                    # Mode B (generic)
                    "operator":    {"type": "string", "enum": ["==", "!=", ">=", "<=", ">", "<"], "title": "Mode B: 通用比較運算子"},
                    "target":      {"title": "Mode B: 目標值（數字或字串）"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.threshold:ThresholdBlockExecutor"},
        },
        {
            "name": "block_count_rows",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "算上游 DataFrame 有幾 row，輸出 1-row DF with `count` 欄位。\n"
                "若 `group_by` 有給，按該欄位分組，每組一 row。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「OOC events 是不是都來自同一 recipe」→ filter(OOC) → groupby_agg(recipeID,count) → **count_rows** → threshold(==, 1)\n"
                "- ✅ 「有多少筆 process event 超過閾值」→ filter / threshold → count_rows → chart\n"
                "- ✅ 「每台機台各有幾筆 OOC」→ count_rows with group_by=toolID\n"
                "- ❌ 要對欄位做 sum / mean / max 之類聚合 → 用 block_groupby_agg\n"
                "- ❌ 要 unique 值數量而不是 row count → 先 drop_duplicates 再 count（目前用 groupby_agg count 替代）\n"
                "\n"
                "== Params ==\n"
                "group_by (string, opt) 有給時按欄位分組 count，每組一列\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe)\n"
                "- 無 group_by：1 row，欄位 [count]\n"
                "- 有 group_by：N rows，欄位 [<group_by>, count]\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 輸出是 DataFrame，不是單一整數；下游用 threshold 比較時記得指 column='count'\n"
                "⚠ 空上游會回 1-row df with count=0（不會丟錯）\n"
                "⚠ group_by 與 block_groupby_agg 不同：這裡只算 row 數，不對其他欄位做聚合\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND : group_by 欄位不存在\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "properties": {
                    "group_by": {"type": "string", "x-column-source": "input.data", "title": "Group by (選填)"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.count_rows:CountRowsBlockExecutor"},
        },
        {
            "name": "block_mcp_foreach",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "對上游 DataFrame 每一 row 呼叫指定 MCP，把 response 合併成新欄位。\n"
                "Async concurrent — `max_concurrency` 限制同時 in-flight 的 HTTP 請求數（預設 5）。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「每筆 OOC process 查一次 fault context」→ process_history → filter(OOC) → mcp_foreach(get_fdc_context)\n"
                "- ✅ 「每個 lot 查一次 recipe 詳細設定」→ upstream df → mcp_foreach(get_recipe_detail, '$lotID')\n"
                "- ✅ enrichment 場景：用上游 row 的某欄當 MCP args，擴充更多資訊\n"
                "- ❌ 單次 MCP call（不依賴 df 每一 row）→ 用 block_mcp_call（不是 foreach）\n"
                "- ❌ 要 join 兩個 df → 用 block_join\n"
                "- ❌ 上游 > 500 rows → 請先 filter / limit，避免 MCP 洪流\n"
                "\n"
                "== Params ==\n"
                "mcp_name        (string, required) MCP 名稱（必須註冊在 mcp_definitions 表）\n"
                "args_template   (object, required) 傳給 MCP 的 args；值可用 `$col_name` 引用當前 row 欄位，e.g. {'targetID':'$lotID'}\n"
                "result_prefix   (string, opt) 合併時的欄位前綴（避免名稱衝突；e.g. 'apc_'）\n"
                "max_concurrency (integer, opt, default 5, max 20) 同時 in-flight 的請求數\n"
                "\n"
                "== Result merging ==\n"
                "- dict 回傳 → 每 key 轉成欄位（加 prefix）\n"
                "- list[dict] → 取第 1 筆（1:1 展開）\n"
                "- 其他 → 存成 `<prefix>raw` JSON 欄位\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe) — 原 df 加上 MCP 回傳的新欄位\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ args_template 裡的 `$col_name` 要精準對上 upstream df 欄位名（case-sensitive）\n"
                "⚠ 沒給 result_prefix 時欄位可能跟 upstream 重名 → 上游欄位會被覆蓋\n"
                "⚠ 上游 > 500 rows 直接 TOO_MANY_ROWS；先 filter 或 limit\n"
                "⚠ 單一 call 失敗會讓整個 block fail（fail-fast，無 per-row skip）\n"
                "\n"
                "== Errors ==\n"
                "- MCP_NOT_FOUND     : mcp_name 沒註冊\n"
                "- TOO_MANY_ROWS     : 上游 > 500 rows\n"
                "- MCP_UNREACHABLE   : MCP 連不上\n"
                "- TEMPLATE_MISSING_COL : args_template 裡的 $col 上游找不到\n"
                "\n"
                "== Performance tips ==\n"
                "- max_concurrency 開大（10~20）可加速，但別打爆 MCP server\n"
                "- 先 filter 縮小上游 rows，foreach 成本線性於 row 數\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["mcp_name", "args_template"],
                "properties": {
                    "mcp_name":        {"type": "string"},
                    "args_template":   {"type": "object", "title": "MCP args (可用 $col 引用 row 欄位)"},
                    "result_prefix":   {"type": "string", "default": "", "title": "結果欄位前綴"},
                    "max_concurrency": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.mcp_foreach:McpForeachBlockExecutor"},
        },
        {
            "name": "block_consecutive_rule",
            "version": "1.0.0",
            "category": "logic",
            "status": "production",
            "description": (
                "== What ==\n"
                "Tail-based 連續 N 次 True 偵測 — Logic Node（triggered + evidence schema）。\n"
                "按 sort_by 排序後，每個 group 檢查**最後 N 筆**是否全為 True。反映**當下狀態**，不是歷史掃描。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「最近 5 次 process 中有 3 次連續 OOC」→ flag_column=spc_xbar_chart_is_ooc, count=3\n"
                "- ✅ 「連續 3 點上升」→ 先 block_delta 得 is_rising → consecutive_rule(flag_column=is_rising, count=3)\n"
                "- ✅ 「連續 N 筆 APC 超出閾值」→ 先 threshold → consecutive_rule(flag_column=triggered_row, count=N)\n"
                "- ❌ 歷史上**曾**有連續 N（審視 run） → 本 block 只看 tail，歷史掃描要自己組 transform+groupby\n"
                "- ❌ Nelson / WECO 多條複合規則 → 用 block_weco_rules（已內建 R1~R8）\n"
                "- ❌ 需要 '9 點同側' 這種要比較 center 的規則 → 用 block_weco_rules R2\n"
                "\n"
                "== Params ==\n"
                "flag_column (string, required) bool column；常見來源：block_threshold.evidence.triggered_row / block_delta 的 <col>_is_rising\n"
                "count       (integer, required, >= 2) N\n"
                "sort_by     (string, required) 排序欄位（e.g. 'eventTime'）；**不會預設**，必填\n"
                "group_by    (string, opt) 每組獨立評估（e.g. toolID）\n"
                "\n"
                "== Output (PR-A evidence semantics) ==\n"
                "port: triggered (bool) — 任一 group 的最後 N 筆全為 True\n"
                "port: evidence (dataframe) — **全部輸入 rows（按 group+sort_by 排序）**，加欄：\n"
                "  triggered_row (bool) — 該筆是否屬於觸發 tail\n"
                "  group, trigger_id, run_position, run_length（僅觸發列填值）\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 忘了 sort_by 會 fail — block 不會猜排序欄；通常給 'eventTime'\n"
                "⚠ flag_column 必須是 bool；給 'PASS'/'OOC' 字串會出錯（先 threshold 轉 bool）\n"
                "⚠ 「歷史上曾連續 N」≠ 「當下 tail 連續 N」— 這個 block 只做後者\n"
                "⚠ evidence 是全部 rows，不是只觸發的 tail；要看 triggered_row 欄\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND      : flag_column / sort_by / group_by 欄位不存在\n"
                "- INVALID_FLAG_TYPE     : flag_column 不是 bool\n"
                "- INSUFFICIENT_DATA     : group 的 row 數 < count\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [
                {"port": "triggered", "type": "bool"},
                {"port": "evidence", "type": "dataframe"},
            ],
            "param_schema": {
                "type": "object",
                "required": ["flag_column", "count", "sort_by"],
                "properties": {
                    "flag_column": {"type": "string", "x-column-source": "input.data"},
                    "count":       {"type": "integer", "minimum": 2},
                    "sort_by":     {"type": "string", "x-column-source": "input.data", "title": "Sort by (必填)"},
                    "group_by":    {"type": "string", "x-column-source": "input.data", "title": "Group by (選填)"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.consecutive_rule:ConsecutiveRuleBlockExecutor"},
        },
        {
            "name": "block_delta",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "計算相鄰點的差值（current - previous）與 trend 旗標（rising / falling）。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「連續 3 點上升」→ block_delta 產 is_rising → block_consecutive_rule(flag_column=<value>_is_rising, count=3)\n"
                "- ✅ 「批次之間的變化量」→ 看 <value>_delta 欄位\n"
                "- ✅ 「哪些 event 是下跌的」→ filter(<value>_is_falling == True)\n"
                "- ❌ 指定 offset（跟 N 筆之前比）→ 用 block_shift_lag（compute_delta=True 也給 delta 欄）\n"
                "- ❌ 滑動平均 / 標準差 → 用 block_rolling_window\n"
                "- ❌ 指數加權 smoothing → 用 block_ewma\n"
                "\n"
                "== Params ==\n"
                "value_column (string, required) 監控欄位（numeric）\n"
                "sort_by      (string, required) 排序欄位（e.g. eventTime）；**不預設**，必填\n"
                "group_by     (string, opt) 各組獨立算 delta（每組第一筆 delta=NaN, is_rising/falling=False）\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe) — 原 df 外加 3 欄：\n"
                "  <value_column>_delta      (number) 當前值 - 前值；每 group 首筆為 NaN\n"
                "  <value_column>_is_rising  (bool)   delta > 0\n"
                "  <value_column>_is_falling (bool)   delta < 0\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 沒排序直接算 delta 會無意義；sort_by 必填\n"
                "⚠ 欄位名是 <value_column>_delta（不是 delta_<value_column>）\n"
                "⚠ 跨 group 第一筆的 delta 是 NaN — is_rising / is_falling 為 False（非 NaN）\n"
                "⚠ delta=0 時 is_rising / is_falling 都是 False\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND  : value_column / sort_by / group_by 不存在\n"
                "- INVALID_VALUE_TYPE: value_column 非數值\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["value_column", "sort_by"],
                "properties": {
                    "value_column": {"type": "string", "x-column-source": "input.data"},
                    "sort_by":      {"type": "string", "x-column-source": "input.data", "title": "Sort by (必填)"},
                    "group_by":     {"type": "string", "x-column-source": "input.data", "title": "Group by (選填)"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.delta:DeltaBlockExecutor"},
        },
        {
            "name": "block_join",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "兩個 DataFrame by key 橫向合併（pandas merge）。右表同名 column 自動加 '_r' 後綴。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「SPC 寬表跟 APC context 合併」→ 兩個 df by (lotID, step) join\n"
                "- ✅ 「Alert records 帶 tool metadata」→ alert df left-join tool df\n"
                "- ❌ 縱向疊加（rows concat）兩張結構相同的 df → 用 block_union\n"
                "- ❌ enrichment: 每 row 呼叫 MCP 取額外欄位 → 用 block_mcp_foreach\n"
                "\n"
                "== Input ports ==\n"
                "left  (dataframe)\n"
                "right (dataframe)\n"
                "\n"
                "== Params ==\n"
                "key (string, required) 單 column 或逗號分隔多欄 (e.g. 'lotID,step')；兩邊都要有同名欄\n"
                "how (string, opt, default 'inner') inner | left | right | outer\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe) — 合併後的 df；右表非 key 同名欄自動加 '_r' 後綴\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ key 兩邊必須同名；不同名要先 rename\n"
                "⚠ 多欄 key 用英文逗號分隔（無空白 or 有空白都可），不是 list\n"
                "⚠ inner join 條件不符會得空 df — 檢查 key 值分佈\n"
                "⚠ 右表欄位會多出 '_r' 後綴；下游要用要注意名稱\n"
                "\n"
                "== Errors ==\n"
                "- KEY_NOT_FOUND     : key 在左或右 df 不存在\n"
                "- EMPTY_AFTER_JOIN  : inner join 後 0 列\n"
            ),
            "input_schema": [
                {"port": "left", "type": "dataframe"},
                {"port": "right", "type": "dataframe"},
            ],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["key"],
                "properties": {
                    # Show the set of columns common to both left and right ports
                    "key": {
                        "type": "string",
                        "title": "Join key(s); 逗號分隔多欄",
                        "x-column-source": "input.left+right",
                    },
                    "how": {"type": "string", "enum": ["inner", "left", "right", "outer"], "default": "inner"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.join:JoinBlockExecutor"},
        },
        {
            "name": "block_groupby_agg",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "Group by + 聚合（pandas groupby + single agg func）。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「每台機台平均 xbar 值」→ group_by=toolID, agg_column=spc_xbar_chart_value, agg_func=mean\n"
                "- ✅ 「每個 recipe 的 OOC 次數」→ filter(OOC) → groupby_agg(recipe, agg_column=spc_status, agg_func=count)\n"
                "- ✅ 多維度：group_by='toolID,step' 逗號分隔\n"
                "- ❌ 只想算 row 數（不聚合其他欄）→ 用 block_count_rows，語意更清楚\n"
                "- ❌ 多個 agg func 同時 → 目前只支援單一 agg_func；要多個就分多個 block 再 join\n"
                "- ❌ Cpk / 統計檢定 → 用 block_cpk / block_hypothesis_test\n"
                "\n"
                "== Params ==\n"
                "group_by   (string, required) 分組欄位；逗號分隔多欄 (e.g. 'toolID,step')\n"
                "agg_column (string, required) 要聚合的欄位\n"
                "agg_func   (string, required) mean / sum / count / min / max / median / std\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe) — columns = [<group_by 各欄>, <agg_column>_<agg_func>]\n"
                "例：group_by=toolID, agg_column=value, agg_func=mean → columns [toolID, value_mean]\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 輸出欄位名是 <agg_column>_<agg_func>（e.g. value_mean），不是 'agg' 或 <agg_column>\n"
                "⚠ agg_func='count' 會算非 null row 數（類似 pandas count），若 agg_column 全有值等同 row count\n"
                "⚠ 多 group_by 要用逗號分隔 string，不是 list\n"
                "⚠ std / median 需要至少 2 筆；組內單筆會是 NaN\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND     : group_by / agg_column 不存在\n"
                "- INVALID_AGG_FOR_TYPE : 對字串欄跑 mean / sum\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["group_by", "agg_column", "agg_func"],
                "properties": {
                    "group_by":   {"type": "string", "title": "Group by column (逗號分隔多欄)", "x-column-source": "input.data"},
                    "agg_column": {"type": "string", "x-column-source": "input.data"},
                    "agg_func": {
                        "type": "string",
                        "enum": ["mean", "sum", "count", "min", "max", "median", "std"],
                    },
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.groupby_agg:GroupByAggBlockExecutor"},
        },
        {
            "name": "block_chart",
            "version": "1.0.0",
            "category": "output",
            "status": "production",
            "description": (
                "== What ==\n"
                "產生圖表 spec（chart_spec）。預設 Vega-Lite（單 y 簡單圖）；符合下列條件會自動切\n"
                "到 ChartDSL (Plotly) 模式：\n"
                "  - 任一 SPC 控制欄位有給（ucl/lcl/center/highlight）\n"
                "  - y 是 array（多條線）\n"
                "  - y_secondary 有給（雙 Y 軸）\n"
                "  - chart_type='boxplot' 或 'heatmap'\n"
                "\n"
                "== chart_type ==\n"
                "  line / bar / scatter / area — 標準\n"
                "  boxplot                     — 箱型圖，x=group_by 欄位、y=value column\n"
                "  heatmap                     — 熱圖，x/y 為類別欄位、value_column 為 cell 值\n"
                "  distribution                — 直方圖 + 常態 PDF 曲線 + μ/±σ 線 + USL/LSL；value_column 給 raw 欄位即可（不需先跑 histogram）\n"
                "  table                       — 以表格呈現 data（不需 x/y）。可選 `columns` 限制欄位、`max_rows` 限制列數（預設 500）\n"
                "\n"
                "== SPC sigma_zones (line chart only) ==\n"
                "  sigma_zones=[1, 2] → 除 UCL/LCL 外加畫 ±1σ / ±2σ 細線（顏色綠→紅逐級深），\n"
                "  σ = (UCL - Center) / 3 自動推算；用於 Nelson A/B/C zone 視覺化。\n"
                "\n"
                "== y params ==\n"
                "  y: string | string[]  — 單值或多值（多值時自動畫多條線）\n"
                "  y_secondary: string[] — 右側 Y 軸系列（雙軸，e.g. TC16 SPC xbar + APC rf_power）\n"
                "\n"
                "== SPC 場景建議搭配 ==\n"
                "  chart_type='line', x='eventTime', y='spc_xbar_chart_value',\n"
                "  ucl_column='spc_xbar_chart_ucl', lcl_column='spc_xbar_chart_lcl',\n"
                "  highlight_column='spc_xbar_chart_is_ooc'\n"
                "→ 標準 xbar 控制圖：值折線 + UCL/LCL 紅虛線 + OOC 紅圈\n"
                "\n"
                "== Boxplot 用法 ==\n"
                "  chart_type='boxplot', y='spc_xbar_chart_value', group_by='toolID'\n"
                "\n"
                "== Heatmap 用法 ==\n"
                "  chart_type='heatmap', x='col_a', y='col_b', value_column='correlation'\n"
                "  常搭配 block_correlation 的 long-format 輸出。\n"
                "\n"
                "== sequence ==\n"
                "多張 chart 在 Pipeline Results 面板的顯示順序；新增時前端自動配 max+1。\n"
                "\n"
                "== When to use (vs 其他輸出 block) ==\n"
                "- ✅ 任何視覺化（line/bar/scatter/heatmap/distribution/boxplot/table）→ 用 block_chart\n"
                "- ✅ 純看中間步驟表格（debug / audit）→ 用 block_data_view（更輕量，不用配 x/y）\n"
                "- ❌ 觸發告警 record → 用 block_alert（它只負責發單一 alert record，不畫 chart）\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ x 欄常見坑：SPC 場景要用 'eventTime'（camelCase），不是 'event_time' / 'timestamp'\n"
                "⚠ y 可以是 string 或 array；要雙軸時把第二條線放 y_secondary（不要塞 y 的 array）\n"
                "⚠ highlight_column 必須是 **bool** 欄位；給數字或字串不會有紅圈\n"
                "⚠ boxplot 必須給 group_by（類別軸），y 是數值；x 不用\n"
                "⚠ heatmap 需要 long-format df（每 row = 一 cell），常搭 block_correlation 輸出\n"
                "⚠ distribution 吃 raw 數值欄位，不要先 histogram；block_chart 會自己 bin\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND      : x / y / ucl_column / lcl_column 等引用欄位不存在\n"
                "- INVALID_CHART_TYPE    : chart_type 不是 enum 之一\n"
                "- MISSING_BOXPLOT_GROUP : boxplot 缺 group_by\n"
                "- MISSING_HEATMAP_VALUE : heatmap 缺 value_column\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "chart_spec", "type": "dict"}],
            "param_schema": {
                "type": "object",
                "required": ["chart_type"],
                "properties": {
                    "chart_type": {"type": "string", "enum": ["line", "bar", "scatter", "area", "boxplot", "heatmap", "distribution", "table"]},
                    "x":     {"type": "string", "x-column-source": "input.data"},
                    # y: string OR array of strings (multi-line / dual-axis)
                    "y":     {"type": ["string", "array"], "items": {"type": "string"}, "x-column-source": "input.data", "title": "y (string or array)"},
                    "y_secondary": {"type": ["string", "array"], "items": {"type": "string"}, "title": "右側 Y 軸欄位 (選填，string/array)", "x-column-source": "input.data"},
                    "value_column": {"type": "string", "title": "heatmap/distribution value 欄位", "x-column-source": "input.data"},
                    "group_by": {"type": "string", "title": "boxplot group_by (boxplot 專用)", "x-column-source": "input.data"},
                    # v3.5 distribution mode params
                    "bins":             {"type": "integer", "minimum": 2, "default": 20, "title": "直方圖 bins (distribution)"},
                    "usl":              {"type": "number", "title": "USL (distribution / SPC)"},
                    "lsl":              {"type": "number", "title": "LSL (distribution / SPC)"},
                    "show_sigma_lines": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 6}, "default": [1, 2, 3], "title": "Distribution σ 線 (1..6)"},
                    # v3.5 SPC line chart extra
                    "sigma_zones":      {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 6}, "title": "SPC ±σ zones 線 (e.g. [1, 2])"},
                    "color": {"type": "string", "x-column-source": "input.data"},
                    # v1.3 B2 style panel
                    "title": {"type": "string", "title": "標題"},
                    "color_scheme": {
                        "type": "string",
                        "enum": ["", "tableau10", "set2", "blues", "reds", "greens"],
                        "default": "",
                        "title": "Color scheme",
                    },
                    "show_legend": {"type": "boolean", "default": True, "title": "顯示圖例"},
                    "width":  {"type": "integer", "default": 600},
                    "height": {"type": "integer", "default": 300},
                    # v3.2 SPC extensions — 任一給值就走 SPC 模式（Plotly）
                    "ucl_column":       {"type": "string", "title": "UCL 欄位 (SPC)", "x-column-source": "input.data"},
                    "lcl_column":       {"type": "string", "title": "LCL 欄位 (SPC)", "x-column-source": "input.data"},
                    "center_column":    {"type": "string", "title": "Center 欄位 (SPC，選填)", "x-column-source": "input.data"},
                    "highlight_column": {"type": "string", "title": "OOC highlight 欄位 (bool)", "x-column-source": "input.data"},
                    # v3.2: 多圖顯示用流水號（1..N）；pipeline 結果面板按此排序
                    "sequence": {
                        "type": "integer",
                        "minimum": 1,
                        "title": "顯示順序（流水號）",
                        "description": "Canvas Pipeline Results 面板按此遞增排序展示多張 charts。新增時前端自動指派 max+1。",
                    },
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.chart:ChartBlockExecutor"},
        },
        {
            "name": "block_shift_lag",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "將指定 column 平移 N 列（pandas .shift(N)）→ 產生 <column>_lag<N> 欄位；\n"
                "若 compute_delta=true，也輸出 <column>_delta = current - previous。\n"
                "適合計算批次之間的 drift（e.g. APC rf_power_bias 本批 vs 上批）。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「本批次 vs N 批前的值差異」→ offset=N, compute_delta=True\n"
                "- ✅ 需要訪問「前 N 筆」的欄位做下游計算（非 delta，是完整前值）\n"
                "- ✅ 負 offset：看「未來 N 筆」的值（e.g. label lookahead）\n"
                "- ❌ 只要相鄰差值（offset=1 + trend 旗標）→ 用 block_delta，它多給 is_rising/is_falling\n"
                "- ❌ 滑動視窗統計（移動平均/標準差）→ 用 block_rolling_window\n"
                "- ❌ 指數平滑 → 用 block_ewma\n"
                "\n"
                "== Params ==\n"
                "column        (string, required) 目標欄位\n"
                "offset        (integer, required, default 1) 正=過去 / 負=未來\n"
                "group_by      (string, opt) 各組內獨立 shift（跨組不外溢）\n"
                "sort_by       (string, opt, 預設 'eventTime') 排序欄位\n"
                "compute_delta (bool, opt, default True) 是否同時輸出 <column>_delta = current - previous\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe) — 原 df 加：\n"
                "  <column>_lag<N> (原型別) 前 N 筆的值\n"
                "  <column>_delta  (number, 當 compute_delta=True) current - <column>_lag<N>\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 首 N 筆的 lag / delta 是 NaN（group_by 下每組首 N 筆都會是 NaN）\n"
                "⚠ 欄位名帶 offset 數字：<column>_lag1, <column>_lag2 不是 <column>_lag\n"
                "⚠ 排序會影響結果 — sort_by 沒給時預設 eventTime；確認上游有這欄或手動指定\n"
                "⚠ 跨 group 不會借值；group_by 有給時每組獨立 shift\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND : column / sort_by / group_by 不存在\n"
                "- INVALID_OFFSET   : offset=0 無意義\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["column", "offset"],
                "properties": {
                    "column":   {"type": "string", "title": "目標欄位", "x-column-source": "input.data"},
                    "offset":   {"type": "integer", "default": 1, "title": "Offset（正=過去、負=未來）"},
                    "group_by": {"type": "string", "title": "Group by（選填；各組內獨立 shift）", "x-column-source": "input.data"},
                    "sort_by":  {"type": "string", "title": "Sort by（選填，預設 eventTime）", "x-column-source": "input.data"},
                    "compute_delta": {"type": "boolean", "default": True, "title": "同時輸出 delta 欄位"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.shift_lag:ShiftLagBlockExecutor"},
        },
        {
            "name": "block_rolling_window",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "滑動視窗統計（pandas .rolling(window).<func>()）— 過去 N 筆的聚合值。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「近 5 筆移動平均（smoothing）」→ window=5, func='mean'\n"
                "- ✅ 「近 10 筆 std 作 volatility 指標」→ window=10, func='std'\n"
                "- ✅ 「最高點 rolling max 當 envelope」→ window=N, func='max'\n"
                "- ❌ 指數加權（近期權重大）→ 用 block_ewma（對近期更敏感）\n"
                "- ❌ 只要相鄰差值 → 用 block_delta / block_shift_lag\n"
                "- ❌ Cpk / 統計檢定 → 用 block_cpk / block_hypothesis_test\n"
                "\n"
                "== Params ==\n"
                "column      (string, required) 目標欄位\n"
                "window      (integer, required, default 5, >= 1) 視窗大小\n"
                "func        (string, required, default 'mean') mean / std / min / max / sum / median\n"
                "min_periods (integer, opt, default 1) 最少需幾筆才算（不足填 NaN）\n"
                "group_by    (string, opt) 各組獨立滑動\n"
                "sort_by     (string, opt, 預設 'eventTime') 排序欄位\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe) — 原 df 加 `<column>_rolling_<func>` 欄位\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 輸出欄位名含 func：<column>_rolling_mean / <column>_rolling_std (不是 <column>_rolling)\n"
                "⚠ 首 window-1 筆（當 min_periods=1 時）會用部分資料算；若要嚴格 = NaN，把 min_periods 設成 window\n"
                "⚠ 不排序會得到亂序的 rolling，結果無意義 — 記得確認 sort_by\n"
                "⚠ 跨 group 不會互相借值\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND : column / sort_by / group_by 不存在\n"
                "- INVALID_FUNC     : func 不在 enum\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["column", "window", "func"],
                "properties": {
                    "column":  {"type": "string", "title": "目標欄位", "x-column-source": "input.data"},
                    "window":  {"type": "integer", "minimum": 1, "default": 5, "title": "Window size"},
                    "func":    {"type": "string", "enum": ["mean", "std", "min", "max", "sum", "median"], "default": "mean"},
                    "min_periods": {"type": "integer", "minimum": 1, "default": 1, "title": "min_periods"},
                    "group_by": {"type": "string", "title": "Group by（選填）", "x-column-source": "input.data"},
                    "sort_by":  {"type": "string", "title": "Sort by（選填，預設 eventTime）", "x-column-source": "input.data"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.rolling_window:RollingWindowBlockExecutor"},
        },
        {
            "name": "block_weco_rules",
            "version": "1.0.0",
            "category": "logic",
            "status": "production",
            "description": (
                "== What ==\n"
                "Western Electric / Nelson 控制圖規則（SPC）— Logic Node（triggered + evidence schema）。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「xbar 有任何 Nelson 規則觸發」→ value_column=spc_xbar_chart_value, ucl_column=...\n"
                "- ✅ 「多台機台各自判 SPC」→ group_by=toolID，每組獨立計算 center/sigma\n"
                "- ✅ 要一次偵測多種行為（mean shift + trend + stratification）→ 勾 R1+R2+R3+R5...\n"
                "- ❌ 單純上下界判斷（沒有 σ 概念）→ 用 block_threshold\n"
                "- ❌ 連續 N 次某 bool 為 True（非 SPC）→ 用 block_consecutive_rule\n"
                "- ❌ 只看 1 點越界 OOC → block_threshold（bound_type='both'）更直接\n"
                "\n"
                "== 8 條 Nelson 規則 ==\n"
                "  R1 = 1 點 > 3σ（OOC）\n"
                "  R2 = 連續 9 點同側（mean shift）\n"
                "  R3 = 連續 6 點嚴格上升或下降（systematic trend）\n"
                "  R4 = 連續 14 點 up/down 交替（over-adjustment）\n"
                "  R5 = 3 點中 2 點 > 2σ 同側（early warning）\n"
                "  R6 = 5 點中 4 點 > 1σ 同側（gradual drift）\n"
                "  R7 = 連續 15 點在 ±1σ 內（stratification / sensor stuck）\n"
                "  R8 = 連續 8 點在 ±1σ 外（bimodal distribution）\n"
                "\n"
                "== Params ==\n"
                "value_column  (string, required) 監控指標欄位\n"
                "center_column (string, opt) Center Line 欄位；沒給用 value_column 平均\n"
                "sigma_source  (string, default 'from_ucl_lcl')\n"
                "  from_ucl_lcl — σ = (ucl_column 平均 - center) / 3\n"
                "  from_value   — σ = 該欄位自身的 std\n"
                "  manual       — 使用者給 manual_sigma 數字\n"
                "ucl_column    (string, 當 sigma_source=from_ucl_lcl 時 required)\n"
                "manual_sigma  (number, 當 sigma_source=manual 時 required)\n"
                "rules         (array, default ['R1','R2','R5','R6']) 啟用規則子集\n"
                "group_by      (string, opt) 每組獨立評估\n"
                "sort_by       (string, opt, 預設 'eventTime') 排序欄位\n"
                "\n"
                "== Output (PR-A evidence semantics) ==\n"
                "port: triggered (bool) — 是否有任一 rule 被觸發\n"
                "port: evidence (dataframe) — **全部輸入 rows（按 group+sort_by 排序）**，加欄：\n"
                "  triggered_row   (bool)      — 該筆是否觸發任一 rule\n"
                "  triggered_rules (str)       — 觸發的 rule ids（CSV，e.g. 'R1,R5'）\n"
                "  violation_side  (str|None)  — 'above' / 'below' / None\n"
                "  center, sigma   (number)    — SPC 基線（每 group 一致）\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 忘了指定 ucl_column（預設 sigma_source=from_ucl_lcl）→ σ 算不出來\n"
                "⚠ rules 陣列拼錯（'r1' 小寫、'R9' 不存在）會被忽略或 fail\n"
                "⚠ evidence 是全部 rows，**不是只觸發列**；要篩觸發列 filter(triggered_row==true)\n"
                "⚠ 少於 rule 要求最小 n（e.g. R2 需要 >= 9 點）該 rule 自動不觸發\n"
                "⚠ center / sigma 在每 group 內是常數；group_by 沒給則是全體常數\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND    : value_column / ucl_column / center_column / sort_by 不存在\n"
                "- MISSING_SIGMA       : sigma_source 的對應欄位或 manual_sigma 沒給\n"
                "- INSUFFICIENT_DATA   : 所有 group rows 都不夠任一 rule 最小 n\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [
                {"port": "triggered", "type": "bool"},
                {"port": "evidence", "type": "dataframe"},
            ],
            "param_schema": {
                "type": "object",
                "required": ["value_column"],
                "properties": {
                    "value_column":  {"type": "string", "title": "監控指標欄位", "x-column-source": "input.data"},
                    "center_column": {"type": "string", "title": "Center Line 欄位（選填）", "x-column-source": "input.data"},
                    "sigma_source":  {
                        "type": "string",
                        "enum": ["from_ucl_lcl", "from_value", "manual"],
                        "default": "from_ucl_lcl",
                        "title": "σ 來源",
                    },
                    "ucl_column":    {"type": "string", "title": "UCL 欄位（sigma_source=from_ucl_lcl 時用）", "x-column-source": "input.data"},
                    "manual_sigma":  {"type": "number", "title": "σ 數字（sigma_source=manual 時用）"},
                    "rules": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]},
                        "default": ["R1", "R2", "R5", "R6"],
                        "title": "啟用規則 (Nelson R1..R8；預設 4 條常用)",
                    },
                    "group_by": {"type": "string", "title": "Group by（選填，每組獨立評估）", "x-column-source": "input.data"},
                    "sort_by":  {"type": "string", "title": "Sort by（選填，預設 eventTime）", "x-column-source": "input.data"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.weco_rules:WecoRulesBlockExecutor"},
        },
        {
            "name": "block_unpivot",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "Wide → long 轉換（pandas melt）。把多欄位「攤平」成一個分類欄 + 一個值欄。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「SPC xbar/r/s/p/c 一次分析」→ unpivot 5 個欄位 → group_by=variable 做 groupby_agg\n"
                "- ✅ 「多個 APC param 共用一張 boxplot」→ unpivot APC 欄位後 chart(boxplot, group_by=variable)\n"
                "- ✅ heatmap 要 long format → unpivot 後接 block_chart(heatmap)\n"
                "- ❌ 反向（long → wide）→ 目前沒有 pivot block；要先聚合成 wide 時考慮 groupby_agg + join\n"
                "- ❌ 只合併兩 df 橫向 → 用 block_join\n"
                "\n"
                "== Params ==\n"
                "id_columns    (array, required) 保留的識別欄 (e.g. ['eventTime','toolID'])\n"
                "value_columns (array, required) 要 melt 的欄位清單（e.g. ['spc_xbar_chart_value','spc_r_chart_value']）\n"
                "variable_name (string, default 'variable') 新增「原欄位名」欄名；常改為 'chart_type' / 'metric'\n"
                "value_name    (string, default 'value') 新增「原欄位值」欄名\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe, long format) — columns = id_columns + [variable_name, value_name]\n"
                "row 數 = 原 row 數 × len(value_columns)\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ id_columns 跟 value_columns 不能有重疊；value_columns 內欄位原本會消失\n"
                "⚠ 忘了 value_columns 必須全部同型別（數值）；混型會被 pandas cast\n"
                "⚠ 輸出的 variable 欄值是原欄位名 string，不是 index\n"
                "⚠ row 數會 × len(value_columns)；大寬表 melt 後可能爆量\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND  : id_columns / value_columns 有欄位不存在\n"
                "- OVERLAP_COLUMNS   : id 與 value 集合重疊\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["id_columns", "value_columns"],
                "properties": {
                    "id_columns":    {"type": "array", "items": {"type": "string"}, "title": "保留欄位"},
                    "value_columns": {"type": "array", "items": {"type": "string"}, "title": "要 melt 的欄位"},
                    "variable_name": {"type": "string", "default": "variable", "title": "分類欄名"},
                    "value_name":    {"type": "string", "default": "value", "title": "值欄名"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.unpivot:UnpivotBlockExecutor"},
        },
        {
            "name": "block_spc_long_form",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "Process-History wide → SPC long format reshape (purpose-built).\n"
                "把 process_history 直出的 spc_<chart>_value/_ucl/_lcl/_is_ooc 欄位攤平成長表，\n"
                "downstream 用 group_by=chart_name 一次掃所有 chart。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「站點所有 SPC charts 任一連 N 次 OOC 就告警」→ 經典組合\n"
                "- ✅ 「對每張 chart 各跑一次 regression / cpk」→ groupby chart_name\n"
                "- ❌ 只處理 1 張特定 chart → 直接 filter 那張的欄位即可，不用 reshape\n"
                "- ❌ APC 參數 → 用 block_apc_long_form\n"
                "\n"
                "== Output columns（固定）==\n"
                "eventTime, toolID, lotID, step, spc_status, fdc_classification (passthrough)\n"
                "chart_name (string), value, ucl, lcl, is_ooc (bool)\n"
                "⚠ 欄位**固定叫 chart_name**，不是 chart_type / chart / metric。\n"
                "\n"
                "== 經典 pipeline ==\n"
                "process_history(step=$step) → spc_long_form\n"
                "  → consecutive_rule(flag_column=is_ooc, count=2,\n"
                "                     sort_by=eventTime, group_by=chart_name)\n"
                "  → alert(severity=HIGH)\n"
                "\n"
                "== Errors ==\n"
                "- INVALID_INPUT  : data 不是 DataFrame\n"
                "- NO_SPC_COLUMNS : 上游沒 spc_*_<field> 欄位\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {"type": "object", "properties": {}},
            "output_columns_hint": ["chart_name", "value", "ucl", "lcl", "is_ooc"],
            "implementation": {"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.spc_long_form:SpcLongFormBlockExecutor"},
        },
        {
            "name": "block_apc_long_form",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "Process-History wide → APC long format reshape (purpose-built).\n"
                "把 process_history 直出的 apc_<param> 欄位攤平成長表，downstream 用\n"
                "group_by=param_name 一次處理所有 APC 參數。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「任一 APC 參數連 N 次超過 X」→ apc_long_form → threshold → consecutive_rule\n"
                "- ✅ 「對每個 APC 參數做 boxplot / histogram」→ groupby param_name\n"
                "- ❌ 只看 1 個指定參數 → 直接用該欄位即可\n"
                "- ❌ SPC chart → 用 block_spc_long_form\n"
                "\n"
                "== Output columns（固定）==\n"
                "eventTime, toolID, lotID, step, spc_status, fdc_classification, apc_id (id 欄)\n"
                "param_name (string, 已剝 apc_ 前綴), value\n"
                "⚠ 欄位**固定叫 param_name**，不是 parameter / metric / apc_param。\n"
                "\n"
                "== 經典 pipeline ==\n"
                "process_history(step=$step) → apc_long_form\n"
                "  → threshold(value_column=value, op='>', threshold=100)\n"
                "  → consecutive_rule(flag_column=triggered_row, count=3,\n"
                "                     sort_by=eventTime, group_by=param_name)\n"
                "  → alert(severity=HIGH)\n"
                "\n"
                "== Errors ==\n"
                "- INVALID_INPUT  : data 不是 DataFrame\n"
                "- NO_APC_COLUMNS : 上游沒 apc_<param> 欄位\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {"type": "object", "properties": {}},
            "output_columns_hint": ["param_name", "value"],
            "implementation": {"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.apc_long_form:ApcLongFormBlockExecutor"},
        },
        {
            "name": "block_union",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "兩個 DataFrame 的縱向合併（row-wise concat，pandas concat axis=0）。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「EQP-01 + EQP-02 各拉一次 process_history → 合併一張分析」\n"
                "- ✅ 「歷史 + 最新 events 合併」\n"
                "- ✅ 兩個 logic node 的 evidence 疊加（alternative: block_any_trigger 處理多 evidence 更正式）\n"
                "- ❌ 橫向合併（by key join）→ 用 block_join\n"
                "- ❌ 多個 logic node OR 合併（含 source_port tag）→ 用 block_any_trigger\n"
                "\n"
                "== Input ports ==\n"
                "primary   (dataframe)\n"
                "secondary (dataframe)\n"
                "\n"
                "== Params ==\n"
                "on_schema_mismatch (string, default 'outer') 欄位不符時的處理：\n"
                "  outer     — 聯集欄位，缺值填 null\n"
                "  intersect — 僅保留共同欄位\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe) — primary rows 在前，secondary 在後（不重新索引）\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 兩個 df 沒有共同欄位且用 'intersect' → 輸出空 df\n"
                "⚠ outer 模式缺值會是 NaN，下游數值聚合要注意\n"
                "⚠ 沒有 dedup 邏輯；重複 row 會保留\n"
                "⚠ 型別不同的同名欄會被 pandas cast（常變 object）\n"
                "\n"
                "== Errors ==\n"
                "- EMPTY_AFTER_UNION : intersect 模式下無共同欄位\n"
            ),
            "input_schema": [
                {"port": "primary", "type": "dataframe"},
                {"port": "secondary", "type": "dataframe"},
            ],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "properties": {
                    "on_schema_mismatch": {
                        "type": "string",
                        "enum": ["outer", "intersect"],
                        "default": "outer",
                        "title": "欄位不符時",
                    },
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.union:UnionBlockExecutor"},
        },
        {
            "name": "block_cpk",
            "version": "1.0.0",
            "category": "logic",
            "status": "production",
            "description": (
                "== What ==\n"
                "Process capability 指標：Cp / Cpu / Cpl / Cpk / Pp / Ppk（製程能力分析）。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「這台機台最近 30 天 Cpk 是多少」→ process_history → cpk(value_column, usl, lsl)\n"
                "- ✅ 多機台比較 Cpk → group_by=toolID，每組各算一次\n"
                "- ✅ 單邊規格（只有 USL 或只有 LSL）→ 只給一個 spec，對應的 Cp/Cpu/Cpl 自動算對\n"
                "- ❌ 只想畫分布直方圖 + 鐘形曲線 → 用 block_chart(chart_type='distribution')\n"
                "- ❌ 判斷 OOC 告警 → 用 block_weco_rules（SPC 規則）\n"
                "- ❌ 顯著性檢定 → 用 block_hypothesis_test\n"
                "\n"
                "== Formulas ==\n"
                "  Cp  = (USL - LSL) / (6σ)\n"
                "  Cpu = (USL - μ) / (3σ)\n"
                "  Cpl = (μ - LSL) / (3σ)\n"
                "  Cpk = min(Cpu, Cpl)\n"
                "  Pp / Ppk 在 MVP 等於 Cp / Cpk（短期 = 長期）\n"
                "\n"
                "== Params ==\n"
                "value_column (string, required) 數值欄位\n"
                "usl          (number, opt) Upper Spec Limit\n"
                "lsl          (number, opt) Lower Spec Limit；**usl / lsl 至少給一個**\n"
                "group_by     (string, opt) 各組獨立計算\n"
                "\n"
                "== Output ==\n"
                "port: stats (dataframe) — per group 一列：n / mu / sigma / cp / cpu / cpl / cpk / pp / ppk / usl / lsl / group\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 只給 USL 沒給 LSL 時 Cp / Cpl 會是 NaN（單邊只算得了 Cpu）\n"
                "⚠ σ 用 sample std (ddof=1)；n=1 時整組 NaN\n"
                "⚠ 輸出 port 叫 `stats`，不是 `data`；下游接 chart 記得連 stats port\n"
                "⚠ Pp/Ppk 現為 MVP：等於 Cp/Cpk；未來接入長期資料才有差\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND  : value_column / group_by 不存在\n"
                "- MISSING_SPEC      : usl / lsl 都沒給\n"
                "- INSUFFICIENT_DATA : group 內 < 2 筆（σ 算不出來）\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "stats", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["value_column"],
                "properties": {
                    "value_column": {"type": "string", "x-column-source": "input.data"},
                    "usl":          {"type": "number", "title": "USL (upper spec limit)"},
                    "lsl":          {"type": "number", "title": "LSL (lower spec limit)"},
                    "group_by":     {"type": "string", "title": "Group by (選填)", "x-column-source": "input.data"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.cpk:CpkBlockExecutor"},
        },
        {
            "name": "block_any_trigger",
            "version": "1.0.0",
            "category": "logic",
            "status": "production",
            "description": (
                "== What ==\n"
                "OR 多個 logic node 的 triggered 值 + 合併所有 evidence — Logic Node（triggered + evidence schema）。\n"
                "用於「任一 rule 觸發 → 發單一聚合告警」的場景，避免 alarm fatigue。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「監控 5 張 SPC charts（Xbar/R/S/P/C）任一觸發就告警」→ 5 個 weco_rules → any_trigger → alert\n"
                "- ✅ 「threshold OR consecutive_rule 任一觸發」→ 兩個 logic node 的 triggered → any_trigger\n"
                "- ❌ AND 所有條件才觸發 → 目前沒有 all_trigger block，可用 threshold 組合或自訂 pipeline\n"
                "- ❌ 只要純粹縱向合併兩個 df → 用 block_union（但不會加 source_port tag）\n"
                "- ❌ 橫向合併 → 用 block_join\n"
                "\n"
                "== Input ports ==\n"
                "trigger_1 .. trigger_4  (bool, 最少連一個)\n"
                "evidence_1 .. evidence_4 (dataframe, 選填；與 trigger_N 配對使用，N 對應同數字)\n"
                "\n"
                "== Params ==\n"
                "（無參數；純 OR 合併）\n"
                "\n"
                "== Output (PR-A evidence semantics) ==\n"
                "port: triggered (bool) — 任一 trigger_* 為 true\n"
                "port: evidence (dataframe) — **所有連接 port 的 evidence concat**（不只觸發的，保留完整 audit trail），加欄：\n"
                "  source_port   (str)  — 來自哪個 trigger_N（e.g. 'trigger_1'）\n"
                "  triggered_row (bool) — 該列是否觸發（沿用上游或 port-level bool）\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ trigger_N 跟 evidence_N 要配對（數字對應）；號碼錯會 source_port 錯標\n"
                "⚠ 一個都沒連 → triggered=False + 空 evidence（不 fail，但沒意義）\n"
                "⚠ evidence concat 後欄位 schema 取**聯集**；缺的欄填 NaN\n"
                "⚠ 如果上游 logic node 的 evidence 欄位衝突（型別不同），pandas 會 cast 成 object\n"
                "\n"
                "== Errors ==\n"
                "- SCHEMA_INCOMPATIBLE : evidence concat 欄位型別衝突嚴重（極少發生）\n"
            ),
            "input_schema": [
                {"port": "trigger_1", "type": "bool"},
                {"port": "trigger_2", "type": "bool"},
                {"port": "trigger_3", "type": "bool"},
                {"port": "trigger_4", "type": "bool"},
                {"port": "evidence_1", "type": "dataframe"},
                {"port": "evidence_2", "type": "dataframe"},
                {"port": "evidence_3", "type": "dataframe"},
                {"port": "evidence_4", "type": "dataframe"},
            ],
            "output_schema": [
                {"port": "triggered", "type": "bool"},
                {"port": "evidence", "type": "dataframe"},
            ],
            "param_schema": {"type": "object", "properties": {}},
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.any_trigger:AnyTriggerBlockExecutor"},
        },
        {
            "name": "block_correlation",
            "version": "1.0.0",
            "category": "logic",
            "status": "production",
            "description": (
                "== What ==\n"
                "計算多欄位 pairwise correlation matrix，輸出 **long format**（可直接餵 block_chart(heatmap)）。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「SPC xbar 跟哪個 APC param 相關性最高」→ columns=[spc_xbar_chart_value, apc_rf_power_bias, ...]\n"
                "- ✅ 「DC sensor 之間共線性分析」→ 多個 dc_* 欄位計算\n"
                "- ✅ 直接接 heatmap：chart_type=heatmap, x=col_a, y=col_b, value_column=correlation\n"
                "- ❌ 要單一 x,y 迴歸（含 R²、residual、CI band）→ 用 block_linear_regression\n"
                "- ❌ 類別欄獨立性（chi-square）→ 用 block_hypothesis_test(test_type='chi_square')\n"
                "\n"
                "== Params ==\n"
                "columns (array, required, >= 2) 要納入的數值欄位\n"
                "method  (string, default 'pearson') pearson | spearman | kendall\n"
                "\n"
                "== Output ==\n"
                "port: matrix (dataframe, long) — 每 pair 一列：\n"
                "  col_a       (string)  第一欄名\n"
                "  col_b       (string)  第二欄名\n"
                "  correlation (number)  相關係數 [-1, 1]\n"
                "  p_value     (number)  顯著性\n"
                "  n           (integer) 有效樣本數\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 輸出是 long format（每 pair 一列），不是 wide matrix；heatmap 正好吃 long\n"
                "⚠ columns 必須是**數值欄**；字串欄 pearson 會出錯（spearman/kendall 也要 rankable）\n"
                "⚠ 欄位有 NaN 會被 pairwise drop；n 可能每 pair 不同\n"
                "⚠ 輸出 port 叫 `matrix`，不是 `data`\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND  : columns 有欄位不存在\n"
                "- INSUFFICIENT_DATA : pair 有效樣本 < 3\n"
                "- INVALID_COL_TYPE  : 欄位非數值\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "matrix", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["columns"],
                "properties": {
                    "columns": {"type": "array", "items": {"type": "string"}, "title": "納入欄位"},
                    "method":  {"type": "string", "enum": ["pearson", "spearman", "kendall"], "default": "pearson"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.correlation:CorrelationBlockExecutor"},
        },
        {
            "name": "block_hypothesis_test",
            "version": "1.0.0",
            "category": "logic",
            "status": "production",
            "description": (
                "== What ==\n"
                "常用統計假設檢定：Welch t-test（2 組均值）/ one-way ANOVA（3+ 組均值）/ chi-square independence（類別獨立性）。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「EQP-01 vs EQP-02 的 xbar 均值有顯著差異嗎」→ t_test, value=xbar, group=toolID\n"
                "- ✅ 「三個 recipe 的 APC 均值」→ anova\n"
                "- ✅ 「toolID 跟 OOC 結果有關聯嗎」→ chi_square, group=toolID, target=spc_status\n"
                "- ❌ 想看 pairwise correlation matrix → 用 block_correlation\n"
                "- ❌ 斜率 / 殘差 / CI band → 用 block_linear_regression\n"
                "- ❌ 對均值做 SPC 控制（Cp/Cpk）→ 用 block_cpk\n"
                "\n"
                "== Params ==\n"
                "test_type     (string, required) 't_test' | 'anova' | 'chi_square'\n"
                "value_column  (string, required for t_test / anova) 數值欄位\n"
                "group_column  (string, required) 分組欄位（所有測試都要）\n"
                "target_column (string, required for chi_square) 類別欄位（與 group_column 做列聯）\n"
                "alpha         (number, default 0.05) 顯著水準\n"
                "\n"
                "== Output ==\n"
                "port: stats (dataframe, 1 row) — test / statistic / p_value / significant(bool) + test-specific fields\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ t_test 要求 group_column 剛好 2 組；anova 要 3+ 組；chi_square 不限\n"
                "⚠ Welch t-test 不假設等變異；大部分情況比 Student's t 穩定\n"
                "⚠ significant=True 只代表 p<alpha，不代表實務差異大（還要看 effect size）\n"
                "⚠ 輸出 port 叫 stats，不是 data\n"
                "\n"
                "== Errors ==\n"
                "- INSUFFICIENT_DATA : n < 2 per group\n"
                "- INVALID_INPUT     : group 數對不上 test_type（t_test != 2 / anova < 3）\n"
                "- COLUMN_NOT_FOUND  : value/group/target column 不存在\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "stats", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["test_type", "group_column"],
                "properties": {
                    "test_type":     {"type": "string", "enum": ["t_test", "anova", "chi_square"]},
                    "value_column":  {"type": "string", "x-column-source": "input.data", "title": "數值欄位 (t_test/anova)"},
                    "group_column":  {"type": "string", "x-column-source": "input.data"},
                    "target_column": {"type": "string", "x-column-source": "input.data", "title": "類別欄位 (chi_square)"},
                    "alpha":         {"type": "number", "minimum": 0.001, "maximum": 0.5, "default": 0.05},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.hypothesis_test:HypothesisTestBlockExecutor"},
        },
        {
            "name": "block_ewma",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "Exponentially Weighted Moving Average（指數加權移動平均）。\n"
                "相較 block_rolling_window（固定長度 SMA），EWMA 權重遞減，對近期更敏感。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「追蹤近期 drift（近期權重大）」→ alpha=0.3 會明顯響應最新幾筆\n"
                "- ✅ 建立 EWMA control chart：以 ewma 為 y，center±σ 為 bound\n"
                "- ✅ 去 noise 時想保留趨勢近期反應 → 比 SMA 優\n"
                "- ❌ 想要嚴格 N 筆視窗 → 用 block_rolling_window（SMA）\n"
                "- ❌ 相鄰差值 / trend bool → 用 block_delta\n"
                "- ❌ N 筆前的絕對值 → 用 block_shift_lag\n"
                "\n"
                "== Params ==\n"
                "value_column (string, required) 數值欄位\n"
                "alpha        (number, required, 0 < α < 1, default 0.2) 平滑係數；α 越大越響應近期\n"
                "sort_by      (string, required) 排序欄位（e.g. eventTime）\n"
                "group_by     (string, opt) 各組獨立 EWMA\n"
                "adjust       (bool, default False) 傳給 pandas .ewm(adjust=)；False 用遞推公式\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe) — 原 df 加 `<value_column>_ewma` 欄位\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ alpha 極端（> 0.9）幾乎等於原值；極小（< 0.05）幾乎不動\n"
                "⚠ sort_by 必填，亂序會得到錯誤 EWMA\n"
                "⚠ 首筆值 = 原 value（初始化），不是 NaN\n"
                "⚠ group_by 有給時跨組不借值；每組獨立初始化\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND : value/sort/group column 不存在\n"
                "- INVALID_ALPHA    : alpha 不在 (0, 1)\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["value_column", "alpha", "sort_by"],
                "properties": {
                    "value_column": {"type": "string", "x-column-source": "input.data"},
                    "alpha":        {"type": "number", "minimum": 0.001, "maximum": 0.999, "default": 0.2, "title": "平滑係數 α"},
                    "sort_by":      {"type": "string", "x-column-source": "input.data"},
                    "group_by":     {"type": "string", "title": "Group by (選填)", "x-column-source": "input.data"},
                    "adjust":       {"type": "boolean", "default": False},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.ewma:EwmaBlockExecutor"},
        },
        {
            "name": "block_mcp_call",
            "version": "1.0.0",
            "category": "source",
            "status": "production",
            "description": (
                "== What ==\n"
                "通用 MCP 呼叫器。從 mcp_definitions 表讀 MCP 的 api_config（endpoint_url / method / headers），\n"
                "帶 args 去 GET 或 POST，回傳 DataFrame。**單次** call，不 foreach。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 呼叫**沒有專用 block** 的 MCP：list_tools / get_alarm_list / get_tool_status / get_process_summary\n"
                "- ✅ 快速 aggregate 類 API（比 flatten 全表再聚合省）\n"
                "- ❌ `get_process_info` → **用 block_process_history**（它懂 flatten 邏輯 + SPC 欄位展開）\n"
                "- ❌ 每 row 呼叫一次（for-each enrichment）→ 用 block_mcp_foreach\n"
                "- ❌ MCP 沒註冊在 mcp_definitions → MCP_NOT_FOUND（要先 seed）\n"
                "\n"
                "== Params ==\n"
                "mcp_name (string, required) MCP 名字（必須在 mcp_definitions 註冊；動態從 DB 讀 description）\n"
                "args     (object, opt) 丟給 MCP 的 query params / body；形狀看 MCP input_schema\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe) — 自動從回傳 JSON 抽 list（依序檢查鍵：events / dataset / items / data / records / rows）；\n"
                "都沒有則把整個回傳當單筆 row。欄位為 MCP 回傳 JSON 的 keys（每個 obj 一 row）。\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 要查 process 資料時優先用 block_process_history，它有 flatten + SPC 欄展開；mcp_call 只給 raw JSON 結構\n"
                "⚠ args 是 object（dict），不是 string；MCP 各自的 input_schema 不同，要查 mcp_definitions\n"
                "⚠ 回傳沒 list 鍵時會變成 1 row 的 wide df；大型 nested dict 需要額外 parse\n"
                "⚠ 不同 MCP 回傳 schema 不同；下游 pipeline 要跟著 MCP 改而改\n"
                "\n"
                "== Errors ==\n"
                "- MCP_NOT_FOUND      : mcp_name 沒註冊\n"
                "- INVALID_MCP_CONFIG : api_config 缺 endpoint_url\n"
                "- MCP_HTTP_ERROR     : MCP 回 4xx/5xx\n"
                "- MCP_UNREACHABLE    : 網路不通\n"
            ),
            "input_schema": [],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["mcp_name"],
                "properties": {
                    "mcp_name": {"type": "string", "title": "MCP 名稱"},
                    "args":     {"type": "object", "title": "呼叫參數 (object)"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.mcp_call:McpCallBlockExecutor"},
            "output_columns_hint": [
                {"name": "<dynamic>", "type": "object", "description": "欄位取決於 MCP 的回傳結構；若要查 process 資料優先用 block_process_history（已 flatten）。對於 list_tools / get_alarm_list 等簡單回傳，每個回傳 object 的 key 會成為一個 column"},
            ],
        },
        {
            "name": "block_linear_regression",
            "version": "1.0.0",
            "category": "logic",
            "status": "production",
            "description": (
                "== What ==\n"
                "OLS 線性回歸 y = slope * x + intercept；支援 group_by 分組（each group 一條 fit）。\n"
                "同時輸出統計量、predicted/residual、信賴區間 band。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「SPC xbar 跟 APC rf_power_bias 有線性關係嗎」→ x=apc_rf_power_bias, y=spc_xbar_chart_value\n"
                "- ✅ 「每台機台自己的趨勢線」→ group_by=toolID\n"
                "- ✅ 要畫 scatter + fit line + CI band → data port 接 chart(scatter)、ci port overlay\n"
                "- ❌ 純 pairwise 相關性（多欄位 matrix）→ 用 block_correlation\n"
                "- ❌ t-test / ANOVA / chi-square → 用 block_hypothesis_test\n"
                "- ❌ 非線性關係 → 目前沒有 polynomial / GLM block\n"
                "\n"
                "== Params ==\n"
                "x_column   (string, required) 自變數\n"
                "y_column   (string, required) 應變數\n"
                "group_by   (string, opt) 每組獨立 fit\n"
                "confidence (number, default 0.95, range 0.5–0.999) CI 水準\n"
                "\n"
                "== Output ports ==\n"
                "stats (dataframe) — per-group row: slope / intercept / r_squared / p_value / n / stderr / group\n"
                "data  (dataframe) — 原 df + `<y>_pred` + `<y>_residual` + group（可餵 chart(scatter)）\n"
                "ci    (dataframe) — 密集網格：x / pred / ci_lower / ci_upper / group（畫信賴區間帶）\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ x_column 若是 eventTime（ISO string）會被自動轉 epoch seconds；slope 是對 epoch 秒的斜率\n"
                "⚠ 三個 port 可同時輸出；接多個下游時只連要的 port\n"
                "⚠ group_by 會讓 stats row 數 = group 數；無 group 則 1 row\n"
                "⚠ x variance=0（所有 x 一樣）→ INSUFFICIENT_DATA，slope 無意義\n"
                "⚠ r_squared 高不代表關係顯著；還要看 p_value\n"
                "\n"
                "== Errors ==\n"
                "- INSUFFICIENT_DATA : n < 3 或 x variance = 0\n"
                "- COLUMN_NOT_FOUND  : x / y / group column 不存在\n"
                "- INVALID_TYPE      : column 非數值（eventTime 會自動轉）\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [
                {"port": "stats", "type": "dataframe"},
                {"port": "data", "type": "dataframe"},
                {"port": "ci", "type": "dataframe"},
            ],
            "param_schema": {
                "type": "object",
                "required": ["x_column", "y_column"],
                "properties": {
                    "x_column":   {"type": "string", "x-column-source": "input.data"},
                    "y_column":   {"type": "string", "x-column-source": "input.data"},
                    "group_by":   {"type": "string", "title": "Group by (選填)", "x-column-source": "input.data"},
                    "confidence": {"type": "number", "minimum": 0.5, "maximum": 0.999, "default": 0.95, "title": "CI 水準 (0–1)"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.linear_regression:LinearRegressionBlockExecutor"},
        },
        {
            "name": "block_histogram",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "計算數值欄位的 histogram（等寬 bin 分布）+ 基本統計（n / mu / sigma / skewness）。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 自訂下游處理 bin 資料（e.g. 找 mode、自製 overlay 圖）\n"
                "- ✅ 拿 per-group 的 μ/σ/skewness 做下游 logic\n"
                "- ❌ **只想畫常態分佈圖（鐘形 + σ 線）→ 直接用 block_chart(chart_type='distribution')**，不用先 histogram\n"
                "- ❌ 製程能力 → 用 block_cpk\n"
                "- ❌ 均值假設檢定 → 用 block_hypothesis_test\n"
                "\n"
                "== Params ==\n"
                "value_column (string, required) 數值欄位\n"
                "bins         (integer, default 20, min 2) 等寬 bin 數\n"
                "group_by     (string, opt) 各組獨立計算\n"
                "\n"
                "== Output ports ==\n"
                "data  (dataframe) — group / bin_left / bin_right / bin_center / count / density\n"
                "stats (dataframe) — group / n / mu / sigma / skewness\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ 輸出 bin 是等寬；要 log-scale 自己先 log 再餵\n"
                "⚠ density = count / (n * bin_width)，才讓多組可比（count 直接比會被 n 稀釋）\n"
                "⚠ 畫鐘形分布圖不用這個 block；chart(distribution) 自己會 bin\n"
                "⚠ 兩個 port：data（bin 列）、stats（summary）；下游只接要的 port\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND  : value/group column 不存在\n"
                "- INSUFFICIENT_DATA : group 少於 2 筆\n"
                "- INVALID_VALUE_TYPE: 非數值欄\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [
                {"port": "data", "type": "dataframe"},
                {"port": "stats", "type": "dataframe"},
            ],
            "param_schema": {
                "type": "object",
                "required": ["value_column"],
                "properties": {
                    "value_column": {"type": "string", "x-column-source": "input.data"},
                    "bins":         {"type": "integer", "minimum": 2, "default": 20, "title": "Bin 數"},
                    "group_by":     {"type": "string", "title": "Group by (選填)", "x-column-source": "input.data"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.histogram:HistogramBlockExecutor"},
        },
        {
            "name": "block_sort",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "多欄排序 + optional top-N cap。用於 ranking / leaderboard 場景。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 「OOC 最多的 3 台機台」→ groupby_agg count → sort(desc) + limit=3\n"
                "- ✅ 「按 eventTime asc 重排」→ columns=[{column:'eventTime', order:'asc'}]\n"
                "- ✅ 多欄排序：先按 toolID asc 再按 eventTime desc\n"
                "- ❌ 需要 is_rising / lag / delta → 用 block_delta / block_shift_lag（那些內含 sort）\n"
                "- ❌ 過濾 rows（非排序取 top） → 用 block_filter\n"
                "\n"
                "== Params ==\n"
                "columns (array, required) list of {column, order='asc'|'desc'}\n"
                "  e.g. [{'column':'ooc_count','order':'desc'}]\n"
                "  e.g. [{'column':'toolID','order':'asc'}, {'column':'eventTime','order':'desc'}]\n"
                "limit   (integer, opt, >= 1) 保留前 N 列\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe) — 排序後的 df；欄位不變，有 limit 則保留前 N 列\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ columns 是 list of objects，不是 list of strings\n"
                "⚠ order 拼錯（'descending' / 'DESC'）會被預設成 'asc'\n"
                "⚠ limit 不是 top；是 head(N) — 要 top 請先 desc 排序再 limit\n"
                "⚠ NaN 預設排到最後（pandas 行為）\n"
                "\n"
                "== Errors ==\n"
                "- COLUMN_NOT_FOUND : columns 有欄位不存在\n"
                "- INVALID_SORT_SPEC: columns 結構不對（缺 column key）\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["columns"],
                "properties": {
                    "columns": {
                        "type": "array",
                        "title": "排序欄位 (list of {column, order})",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "order":  {"type": "string", "enum": ["asc", "desc"], "default": "asc"},
                            },
                        },
                    },
                    "limit":   {"type": "integer", "minimum": 1, "title": "Top-N (選填)"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.sort:SortBlockExecutor"},
        },
        {
            "name": "block_alert",
            "version": "1.0.0",
            "category": "output",
            "status": "production",
            "description": (
                "== What ==\n"
                "當上游 Logic Node 觸發時，包裝成一筆告警 record。**不負責呈現 evidence**；\n"
                "Evidence 呈現由 Canvas 從 Logic Node 的 evidence port 直接展示。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 任何「有 triggered+evidence port 的 Logic Node」下游要發告警\n"
                "- ✅ 多條 rule OR 後統一告警：logic_nodes → any_trigger → alert\n"
                "- ❌ 只想顯示資料 / 畫圖 → 用 block_chart / block_data_view\n"
                "- ❌ 上游不是 Logic Node（沒 triggered port）→ 接不起來\n"
                "- ❌ 想要多筆告警（per-row alert）→ 本 block 是 single aggregated alert\n"
                "\n"
                "== Connect ==\n"
                "input.triggered ← upstream logic_node.triggered (bool)\n"
                "input.evidence  ← upstream logic_node.evidence  (dataframe)\n"
                "上游必須是 Logic Node（block_threshold / block_consecutive_rule / block_weco_rules / block_any_trigger / block_cpk / block_correlation / block_hypothesis_test / block_linear_regression）\n"
                "\n"
                "== Params ==\n"
                "severity         (string, required) LOW | MEDIUM | HIGH | CRITICAL\n"
                "title_template   (string, opt)      支援 {column_name}（從 evidence 第一筆取）及 {evidence_count}\n"
                "message_template (string, opt)      同上\n"
                "\n"
                "== Behaviour ==\n"
                "- triggered=False → output.alert 為空 DF（不做事）\n"
                "- triggered=True  → output.alert 一筆 row：severity / title / message / evidence_count / first_event_time / last_event_time / emitted_at\n"
                "\n"
                "== Output ==\n"
                "port: alert (dataframe) — 0 或 1 row\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ template 用 `{column}` 引用 evidence 欄位，拼錯欄位名會保留 raw placeholder\n"
                "⚠ evidence 沒 eventTime 欄時，first_event_time / last_event_time 會是 None\n"
                "⚠ 不 triggered 時 output 是空 df；下游計 row 數要注意\n"
                "⚠ 別把 Logic Node 的 triggered 連到 chart；chart 要 evidence（dataframe）\n"
                "\n"
                "== Errors ==\n"
                "- INVALID_TEMPLATE  : template 語法錯\n"
                "- MISSING_UPSTREAM  : triggered / evidence port 沒連\n"
            ),
            "input_schema": [
                {"port": "triggered", "type": "bool"},
                {"port": "evidence", "type": "dataframe"},
            ],
            "output_schema": [{"port": "alert", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["severity"],
                "properties": {
                    "severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
                    "title_template": {"type": "string"},
                    "message_template": {"type": "string"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.alert:AlertBlockExecutor"},
        },
        {
            "name": "block_data_view",
            "version": "1.0.0",
            "category": "output",
            "status": "production",
            "description": (
                "== What ==\n"
                "把上游 DataFrame **釘在 Pipeline Results 的資料視圖區**，讓人類可以在執行結果面板\n"
                "看到任何中間步驟的資料，不需要配置 chart_type/x/y 等圖表參數。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ Diagnostic Rule 要把「最近 N 筆 process 資料」當輸出秀給工程師\n"
                "- ✅ 想 audit 某個中間 node 的輸出（接一條邊過去即可，純顯示用）\n"
                "- ✅ 比 block_chart(chart_type='table') **更輕量**：沒有 chart schema 的包袱\n"
                "- ❌ 要視覺化（line/bar/heatmap 等）→ 用 block_chart\n"
                "- ❌ 要發告警 record → 用 block_alert\n"
                "- ❌ 純中間計算（沒要給人看）→ 不需要 data_view\n"
                "\n"
                "== Multiple views ==\n"
                "同一 pipeline 可以放多個 block_data_view（例如一個秀原始 5 筆 + 一個秀 Filter 後的 3 筆）。\n"
                "用 `sequence` 參數控制呈現順序（ascending；未指定則以 canvas position.x 為 tiebreak）。\n"
                "\n"
                "== Params ==\n"
                "title       (string, opt, default 'Data View') 標題\n"
                "description (string, opt) 副標\n"
                "columns     (array, opt) 要顯示的欄位清單；未給則全部\n"
                "max_rows    (integer, opt, default 200, min 1) 最多顯示列數\n"
                "sequence    (integer, opt) 多視圖時的排序（ascending）\n"
                "\n"
                "== Output ==\n"
                "port: data_view (dict) — Pipeline Results 自動收集到 result_summary.data_views；\n"
                "前端以表格呈現（含 title + description + columns + rows）\n"
                "\n"
                "== Common mistakes ==\n"
                "⚠ columns 指定不存在的欄位會被忽略（不 fail）\n"
                "⚠ max_rows 預設 200；大型 df 先 filter/limit 再接，避免 UI 卡頓\n"
                "⚠ sequence 整數非連續也 OK；只看相對大小決定順序\n"
                "⚠ 輸出 port 是 `data_view`（dict），不是 dataframe；不能當下游 dataframe 輸入\n"
                "\n"
                "== Errors ==\n"
                "（鮮少 fail，主要是上游無 data 才空表）\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data_view", "type": "dict"}],
            "param_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "title": "標題（預設 'Data View'）"},
                    "description": {"type": "string", "title": "副標（選填）"},
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "title": "要顯示的欄位（未指定則全部）",
                    },
                    "max_rows": {"type": "integer", "minimum": 1, "default": 200, "title": "最多顯示列數（預設 200）"},
                    "sequence": {"type": "integer", "title": "多視圖時的排序（ascending）"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.data_view:DataViewBlockExecutor"},
        },
        {
            "name": "block_compute",
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": (
                "== What ==\n"
                "對上游 dataframe **加一個衍生 column**，值由 expression tree 算出。\n"
                "這是「純值運算」的 primitive — 給下游 rolling_window / threshold / groupby\n"
                "一個明確的 numeric / boolean 欄位可吃。\n"
                "\n"
                "== When to use ==\n"
                "- ✅ 從 `spc_status` 衍生 `spc_is_any_ooc = (spc_status != 'PASS') as int` 讓 rolling_sum 可用\n"
                "- ✅ 合併多個 boolean column：`is_any_spc_ooc = xbar_ooc OR r_ooc OR s_ooc`\n"
                "- ✅ 將字串 cast 成數值 / 反之：`v_num = as_float(v_str)`\n"
                "- ❌ 做 group 統計 → 用 block_groupby_agg\n"
                "- ❌ 複雜 regex / apply → 超出本 block 能力\n"
                "\n"
                "== Params ==\n"
                "column      (string, 必填) 新欄位名稱\n"
                "expression  (object, 必填) expression tree，節點三種：\n"
                "  literal            42, 'PASS', true, null, [..]\n"
                "  column ref         {column: 'spc_status'}\n"
                "  op node            {op: '<name>', operands: [...]}\n"
                "\n"
                "== Ops ==\n"
                "Comparison: eq ne gt gte lt lte\n"
                "Logical:    and or not\n"
                "Set:        in not_in     (第二參數為 list)\n"
                "Arithmetic: add sub mul div\n"
                "Cast:       as_int as_float as_str as_bool\n"
                "Null:       coalesce is_null is_not_null\n"
                "\n"
                "== Output ==\n"
                "port: data (dataframe)    原 df + 一個新 column\n"
                "\n"
                "== Example ==\n"
                "加 `spc_is_any_ooc`：\n"
                "  {\n"
                "    \"column\": \"spc_is_any_ooc\",\n"
                "    \"expression\": {\n"
                "      \"op\": \"as_int\",\n"
                "      \"operands\": [{\n"
                "        \"op\": \"ne\",\n"
                "        \"operands\": [{\"column\": \"spc_status\"}, \"PASS\"]\n"
                "      }]\n"
                "    }\n"
                "  }\n"
            ),
            "input_schema": [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": {
                "type": "object",
                "required": ["column", "expression"],
                "properties": {
                    "column": {"type": "string", "title": "新欄位名稱"},
                    "expression": {"type": "object", "title": "Expression tree"},
                },
            },
            "implementation": {"type": "python", "ref": "app.services.pipeline_builder.blocks.compute:ComputeBlockExecutor"},
        },
    ]


async def _deprecate_renamed_blocks(db: AsyncSession) -> None:
    """Mark legacy-named blocks as deprecated so they stop appearing in the catalog."""
    renamed = [("block_mcp_fetch", "1.0.0")]  # renamed to block_process_history
    repo = BlockRepository(db)
    for name, version in renamed:
        existing = await repo.get_by_name_version(name, version)
        if existing is not None and existing.status != "deprecated":
            existing.status = "deprecated"
            await db.flush()
            logger.info("Pipeline Builder: deprecated legacy block %s@%s", name, version)


async def seed_phase1_blocks(db: AsyncSession) -> int:
    """Upsert Phase-1 standard blocks. Returns count of blocks seeded."""
    await _deprecate_renamed_blocks(db)
    from python_ai_sidecar.pipeline_builder.seed_examples import examples_by_name
    repo = BlockRepository(db)
    specs = _blocks()
    examples_map = examples_by_name()
    for spec in specs:
        examples = examples_map.get(spec["name"], [])
        # Split optional field out of spec to avoid duplicate kwargs in upsert
        out_cols_hint = spec.pop("output_columns_hint", None)
        await repo.upsert(**spec, examples=examples, output_columns_hint=out_cols_hint)
    await db.commit()
    logger.info("Pipeline Builder: seeded %d standard blocks", len(specs))
    return len(specs)
