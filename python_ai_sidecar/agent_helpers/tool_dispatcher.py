"""Tool Dispatcher — executes Anthropic tool_use blocks via internal API calls.

Each tool maps to an existing FastAPI endpoint or service method.
Tools are also defined here as Anthropic-compatible JSON schemas.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from python_ai_sidecar.agent_helpers._model_stubs import MCPDefinitionModel
from python_ai_sidecar.agent_helpers.agent_memory_service import AgentMemoryService

logger = logging.getLogger(__name__)


# ── Tool Definitions (Anthropic SDK format) ────────────────────────────────

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "confirm_pipeline_intent",
        "description": (
            "**chat mode 與 builder mode 都適用** — 遇到模糊 prompt 時，\n"
            "先把你「打算建什麼」用結構化方式寫下來，讓 user 點 ✅ 確認再 build，\n"
            "避免猜錯方向白費一輪。\n"
            "\n"
            "## 什麼算模糊（任一條件成立 → 必先呼本工具，不要直接 build_pipeline_live）\n"
            "  1. 含模糊指代：「該機台」「該站」「這個 lot」「最近一次」\n"
            "  2. 跨領域：同時提多種 metric 來源（SPC + APC + FDC）卻沒指定要看哪一種\n"
            "  3. 動詞模糊：「分析一下」「確認」「看看」（用戶沒指定要做什麼產出）\n"
            "  4. **呈現方式不明：用戶沒明確說 chart / table / alert / scalar**\n"
            "     - 「各站點 OOC rate」→ 模糊（table？bar chart？pareto？time-series？user 沒講）\n"
            "     - 「OOC 趨勢」→ 模糊（單線？多 step 多線？per-tool？）\n"
            "     - 「比較 A 和 B」→ 模糊（並排 chart？diff table？scatter？）\n"
            "\n"
            "## 什麼算具體（可直接 build_pipeline_live，不用本工具）\n"
            "  - 「把 alert severity 改 HIGH」（精確動作）\n"
            "  - 「檢查 STEP_001 SPC charts 連 2 次 OOC 告警」（精確 input + 規則 + 輸出）\n"
            "  - 「加一張 EQP-01 xbar trend chart」（精確 metric + 圖表）\n"
            "  - 「列表顯示 EQP-07 各站點 OOC rate」（用戶說了「列表」=表格）\n"
            "\n"
            "## 自我檢查（呼 build_pipeline_live 前先想一秒）\n"
            "你能用一句話寫出 **inputs + logic + presentation** 全部具體嗎？\n"
            "  能 → 直接 build_pipeline_live\n"
            "  不能（presentation 是你猜的）→ 先 confirm_pipeline_intent\n"
            "\n"
            "本 tool 不真的建 pipeline — 只 emit 一張 design-intent 卡片給 user 看。User\n"
            "點 ✅ 後系統會自動發 follow-up `[intent_confirmed:<id>]` 訊息給你，那時你才呼\n"
            "build_pipeline_live。User 點 ✏️ 改、或 ❌ 取消，會自然中斷流程。"
        ),
        "input_schema": {
            "type": "object",
            "required": ["inputs", "logic", "presentation"],
            "properties": {
                "inputs": {
                    "type": "array",
                    "description": "你判斷 pipeline 要拿哪些 input 的清單。每項一個物件。",
                    "items": {
                        "type": "object",
                        "required": ["name", "source"],
                        "properties": {
                            "name": {"type": "string", "description": "input 名（e.g. equipment_id, step）"},
                            "source": {
                                "type": "string",
                                "enum": ["user_input", "event_payload", "literal"],
                                "description": "user_input=希望使用者填；event_payload=auto-patrol 從事件帶來；literal=寫死",
                            },
                            "rationale": {"type": "string", "description": "為何要這個 input（一句話）"},
                        },
                    },
                },
                "logic": {
                    "type": "string",
                    "description": "1-2 句白話描述 pipeline 在算什麼（不寫 block name）",
                },
                "presentation": {
                    "type": "string",
                    "enum": ["alert", "chart", "table", "scalar", "mixed"],
                    "description": "輸出形式 — alert=告警/chart=圖表/table=表格/scalar=單一數值/mixed=多種",
                },
                "alternatives": {
                    "type": "array",
                    "description": "0-2 個你想到的『也可能是這樣解讀』，給 user 對照（選填）",
                    "items": {
                        "type": "object",
                        "required": ["summary"],
                        "properties": {
                            "summary": {"type": "string", "description": "另一種解讀（一句話）"},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "build_pipeline_live",
        "description": (
            "Phase 5-UX-6: 為資料問題動手建一條 pipeline，逐步把 node 拖到 canvas 上。\n"
            "\n"
            "使用時機：\n"
            "  - 使用者問「EQP-01 最近 50 次 SPC xbar 趨勢」「比較 apc_etch_time_offset 跟 spc_xbar」等需要 pipeline 的分析\n"
            "  - `search_published_skills` 找不到符合的已發佈 Skill 時\n"
            "\n"
            "這不是一次性輸出 pipeline_json — 你只要描述**目標**，系統會啟動 Glass Box\n"
            "builder sub-agent，它會一個個呼叫 `add_node` / `connect` / `set_param` 工具把\n"
            "pipeline 建起來並跑。過程在 canvas overlay 上即時呈現給使用者看。\n"
            "\n"
            "輸入：\n"
            "  - goal (必填) — 自然語言描述要建什麼 pipeline，e.g. 「EQP-07 最近 100 次\n"
            "    process 的 xbar_chart trend，配對 apc_etch_time_offset 做線性回歸」\n"
            "  - notes (選填) — 給 sub-agent 的補充 context（已知機台/批次 filter 等）\n"
            "\n"
            "這個工具回傳：`{pipeline_json, summary, node_count, run_status}`，你拿到後\n"
            "用人話向使用者總結做了什麼、結果如何。詳細圖表/資料表已在 canvas overlay\n"
            "自動 render 給使用者，不用你重複描述。"
        ),
        "input_schema": {
            "type": "object",
            "required": ["goal"],
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "要建的 pipeline 的自然語言說明（越具體越好）",
                },
                "notes": {
                    "type": "string",
                    "description": "選填的額外 context，例如已知的機台/批次/時間範圍 filter",
                },
                "base_pipeline_id": {
                    "type": "integer",
                    "description": "選填。若使用者正在改某條既有 pipeline，傳它的 id，sub-agent 會從當前狀態接續編輯",
                },
            },
        },
    },
    {
        "name": "propose_pipeline_patch",
        "description": (
            "Phase 5-UX-5 (Copilot): 提出對目前畫布 pipeline 的結構性修改提案。\n"
            "\n"
            "使用時機：\n"
            "  - 使用者正在 /admin/pipeline-builder 編輯一條 pipeline，提出修改需求\n"
            "    （e.g. 『加一個 Rolling Window 檢查連續 3 次 OOC』）\n"
            "  - 你 *不要* 直接改 canvas；而是回傳 patch 提案，前端會顯示\n"
            "    『套用到 Canvas / 不用了』兩個按鈕，等使用者確認後才真正改動\n"
            "\n"
            "Patch ops 支援：\n"
            "  - insert_after  : 在某個既有 node 之後插入新 node + 連邊\n"
            "  - insert_before : 在某個既有 node 之前插入新 node + 連邊\n"
            "  - update_params : 就地改既有 node 的 params\n"
            "  - delete_node   : 刪除既有 node（連帶邊會被前端清乾淨）\n"
            "  - connect_edge  : 新增一條邊（通常配 insert 用）\n"
            "\n"
            "每個 patch 裡的 block_id 必須是 blocks catalog 裡的合法值（參考 prompt 裡的\n"
            "『Available Blocks』列表）。Params 結構要符合該 block 的 param_schema。\n"
            "若你需要查既有 canvas，對話 context 中會有當前 pipeline_json 的摘要。"
        ),
        "input_schema": {
            "type": "object",
            "required": ["patches", "reason"],
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "1-2 句話人類可讀的說明：你打算做什麼改變、為什麼（使用者會看到）",
                },
                "patches": {
                    "type": "array",
                    "description": "List of structural patches to propose; applied in order by frontend if user accepts",
                    "items": {
                        "type": "object",
                        "required": ["op"],
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": ["insert_after", "insert_before", "update_params", "delete_node", "connect_edge"],
                            },
                            "anchor_node_id": {"type": "string", "description": "Existing node id, used by insert_after / insert_before"},
                            "node_id": {"type": "string", "description": "Existing node id, used by update_params / delete_node"},
                            "new_node_id": {"type": "string", "description": "Desired id for the newly-inserted node (insert_*)"},
                            "block_id": {"type": "string", "description": "Block name, e.g. block_rolling_window (insert_*)"},
                            "block_version": {"type": "string", "default": "1.0.0"},
                            "params": {"type": "object", "description": "Block params for insert_* or update_params"},
                            "from": {
                                "type": "object",
                                "description": "connect_edge source: {node, port}",
                                "properties": {"node": {"type": "string"}, "port": {"type": "string"}},
                            },
                            "to": {
                                "type": "object",
                                "description": "connect_edge sink: {node, port}",
                                "properties": {"node": {"type": "string"}, "port": {"type": "string"}},
                            },
                        },
                    },
                },
            },
        },
    },
    {
        "name": "search_published_skills",
        "description": (
            "PR-C: 搜尋已發佈的 Skills（pb_published_skills，kind=skill 的 pipelines）。\n"
            "當使用者描述一個查案需求時，先呼叫這個工具看有沒有現成 skill 可用，\n"
            "再用 invoke_published_skill 執行。回傳：slug / use_case / when_to_use / inputs_schema。\n"
            "以簡體或中文/英文關鍵字搜尋，會 match use_case + name + tags 欄位。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然語言查詢（e.g. 'xbar OOC' / 'recipe drift')"},
                "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "invoke_published_skill",
        "description": (
            "PR-C: 執行一個已發佈的 Skill（by slug）。會回傳統一的\n"
            "{triggered, evidence, charts} 契約；charts 直接可餵給前端 Data Explorer 渲染。\n"
            "slug 從 search_published_skills 取得；inputs 必須符合該 skill 的 inputs_schema。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Skill 的 stable identifier"},
                "inputs": {"type": "object", "description": "Pipeline inputs（name→value）"},
            },
            "required": ["slug", "inputs"],
        },
    },
    {
        "name": "execute_skill",
        "description": (
            "執行一個已登錄的診斷技能 (Skill)，自動撈取資料並執行診斷。"
            "回傳 llm_readable_data (含 status/diagnosis_message/problematic_targets)。"
            "⚠️ 只能讀取 llm_readable_data，嚴禁解析 ui_render_payload。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "integer", "description": "要執行的 Skill ID"},
                "params": {
                    "type": "object",
                    "description": "Skill 所需的輸入參數，例如 {lot_id, tool_id, operation_number}",
                },
            },
            "required": ["skill_id", "params"],
        },
    },
    {
        "name": "query_data",
        "description": (
            "查詢任何製程資料的統一工具。所有資料查詢都用這個。\n"
            "\n"
            "== data_source 選擇（必填）==\n"
            "從 <mcp_catalog>（系統 prompt 動態注入）裡挑 `name` 欄位填入。\n"
            "挑選原則：讀每個 MCP 的 description（用途 / 回傳欄位 / 典型問題都寫在裡面），\n"
            "和使用者問題語意 match 度最高的那個 MCP。\n"
            "**不要憑記憶猜 MCP 名稱** — catalog 是唯一真相，新 MCP 隨時會加。\n"
            "\n"
            "== 回傳 ==\n"
            "扁平化的 process events 會帶 metadata（total_events, ooc_count, ooc_rate,\n"
            "ooc_by_step, ooc_by_tool）；其他 MCP 回原始 JSON。根據回傳的數據用文字\n"
            "回答使用者的問題。\n"
            "\n"
            "== visualization_hint（可選）==\n"
            "使用者明確要看圖/趨勢/chart 時才加，前端自動渲染 Data Explorer：\n"
            '  {"data_source": "spc_data"} — 所有 SPC charts\n'
            '  {"data_source": "spc_data", "filter": {"chart_type": "xbar_chart"}} — 只看 xbar\n'
            '  {"data_source": "apc_data", "filter": {"param_name": "etch_time_offset"}} — APC 單參數\n'
            '  {"data_source": "overlay", "left": {"dataset":"spc_data","field":"value","filter":{"chart_type":"xbar_chart"}}, "right": {"dataset":"apc_data","field":"value","filter":{"param_name":"rf_power_bias"}}} — 雙軸疊圖\n'
            "不給 hint = 純文字回答，不開圖表。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data_source": {
                    "type": "string",
                    "description": "MCP 名稱 — 從 <mcp_catalog> 的 name 欄位選一個",
                },
                "params": {
                    "type": "object",
                    "description": "查詢參數，如 {equipment_id: 'EQP-01', since: '24h'}",
                },
                "visualization_hint": {
                    "type": "object",
                    "description": "可選。告訴前端要顯示什麼圖表。不給 = 純文字回答。",
                },
            },
            "required": ["data_source", "params"],
        },
    },
    {
        "name": "execute_mcp",
        "description": (
            "（內部工具）直接查詢底層資料源，回傳 raw data。"
            "⚠️ 優先使用 query_data — 它會自動扁平化資料並產生互動圖表。"
            "execute_mcp 只在 query_data 不支援的特殊場景使用。"
            "mcp_name 必填，填入 <mcp_catalog> 中的 name 欄位。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mcp_name": {"type": "string", "description": "MCP 名稱"},
                "params": {"type": "object", "description": "MCP 輸入參數"},
            },
            "required": ["mcp_name", "params"],
        },
    },
    {
        "name": "list_skills",
        "description": "列出所有 public Skills 及其 skill_id、名稱、描述和所需參數。用於了解有哪些可用診斷工具。",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_mcps",
        "description": (
            "列出所有 Custom MCP（已建立的資料處理管線，含 processing_script）。"
            "draft_skill 的 mcp_ids 必須從此清單中選取 Custom MCP ID。"
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_system_mcps",
        "description": (
            "列出所有 System MCP（底層資料來源）及其 input_schema。"
            "建立新 Custom MCP 時，先用此工具找到對應的 system_mcp_id，再呼叫 draft_mcp。"
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "draft_skill",
        "description": (
            "以草稿模式建立新的診斷技能。寫入 Draft DB 而非正式 registry，"
            "並回傳 deep_link 供人類在 UI 審查後正式發佈。"
            "⚠️ 呼叫前必須先用 list_mcps 取得可用 MCP 清單，再把對應 MCP 的 id 填入 mcp_ids。"
            "⚠️ human_recommendation（專家處置建議）僅在使用者明確提供時才填入，否則一律留空讓使用者自行決定。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill 名稱"},
                "description": {"type": "string", "description": "Skill 說明"},
                "diagnostic_prompt": {"type": "string", "description": "診斷條件"},
                "problem_subject": {"type": "string", "description": "問題目標欄位名稱"},
                "human_recommendation": {"type": "string", "description": "專家處置建議（使用者未提供時留空）"},
                "mcp_ids": {"type": "array", "items": {"type": "integer"}, "description": "綁定的 MCP ID 清單（必填，先用 list_mcps 取得正確 ID）"},
                "mcp_input_params": {"type": "object", "description": "本次分析時傳入 MCP 的實際輸入參數（key-value），供草稿卡顯示供人工確認"},
            },
            "required": ["name", "diagnostic_prompt", "mcp_ids"],
        },
    },
    {
        "name": "draft_mcp",
        "description": "以草稿模式建立新的 Custom MCP。寫入 Draft DB，回傳 deep_link 供人類審查。",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "MCP 名稱"},
                "description": {"type": "string", "description": "說明"},
                "system_mcp_id": {"type": "integer", "description": "綁定的 System MCP ID"},
                "processing_intent": {"type": "string", "description": "處理意圖描述"},
            },
            "required": ["name", "system_mcp_id", "processing_intent"],
        },
    },
    {
        "name": "build_mcp",
        "description": (
            "自動建立 Custom MCP 完整流程：sample-fetch → LLM 生成 processing_script → 沙盒測試 → 存入 DB。\n"
            "比 draft_mcp 更完整：不需要人工介入即可完成 MCP 建立（自動重試 2 次）。\n"
            "⚠️ 呼叫前必須先用 list_system_mcps 確認 system_mcp_id。\n"
            "成功後回傳 mcp_id，可直接用於 draft_skill 或 build_skill。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "MCP 名稱"},
                "description": {"type": "string", "description": "說明（選填）"},
                "system_mcp_id": {"type": "integer", "description": "System MCP ID（先用 list_system_mcps 取得）"},
                "processing_intent": {"type": "string", "description": "加工意圖，例如「計算每個 lot 的 OOC 比率並標記異常」"},
                "sample_params": {"type": "object", "description": "傳給 System MCP 的抽樣參數（選填）"},
            },
            "required": ["name", "system_mcp_id", "processing_intent"],
        },
    },
    {
        "name": "build_skill",
        "description": (
            "自動建立 Skill 完整流程：執行 MCP 取得樣本輸出 → LLM 生成 diagnose() 診斷程式碼 → 存入 DB。\n"
            "比 draft_skill 更完整：不需要人工介入即可完成 Skill 建立。\n"
            "⚠️ 呼叫前必須先用 list_mcps 確認 mcp_id（需為 Custom MCP）。\n"
            "成功後回傳 skill_id 與 LLM 生成的診斷結果預覽。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill 名稱"},
                "description": {"type": "string", "description": "說明（選填）"},
                "mcp_id": {"type": "integer", "description": "綁定的 Custom MCP ID（先用 list_mcps 取得）"},
                "diagnostic_prompt": {"type": "string", "description": "診斷條件，例如「若最近 10 筆中有 3 筆以上 OOC 則判為異常」"},
                "problem_subject": {"type": "string", "description": "問題目標欄位（選填）"},
                "human_recommendation": {"type": "string", "description": "專家處置建議（選填，使用者未明確提供時留空）"},
            },
            "required": ["name", "mcp_id", "diagnostic_prompt"],
        },
    },
    {
        "name": "patch_mcp",
        "description": (
            "修改現有 Custom MCP 的欄位。可更新 name、description、processing_intent、diagnostic_prompt。"
            "⚠️ 只能修改 Custom MCP（mcp_type=custom），不可修改 System MCP。"
            "修改後用戶會在 MCP Builder 看到更新後的設定。"
            "如果需要重新生成 processing_script，修改 processing_intent 後提示用戶到 MCP Builder 點擊 Try Run。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mcp_id": {"type": "integer", "description": "Custom MCP ID（先用 list_mcps 取得）"},
                "name": {"type": "string", "description": "新的 MCP 名稱（選填）"},
                "description": {"type": "string", "description": "新的說明（選填）"},
                "processing_intent": {"type": "string", "description": "新的加工意圖（選填，修改後需重新 Try Run 才能更新 processing_script）"},
                "diagnostic_prompt": {"type": "string", "description": "新的診斷條件（選填）"},
            },
            "required": ["mcp_id"],
        },
    },
    {
        "name": "patch_skill_raw",
        "description": (
            "以 OpenClaw Markdown 格式修改現有 Skill 的診斷條件、目標、處置建議。"
            "先用 GET /agentic/skills/{skill_id}/raw 取得現有 Markdown 再修改。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "integer", "description": "Skill ID"},
                "raw_markdown": {"type": "string", "description": "完整的 OpenClaw Markdown 字串"},
            },
            "required": ["skill_id", "raw_markdown"],
        },
    },
    {
        "name": "list_routine_checks",
        "description": "列出所有排程巡檢 (RoutineCheck)，含 id、名稱、綁定 Skill、執行間隔、啟用狀態。用於了解目前有哪些主動巡檢任務。",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_event_types",
        "description": "列出所有 EventType（異常事件類型），含 id、名稱、屬性欄位、已連結的 diagnosis_skill_ids。用於了解有哪些事件可以觸發 Skill 診斷。",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "navigate",
        "description": (
            "在 UI 中導航至指定頁面或開啟特定資源的編輯器。"
            "適用場景：patch_mcp 修改後引導用戶到 MCP Builder 點 Try Run；"
            "或需要用戶手動審查/確認某個 MCP/Skill 設定時。"
            "呼叫此工具後 UI 會自動切換到對應視圖並開啟編輯器，不需要用戶手動操作。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["mcp-edit", "skill-edit", "mcp-builder", "skill-builder"],
                    "description": "導航目標：mcp-edit=開啟指定 MCP 編輯器，skill-edit=開啟指定 Skill 編輯器，mcp-builder=切換到 MCP Builder 清單，skill-builder=切換到 Skill Builder 清單",
                },
                "id": {
                    "type": "integer",
                    "description": "目標資源 ID（mcp-edit/skill-edit 時必填）",
                },
                "message": {
                    "type": "string",
                    "description": "顯示給用戶的引導訊息，例如「請在 MCP Builder 中點擊 Try Run 重新生成腳本」",
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "draft_routine_check",
        "description": (
            "以草稿模式建立排程巡檢。Agent 提案後需人工在 巢狀建構器 (Nested Builder) 確認後發佈。\n"
            "⚠️ 提供 skill_id（現有 Skill）或 skill_draft（建立新 Skill，先用 list_skills 確認無重複）。\n"
            "⚠️ skill_draft 需包含：name, description, mcp_ids（用 list_mcps 取得正確 custom MCP ID）, diagnostic_prompt, problem_subject, human_recommendation。\n"
            "schedule_interval 可選: '30m' | '1h' | '4h' | '8h' | '12h' | 'daily'。\n"
            "daily 模式須填 schedule_time (HH:MM)。若用戶說「最近N天」請計算 expire_at (YYYY-MM-DD)。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "排程名稱"},
                "skill_id": {"type": "integer", "description": "綁定現有 Skill 的 ID（與 skill_draft 二擇一）"},
                "skill_draft": {
                    "type": "object",
                    "description": "若需建立新 Skill：{name, description, mcp_ids, diagnostic_prompt, problem_subject, human_recommendation}",
                },
                "schedule_interval": {
                    "type": "string",
                    "enum": ["30m", "1h", "4h", "8h", "12h", "daily"],
                    "description": "執行間隔（預設 1h）",
                },
                "skill_input": {
                    "type": "object",
                    "description": "固定傳給 Skill 的執行參數，例如 {lot_id, tool_id}",
                },
                "schedule_time": {"type": "string", "description": "每日執行時間 HH:MM（僅 daily 模式，例如 '08:00'）"},
                "expire_at": {"type": "string", "description": "效期 YYYY-MM-DD，到期後自動停用。若使用者說『最近N天』請自動計算今日+N天的日期填入。"},
                "generated_event_name": {"type": "string", "description": "ABNORMAL 時建立的 EventType 名稱（預設為 '{name} 異常警報'）"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "draft_event_skill_link",
        "description": (
            "以草稿模式將 Skill 連結至 EventType 的診斷鏈。Agent 提案後需人工確認後發佈。\n"
            "⚠️ 提供 event_type_id（現有）或 event_type_name（新建 EventType）。\n"
            "⚠️ 提供 skill_id（現有）或 skill_draft（新建 Skill）。\n"
            "先用 list_event_types 與 list_skills 確認現有清單再決定是否新建。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_type_id": {"type": "integer", "description": "現有 EventType 的 ID（與 event_type_name 二擇一）"},
                "event_type_name": {"type": "string", "description": "新建 EventType 的名稱"},
                "skill_id": {"type": "integer", "description": "現有 Skill 的 ID（與 skill_draft 二擇一）"},
                "skill_draft": {
                    "type": "object",
                    "description": "若需建立新 Skill：{name, description, mcp_ids, diagnostic_prompt, problem_subject, human_recommendation}",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_memory",
        "description": "搜尋 Agent 的長期記憶。用於查詢歷史診斷結果或使用者曾說的話。支援 Metadata 過濾以精準提取同類型經驗。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜尋關鍵字"},
                "top_k": {"type": "integer", "description": "回傳筆數 (預設 5)", "default": 5},
                "task_type": {"type": "string", "description": "限定記憶類型 (可選)，例如 draw_chart / troubleshooting"},
                "data_subject": {"type": "string", "description": "限定資料對象/機台 (可選)，例如 TETCH01"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "save_memory",
        "description": "明確儲存一條長期記憶，例如「使用者確認 TETCH01 已維修完畢」。支援 Metadata 標籤以利日後精準提取。",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "記憶內容 (純文字)"},
                "task_type": {"type": "string", "description": "任務類型標籤 (可選)，例如 draw_chart / troubleshooting"},
                "data_subject": {"type": "string", "description": "資料對象/機台標籤 (可選)，例如 TETCH01"},
                "tool_name": {"type": "string", "description": "關聯工具名稱標籤 (可選)，例如 execute_mcp"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "update_user_preference",
        "description": (
            "更新使用者的個人偏好設定，例如回答語言、報告格式偏好。"
            "送出前會經過 LLM 守門審查，若含惡意指令將被阻擋。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "新的偏好設定文字"},
            },
            "required": ["text"],
        },
    },
    # ── Ad-hoc Analysis (the ONLY entry point for analysis + charts) ──────
    {
        "name": "execute_analysis",
        "description": (
            "== What ==\n"
            "規劃並執行一個 data pipeline：撈資料 → 處理 → 產圖/產結論。\n"
            "產出的 code 可一鍵儲存為 Skill → Auto-Patrol。\n"
            "\n"
            "== Use when ==\n"
            "- <skill_catalog> 裡沒有現成 Skill 能完成使用者的需求\n"
            "- 需要圖表（chart）、趨勢分析、條件判斷、複合分析\n"
            "- 需要資料處理（filter / flatten / aggregate）後再呈現\n"
            "\n"
            "== mode ==\n"
            "mode='auto'（推薦）：給 title + description，後端自動生成 pipeline code 並執行。\n"
            "description 要寫清楚 pipeline plan：資料來源 + 處理邏輯 + 呈現方式。\n"
            "\n"
            "mode='code'：自行提供 steps[].python_code，僅限 auto 失敗時的 fallback。\n"
            "  - 用 await execute_mcp(mcp_name, params) 撈資料\n"
            "  - 在最後一步 assign _findings.outputs[key] = data\n"
            "  - 圖表由 ChartMiddleware 從 output_schema type 自動產生\n"
            "  - 可用變數：equipment_id, lot_id, step, event_time, _input\n"
            "  - 禁止 import requests/os/sys/subprocess\n"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "分析標題（顯示在分析面板頂部）",
                },
                "mode": {
                    "type": "string",
                    "enum": ["auto", "code"],
                    "description": "auto=後端自動生成分析（推薦）, code=自行提供 steps python_code",
                },
                "description": {
                    "type": "string",
                    "description": "mode=auto 時必填：分析需求描述（自然語言），例如「分析 STEP_020 的 SPC xbar chart 趨勢，以 trend chart 呈現」",
                },
                "steps": {
                    "type": "array",
                    "description": "mode=code 時必填：分析步驟清單",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step_id": {"type": "string"},
                            "nl_segment": {"type": "string"},
                            "python_code": {"type": "string"},
                        },
                        "required": ["step_id", "nl_segment", "python_code"],
                    },
                },
                "input_params": {
                    "type": "object",
                    "description": "執行參數（例如 {step: 'STEP_013', equipment_id: 'EQP-01'}）",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "search_catalog",
        "description": (
            "搜尋 Skill / Custom MCP / System MCP / Agent Tool 目錄。"
            "用於發現可用工具或確認某類分析需求是否已有現成解決方案。"
            "catalog 可選：skills | mcps | system_mcps | agent_tools"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "catalog": {
                    "type": "string",
                    "enum": ["skills", "mcps", "system_mcps", "agent_tools"],
                    "description": "要搜尋的目錄類型",
                },
                "query": {
                    "type": "string",
                    "description": "關鍵字（用於名稱/描述過濾，留空回傳全部）",
                },
            },
            "required": ["catalog"],
        },
    },
    {
        "name": "update_plan",
        "description": (
            "v1.4 Plan Panel — Claude-Code-style live todo list shown above the chat.\n"
            "\n"
            "**第一輪呼叫（必做）**：\n"
            "  action='create', items=[{id, title, status: 'pending'}]\n"
            "  3-7 個高層 todo，涵蓋 fetch / process / present / output。\n"
            "\n"
            "**進度更新**：\n"
            "  action='update', id=<existing item id>, status='in_progress'|'done'|'failed'\n"
            "  選填 note='額外說明'（e.g. \"已加 4 個 nodes\"）。\n"
            "\n"
            "你必須在開始任何其他工具之前先 emit 一個 `create` plan，"
            "讓使用者馬上看到接下來會做什麼。每完成一個階段立刻 update。"
        ),
        "input_schema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {"type": "string", "enum": ["create", "update"]},
                "items": {
                    "type": "array",
                    "description": "create 時填，建議 3-7 項",
                    "items": {
                        "type": "object",
                        "required": ["id", "title", "status"],
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "done", "failed"]},
                        },
                    },
                },
                "id": {"type": "string", "description": "update 時的 plan item id"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "done", "failed"]},
                "note": {"type": "string"},
            },
        },
    },
]


# ── Dispatcher ─────────────────────────────────────────────────────────────

class ToolDispatcher:
    """Routes tool_use blocks to the appropriate backend endpoint or service."""

    def __init__(
        self,
        db: AsyncSession,
        base_url: str,
        auth_token: str,
        user_id: int,
        java: Any = None,
    ) -> None:
        self._db = db
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
        self._user_id = user_id
        # Phase 8-A-1d: when java client is provided, mcp_id resolution +
        # memory operations route via Java instead of local SQLAlchemy.
        self._java = java
        self._memory_svc = AgentMemoryService(db) if db is not None else None

    # Tools that return conversational/structural data — skip DataProfile for these
    _NON_DATA_TOOLS = frozenset({
        "navigate", "save_memory", "search_memory", "update_user_preference",
        "list_skills", "list_mcps", "list_system_mcps",
        "list_routine_checks", "list_event_types",
        "draft_skill", "draft_mcp", "draft_routine_check", "draft_event_skill_link",
        "build_mcp", "build_skill",
        "patch_mcp", "patch_skill_raw",
        "search_catalog",   # returns catalog items, not raw datasets
        "execute_analysis",  # result already processed in sandbox
    })

    # Catalog type → API endpoint mapping
    _CATALOG_ENDPOINTS: Dict[str, str] = {
        "skills":       "/api/v1/skill-definitions",
        "mcps":         "/api/v1/mcp-definitions?type=custom",
        "system_mcps":  "/api/v1/mcp-definitions?type=system",
        "agent_tools":  "/api/v1/agent-tools",
    }

    async def _resolve_mcp_id(self, tool_input: Dict[str, Any]) -> Optional[int]:
        """Resolve mcp_id from mcp_name or mcp_id in tool_input.

        Returns the resolved integer ID, or None if neither provided / not found.
        Prefers mcp_name over mcp_id for semantic clarity.
        """
        mcp_name = tool_input.get("mcp_name")
        if mcp_name:
            if self._java is not None:
                mcp = await self._java.get_mcp_by_name(mcp_name)
                if mcp:
                    return mcp.get("id")
                return None
            result = await self._db.execute(
                select(MCPDefinitionModel).where(MCPDefinitionModel.name == mcp_name)
            )
            mcp = result.scalar_one_or_none()
            if mcp:
                return mcp.id
            return None  # name given but not found → surface error to model
        return tool_input.get("mcp_id")

    async def _execute_inner(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool and return its result as a dict (inner, no profiling)."""
        logger.info("ToolDispatcher.execute: tool=%s input=%s", tool_name, json.dumps(tool_input, ensure_ascii=False)[:200])
        try:
            match tool_name:
                case "search_published_skills":
                    # Use JavaAPIClient (X-Internal-Token on /internal/*) since
                    # the sidecar's auth_token is the internal token, not a
                    # user JWT — the public /api/v1/* endpoint would 401.
                    if self._java is not None:
                        rows = await self._java.search_published_skills(
                            tool_input.get("query", ""),
                            tool_input.get("top_k", 5) or 5,
                        )
                        return rows  # list of skill dicts
                    return {"status": "error", "message": "Java client not configured"}
                case "invoke_published_skill":
                    return await self._invoke_published_skill(tool_input)
                case "execute_skill":
                    # PR-4E: deprecated path — logged so we can track remaining
                    # legacy usage before Phase 4-F hard-removes it.
                    logger.warning(
                        "DEPRECATED: execute_skill called (skill_id=%s). Migrate to "
                        "invoke_published_skill via the Pipeline Builder.",
                        tool_input.get("skill_id"),
                    )
                    return await self._call_api(
                        "POST",
                        f"/api/v1/execute/skill/{tool_input['skill_id']}",
                        body=tool_input.get("params", {}),
                    )
                case "query_data":
                    # query_data = execute_mcp + flatten + metadata
                    data_source = tool_input.get("data_source") or tool_input.get("mcp_name", "")
                    params = tool_input.get("params", {})
                    viz_hint = tool_input.get("visualization_hint")
                    # Resolve MCP and call it
                    mcp_id = await self._resolve_mcp_id({"mcp_name": data_source})
                    if mcp_id is None:
                        return {
                            "status": "error",
                            "code": "MCP_NOT_FOUND",
                            "message": f"⚠️ 找不到 MCP '{data_source}'。請確認 <mcp_catalog> 中的 name 欄位。",
                        }
                    raw_result = await self._call_api("POST", f"/api/v1/execute/mcp/{mcp_id}", body=params)
                    # Flatten the result
                    # Only flatten get_process_info (has events[]).
                    # Other MCPs (get_process_summary, list_tools, etc.) return aggregated
                    # data that LLM should read directly — no flattening needed.
                    _FLATTEN_MCPS = {"get_process_info"}
                    try:
                        from python_ai_sidecar.agent_helpers_native.data_flattener import flatten, build_llm_summary
                        od = raw_result.get("output_data", {}) if isinstance(raw_result, dict) else {}
                        raw_ds = od.get("_raw_dataset") or od.get("dataset") or []
                        flatten_input = raw_ds[0] if isinstance(raw_ds, list) and len(raw_ds) == 1 and isinstance(raw_ds[0], dict) else raw_ds

                        if data_source in _FLATTEN_MCPS and isinstance(flatten_input, dict) and flatten_input.get("events"):
                            flat_result = flatten(flatten_input)
                            llm_summary = build_llm_summary(flat_result.metadata, flat_result)
                            return {
                                "status": "success",
                                "mcp_name": data_source,
                                "llm_readable_data": llm_summary,
                                "_flat_data": flat_result.to_dict(),
                                "_flat_metadata": flat_result.metadata,
                                "_visualization_hint": viz_hint,
                                "_raw_result": raw_result,
                            }
                        else:
                            # Non-event MCPs: pass raw result directly to LLM
                            import json as _json
                            raw_text = _json.dumps(flatten_input, ensure_ascii=False, default=str)[:6000]
                            return {
                                "status": "success",
                                "mcp_name": data_source,
                                "llm_readable_data": raw_text,
                                "_flat_data": None,
                                "_flat_metadata": None,
                                "_visualization_hint": None,
                                "_raw_result": raw_result,
                            }
                    except Exception as exc:
                        logger.exception("query_data flatten failed: %s", exc)
                        return {
                            "status": "success",
                            "mcp_name": data_source,
                            "llm_readable_data": str(raw_result)[:4000],
                            "_flat_data": None,
                            "_flat_metadata": None,
                            "_visualization_hint": viz_hint,
                            "_raw_result": raw_result,
                        }
                case "execute_mcp":
                    mcp_id = await self._resolve_mcp_id(tool_input)
                    if mcp_id is None:
                        name_hint = tool_input.get("mcp_name", "")
                        return {
                            "status": "error",
                            "code": "MCP_NOT_FOUND",
                            "message": (
                                f"⚠️ 找不到 MCP '{name_hint}'。"
                                "請確認 <mcp_catalog> 中的 name 欄位是否正確。"
                            ),
                        }
                    return await self._call_api(
                        "POST",
                        f"/api/v1/execute/mcp/{mcp_id}",
                        body=tool_input.get("params", {}),
                    )
                case "list_skills":
                    return await self._call_api("GET", "/api/v1/skill-definitions")
                case "list_mcps":
                    return await self._call_api("GET", "/api/v1/mcp-definitions?type=custom")
                case "list_system_mcps":
                    return await self._call_api("GET", "/api/v1/mcp-definitions?type=system")
                case "draft_skill":
                    return await self._call_api("POST", "/api/v1/agent/draft/skill", body=tool_input)
                case "draft_mcp":
                    return await self._call_api("POST", "/api/v1/agent/draft/mcp", body=tool_input)
                case "build_mcp":
                    return await self._call_api("POST", "/api/v1/mcp-definitions/agent-build", body=tool_input)
                case "build_skill":
                    return await self._call_api("POST", "/api/v1/skill-definitions/agent-build", body=tool_input)
                case "list_routine_checks":
                    return await self._call_api("GET", "/api/v1/routine-checks")
                case "list_event_types":
                    return await self._call_api("GET", "/api/v1/event-types")
                case "draft_routine_check":
                    return await self._call_api("POST", "/api/v1/agent/draft/routine_check", body=tool_input)
                case "draft_event_skill_link":
                    return await self._call_api("POST", "/api/v1/agent/draft/event_skill_link", body=tool_input)
                case "patch_mcp":
                    mcp_id = tool_input.pop("mcp_id")
                    if not tool_input:
                        return {"error": "至少需提供一個要修改的欄位"}
                    return await self._call_api("PATCH", f"/api/v1/mcp-definitions/{mcp_id}", body=tool_input)
                case "patch_skill_raw":
                    return await self._call_api(
                        "PUT",
                        f"/api/v1/agentic/skills/{tool_input['skill_id']}/raw",
                        body={"raw_markdown": tool_input["raw_markdown"]},
                    )
                case "navigate":
                    return {
                        "action": "navigate",
                        "target": tool_input.get("target"),
                        "id": tool_input.get("id"),
                        "message": tool_input.get("message", ""),
                        "deep_link": f"{tool_input.get('target')}:{tool_input.get('id', '')}",
                    }
                case "update_plan":
                    # v1.4 Plan Panel — agent emits/updates a todo list.
                    # Two modes:
                    #   action="create" + items=[...] → declare initial plan
                    #   action="update" + id + status (+ note) → mark progress
                    # Result is pure metadata; tool_execute relays it as an
                    # SSE event ("plan" or "plan_update") to the Frontend.
                    action = (tool_input.get("action") or "create").lower()
                    if action == "create":
                        items = tool_input.get("items") or []
                        return {
                            "_plan_action": "create",
                            "items": items,
                            "status": "success",
                        }
                    if action == "update":
                        return {
                            "_plan_action": "update",
                            "id": tool_input.get("id"),
                            "status_value": tool_input.get("status"),
                            "note": tool_input.get("note"),
                            "status": "success",
                        }
                    return {
                        "status": "error",
                        "code": "BAD_PLAN_ACTION",
                        "message": "update_plan.action must be 'create' or 'update'",
                    }
                case "search_memory":
                    # Phase 8-A-1d: route via Java when available (chat native)
                    top_k = tool_input.get("top_k", 5)
                    if self._java is not None:
                        rows = await self._java.list_agent_memories(
                            user_id=self._user_id,
                            task_type=tool_input.get("task_type"),
                        )
                        # Naive client-side keyword filter (no vector search on
                        # this legacy endpoint; sidecar's experience_memory is
                        # the proper RAG path).
                        q = (tool_input.get("query") or "").lower()
                        if q:
                            rows = [r for r in rows if q in (r.get("content") or "").lower()]
                        rows = rows[:top_k]
                        return {
                            "memories": rows,
                            "count": len(rows),
                            "filter_applied": {"strategy": "java_keyword"},
                        }
                    if self._memory_svc is None:
                        return {"memories": [], "count": 0, "filter_applied": {"strategy": "unavailable"}}
                    memories, filter_applied = await self._memory_svc.search_with_metadata(
                        user_id=self._user_id,
                        query=tool_input["query"],
                        top_k=top_k,
                        task_type=tool_input.get("task_type"),
                        data_subject=tool_input.get("data_subject"),
                    )
                    return {
                        "memories": [AgentMemoryService.to_dict(m) for m in memories],
                        "count": len(memories),
                        "filter_applied": filter_applied,
                    }
                case "save_memory":
                    if self._java is not None:
                        body = {
                            "userId": self._user_id,
                            "content": tool_input["content"],
                            "source": "agent_request",
                            "taskType": tool_input.get("task_type"),
                            "dataSubject": tool_input.get("data_subject"),
                            "toolName": tool_input.get("tool_name"),
                        }
                        saved = await self._java.save_agent_memory(body)
                        return {
                            "saved": True,
                            "memory_id": saved.get("id"),
                            "content": saved.get("content"),
                        }
                    if self._memory_svc is None:
                        return {"saved": False, "error": "memory service unavailable"}
                    m = await self._memory_svc.write(
                        user_id=self._user_id,
                        content=tool_input["content"],
                        source="agent_request",
                        task_type=tool_input.get("task_type"),
                        data_subject=tool_input.get("data_subject"),
                        tool_name=tool_input.get("tool_name"),
                    )
                    return {"saved": True, "memory_id": m.id, "content": m.content}
                case "update_user_preference":
                    return await self._call_api(
                        "POST",
                        "/api/v1/agent/preference",
                        body={"user_id": self._user_id, "text": tool_input["text"]},
                    )
                # ── Ad-hoc Analysis (the only entry point for analysis + charts) ──────
                case "execute_analysis":
                    body = {
                        "title": tool_input.get("title", "Ad-hoc 分析"),
                        "mode": tool_input.get("mode", "auto"),
                        "description": tool_input.get("description", tool_input.get("title", "")),
                        "steps": tool_input.get("steps", []),
                        "input_params": tool_input.get("input_params", {}),
                    }
                    # Pass flat_data so sandbox code can read it directly
                    if tool_input.get("_flat_data"):
                        body["_flat_data"] = tool_input["_flat_data"]
                    return await self._call_api(
                        "POST",
                        "/api/v1/analysis/run",
                        body=body,
                        timeout=120.0,
                    )
                # ── [v15.1] Catalog search across skills / mcps / system_mcps / agent_tools
                case "search_catalog":
                    return await self._search_catalog(
                        catalog=tool_input.get("catalog", "skills"),
                        query=tool_input.get("query", ""),
                    )
                case _:
                    return {"error": f"Unknown tool: {tool_name}"}
        except Exception as exc:
            logger.exception("ToolDispatcher error: tool=%s", tool_name)
            return {"error": str(exc), "tool": tool_name}

    async def execute(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool, then attach DataProfile if result contains a dataset."""
        result = await self._execute_inner(tool_name, tool_input)

        # [P0 v15] Smart Sampling Interceptor — skip non-data tools for efficiency
        if tool_name not in self._NON_DATA_TOOLS:
            try:
                from python_ai_sidecar.agent_helpers_native.data_profile_service import DataProfileService, is_data_source
                if is_data_source(result):
                    profile = DataProfileService.build_profile(result)
                    if profile:
                        result["_data_profile"] = profile
                        logger.debug("DataProfile attached: tool=%s cols=%s", tool_name, list(profile.get("meta", {}).keys()))
            except Exception as exc:
                logger.warning("Smart Sampling interceptor failed (non-blocking): %s", exc)

        # Phase 2-E: tool result truncation safety net. Without this, a single
        # process_history that returns 50k rows feeds 200k+ tokens straight into
        # the next iteration's prompt and detonates the ReAct loop.
        result = _truncate_oversized_result(result, tool_name=tool_name)

        return result

    async def _invoke_published_skill(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """PR-C: resolve published skill by slug → load its pipeline → execute."""
        slug = tool_input.get("slug")
        if not slug:
            return {"status": "error", "message": "slug is required"}
        inputs = tool_input.get("inputs") or {}

        # 1. Find the published skill via internal search (X-Internal-Token).
        if self._java is None:
            return {"status": "error", "message": "Java client not configured"}
        search = await self._java.search_published_skills(slug, 20)
        match = None
        if isinstance(search, list):
            for row in search:
                if isinstance(row, dict) and row.get("slug") == slug:
                    match = row
                    break
        if match is None:
            return {"status": "error", "message": f"Published skill '{slug}' not found"}

        # 2. Load its pipeline definition via internal endpoint.
        pipe_id = match.get("pipeline_id")
        if pipe_id is None:
            return {"status": "error", "message": "Skill row missing pipeline_id"}
        pipe = await self._java.get_pipeline(pipe_id)
        if not isinstance(pipe, dict) or "pipeline_json" not in pipe:
            return {"status": "error", "message": f"Pipeline {pipe_id} payload not available"}

        # 3. Execute via sidecar's own /internal/pipeline/execute — same
        # process, native executor, telemetry bumps via pipeline_id.
        import httpx
        from python_ai_sidecar.config import CONFIG
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                "http://127.0.0.1:8050/internal/pipeline/execute",
                headers={"X-Service-Token": CONFIG.service_token},
                json={
                    "pipeline_json": pipe["pipeline_json"],
                    "triggered_by": "agent",
                    "inputs": inputs,
                    "pipeline_id": pipe_id,
                },
            )
            try:
                exec_result = r.json()
            except Exception:
                exec_result = {"status": "error", "message": f"Executor HTTP {r.status_code}"}
        if not isinstance(exec_result, dict):
            return {"status": "error", "message": "Executor returned non-dict"}

        # Summarize for LLM — Agent shouldn't need to parse every node_result.
        # data_views must come through so list-type skills (list-apcs, list-tools
        # etc., which output via block_data_view rather than chart_spec) actually
        # surface their rows; without this the LLM sees triggered=false / charts=[]
        # and concludes "no data".
        summary = exec_result.get("result_summary") or {}
        raw_views = summary.get("data_views") if isinstance(summary, dict) else None
        compact_views: list[dict[str, Any]] = []
        if isinstance(raw_views, list):
            for v in raw_views:
                if not isinstance(v, dict):
                    continue
                rows = v.get("rows") or []
                compact_views.append({
                    "title": v.get("title"),
                    "columns": v.get("columns") or [],
                    "row_count": len(rows) if isinstance(rows, list) else 0,
                    # cap to 50 rows to keep tool result LLM-friendly; full rows
                    # still rendered in the UI's Pipeline Results panel
                    "rows": rows[:50] if isinstance(rows, list) else [],
                })
        return {
            "status": exec_result.get("status", "unknown"),
            "slug": slug,
            "skill_name": match.get("name"),
            "triggered": bool(summary.get("triggered")) if isinstance(summary, dict) else False,
            "evidence_rows": (summary.get("evidence_rows") if isinstance(summary, dict) else 0),
            "charts": (summary.get("charts") if isinstance(summary, dict) else []) or [],
            "data_views": compact_views,
            "run_id": exec_result.get("run_id"),
            "error_message": exec_result.get("error_message"),
        }

    async def _call_api(
        self, method: str, path: str, body: Optional[Dict] = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                resp = await client.get(url, headers=self._headers)
            elif method == "POST":
                resp = await client.post(url, headers=self._headers, json=body or {})
            elif method == "PUT":
                resp = await client.put(url, headers=self._headers, json=body or {})
            elif method == "PATCH":
                resp = await client.patch(url, headers=self._headers, json=body or {})
            elif method == "DELETE":
                resp = await client.delete(url, headers=self._headers)
            else:
                return {"error": f"Unsupported method: {method}"}

            try:
                return resp.json()
            except Exception:
                return {"error": f"Non-JSON response ({resp.status_code})", "body": resp.text[:500]}

    async def _search_catalog(self, catalog: str, query: str = "") -> Dict[str, Any]:
        """Fetch a catalog list and optionally filter by query string (name/description)."""
        endpoint = self._CATALOG_ENDPOINTS.get(catalog)
        if not endpoint:
            return {"error": f"Unknown catalog: {catalog}. Valid: {list(self._CATALOG_ENDPOINTS)}"}

        raw = await self._call_api("GET", endpoint)

        # Unwrap StandardResponse envelope → list of items
        items: List[Dict[str, Any]] = []
        if isinstance(raw, dict):
            data = raw.get("data", raw)
            if isinstance(data, dict):
                items = data.get("items", data.get("skills", data.get("mcps", [])))
            elif isinstance(data, list):
                items = data
        elif isinstance(raw, list):
            items = raw

        # Filter by query (name or description, case-insensitive)
        if query:
            q = query.lower()
            items = [
                it for it in items
                if q in str(it.get("name", "")).lower()
                or q in str(it.get("description", "")).lower()
            ]

        return {"catalog": catalog, "query": query, "total": len(items), "items": items}


# ── Phase 2-E: tool result truncation safety net ─────────────────────────

# Tokens, not chars. 4000 tokens is "generous enough for one-pass insight" but
# nowhere near the multi-50k-token results that detonate context. Tool authors
# already pass `limit` params for soft control; this is the hard backstop.
TOOL_RESULT_TOKEN_CAP = 4000

# Tools whose result the LLM legitimately needs in full (small / structured /
# already capped upstream). Skip truncation for these to avoid surprises.
_NEVER_TRUNCATE = {
    "update_plan", "explain", "finish",  # control-plane tools
    "save_memory",  # memory writes return small ack
}


def _truncate_oversized_result(result: Any, *, tool_name: str = "") -> Any:
    """If `result` JSON-serializes to more than TOOL_RESULT_TOKEN_CAP tokens,
    smart-truncate large list fields and attach `_truncated: true` flag."""
    if tool_name in _NEVER_TRUNCATE:
        return result
    if not isinstance(result, dict):
        return result

    try:
        from python_ai_sidecar.agent_helpers_native.token_counter import count_tokens
        serialized = json.dumps(result, ensure_ascii=False, default=str)
        tokens = count_tokens(serialized)
    except Exception:  # noqa: BLE001
        return result

    if tokens <= TOOL_RESULT_TOKEN_CAP:
        return result

    truncated = _smart_truncate_dict(result, tokens, count_tokens)
    if truncated is not result:
        truncated["_truncated"] = True
        truncated["_original_size_tokens"] = tokens
        truncated["_truncation_hint"] = (
            "Result was capped — narrow your filters (date range, equipment, step) and "
            "re-call the tool if you need more rows."
        )
        logger.info(
            "tool_result truncated: tool=%s original=%d tokens cap=%d",
            tool_name, tokens, TOOL_RESULT_TOKEN_CAP,
        )
    return truncated


def _smart_truncate_dict(d: Dict[str, Any], current_tokens: int, count_fn) -> Dict[str, Any]:
    """Walk shallow dict fields and shrink the largest list-of-dict / list / str
    fields until under cap. We mutate a shallow copy so the original dict
    (which may be in caches / memos elsewhere) is not affected."""
    out: Dict[str, Any] = dict(d)

    # Identify list-shaped fields ranked by their JSON size — biggest first.
    candidates: List[tuple[str, int]] = []
    for k, v in out.items():
        if k.startswith("_"):  # internal flags — leave alone
            continue
        if isinstance(v, list) and v:
            try:
                candidates.append((k, count_fn(json.dumps(v, ensure_ascii=False, default=str))))
            except Exception:  # noqa: BLE001
                continue
    candidates.sort(key=lambda kv: kv[1], reverse=True)

    target = TOOL_RESULT_TOKEN_CAP
    for key, _size in candidates:
        if current_tokens <= target:
            break
        original_list = out[key]
        # Halve until under target; keep at least 5 items so the LLM still
        # sees representative samples.
        keep = max(5, len(original_list) // 2)
        while keep < len(original_list):
            out[key] = original_list[:keep]
            try:
                current_tokens = count_fn(json.dumps(out, ensure_ascii=False, default=str))
            except Exception:  # noqa: BLE001
                break
            if current_tokens <= target:
                break
            keep = max(5, keep // 2)
            if keep <= 5:
                out[key] = original_list[:keep]
                break
        out[f"_{key}_total_count"] = len(original_list)
        out[f"_{key}_kept_count"] = len(out[key]) if isinstance(out[key], list) else 0

    return out
