"""FastAPI Backend Service — Application Entry Point (v8)."""


import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.services.mcp_builder_service import _DEFAULT_TRY_RUN_SYSTEM_PROMPT
from app.core.exceptions import AppException
from app.core.logging import AppLogger
from app.core.response import HealthResponse, StandardResponse
from app.database import init_db, get_db
from app.middleware import RequestLoggingMiddleware
from app.routers import (
    auth_router,
    builder_router,
    data_subjects_router,
    diagnostic_router,
    event_types_router,
    alarms_router,
    system_events_router,
    help_router,
    items_router,
    mcp_definitions_router,
    mock_data_router,
    mock_data_studio_router,
    routine_check_router,
    skill_definitions_router,
    system_parameters_router,
    users_router,
    # v12 Agent
    agent_router,
    agent_execute_router,
    agent_draft_router,
    # v12.5 Expert Mode
    agentic_skill_router,
    # v15.0 Agent Tool Chest
    agent_tool_router,
    # v15.2 Shadow Analyst
    shadow_analyst_router,
    # v15.3 Generic Tools
    generic_tools_router,
    # AIOps Automation Platform
    script_registry_router,
    cron_jobs_router,
    actions_router,
    # v2.0 Auto-Patrol
    auto_patrols_router,
    # v2.0 Diagnostic Rules
    diagnostic_rules_router,
)
from app.routers.agent_chat_router import router as agent_chat_router
from app.routers.agent_memory_router import router as agent_memory_router
from app.routers.agent_preference_router import router as agent_preference_router
# Phase 1: Reflective experience memory
from app.routers.experience_memory import router as experience_memory_router
# System Monitor
from app.routers.monitor_router import router as monitor_router
# Ad-hoc analysis + promote
from app.routers.analysis import router as analysis_router
# My Skills (user-created skills for Agent chat)
from app.routers.my_skills import router as my_skills_router
# Dashboard briefing (AI-generated fab/tool briefing via SSE)
from app.routers.briefing import router as briefing_router

settings = get_settings()
_SIM = settings.ONTOLOGY_SIM_URL  # e.g. "http://localhost:8001"
logger = AppLogger("main").get_logger()

# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------

_MOCK_DATA_SUBJECTS = [
    {
        "name": "APC_Data",
        "description": "Advanced Process Control 測量資料，用於監控製程參數偏移",
        "api_config": {
            "endpoint_url": "/api/v1/mock/apc",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "lot_id", "type": "string", "description": "批次 ID", "required": True},
                {"name": "operation_number", "type": "string", "description": "站點代碼", "required": True},
            ]
        },
        "output_schema": {
            "fields": [
                {"name": "lot_id", "type": "string", "description": "批次 ID"},
                {"name": "operation_number", "type": "string", "description": "站點代碼"},
                {"name": "apc_name", "type": "string", "description": "APC 控制器名稱 (e.g., TETCH01_CD_Control)"},
                {"name": "apc_model_name", "type": "string", "description": "使用的模型版本名稱 (e.g., Etch_CD_EWMA_v2.1)"},
                {"name": "model_update_time", "type": "string", "description": "模型最後發布/更新時間 (ISO 8601 DateTime)"},
                {"name": "parameters", "type": "array", "description": "補償參數陣列，每個物件含 name (參數名稱)、value (補償數值)、update_time (計算時間)"},
            ]
        },
    },
    {
        "name": "Recipe_Data",
        "description": "製程 Recipe 參數，含最後修改時間",
        "api_config": {
            "endpoint_url": "/api/v1/mock/recipe",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "lot_id", "type": "string", "description": "批次 ID", "required": True},
                {"name": "tool_id", "type": "string", "description": "機台代碼", "required": True},
                {"name": "operation_number", "type": "string", "description": "站點代碼", "required": True},
            ]
        },
        "output_schema": {
            "fields": [
                {"name": "recipe_name", "type": "string", "description": "Recipe 名稱"},
                {"name": "parameters", "type": "object", "description": "製程參數集合（壓力/功率/氣體/溫度/時間）"},
                {"name": "last_modified_at", "type": "string", "description": "最後修改時間 (ISO 8601)，動態計算為 12 小時前"},
                {"name": "modified_by", "type": "string", "description": "最後修改者"},
                {"name": "version", "type": "number", "description": "Recipe 版本號"},
                {"name": "is_locked", "type": "boolean", "description": "是否已鎖定"},
            ]
        },
    },
    {
        "name": "EC_Data",
        "description": "機台硬體 Equipment Constants 基準參數",
        "api_config": {
            "endpoint_url": "/api/v1/mock/ec",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "tool_id", "type": "string", "description": "機台代碼", "required": True},
            ]
        },
        "output_schema": {
            "fields": [
                {"name": "tool_id", "type": "string", "description": "機台代碼"},
                {"name": "chamber", "type": "string", "description": "腔體編號"},
                {"name": "hardware_constants", "type": "object", "description": "硬體常數集合（RF 匹配電容、節流閥、渦輪泵速度等）"},
                {"name": "baseline_date", "type": "string", "description": "基準量測日期"},
                {"name": "pm_status", "type": "string", "description": "預防維護狀態: normal/pm_due"},
                {"name": "maintenance_cycle_days", "type": "number", "description": "維護週期（天）"},
            ]
        },
    },
    {
        "name": "SPC_Chart_Data",
        "description": "Etch CD SPC 管制圖資料（100 筆，10 台機台 × 10 批貨，TETCH01 前 4 批 OOC）",
        "api_config": {
            "endpoint_url": "/api/v1/mock/spc",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "chart_name", "type": "string", "description": "SPC 管制圖名稱（可選，e.g. CD；不帶則回傳全部 100 筆）", "required": False},
            ]
        },
        "output_schema": {
            "fields": [
                {"name": "datetime",  "type": "string",  "description": "SPC 量測時間 (ISO 8601)"},
                {"name": "value",     "type": "number",  "description": "CD 量測值（nm）"},
                {"name": "UCL",       "type": "number",  "description": "管制上限 Upper Control Limit（46.5 nm）"},
                {"name": "LCL",       "type": "number",  "description": "管制下限 Lower Control Limit（43.5 nm）"},
                {"name": "tool",      "type": "string",  "description": "蝕刻機台代碼 (e.g., TETCH01)"},
                {"name": "lotID",     "type": "string",  "description": "批次 ID (e.g., L2603001)"},
                {"name": "recipe",    "type": "string",  "description": "Recipe ID (e.g., ETH_RCP_01)"},
                {"name": "DCItem",    "type": "string",  "description": "量測項目名稱（固定為 CD）"},
                {"name": "ChartName", "type": "string",  "description": "SPC 管制圖名稱（固定為 CD）"},
            ]
        },
    },
    {
        "name": "APC_tuning_value",
        "description": "APC 補償調整值（etchTime per lot，100 筆，TETCH01 前 4 批 etchTime 異常偏低，呼應 SPC OOC）",
        "api_config": {
            "endpoint_url": "/api/v1/mock/apc_tuning",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "apc_name", "type": "string", "description": "APC 控制器名稱（可選，e.g. TETCH01_CD_Control，不帶則回傳全部 100 筆）", "required": False},
            ]
        },
        "output_schema": {
            "fields": [
                {"name": "APCName",    "type": "string",  "description": "APC 控制器名稱 (e.g., TETCH01_CD_Control)"},
                {"name": "ReportTime", "type": "string",  "description": "APC 回報時間，動態計算為 now-1h 起每 5 min (ISO 8601)"},
                {"name": "DCName",     "type": "string",  "description": "量測項目名稱（固定為 etchTime）"},
                {"name": "DCValue",    "type": "number",  "description": "etchTime 量測值（sec）；正常 10~15，TETCH01 前 4 批異常偏低 5~6"},
                {"name": "LotID",      "type": "string",  "description": "批次 ID (e.g., L2603001)"},
            ]
        },
    },
]


