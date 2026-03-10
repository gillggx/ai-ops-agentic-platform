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

from app.services.agent_memory_service import AgentMemoryService

logger = logging.getLogger(__name__)


# ── Tool Definitions (Anthropic SDK format) ────────────────────────────────

TOOL_SCHEMAS: List[Dict[str, Any]] = [
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
        "name": "execute_mcp",
        "description": (
            "執行一個 MCP 節點 (system 或 custom)，回傳 dataset。"
            "system MCP 直接查詢底層 API；custom MCP 執行 Python 腳本。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mcp_id": {"type": "integer", "description": "要執行的 MCP ID"},
                "params": {"type": "object", "description": "MCP 輸入參數"},
            },
            "required": ["mcp_id", "params"],
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
    # ── [v15.1] Agent Tool Chest ───────────────────────────────────────────
    {
        "name": "execute_agent_tool",
        "description": (
            "【第二優先級】執行你自己先前累積的 Agent Tool（私有工具）。"
            "適用條件：現有 Skill 不符合，但你的工具庫中有描述相符、曾成功執行過的腳本。"
            "傳入 tool_id（從 tools_manifest.agent_tools 取得）和 raw_data（已撈取的 df 資料）。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_id": {"type": "integer", "description": "Agent Tool ID（從 tools_manifest.agent_tools 取得）"},
                "raw_data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "要分析的資料集（list-of-dicts，即 df 來源）",
                },
            },
            "required": ["tool_id", "raw_data"],
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
    ) -> None:
        self._db = db
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
        self._user_id = user_id
        self._memory_svc = AgentMemoryService(db)

    # Tools that return conversational/structural data — skip DataProfile for these
    _NON_DATA_TOOLS = frozenset({
        "navigate", "save_memory", "search_memory", "update_user_preference",
        "list_skills", "list_mcps", "list_system_mcps",
        "list_routine_checks", "list_event_types",
        "draft_skill", "draft_mcp", "draft_routine_check", "draft_event_skill_link",
        "patch_mcp", "patch_skill_raw",
        "search_catalog",  # returns catalog items, not raw datasets
    })

    # Catalog type → API endpoint mapping
    _CATALOG_ENDPOINTS: Dict[str, str] = {
        "skills":       "/api/v1/skill-definitions",
        "mcps":         "/api/v1/mcp-definitions?type=custom",
        "system_mcps":  "/api/v1/mcp-definitions?type=system",
        "agent_tools":  "/api/v1/agent-tools",
    }

    async def _execute_inner(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool and return its result as a dict (inner, no profiling)."""
        logger.info("ToolDispatcher.execute: tool=%s input=%s", tool_name, json.dumps(tool_input, ensure_ascii=False)[:200])
        try:
            match tool_name:
                case "execute_skill":
                    return await self._call_api(
                        "POST",
                        f"/api/v1/execute/skill/{tool_input['skill_id']}",
                        body=tool_input.get("params", {}),
                    )
                case "execute_mcp":
                    return await self._call_api(
                        "POST",
                        f"/api/v1/execute/mcp/{tool_input['mcp_id']}",
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
                case "search_memory":
                    top_k = tool_input.get("top_k", 5)
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
                # ── [v15.1] Agent Tool Chest execution ────────────────────
                case "execute_agent_tool":
                    return await self._call_api(
                        "POST",
                        f"/api/v1/agent-tools/{tool_input['tool_id']}/execute",
                        body={"raw_data": tool_input.get("raw_data", [])},
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
                from app.services.data_profile_service import DataProfileService, is_data_source
                if is_data_source(result):
                    profile = DataProfileService.build_profile(result)
                    if profile:
                        result["_data_profile"] = profile
                        logger.debug("DataProfile attached: tool=%s cols=%s", tool_name, list(profile.get("meta", {}).keys()))
            except Exception as exc:
                logger.warning("Smart Sampling interceptor failed (non-blocking): %s", exc)

        return result

    async def _call_api(
        self, method: str, path: str, body: Optional[Dict] = None
    ) -> Dict[str, Any]:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
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
