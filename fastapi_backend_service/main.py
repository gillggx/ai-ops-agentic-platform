"""FastAPI Backend Service — Application Entry Point (v8)."""


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
    generated_events_router,
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
)
from app.routers.agent_chat_router import router as agent_chat_router
from app.routers.agent_memory_router import router as agent_memory_router
from app.routers.agent_preference_router import router as agent_preference_router

settings = get_settings()
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
    {
        "name": "OntologySim — 批次清單",
        "description": "OntologySimulator MES：查詢所有批次狀態（Waiting / Processing / Finished）",
        "api_config": {
            "endpoint_url": "http://localhost:8001/api/v1/lots",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "status", "type": "string", "description": "篩選批次狀態（可選：Waiting / Processing / Finished）", "required": False},
            ]
        },
    },
    {
        "name": "OntologySim — 機台狀態",
        "description": "OntologySimulator MES：查詢全部 10 台機台的即時狀態（Idle / Busy / Hold）",
        "api_config": {
            "endpoint_url": "http://localhost:8001/api/v1/tools",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {"fields": []},
    },
    {
        "name": "OntologySim — 事件時間線",
        "description": "OntologySimulator MES：查詢製程事件時間線（TOOL_EVENT / LOT_EVENT）",
        "api_config": {
            "endpoint_url": "http://localhost:8001/api/v1/events",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "toolID", "type": "string", "description": "機台 ID（可選，e.g. EQP-01）", "required": False},
                {"name": "lotID",  "type": "string", "description": "批次 ID（可選，e.g. LOT-0001）", "required": False},
                {"name": "limit",  "type": "integer","description": "回傳筆數上限（預設 50）", "required": False},
            ]
        },
    },
    {
        "name": "OntologySim — 物件歷史",
        "description": "OntologySimulator 時間機器：查詢 APC/DC/SPC/Recipe 物件的歷史快照序列",
        "api_config": {
            "endpoint_url": "http://localhost:8001/api/v1/analytics/history",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "targetID",    "type": "string", "description": "批次或機台 ID（e.g. LOT-0001 / EQP-01）", "required": True},
                {"name": "objectName",  "type": "string", "description": "物件類型：DC / APC / SPC / RECIPE", "required": True},
                {"name": "limit",       "type": "integer","description": "回傳快照筆數（預設 20）", "required": False},
            ]
        },
    },
    {
        "name": "OntologySim — 時間機器查詢",
        "description": "OntologySimulator 時間機器：給定時間戳記、步驟、物件，回傳當下的完整快照狀態",
        "api_config": {
            "endpoint_url": "http://localhost:8001/api/v1/context/query",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "eventTime",   "type": "string", "description": "查詢時間點 (ISO 8601，e.g. 2025-01-04T16:21:00)", "required": True},
                {"name": "targetID",    "type": "string", "description": "批次或機台 ID", "required": True},
                {"name": "objectName",  "type": "string", "description": "物件類型：DC / APC / SPC / RECIPE", "required": True},
                {"name": "step",        "type": "string", "description": "步驟代碼（e.g. STEP_042）", "required": False},
            ]
        },
    },
    # ── v2 System MCPs (time-window forensics, v16 spec) ──────────────────────
    {
        "name": "get_process_context",
        "description": "還原製程現場。一次取回指定 Lot+Step 的 Recipe/APC/DC/SPC 完整快照與 LLM 摘要。Agent 拿到事件後用此 MCP 展開細節。",
        "api_config": {
            "endpoint_url": "http://localhost:8001/api/v2/ontology/context",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "lot_id",     "type": "string", "description": "批次 ID（e.g. LOT-0001）", "required": True},
                {"name": "step",       "type": "string", "description": "步驟代碼（e.g. STEP_047）", "required": True},
                {"name": "event_time", "type": "string", "description": "製程開始時間 ISO8601，用於鎖定特定 cycle（可選）", "required": False},
            ]
        },
    },
    {
        "name": "get_lot_trajectory",
        "description": "批次旅程。查詢指定批次走過的所有步驟、機台、SPC 狀態。用途：這批貨在哪裡發生 OOC？",
        "api_config": {
            "endpoint_url": "http://localhost:8001/api/v2/ontology/trajectory/lot/{lot_id}",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "lot_id", "type": "string", "description": "批次 ID（e.g. LOT-0001）", "required": True},
            ]
        },
    },
    {
        "name": "get_tool_trajectory",
        "description": "設備履歷。查詢指定機台最近處理過的批次與 SPC 結果。用途：這台機台異常前跑過哪些貨？",
        "api_config": {
            "endpoint_url": "http://localhost:8001/api/v2/ontology/trajectory/tool/{tool_id}",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "tool_id", "type": "string", "description": "機台 ID（e.g. EQP-01）", "required": True},
                {"name": "limit",   "type": "integer","description": "回傳筆數上限（預設 50）", "required": False},
            ]
        },
    },
    {
        "name": "get_object_history",
        "description": "物件效能歷史。查詢 APC 模型、Recipe、DC、SPC 物件的歷史快照序列，了解長期趨勢。",
        "api_config": {
            "endpoint_url": "http://localhost:8001/api/v2/ontology/history/{object_type}/{object_id}",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "object_type", "type": "string", "description": "物件類型：APC / DC / SPC / RECIPE", "required": True},
                {"name": "object_id",   "type": "string", "description": "物件 ID（e.g. APC-047）", "required": True},
                {"name": "limit",       "type": "integer","description": "回傳筆數上限（預設 50）", "required": False},
            ]
        },
    },
    {
        "name": "get_baseline_stats",
        "description": "DC 參數基準統計。回傳指定機台在時間區間內的 DC 參數 mean/std_dev/3-sigma 控制限。Agent 用此判斷當前量測值是否異常。",
        "api_config": {
            "endpoint_url": "http://localhost:8001/api/v2/ontology/stats/baseline",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {
            "fields": [
                {"name": "tool_id",    "type": "string", "description": "機台 ID（e.g. EQP-01）", "required": True},
                {"name": "recipe_id",  "type": "string", "description": "Recipe ID（可選，e.g. RCP-003）", "required": False},
                {"name": "start_time", "type": "string", "description": "統計區間起始（ISO8601）", "required": False},
                {"name": "end_time",   "type": "string", "description": "統計區間結束（ISO8601）", "required": False},
            ]
        },
    },
    {
        "name": "search_ooc_events",
        "description": "跨批次 OOC 事件搜尋。查詢符合條件的 SPC OOC 事件清單。用途：過去 24h EQP-01 有哪些批次 OOC？",
        "api_config": {
            "endpoint_url": "http://localhost:8001/api/v2/ontology/search",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
        },
        "input_schema": {
            "fields": [
                {"name": "tool_id",    "type": "string", "description": "機台 ID（可選）", "required": False},
                {"name": "lot_id",     "type": "string", "description": "批次 ID（可選）", "required": False},
                {"name": "step",       "type": "string", "description": "步驟代碼（可選）", "required": False},
                {"name": "status",     "type": "string", "description": "SPC 狀態：OOC 或 PASS（可選）", "required": False},
                {"name": "start_time", "type": "string", "description": "查詢區間起始（ISO8601）", "required": False},
                {"name": "end_time",   "type": "string", "description": "查詢區間結束（ISO8601）", "required": False},
                {"name": "limit",      "type": "integer","description": "回傳筆數上限（預設 50）", "required": False},
            ]
        },
    },
]