_ONTOLOGY_SYSTEM_MCPS = [
    # ── v3 MCP Design: 3-Layer Architecture ────────────────────────────────────
    # Layer 1: get_process_summary  — 聚合統計（快速概覽）
    # Layer 2: get_process_info     — 範圍調查（event + object data）
    # Layer 3: query_object_timeseries — 深潛（單一參數長時序）
    {
        "name": "get_process_summary",
        "description": (
            "== What ==\n"
            "OOC 統計、機台分佈、近期異常的聚合視圖。不回傳 raw measurement data。\n"
            "\n"
            "== Use when ==\n"
            "- 回答「OOC 率多少」「哪些機台有問題」「最近狀況如何」\n"
            "- 全廠 / 全機台範圍的快速概覽（毫秒級）\n"
            "\n"
            "== Don't use when ==\n"
            "- 需要 raw measurement value 或要畫 chart → 用 get_process_info\n"
            "- 需要單一參數的長期時序 → 用 query_object_timeseries\n"
            "\n"
            "== Returns ==\n"
            "{\n"
            "  total_events, ooc_count, ooc_rate,\n"
            "  by_tool:   [{toolID, count, ooc_count}, ...],\n"
            "  by_step:   [{step, count, ooc_count}, ...],\n"
            "  recent_ooc:[{eventTime, lotID, toolID, step, spc_status}, ...]  // 最近 5 筆\n"
            "}\n"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v1/process/summary",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "toolID", "type": "string", "description": "機台 ID，e.g. EQP-01", "required": False},
                {"name": "lotID",  "type": "string", "description": "批次 ID，e.g. LOT-0001", "required": False},
                {"name": "step",   "type": "string", "description": "站點代碼，e.g. STEP_020", "required": False},
                {"name": "since",  "type": "string", "description": "時間窗 '24h'/'7d'/'30d'，不帶時預設 '24h'", "required": False},
            ]
        },
    },
    {
        "name": "get_process_info",
        "description": (
            "== What ==\n"
            "取得 process events，每筆含 SPC + APC + DC + RECIPE 完整 nested 物件資料。\n"
            "**一次呼叫拿到所有相關物件**，不需要再呼叫其他 MCP 補資料。\n"
            "\n"
            "== Use when ==\n"
            "- 需要看單筆/多筆 process 的詳細感測資料\n"
            "- 要做 SPC trend / APC drift / Recipe consistency 分析\n"
            "- 要拿給系統 chart middleware 自動畫 SPC chart（需 objectName='SPC' 或不帶）\n"
            "- 查單一 lot 的根因（不帶 objectName，回傳全部 4 種物件）\n"
            "\n"
            "== Don't use when ==\n"
            "- 只要 OOC 統計數字 → 用 get_process_summary 更快\n"
            "- 要看單一參數 30+ 天的長期時序 → 用 query_object_timeseries\n"
            "\n"
            "== Required params ==\n"
            "至少帶 toolID / lotID / step 三選一（不帶會回 400）\n"
            "\n"
            "== Optional params ==\n"
            "objectName : 'SPC' | 'APC' | 'DC' | 'RECIPE' | 'FDC' | 'EC'（filter to one；不帶=全回）\n"
            "since      : '24h' | '7d' | '30d'（時間窗，不帶時預設 '24h'）\n"
            "limit      : 1~200（最近 N 筆，預設 50；查「最近 N 次 process」用此欄位）\n"
            "eventTime  : ISO8601（精確定位某次 process）\n"
            "\n"
            "== Returns ==\n"
            "{\n"
            "  total: int,\n"
            "  events: [\n"
            "    {\n"
            "      eventTime, lotID, toolID, step, spc_status, fdc_classification,\n"
            "      SPC?:    {charts: {xbar_chart: {value, ucl, lcl, is_ooc}, r_chart, s_chart, p_chart, c_chart}, spc_status},\n"
            "      APC?:    {objectID, mode, parameters: {etch_time_offset, rf_power_bias, ... ~20 params}},\n"
            "      DC?:     {objectID, parameters: {chamber_pressure, rf_forward_power, ... ~30 sensors}},\n"
            "      RECIPE?: {objectID, recipe_version, parameters: {etch_time_s, target_thickness_nm, ...}},\n"
            "      FDC?:    {classification: 'NORMAL'|'WARNING'|'FAULT', fault_code, confidence, contributing_sensors, description},\n"
            "      EC?:     {constants: {rf_power_offset: {value, nominal, tolerance_pct, deviation_pct, status, unit}, ...}}\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "\n"
            "events 已按 eventTime DESC 排序。欄位用 camelCase。spc_status 值是 'PASS'|'OOC'。\n"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v1/process/info",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "toolID",     "type": "string", "description": "機台 ID，e.g. EQP-01", "required": False},
                {"name": "lotID",      "type": "string", "description": "批次 ID，e.g. LOT-0001", "required": False},
                {"name": "step",       "type": "string", "description": "站點代碼，e.g. STEP_020", "required": False},
                {"name": "objectName", "type": "string", "description": "物件篩選：SPC / DC / APC / RECIPE", "required": False},
                {"name": "eventTime",  "type": "string", "description": "ISO8601 精確定位某次 process（可選）", "required": False},
                {"name": "since",      "type": "string", "description": "時間窗 '24h'/'7d'/'30d'（與 limit 二選一；查『最近 N 次』請用 limit）", "required": False},
                {"name": "limit",      "type": "integer", "description": "回傳最近 N 筆 events（1~500，預設 50）。查『最近 N 次 process』請用此欄位。", "required": False},
            ]
        },
    },
    # query_object_timeseries — DISABLED from LLM catalog.
    # Endpoint still exists at /api/v1/objects/query but LLM can't see it.
    # Reason: LLM consistently picks this over get_process_info for SPC queries,
    # then calls it 5x (once per chart_type) and invents non-existent chart names.
    # get_process_info(objectName='SPC') returns all 5 charts in one call.
    {
        "name": "list_tools",
        "description": (
            "== What ==\n"
            "列出廠內所有機台及其目前狀態。\n"
            "\n"
            "== Use when ==\n"
            "- 確認有哪些機台 ID 可用\n"
            "- 查每台機台目前是 Busy / Idle / Maintenance\n"
            "\n"
            "== Returns ==\n"
            "[{tool_id, status}, ...]  // 約 10 筆\n"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v1/tools",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {"fields": []},
    },
    {
        "name": "get_simulation_status",
        "description": (
            "== What ==\n"
            "Simulator 整體狀態快照（系統健康檢查用）。\n"
            "\n"
            "== Use when ==\n"
            "- 了解目前有多少 lot 在跑、多少機台 busy\n"
            "- 確認 simulator 是否正常運作\n"
            "\n"
            "== Returns ==\n"
            "{lots: {Processing, Waiting}, tools: {Busy}, total_events, total_snapshots}\n"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v1/status",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {"fields": []},
    },
    # NOTE: get_lot_trajectory, get_tool_trajectory, etc. were using /api/v2/ontology/...
    # endpoints which do NOT exist in the current OntologySimulator. Removed to prevent
    # seeding broken MCPs. Re-add when v2 endpoints are implemented.
]

_UNUSED_V2_MCPS = [
    {
        "name": "get_lot_trajectory",
        "description": (
            "【批次製程路徑】查詢一個批次走過的所有步驟序列。\n"
            "回傳結構：{lot_id, total_steps, steps: [{step, tool_id, start_time, end_time, recipe_id, apc_id, spc_status, dc_snapshot_id, spc_snapshot_id}]}\n"
            "- steps 已去重複（每個 step 一筆，合併 ProcessStart + ProcessEnd）\n"
            "- spc_status: 'PASS'、'OOC' 或 null（null 表示步驟進行中，尚無 ProcessEnd）\n"
            "- start_time/end_time: ISO8601 字串，可帶入 get_process_context 的 event_time\n"
            "使用時機：\n"
            "  ① 這批貨在哪些步驟發生 OOC？→ 過濾 spc_status='OOC'\n"
            "  ② 這批貨跑了哪台機台？→ 看 tool_id\n"
            "  ③ 只要最近 N 步：填 limit\n"
            "⚠️ 此 simulator 時間軸與現實日曆無關。使用者說「今天」→ 不要加 start_time/end_time，直接查。"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v2/ontology/trajectory/lot/{{lot_id}}",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "lot_id",     "type": "string",  "description": "批次 ID，格式 LOT-XXXX，e.g. LOT-0001", "required": True},
                {"name": "start_time", "type": "string",  "description": "查詢時間窗口起始（ISO8601），e.g. 2026-03-15T05:00:00（可選）⚠️ 僅在使用者提供明確時間戳時使用，勿從「今天」推算", "required": False},
                {"name": "end_time",   "type": "string",  "description": "查詢時間窗口結束（ISO8601），e.g. 2026-03-15T12:00:00（可選）⚠️ 同上", "required": False},
                {"name": "limit",      "type": "integer", "description": "回傳步驟筆數上限，預設 500（可選）", "required": False},
            ]
        },
    },
    {
        "name": "get_tool_trajectory",
        "description": (
            "【機台批次履歷】查詢一台機台最近處理過的所有批次與步驟。\n"
            "回傳結構：{tool_id, tool_info, total_batches, batches: [{lot_id, step, start_time, end_time, recipe_id, apc_id, spc_status, dc_snapshot_id, spc_snapshot_id}]}\n"
            "- 每筆 batch 已含 apc_id + spc_status，**不需要再呼叫其他 API 就能直接統計 APC 與 OOC 的關聯**\n"
            "- spc_status: 'PASS'、'OOC' 或 null（進行中）\n"
            "\n"
            "⚠️ 日期篩選鐵律：此 simulator 的時間軸與現實日曆無關。\n"
            "  - 使用者說「今天」、「最近」→ **直接呼叫，不帶 start_time/end_time**（結果已按時間倒序，最新在前）\n"
            "  - 若加了時間篩選卻回傳空 batches，必須立即重試（不帶時間篩選）再分析\n"
            "  - 只有在使用者提供明確時間戳（如 '2026-03-15T06:00:00'）時才使用時間篩選\n"
            "\n"
            "✅ 正確使用流程（APC OOC 分析）：\n"
            "  1. 呼叫本 API（不帶時間篩選）取得 batches 清單\n"
            "  2. 直接從 batches 過濾 spc_status='OOC'，統計各 apc_id 出現次數\n"
            "  3. 排序得出「OOC 最多的 APC 模型」→ 不需要追查每個 lot\n"
            "\n"
            "❌ 錯誤用法：\n"
            "  - 把「今天」轉成日曆日期（如 2025-04-05）後當 start_time 傳入 → 一定空\n"
            "  - 拿到 batches 後再逐一呼叫 get_lot_trajectory（沒必要，資料已在 batches 裡）\n"
            "\n"
            "其他使用時機：\n"
            "  ① 這台機台最近跑過哪些貨？→ 直接呼叫，不加時間\n"
            "  ② 異常前最後幾批：加 limit=20，結果已按時間倒序排列（最新在前）"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v2/ontology/trajectory/tool/{{tool_id}}",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "tool_id",    "type": "string",  "description": "機台 ID，格式 EQP-XX，e.g. EQP-01", "required": True},
                {"name": "start_time", "type": "string",  "description": "查詢時間窗口起始（ISO8601）⚠️ 僅在使用者提供明確時間戳時使用，勿從「今天」推算日期", "required": False},
                {"name": "end_time",   "type": "string",  "description": "查詢時間窗口結束（ISO8601）⚠️ 同上，勿推算", "required": False},
                {"name": "limit",      "type": "integer", "description": "回傳批次筆數上限，預設 200（可選）", "required": False},
            ]
        },
    },
    {
        "name": "get_tool_step_trajectory",
        "description": (
            "【機台×步驟交叉查詢】查詢某台機台上，特定步驟跑過哪些批次，並列出每批次的 SPC 結果。\n"
            "回傳結構：{tool_id, step, total_batches, batches: [{lot_id, start_time, end_time, recipe_id, apc_id, spc_status, dc_snapshot_id, spc_snapshot_id}], summary}\n"
            "- summary 直接寫出 OOC 數量，e.g. 'Tool EQP-01, Step STEP_002: 2 lot(s) found. OOC: 1 / 2.'\n"
            "使用時機：\n"
            "  ① 某台機台在某步驟的良率/OOC 率 → 直接看 summary\n"
            "  ② 找出該步驟所有 OOC 批次 → 過濾 spc_status='OOC'\n"
            "  ③ 跨時段比較：加 start_time/end_time（需明確時間戳，勿用「今天」推算）\n"
            "⚠️ simulator 時間軸與現實日曆無關，使用者說「今天」→ 不帶時間篩選直接查"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v2/ontology/trajectory/tool/{{tool_id}}/step/{{step}}",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "tool_id",    "type": "string",  "description": "機台 ID，格式 EQP-XX，e.g. EQP-01", "required": True},
                {"name": "step",       "type": "string",  "description": "步驟代碼，格式 STEP_XXX，e.g. STEP_002", "required": True},
                {"name": "start_time", "type": "string",  "description": "查詢時間窗口起始（ISO8601），可選", "required": False},
                {"name": "end_time",   "type": "string",  "description": "查詢時間窗口結束（ISO8601），可選", "required": False},
                {"name": "limit",      "type": "integer", "description": "回傳批次筆數上限，預設 200（可選）", "required": False},
            ]
        },
    },
    {
        "name": "get_object_history",
        "description": (
            "【物件歷史快照序列】查詢一個物件在不同時間點的參數快照，追蹤長期趨勢。\n"
            "回傳結構：{object_type, object_id, total_records, history: [{snapshot_id, event_time, lot_id, tool_id, step, spc_status, parameters: {}}]}\n"
            "object_type 與 object_id 的對應：\n"
            "  - APC：object_id 格式 APC-XXX（e.g. APC-005），同一個 APC 模型被多批次使用，history 有多筆\n"
            "       parameters 含：rf_power_bias, model_intercept 等 APC 調整量，用於追蹤 APC 漂移\n"
            "  - RECIPE：object_id 格式 RCP-XXX（e.g. RCP-018），追蹤 Recipe 參數修改歷史\n"
            "  - DC：object_id 格式 DC-LOT-XXXX-STEP_XXX-timestamp，每次製程唯一，通常只有 1 筆\n"
            "       parameters 含：chamber_pressure, foreline_pressure 等 30 個量測值\n"
            "  - SPC：object_id 格式 SPC-LOT-XXXX-STEP_XXX-timestamp，每次製程唯一，通常只有 1 筆\n"
            "⚠️ APC/RECIPE 的 object_id 可從 get_lot_trajectory 或 get_process_context 的 apc_id/recipe_id 欄位取得\n"
            "⚠️ DC/SPC 的 object_id 唯一對應一次製程，要追蹤趨勢應改用 get_tool_trajectory + get_process_context"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v2/ontology/history/{{object_type}}/{{object_id}}",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "object_type", "type": "string",  "description": "物件類型：APC / DC / SPC / RECIPE（大寫）", "required": True},
                {"name": "object_id",   "type": "string",  "description": "物件 ID，e.g. APC-005 或 RCP-018（從 get_lot_trajectory 的 apc_id/recipe_id 欄位取得）", "required": True},
                {"name": "start_time",  "type": "string",  "description": "查詢時間窗口起始（ISO8601），可選", "required": False},
                {"name": "end_time",    "type": "string",  "description": "查詢時間窗口結束（ISO8601），可選", "required": False},
                {"name": "limit",       "type": "integer", "description": "回傳筆數上限，預設 200（可選）", "required": False},
            ]
        },
    },
    {
        "name": "get_baseline_stats",
        "description": (
            "【DC 參數基準統計】計算某台機台歷史上的 DC 參數統計基準（mean/std_dev/3σ 控制限）。\n"
            "回傳結構：{tool_id, sample_count, param_count, stats: {參數名: {mean, std_dev, min, max, ucl_3sigma, lcl_3sigma}}, summary}\n"
            "- stats 含 ~30 個 DC 參數，如 chamber_pressure, throttle_position_pct 等\n"
            "- ucl_3sigma = mean + 3×std_dev，lcl_3sigma = mean - 3×std_dev\n"
            "使用時機：\n"
            "  ① 拿到某批次的 DC 量測值後，與此基準比較判斷是否異常\n"
            "  ② 建立 SPC 控制圖的管制界限\n"
            "  ③ 搭配 recipe_id 過濾，只統計特定 Recipe 的歷史數據"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v2/ontology/stats/baseline",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "tool_id",    "type": "string", "description": "機台 ID，格式 EQP-XX，e.g. EQP-01", "required": True},
                {"name": "recipe_id",  "type": "string", "description": "只統計使用此 Recipe 的批次，格式 RCP-XXX，e.g. RCP-013（可選）", "required": False},
                {"name": "start_time", "type": "string", "description": "統計區間起始（ISO8601），可選", "required": False},
                {"name": "end_time",   "type": "string", "description": "統計區間結束（ISO8601），可選", "required": False},
            ]
        },
    },
    {
        "name": "search_ooc_events",
        "description": (
            "【跨批次 OOC 事件搜尋】快速搜尋符合條件的 SPC 異常事件，支援多維度過濾。\n"
            "⚠️ 此 MCP 使用 POST 方法，所有參數放在 JSON body 中。\n"
            "回傳結構：{total, ooc_count, pass_count, summary, events: [{event_id, lot_id, tool_id, step, spc_status, event_time, dc_snapshot_id, spc_snapshot_id}]}\n"
            "- summary 已整理好統計摘要，可直接引用\n"
            "- events 按 event_time 倒序（最新在前）\n"
            "使用時機（所有參數均可選，全空則回傳最新 50 筆）：\n"
            "  ① 某機台的全部 OOC：填 tool_id='EQP-01', status='OOC'\n"
            "  ② 某批次的所有異常：填 lot_id='LOT-0002'\n"
            "  ③ 某步驟跨機台的 OOC：填 step='STEP_072'\n"
            "  ④ 時段內異常：填 start_time/end_time\n"
            "  ⑤ 拿到 event 後，用 dc_snapshot_id 或 lot_id+step 進一步呼叫 get_process_context 展開細節"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v2/ontology/search",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
        },
        "input_schema": {
            "fields": [
                {"name": "tool_id",    "type": "string",  "description": "機台 ID（可選），e.g. EQP-01", "required": False},
                {"name": "lot_id",     "type": "string",  "description": "批次 ID（可選），e.g. LOT-0002", "required": False},
                {"name": "step",       "type": "string",  "description": "步驟代碼（可選），e.g. STEP_072", "required": False},
                {"name": "status",     "type": "string",  "description": "SPC 狀態過濾：'OOC' 或 'PASS'（可選）", "required": False},
                {"name": "start_time", "type": "string",  "description": "查詢時間窗口起始（ISO8601），可選", "required": False},
                {"name": "end_time",   "type": "string",  "description": "查詢時間窗口結束（ISO8601），可選", "required": False},
                {"name": "limit",      "type": "integer", "description": "回傳筆數上限，預設 50（可選）", "required": False},
            ]
        },
    },
    {
        "name": "get_tools_status_overview",
        "description": (
            "【機台清單與狀態總覽】一次取得廠內所有機台（EQP-01～EQP-10）的即時狀態。\n"
            "\n"
            "回傳欄位說明：\n"
            "- tool_id: 機台代碼（EQP-01 ~ EQP-10）\n"
            "- current_status: 機台目前狀態 — 'Busy'（有批次在跑）或 'Idle'（閒置）\n"
            "- current_lot: 若 Busy，顯示目前正在處理的批次 ID；若 Idle 則為 null\n"
            "- last_spc_status: 最近一批完成後的 SPC 結果 — 'PASS'、'OOC'、或 'N/A'\n"
            "- recent_ooc_count: 最近 N 批中 SPC = OOC 的次數（N 由 recent_batches 參數決定，預設 5）\n"
            "- last_activity: 最後一次 ProcessEnd 時間（ISO8601），代表最後完成批次的時間\n"
            "- total_batches_processed: 該機台歷史上處理的批次總數\n"
            "\n"
            "典型使用情境：\n"
            "① 「哪些機台是閒置的？」→ 直接查詢，過濾 current_status='Idle'\n"
            "② 「哪些機台最近有 OOC？」→ 過濾 last_spc_status='OOC' 或 recent_ooc_count > 0\n"
            "③ 「機台清單和狀態」→ 直接呼叫，無需任何參數\n"
            "④ 快速判斷整體廠況健康度前的第一步查詢\n"
            "\n"
            "⚠️ 此 API 不需要任何必填參數，直接呼叫即可取得所有機台狀態。\n"
            "⚠️ 若需要某機台的詳細製程歷史，請接著呼叫 get_tool_trajectory（帶入 tool_id）。"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v2/ontology/tools/status",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "recent_batches", "type": "integer", "description": "每台機台統計最近幾批的 OOC 情況，預設 5，最大 20（可選）", "required": False},
            ]
        },
    },
    {
        "name": "get_dc_timeseries",
        "description": (
            "【DC 參數時間序列】取得特定機台 × 站點的 DC 製程參數時間序列，專為 SPC Chart 設計。\n"
            "\n"
            "每個資料點 = 一次 ProcessEnd（一批貨跑完這個站），時間順序由舊到新。\n"
            "\n"
            "回傳內容：\n"
            "- series: { 參數名: [{t, lot_id, value}, ...] } — 每個參數的時間序列值\n"
            "- baseline: { 參數名: {mean, std_dev, ucl_3sigma, lcl_3sigma} } — 同窗口計算的管制界限\n"
            "- spc_status_series: [{t, lot_id, spc_status}] — 每個時間點是否 OOC，用於標記異常點\n"
            "- param_names: 所有可用的 DC 參數名稱清單\n"
            "- sample_count: 回傳的資料點數\n"
            "\n"
            "典型使用情境：\n"
            "① 畫 SPC 趨勢圖：用 series[param] 的 value + baseline[param] 的 ucl/lcl 畫折線圖\n"
            "② 偵測連續 OOC：分析 spc_status_series 找連續幾點 status=OOC\n"
            "③ 參數偏移診斷：比較最近幾點的 value 是否持續偏向 UCL 或 LCL 方向\n"
            "④ 多參數比較：同時看多個 DC 參數的走勢，找出異常根因\n"
            "\n"
            "⚠️ 必填：tool_id（機台）和 step（站點）\n"
            "⚠️ 可選：params（只取指定參數，逗號分隔，e.g. 'chamber_pressure,cf4_flow_sccm'）；limit（預設 50 筆）\n"
            "⚠️ 與 get_process_context 的差別：get_process_context 是「單批單點」的完整快照；"
            "get_dc_timeseries 是「多批時間序列」，只有 DC 數值，適合趨勢分析和 SPC 圖表。"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v2/ontology/timeseries/tool/{{tool_id}}/step/{{step}}",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "tool_id", "type": "string",  "description": "機台代碼，e.g. EQP-01", "required": True},
                {"name": "step",    "type": "string",  "description": "站點代碼，e.g. STEP_072", "required": True},
                {"name": "params",  "type": "string",  "description": "要取的 DC 參數名稱（逗號分隔），e.g. 'chamber_pressure,cf4_flow_sccm'，不填則回傳全部（可選）", "required": False},
                {"name": "limit",   "type": "integer", "description": "回傳最近幾筆製程記錄，預設 50，最大 500（可選）", "required": False},
            ]
        },
    },
    {
        "name": "get_equipment_constants",
        "description": (
            "【機台設備常數 Equipment Constants】查詢一台機台的當前設備常數與黃金基準比對。\n"
            "回傳結構：{tool_id, constants: {param_name: {value, setpoint, tolerance_pct, deviation_pct, status}}, drift_count, summary}\n"
            "- status: 'NORMAL' | 'DRIFT' | 'ALERT'\n"
            "- drift_count: 偏移超出容忍值的參數數量\n"
            "- summary: 一句直接可用的摘要（e.g. '3 parameters drifting, rf_power_offset most critical'）\n"
            "使用時機：\n"
            "  ① 機台發生異常時，快速確認 EC 是否為根因\n"
            "  ② 定期巡檢 EC 漂移狀況\n"
            "  ③ OOC 根因分析時，排除或確認 EC 異常\n"
            "⚠️ 不需要任何時間參數，直接帶入 tool_id 即可"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v2/ontology/equipment/{{tool_id}}/constants",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "tool_id", "type": "string", "description": "機台 ID，格式 EQP-XX，e.g. EQP-01", "required": True},
            ]
        },
    },
    {
        "name": "get_fdc_uchart",
        "description": (
            "【FDC U-Chart 缺陷密度管制圖】查詢一台機台在特定步驟的 FDC 缺陷計數時序，以 U-chart 呈現。\n"
            "回傳結構：{tool_id, step, uchart: [{event_time, lot_id, defect_count, sample_size, u_value, spc_status}], baseline: {u_bar, ucl, lcl, n_average}, ooc_count, summary}\n"
            "- u_value = defect_count / sample_size（每單位缺陷數）\n"
            "- spc_status: 'PASS' | 'OOC'\n"
            "- baseline.ucl/lcl 為動態控制限（依 u_bar 與 sample_size 計算）\n"
            "使用時機：\n"
            "  ① 監控製程缺陷率趨勢（純視覺化）\n"
            "  ② 結合 SPC OOC 事件做雙重驗證\n"
            "  ③ 製程改善前後比對\n"
            "⚠️ 使用 analyze_data(template='spc_chart') 畫圖時：value_col='u_value', time_col='event_time', ucl=baseline.ucl, lcl=baseline.lcl"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v2/ontology/fdc/{{tool_id}}/uchart",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "tool_id", "type": "string", "description": "機台 ID，格式 EQP-XX，e.g. EQP-01", "required": True},
                {"name": "step",    "type": "string", "description": "步驟代碼，格式 STEP_XXX，e.g. STEP_002（可選，不填則返回所有步驟）", "required": False},
                {"name": "limit",   "type": "integer", "description": "回傳批次數上限，預設 50（可選）", "required": False},
            ]
        },
    },
    {
        "name": "get_ocap",
        "description": (
            "【OCAP 異常處置計畫 Out-of-Control Action Plan】當 SPC_status=OOC 時，查詢對應的標準處置流程。\n"
            "回傳結構：{lot_id, step, spc_status, triggered_by: [{chart, parameter, violation_type, value, ucl, lcl}], "
            "actions: [{priority, category, action, owner, deadline_hours}], severity, summary}\n"
            "- triggered_by: 哪些 SPC chart 觸發 OOC + 違規類型（超出控制限 / 連續趨勢 / 等）\n"
            "- actions: 依優先序排列的處置步驟，包含負責人與時限\n"
            "- severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'\n"
            "使用時機：\n"
            "  ① 確認某批次 OOC 後，立即查詢應採取哪些行動\n"
            "  ② 與 get_process_context 搭配，做完整根因分析\n"
            "  ③ spc_status=PASS 時仍可呼叫，回傳 actions=[] severity='LOW'\n"
            "⚠️ lot_id + step 都必須填入；可從 get_lot_trajectory 或 get_tool_trajectory 取得"
        ),
        "api_config": {
            "endpoint_url": f"{_SIM}/api/v2/ontology/ocap/{{lot_id}}/{{step}}",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "lot_id", "type": "string", "description": "批次 ID，格式 LOT-XXXX，e.g. LOT-0001", "required": True},
                {"name": "step",   "type": "string", "description": "步驟代碼，格式 STEP_XXX，e.g. STEP_005", "required": True},
            ]
        },
    },
]  # end _UNUSED_V2_MCPS


