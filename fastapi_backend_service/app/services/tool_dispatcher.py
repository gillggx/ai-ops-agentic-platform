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
        "name": "draft_routine_check",
        "description": (
            "以草稿模式建立排程巡檢。Agent 提案後需人工在 Event Link Builder 確認後發佈。\n"
            "⚠️ 提供 skill_id（現有 Skill）或 skill_draft（建立新 Skill，先用 list_skills 確認無重複）。\n"
            "schedule_interval 可選: '30m' | '1h' | '4h' | '8h' | '12h' | 'daily'。"
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
        "description": "搜尋 Agent 的長期記憶。用於查詢歷史診斷結果或使用者曾說的話。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜尋關鍵字"},
                "top_k": {"type": "integer", "description": "回傳筆數 (預設 5)", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "save_memory",
        "description": "明確儲存一條長期記憶，例如「使用者確認 TETCH01 已維修完畢」。",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "記憶內容 (純文字)"},
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

    async def execute(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool and return its result as a dict."""
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
                case "patch_skill_raw":
                    return await self._call_api(
                        "PUT",
                        f"/api/v1/agentic/skills/{tool_input['skill_id']}/raw",
                        body={"raw_markdown": tool_input["raw_markdown"]},
                    )
                case "search_memory":
                    top_k = tool_input.get("top_k", 5)
                    memories = await self._memory_svc.search(
                        self._user_id, tool_input["query"], top_k=top_k
                    )
                    return {
                        "memories": [AgentMemoryService.to_dict(m) for m in memories],
                        "count": len(memories),
                    }
                case "save_memory":
                    m = await self._memory_svc.write(
                        user_id=self._user_id,
                        content=tool_input["content"],
                        source="agent_request",
                    )
                    return {"saved": True, "memory_id": m.id, "content": m.content}
                case "update_user_preference":
                    return await self._call_api(
                        "POST",
                        "/api/v1/agent/preference",
                        body={"user_id": self._user_id, "text": tool_input["text"]},
                    )
                case _:
                    return {"error": f"Unknown tool: {tool_name}"}
        except Exception as exc:
            logger.exception("ToolDispatcher error: tool=%s", tool_name)
            return {"error": str(exc), "tool": tool_name}

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
            elif method == "DELETE":
                resp = await client.delete(url, headers=self._headers)
            else:
                return {"error": f"Unsupported method: {method}"}

            try:
                return resp.json()
            except Exception:
                return {"error": f"Non-JSON response ({resp.status_code})", "body": resp.text[:500]}