_SEED_EVENT_TYPES = [
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


async def _seed_data() -> None:
    """On startup: create default users, built-in DataSubjects/EventTypes, SystemParameters."""
    from sqlalchemy import select
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

        # ── 1b. Seed system MCPs (mirrors of DataSubjects, mcp_type='system') ──
        from app.models.mcp_definition import MCPDefinitionModel as _MCPModel
        try:
            for spec in _MOCK_DATA_SUBJECTS:
                result = await db.execute(
                    select(_MCPModel).where(
                        _MCPModel.name == spec["name"],
                        _MCPModel.mcp_type == "system",
                    )
                )
                if result.scalar_one_or_none() is None:
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
                    logger.info("Seeded system MCP: %s", spec["name"])
        except Exception as _seed_err:
            logger.warning(
                "System MCP seeding skipped (schema not ready — run migration 0005): %s",
                _seed_err,
            )
            await db.rollback()

        # ── 1c. Seed OntologySimulator system MCPs ────────────────────────────
        try:
            for spec in _ONTOLOGY_SYSTEM_MCPS:
                result = await db.execute(
                    select(_MCPModel).where(
                        _MCPModel.name == spec["name"],
                        _MCPModel.mcp_type == "system",
                    )
                )
                if result.scalar_one_or_none() is None:
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
        except Exception as _seed_err2:
            logger.warning("OntologySim MCP seeding skipped: %s", _seed_err2)
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
    await start_scheduler(base_url=f"http://127.0.0.1:{settings.PORT if hasattr(settings, 'PORT') else 8000}")
    logger.info("APScheduler started")
    yield
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
app.include_router(generated_events_router, prefix=_PREFIX)
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