_SEED_EVENT_TYPES = [
    {
        "name": "OOC",
        "description": "SPC Out-of-Control violation — published by Ontology Simulator via NATS when any sensor breaches control limits",
        "attributes": [
            {"name": "equipment_id",  "type": "string",  "required": True,  "description": "機台代碼 (e.g. CVD-01)"},
            {"name": "lot_id",        "type": "string",  "required": True,  "description": "批次 ID (e.g. LOT-8821)"},
            {"name": "step_id",       "type": "string",  "required": True,  "description": "製程步驟代碼"},
            {"name": "parameter",     "type": "string",  "required": True,  "description": "違反管制界限的感測器參數"},
            {"name": "ooc_details",   "type": "object",  "required": True,  "description": "{ rule, value, ucl, lcl, sigma }"},
            {"name": "severity",      "type": "string",  "required": False, "description": "warning | critical"},
            {"name": "timestamp",     "type": "string",  "required": False, "description": "ISO 8601 事件時間"},
        ],
    },
    {
        "name": "SPC_OOC_Etch_CD",
        "description": "Etch 製程 CD (Critical Dimension) SPC 超出管制界限 (Out-of-Control) 事件",
        "attributes": [
            {"name": "lot_id",                "type": "string",  "required": True,  "description": "觸發事件的批次 ID"},
            {"name": "tool_id",               "type": "string",  "required": True,  "description": "發生異常的蝕刻機台代碼"},
            {"name": "chamber_id",            "type": "string",  "required": True,  "description": "異常腔體編號 (e.g., CH1, CH2)"},
            {"name": "recipe_id",             "type": "string",  "required": False, "description": "當時執行的 Recipe ID"},
            {"name": "operation_number",      "type": "string",  "required": True,  "description": "站點代碼 (e.g., 3200)"},
            {"name": "apc_model_name",        "type": "string",  "required": False, "description": "觸發時使用的 APC 模型名稱"},
            {"name": "process_timestamp",     "type": "string",  "required": True,  "description": "製程完成時間戳記 (ISO 8601)"},
            {"name": "ooc_parameter",         "type": "string",  "required": True,  "description": "超出管制界限的量測參數名稱 (e.g., CD_Mean)"},
            {"name": "rule_violated",         "type": "string",  "required": True,  "description": "違反的 SPC 管制規則 (e.g., Western Electric Rule 1)"},
            {"name": "consecutive_ooc_count", "type": "number",  "required": True,  "description": "連續超出管制的點位次數"},
            {"name": "SPC_CHART",             "type": "string",  "required": True,  "description": "SPC 圖表名稱，對應 DataSubject 查詢參數 chart_name (e.g., CD)"},
        ],
    },
]


_DEFAULT_SYSTEM_PARAMS = [
    {
        "key": "PROMPT_MCP_GENERATE",
        "description": "MCP 設計時 LLM 生成 Prompt（使用者訊息範本，含 {data_subject_name}, {data_subject_output_schema}, {processing_intent} 變數）",
        "value": (
            "你是半導體製程系統整合專家，同時也是 Python 資料處理工程師。\n\n"
            "以下是一個 DataSubject（資料源）的名稱與輸出格式：\n"
            "DataSubject 名稱：{data_subject_name}\n"
            "輸出 Schema（Raw Format）：\n"
            "{data_subject_output_schema}\n\n"
            "使用者希望對此資料執行以下加工意圖：\n"
            "「{processing_intent}」\n\n"
            "請完成以下 4 項任務，以 JSON 格式回傳：\n\n"
            "1. **processing_script**（str）：\n"
            "   - 撰寫一段 Python 函式 `process(raw_data: dict) -> dict`\n"
            "   - raw_data 的結構符合上面的輸出 Schema\n"
            "   - 根據加工意圖進行計算（例如：計算移動平均、標示 OOC、排序等）\n"
            "   - 回傳的 dict 結構就是處理後的 Dataset\n\n"
            "2. **output_schema**（object）：\n"
            '   - 定義 process() 函式回傳值的 Schema\n'
            '   - 格式：{"fields": [{"name": str, "type": str, "description": str}]}\n\n'
            "3. **ui_render_config**（object）：\n"
            "   - 根據輸出 Schema 建議最適合的圖表呈現方式\n"
            '   - 格式：{"chart_type": "trend|bar|table|scatter", "x_axis": str, "y_axis": str, "series": [str], "notes": str}\n\n'
            "4. **input_definition**（object）：\n"
            "   - 分析此加工邏輯需要哪些 Input 參數\n"
            '   - 格式：{"params": [{"name": str, "type": str, "source": "event|manual|data_subject", "description": str, "required": bool}]}\n\n'
            "5. **summary**（str）：對整個 MCP 設計的一句話摘要\n\n"
            "只回傳 JSON，不要有其他文字：\n"
            '{\n  "processing_script": "...",\n  "output_schema": {},\n  "ui_render_config": {},\n  "input_definition": {},\n  "summary": "..."\n}'
        ),
    },
    {
        "key": "PROMPT_MCP_TRY_RUN",
        "description": "MCP Try Run 時的 LLM System Prompt（安全規範 + 沙盒可用清單 + 多圖記憶體繪圖規範 + 標準輸出格式）",
        "value": _DEFAULT_TRY_RUN_SYSTEM_PROMPT,
    },
    {
        "key": "PROMPT_SKILL_DIAGNOSIS",
        "description": "Skill 模擬診斷 LLM System Prompt（診斷 AI 角色定義 + 固定 JSON 輸出格式）",
        "value": (
            "你是智能診斷 AI。根據使用者提供的「異常判斷條件」與 MCP 輸出資料，判斷該條件是否被觸發。\n\n"
            "【核心概念】使用者撰寫的是「異常判斷條件（anomaly condition）」，不是正常條件。\n"
            "你的任務：判斷此異常條件在資料中是否成立。\n\n"
            "【status 判定規則 — 嚴格二選一】\n"
            "- ABNORMAL：資料「符合」使用者描述的異常條件 → 回傳 ABNORMAL\n"
            "- NORMAL  ：資料「不符合」使用者描述的異常條件 → 回傳 NORMAL\n\n"
            "⚠️ conclusion 與 status 必須一致。\n\n"
            "【重要限制】絕對不可生成任何「處置建議 (recommendation)」，那是由領域專家撰寫。\n\n"
            "【回傳格式 — 只回傳 JSON，不要其他文字，不要 markdown fence】\n"
            "{\n"
            '  "status": "NORMAL 或 ABNORMAL",\n'
            '  "conclusion": "一句話結論",\n'
            '  "evidence": ["具體觀察 1", "具體觀察 2"],\n'
            '  "summary": "2~3 句完整說明"\n'
            "}"
        ),
    },
]


# Phase 1 memory system replaces these static seeds. The reflective
# experience memory (agent_experience_memory table) now handles learning
# from successful interactions. Stale system memories caused more harm
# than good — the "禁止用 execute_jit 畫 SPC" rule directly contradicted
# the new _chart DSL architecture and kept regenerating every restart.
_SYSTEM_MEMORIES: list = [
    # Intentionally empty — Phase 1 memory lifecycle handles all agent learning.
    # Legacy seeds removed:
    #   - "SPC 限制" → contradicted _chart DSL, kept regenerating
    #   - "時間篩選鐵律" → now encoded in soul prompt §1.15, doesn't need RAG
]


async def _seed_data() -> None:
    """On startup: create default users, built-in DataSubjects/EventTypes, SystemParameters."""
    from sqlalchemy import select, delete
    from app.models.data_subject import DataSubjectModel
    from app.models.event_type import EventTypeModel
    from app.models.system_parameter import SystemParameterModel
    from app.models.user import UserModel
    from app.core.security import get_password_hash
    import json as _json

    _DEFAULT_USERS = [
        {"username": "admin", "email": "admin@example.com", "password": "admin",
         "is_superuser": True, "roles": ["it_admin", "expert_pe", "general_user"]},
        {"username": "gill",  "email": "gill@example.com",  "password": "gill",
         "is_superuser": True, "roles": ["it_admin", "expert_pe", "general_user"]},
    ]

    async for db in get_db():
        # ── 0. Seed default users ────────────────────────────────────────────
        for u in _DEFAULT_USERS:
            result = await db.execute(
                select(UserModel).where(UserModel.username == u["username"])
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                obj = UserModel(
                    username=u["username"],
                    email=u["email"],
                    hashed_password=get_password_hash(u["password"]),
                    is_active=True,
                    is_superuser=u["is_superuser"],
                    roles=_json.dumps(u["roles"]),
                )
                db.add(obj)
                logger.info("Seeded default user: %s", u["username"])
            else:
                # Ensure roles are up-to-date
                desired = _json.dumps(u["roles"])
                if existing.roles != desired:
                    existing.roles = desired
                    logger.info("Updated roles for user: %s", u["username"])

        # Commit users so subsequent seed steps can reference them safely
        # (Postgres enforces FKs strictly; SQLite historically had them off).
        try:
            await db.commit()
        except Exception as _user_commit_err:
            logger.warning("User seed commit failed: %s", _user_commit_err)
            await db.rollback()

        # ── 0b. Optional cleanup: set env var RESET_TO_ONTOLOGY_ONLY=true to trigger ──
        # Removes all custom MCPs, Skills, RoutineChecks, GeneratedEvents, and legacy
        # system MCPs — leaving only the canonical _ONTOLOGY_SYSTEM_MCPS.
        # Usage:
        #   RESET_TO_ONTOLOGY_ONLY=true uvicorn main:app          # local
        #   sudo systemctl set-environment RESET_TO_ONTOLOGY_ONLY=true && sudo systemctl restart aiops
        #   sudo systemctl unset-environment RESET_TO_ONTOLOGY_ONLY  # clear after reset
        import os as _os
        if _os.getenv("RESET_TO_ONTOLOGY_ONLY", "").lower() in ("true", "1", "yes"):
            try:
                from app.models.generated_event import GeneratedEventModel
                from app.models.routine_check import RoutineCheckModel
                from app.models.skill_definition import SkillDefinitionModel
                from app.models.mcp_definition import MCPDefinitionModel as _MCPClean

                await db.execute(delete(GeneratedEventModel))
                await db.execute(delete(RoutineCheckModel))
                await db.execute(delete(SkillDefinitionModel))
                await db.execute(delete(_MCPClean).where(_MCPClean.mcp_type == "custom"))
                _canonical_names = {s["name"] for s in _ONTOLOGY_SYSTEM_MCPS}
                await db.execute(
                    delete(_MCPClean).where(
                        (_MCPClean.mcp_type == "system") & (_MCPClean.name.notin_(_canonical_names))
                    )
                )
                await db.commit()
                logger.info("RESET_TO_ONTOLOGY_ONLY: cleanup complete")
            except Exception as _clean_err:
                logger.warning("RESET_TO_ONTOLOGY_ONLY cleanup failed: %s", _clean_err)
                await db.rollback()

        # ── 1. Seed built-in DataSubjects (legacy; keep for backward compat) ──
        for spec in _MOCK_DATA_SUBJECTS:
            result = await db.execute(
                select(DataSubjectModel).where(DataSubjectModel.name == spec["name"])
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                obj = DataSubjectModel(
                    name=spec["name"],
                    description=spec["description"],
                    api_config=_json.dumps(spec["api_config"], ensure_ascii=False),
                    input_schema=_json.dumps(spec["input_schema"], ensure_ascii=False),
                    output_schema=_json.dumps(spec["output_schema"], ensure_ascii=False),
                    is_builtin=True,
                )
                db.add(obj)
                logger.info("Seeded built-in DataSubject: %s", spec["name"])
            else:
                # Always keep builtin schemas in sync with spec
                new_input  = _json.dumps(spec["input_schema"],  ensure_ascii=False)
                new_output = _json.dumps(spec["output_schema"], ensure_ascii=False)
                changed = False
                if existing.input_schema != new_input:
                    existing.input_schema = new_input
                    changed = True
                if existing.output_schema != new_output:
                    existing.output_schema = new_output
                    changed = True
                if changed:
                    logger.info("Updated schemas for DataSubject: %s", spec["name"])

        # ── 1c. Seed OntologySimulator system MCPs ────────────────────────────
        from app.models.mcp_definition import MCPDefinitionModel as _MCPModel
        try:
            for spec in _ONTOLOGY_SYSTEM_MCPS:
                result = await db.execute(
                    select(_MCPModel).where(
                        _MCPModel.name == spec["name"],
                        _MCPModel.mcp_type == "system",
                    )
                )
                existing_mcp = result.scalar_one_or_none()
                if existing_mcp is None:
                    sys_obj = _MCPModel(
                        name=spec["name"],
                        description=spec["description"],
                        mcp_type="system",
                        api_config=_json.dumps(spec["api_config"], ensure_ascii=False),
                        input_schema=_json.dumps(spec["input_schema"], ensure_ascii=False),
                        processing_intent="",
                        visibility="public",
                    )
                    db.add(sys_obj)
                    logger.info("Seeded OntologySim system MCP: %s", spec["name"])
                else:
                    # Always sync description and schemas from canonical spec
                    existing_mcp.description = spec["description"]
                    existing_mcp.api_config = _json.dumps(spec["api_config"], ensure_ascii=False)
                    existing_mcp.input_schema = _json.dumps(spec["input_schema"], ensure_ascii=False)
                    logger.info("Updated OntologySim system MCP: %s", spec["name"])
            # Remove stale system MCPs not in canonical list
            _canonical_names = {s["name"] for s in _ONTOLOGY_SYSTEM_MCPS}
            _stale_result = await db.execute(
                select(_MCPModel).where(
                    _MCPModel.mcp_type == "system",
                    _MCPModel.name.notin_(_canonical_names),
                )
            )
            for stale_mcp in _stale_result.scalars().all():
                logger.info("Removing stale system MCP: %s (id=%s)", stale_mcp.name, stale_mcp.id)
                await db.delete(stale_mcp)

        except Exception as _seed_err2:
            logger.warning("OntologySim MCP seeding skipped: %s", _seed_err2)
            await db.rollback()

        # ── 1d. Seed system shared memories ────────────────────────────────────
        # System memories are attached to the admin user (first seeded user).
        # SQLite historically allowed user_id=0 (FKs off by default); Postgres
        # enforces FKs strictly, so we anchor these on a real user row.
        try:
            from app.models.agent_memory import AgentMemoryModel as _MemModel
            import json as _json2

            # Find the admin user to own system memories
            _admin_res = await db.execute(
                select(UserModel).where(UserModel.username == "admin")
            )
            _admin = _admin_res.scalar_one_or_none()
            if _admin is None:
                logger.warning("System memory seeding skipped: admin user not found")
            else:
                _sys_user_id = _admin.id
                for mem_spec in _SYSTEM_MEMORIES:
                    tags_json = _json2.dumps(mem_spec["tags"], ensure_ascii=False)
                    content_prefix = mem_spec["content"][:80]
                    result = await db.execute(
                        select(_MemModel).where(
                            _MemModel.user_id == _sys_user_id,
                            _MemModel.content.like(content_prefix[:60] + "%"),
                        )
                    )
                    existing_mem = result.scalar_one_or_none()
                    if existing_mem is None:
                        db.add(_MemModel(
                            user_id=_sys_user_id,
                            content=mem_spec["content"],
                            source=mem_spec["source"],
                            embedding=tags_json,
                            ref_id=None,
                        ))
                        logger.info("Seeded system memory: %s...", mem_spec["content"][:50])
                    else:
                        existing_mem.content = mem_spec["content"]
                        existing_mem.embedding = tags_json
                        logger.info("Updated system memory: %s...", mem_spec["content"][:50])
            await db.commit()
        except Exception as _mem_err:
            logger.warning("System memory seeding skipped: %s", _mem_err)
            await db.rollback()

        # ── 2. Seed built-in EventTypes (create or update attributes) ─────
        for spec in _SEED_EVENT_TYPES:
            result = await db.execute(
                select(EventTypeModel).where(EventTypeModel.name == spec["name"])
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                obj = EventTypeModel(
                    name=spec["name"],
                    description=spec["description"],
                    attributes=_json.dumps(spec["attributes"], ensure_ascii=False),
                )
                db.add(obj)
                logger.info("Seeded built-in EventType: %s", spec["name"])
            else:
                # Always keep builtin attributes in sync with spec
                new_attrs = _json.dumps(spec["attributes"], ensure_ascii=False)
                if existing.attributes != new_attrs:
                    existing.attributes = new_attrs
                    logger.info("Updated attributes for EventType: %s", spec["name"])

        # ── 3. Seed default SystemParameters (create or force-update critical prompts) ──
        # Keys in this set are always updated to ensure breaking changes propagate.
        _FORCE_UPDATE_PARAMS = {"PROMPT_SKILL_DIAGNOSIS", "PROMPT_MCP_TRY_RUN"}
        for spec in _DEFAULT_SYSTEM_PARAMS:
            result = await db.execute(
                select(SystemParameterModel).where(SystemParameterModel.key == spec["key"])
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                obj = SystemParameterModel(
                    key=spec["key"],
                    value=spec["value"],
                    description=spec["description"],
                )
                db.add(obj)
                logger.info("Seeded SystemParameter: %s", spec["key"])
            elif spec["key"] in _FORCE_UPDATE_PARAMS:
                existing.value = spec["value"]
                existing.description = spec["description"]
                logger.info("Force-updated SystemParameter: %s", spec["key"])

        await db.commit()
        break  # only need one iteration


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


# Module-level task refs to prevent GC from killing background tasks
_bg_tasks: list = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    # Import all models so Base.metadata has them registered
    import app.models  # noqa: F401
    await init_db()
    logger.info("Database initialised")
    await _seed_data()
    logger.info("Startup seeding complete")
    # Phase 11: start the proactive inspection scheduler
    from app.scheduler import start_scheduler, stop_scheduler
    await start_scheduler(base_url=f"http://127.0.0.1:{getattr(settings, 'PORT', 8001)}")
    logger.info("APScheduler started")
    # AIOps: start cron scheduler FIRST, then load persisted jobs
    from app.services.cron_scheduler_service import get_scheduler, load_all_jobs_into_scheduler
    from app.services.auto_patrol_service import load_schedule_patrols_into_scheduler
    cron_scheduler = get_scheduler()
    if not cron_scheduler.running:
        cron_scheduler.start()
        logger.info("AIOps CronScheduler started")
    async for db in get_db():
        await load_all_jobs_into_scheduler(db)
        await load_schedule_patrols_into_scheduler(db)
        break
    # v18: Event-Driven Poller
    from app.services.event_poller_service import run_event_poller
    _bg_tasks.append(asyncio.ensure_future(run_event_poller(interval=30)))
    logger.info("v18 EventPoller started (interval=30s)")
    # v2.0: NATS OOC Event Subscriber (only if NATS is configured and reachable)
    from app.services.nats_subscriber_service import start_nats_subscriber, stop_nats_subscriber
    _nats_url = getattr(settings, "NATS_URL", "") or ""
    if _nats_url and _nats_url != "nats://localhost:4222":
        start_nats_subscriber(_nats_url)
        logger.info("NATS OOC subscriber started (url=%s)", _nats_url)
    else:
        logger.info("NATS subscriber skipped (no NATS server configured)")
    yield
    _poller_task.cancel()
    try:
        await _poller_task
    except asyncio.CancelledError:
        pass
    stop_nats_subscriber()
    cron_scheduler.shutdown(wait=False)
    stop_scheduler()
    logger.info("Application shutting down")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "FastAPI 後端服務 v8 — RBAC · Data Subject · MCP Builder · Skill Builder"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

_PREFIX = settings.API_V1_PREFIX  # default: /api/v1

app.include_router(auth_router, prefix=_PREFIX)
app.include_router(users_router, prefix=_PREFIX)
app.include_router(items_router, prefix=_PREFIX)
app.include_router(diagnostic_router, prefix=_PREFIX)
app.include_router(builder_router, prefix=_PREFIX)
# Phase 8 routers
app.include_router(mock_data_router, prefix=_PREFIX)
app.include_router(mock_data_studio_router, prefix=_PREFIX)
app.include_router(data_subjects_router, prefix=_PREFIX)
app.include_router(event_types_router, prefix=_PREFIX)
app.include_router(mcp_definitions_router, prefix=_PREFIX)
app.include_router(skill_definitions_router, prefix=_PREFIX)
app.include_router(system_parameters_router, prefix=_PREFIX)
# Phase 11 routers
app.include_router(routine_check_router, prefix=_PREFIX)
app.include_router(alarms_router, prefix=_PREFIX)
app.include_router(system_events_router, prefix=_PREFIX)
# Help Chat
app.include_router(help_router, prefix=_PREFIX)
# v12 Agent routers
app.include_router(agent_router, prefix=_PREFIX)
app.include_router(agent_execute_router, prefix=_PREFIX)
app.include_router(agent_draft_router, prefix=_PREFIX)
# v12.5 Expert Mode — bi-directional Markdown parser
app.include_router(agentic_skill_router, prefix=_PREFIX)
app.include_router(agent_tool_router, prefix=_PREFIX)
app.include_router(shadow_analyst_router, prefix=_PREFIX)  # v15.2 Shadow Analyst
app.include_router(generic_tools_router, prefix=_PREFIX)   # v15.3 Generic Tools
# v13 Real Agentic Platform
app.include_router(agent_chat_router, prefix=_PREFIX)
app.include_router(agent_memory_router, prefix=_PREFIX)
app.include_router(agent_preference_router, prefix=_PREFIX)
# AIOps Automation Platform
app.include_router(script_registry_router, prefix=_PREFIX)  # /api/v1/script-registry/...
app.include_router(cron_jobs_router, prefix=_PREFIX)         # /api/v1/cron-jobs/...
app.include_router(actions_router, prefix=_PREFIX)           # /api/v1/actions/...
# v2.0 Auto-Patrol
app.include_router(auto_patrols_router, prefix=_PREFIX)      # /api/v1/auto-patrols/...
# v2.0 Diagnostic Rules
app.include_router(diagnostic_rules_router, prefix=_PREFIX)  # /api/v1/diagnostic-rules/...
# Phase 1: Reflective experience memory
app.include_router(experience_memory_router, prefix=_PREFIX)  # /api/v1/experience-memory/...
app.include_router(monitor_router, prefix=_PREFIX)            # /api/v1/system/monitor
app.include_router(analysis_router, prefix=_PREFIX)            # /api/v1/analysis/run + /promote
app.include_router(my_skills_router, prefix=_PREFIX)           # /api/v1/my-skills/...
app.include_router(briefing_router, prefix=_PREFIX)            # /api/v1/briefing

# ---------------------------------------------------------------------------
# Global Exception Handlers
# ---------------------------------------------------------------------------


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=StandardResponse.error(
            message=exc.detail,
            error_code=exc.error_code,
        ).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = exc.errors()
    detail = "; ".join(
        f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
        for e in errors
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=StandardResponse.error(
            message=detail,
            error_code="UNPROCESSABLE_ENTITY",
        ).model_dump(),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=StandardResponse.error(
            message=str(exc.detail),
            error_code="HTTP_ERROR",
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=StandardResponse.error(
            message="伺服器發生未預期的錯誤",
            error_code="INTERNAL_SERVER_ERROR",
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Utility Endpoints
# ---------------------------------------------------------------------------


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["health"],
    summary="健康檢查",
)
async def health_check() -> HealthResponse:
    from sqlalchemy import text

    db_status = "unavailable"
    try:
        async for session in get_db():
            await session.execute(text("SELECT 1"))
            db_status = "connected"
            break
    except Exception:
        db_status = "unavailable"

    return HealthResponse(
        status="ok" if db_status == "connected" else "degraded",
        version=settings.APP_VERSION,
        database=db_status,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Static Frontend  (mounted LAST so API routes take priority)
# ---------------------------------------------------------------------------

# OntologySimulator Next.js static export (must be mounted before "/" catch-all)
_SIMULATOR_DIR = Path(__file__).parent.parent / "ontology_simulator" / "frontend" / "out"
if _SIMULATOR_DIR.exists():
    app.mount("/simulator", StaticFiles(directory=_SIMULATOR_DIR, html=True), name="simulator")

_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="frontend")


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
