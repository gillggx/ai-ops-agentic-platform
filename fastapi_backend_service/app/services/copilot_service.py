"""Copilot Chat Service.

Handles intent parsing (LLM), interactive slot filling, and direct
MCP / Skill invocation — without requiring an Event Type binding.
"""

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import anthropic

from app.config import get_settings
from app.repositories.data_subject_repository import DataSubjectRepository
from app.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.services.event_pipeline_service import EventPipelineService
from app.services.mcp_builder_service import MCPBuilderService, _extract_json, _get_text
from app.services.mcp_definition_service import _normalize_output
from app.services.sandbox_service import execute_script

logger = logging.getLogger(__name__)

_MODEL = get_settings().LLM_MODEL


def _j(s: Optional[str]) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


class CopilotService:
    """LLM-powered copilot for direct MCP/Skill invocation via natural language."""

    def __init__(
        self,
        mcp_repo: MCPDefinitionRepository,
        skill_repo: SkillDefinitionRepository,
        ds_repo: DataSubjectRepository,
    ) -> None:
        self._mcp_repo = mcp_repo
        self._skill_repo = skill_repo
        self._ds_repo = ds_repo
        settings = get_settings()
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def stream_chat(
        self,
        message: str,
        slot_context: Dict[str, Any],
        history: List[Dict[str, str]],
        base_url: str = "",
    ) -> AsyncIterator[Dict[str, Any]]:
        """Parse intent, fill slots, then execute MCP or Skill.

        Yields SSE-ready dicts:
          {type: "thinking", message}
          {type: "chat", message}
          {type: "question", question, slot_context, tool_id, tool_type}
          {type: "mcp_result", mcp_id, mcp_name, mcp_output}
          {type: "skill_result", skill_id, skill_name, mcp_name, status,
                                 conclusion, evidence, summary,
                                 human_recommendation, mcp_output}
          {type: "error", message}
          {type: "done"}
        """
        return self._stream_chat_impl(message, slot_context, history, base_url)

    async def _stream_chat_impl(
        self,
        message: str,
        slot_context: Dict[str, Any],
        history: List[Dict[str, str]],
        base_url: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        # 1. Load tool catalog
        mcps = await self._mcp_repo.get_all()
        skills = await self._skill_repo.get_all()

        # Build an MCP lookup dict for fallback param resolution
        mcp_lookup: Dict[int, Any] = {m.id: m for m in mcps}

        # Build required-param map per MCP (derived from skill param_mappings)
        mcp_params_map: Dict[int, List[str]] = {}
        for skill in skills:
            for mapping in (_j(skill.param_mappings) or []):
                mid = mapping.get("mcp_id")
                pname = mapping.get("mcp_param")
                if mid and pname:
                    mcp_params_map.setdefault(mid, [])
                    if pname not in mcp_params_map[mid]:
                        mcp_params_map[mid].append(pname)

        # Also build required params for skills directly
        skill_params_map: Dict[int, List[str]] = {}
        for skill in skills:
            params = []
            for mapping in (_j(skill.param_mappings) or []):
                pname = mapping.get("mcp_param")
                if pname and pname not in params:
                    params.append(pname)

            # Fallback: if no param_mappings, derive required params from the
            # bound MCP's input_definition so slot filling still triggers.
            if not params:
                mcp_id_list = _j(skill.mcp_ids) or []
                if mcp_id_list:
                    bound_mcp = mcp_lookup.get(mcp_id_list[0])
                    if bound_mcp:
                        input_def = _j(bound_mcp.input_definition) if hasattr(bound_mcp, "input_definition") else None
                        for p in (input_def or {}).get("params", []):
                            if p.get("required") and p.get("name") and p["name"] not in params:
                                params.append(p["name"])

            skill_params_map[skill.id] = params

        mcp_catalog = self._build_mcp_catalog(mcps, mcp_params_map)
        skill_catalog = self._build_skill_catalog(skills, skill_params_map)

        # 2. Parse intent via LLM
        yield {"type": "thinking", "message": "🤔 正在分析您的請求..."}

        try:
            intent_result = await self._parse_intent(
                message=message,
                slot_context=slot_context,
                history=history,
                mcp_catalog=mcp_catalog,
                skill_catalog=skill_catalog,
            )
        except Exception as exc:
            logger.exception("Intent parsing failed")
            yield {"type": "error", "message": f"意圖解析失敗：{exc}"}
            yield {"type": "done"}
            return

        intent = intent_result.get("intent", "general_chat")
        tool_id = intent_result.get("tool_id")
        extracted_params = intent_result.get("extracted_params") or {}
        missing_params = intent_result.get("missing_params") or []
        is_ready = intent_result.get("is_ready", False)
        reply_message = intent_result.get("reply_message", "")
        tab_title = intent_result.get("tab_title", "")

        # 3. Merge slot_context with newly extracted params
        # Strip internal _selected_tool_* keys before using as API params
        clean_slot = {k: v for k, v in slot_context.items() if not k.startswith("_selected_")}
        merged_params = {**clean_slot, **extracted_params}

        # If user pre-selected a tool via slash menu, override LLM's choice
        forced_id   = slot_context.get("_selected_tool_id")
        forced_type = slot_context.get("_selected_tool_type")
        if forced_id and forced_type and intent == "general_chat" and not reply_message:
            intent  = "execute_mcp" if forced_type == "mcp" else "execute_skill"
            tool_id = forced_id

        # 4. Route by intent
        if intent == "general_chat" or intent not in ("execute_mcp", "execute_skill", "mcp_call", "skill_call"):
            yield {
                "type": "chat",
                "message": reply_message
                or "您好！我是您的 AI Copilot。請描述您想查詢的資料或診斷的問題，或輸入 / 選擇工具。",
            }
            yield {"type": "done"}
            return

        if intent in ("execute_mcp", "mcp_call"):
            # Re-check missing params after merge
            required = mcp_params_map.get(tool_id, []) if tool_id else []
            still_missing = [p for p in required if p not in merged_params]
            if not is_ready or still_missing:
                yield {
                    "type": "question",
                    "question": reply_message or f"請提供以下必填參數：{', '.join(still_missing or missing_params)}",
                    "slot_context": merged_params,
                    "tool_id": tool_id,
                    "tool_type": "mcp",
                }
                yield {"type": "done"}
                return

            async for event in self._execute_mcp(tool_id, merged_params, base_url, tab_title):
                yield event
            yield {"type": "done"}
            return

        if intent in ("execute_skill", "skill_call"):
            required = skill_params_map.get(tool_id, []) if tool_id else []
            still_missing = [p for p in required if p not in merged_params]
            if not is_ready or still_missing:
                yield {
                    "type": "question",
                    "question": reply_message or f"請提供以下必填參數：{', '.join(still_missing or missing_params)}",
                    "slot_context": merged_params,
                    "tool_id": tool_id,
                    "tool_type": "skill",
                }
                yield {"type": "done"}
                return

            async for event in self._execute_skill(tool_id, merged_params, base_url, tab_title):
                yield event
            yield {"type": "done"}
            return

        yield {"type": "chat", "message": "我無法識別您的請求，請重新描述或使用 / 選單選擇工具。"}
        yield {"type": "done"}

    # ── Intent Parsing ────────────────────────────────────────────

    async def _parse_intent(
        self,
        message: str,
        slot_context: Dict[str, Any],
        history: List[Dict[str, str]],
        mcp_catalog: str,
        skill_catalog: str,
    ) -> Dict[str, Any]:
        # Build clean slot context display (hide internal keys)
        clean_slot = {k: v for k, v in slot_context.items() if not k.startswith("_selected_")}
        slot_ctx_str = json.dumps(clean_slot, ensure_ascii=False) if clean_slot else "（尚無已收集的參數）"

        # Build pre-selected tool hint
        forced_id   = slot_context.get("_selected_tool_id")
        forced_type = slot_context.get("_selected_tool_type")
        forced_hint = ""
        if forced_id and forced_type:
            forced_hint = f"\n## ⚠️ 使用者已預先選擇工具\n使用者透過 Slash 選單選擇了 tool_id={forced_id} (type={forced_type})，請優先使用此工具（除非使用者明確要求其他工具）。"

        system_prompt = f"""你是一個半導體工廠的 AI Copilot 助手，負責解析使用者意圖、識別工具並提取查詢參數。
{forced_hint}

## ⚠️ CRITICAL RULE — 必須嚴格遵守，違反即為系統性錯誤
If the user's prompt does NOT explicitly contain values for ALL required parameters of the selected tool,
you MUST NOT set is_ready=true. You MUST set is_ready=false and ask the user to provide the missing values.
Never assume, fabricate, or substitute default values for required parameters (such as lot_id, tool_id,
operation_number). The user must explicitly supply them. Executing a tool without confirmed parameter
values is strictly forbidden.

## 可用工具

### 🔍 MCP 資料查詢工具
{mcp_catalog}

### 🧠 Skill 智能診斷技能
{skill_catalog}

## 已收集的參數（Slot Context）
{slot_ctx_str}

## 回傳格式
請嚴格回傳以下 JSON（不加任何前後文字、不加 markdown）：
{{
  "intent": "execute_mcp | execute_skill | general_chat",
  "tool_id": <整數 ID 或 null>,
  "tool_type": "mcp | skill | null",
  "extracted_params": {{}},
  "missing_params": [],
  "is_ready": false,
  "reply_message": "給使用者看的話（追問缺少的參數、播報執行進度、或一般回覆）",
  "tab_title": "若 is_ready=true，生成一個簡短頁籤標題（如 '🔍 APC: L12345' 或 '🧠 CD 異常診斷'）"
}}

## 規則
1. 若使用者描述需要查詢資料 → intent = "execute_mcp"，選擇最匹配的 MCP
2. 若使用者描述需要進行異常診斷 → intent = "execute_skill"，選擇最匹配的 Skill
3. 從使用者訊息中提取參數放入 extracted_params（如 lot_id, tool_id, operation_number, chart_name 等）
4. 已在 Slot Context 中的參數不算 missing_params
5. missing_params 只列必填且尚未收集的參數名稱（字串陣列）
6. 若所有必填參數齊全（含 Slot Context 中已有的，且來自使用者明確提供）→ is_ready = true，同時生成 tab_title
7. 若有 missing_params → is_ready = false，在 reply_message 中用繁體中文友善地追問（一次最多問 2 個）
8. 若是一般問候或聊天 → intent = "general_chat"，在 reply_message 回覆
9. lot ID 常見格式如 L12345 或 N97A45.00，operation number 是製程站點編號如 3200 或 24981
10. tab_title 要簡短（15 字以內），包含工具名稱與關鍵參數，例如 '🔍 APC: L12345@3200'"""

        messages: List[Dict[str, str]] = []
        for h in history[-6:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        return _extract_json(_get_text(response.content))

    # ── Catalog Builders ─────────────────────────────────────────

    def _build_mcp_catalog(self, mcps: List[Any], mcp_params_map: Dict[int, List[str]]) -> str:
        """Build a text catalog of available MCPs for the LLM intent prompt."""
        lines = []
        for mcp in mcps:
            params = mcp_params_map.get(mcp.id, [])
            if params:
                params_str = ", ".join(f"{p} [REQUIRED]" for p in params)
            else:
                params_str = "（無需額外參數）"
            intent = mcp.processing_intent or mcp.name
            lines.append(f"- [ID:{mcp.id}] {mcp.name}: {intent} | 必填參數: {params_str}")
        return "\n".join(lines) if lines else "（無可用 MCP）"

    def _build_skill_catalog(self, skills: List[Any], skill_params_map: Dict[int, List[str]]) -> str:
        """Build a text catalog of available Skills for the LLM intent prompt."""
        lines = []
        for skill in skills:
            desc = skill.description or skill.name
            params = skill_params_map.get(skill.id, [])
            if params:
                params_str = ", ".join(f"{p} [REQUIRED]" for p in params)
            else:
                params_str = "（無需額外參數）"
            lines.append(f"- [ID:{skill.id}] {skill.name}: {desc} | 必填參數: {params_str}")
        return "\n".join(lines) if lines else "（無可用 Skill）"

    # ── MCP Direct Execution ─────────────────────────────────────

    async def _execute_mcp(
        self,
        tool_id: int,
        params: Dict[str, Any],
        base_url: str,
        tab_title: str = "",
    ) -> AsyncIterator[Dict[str, Any]]:
        """Fetch DataSubject data, run MCP script, and yield mcp_result SSE events."""
        mcp = await self._mcp_repo.get_by_id(tool_id)
        if not mcp:
            yield {"type": "error", "message": f"找不到 MCP id={tool_id}"}
            return

        ds = await self._ds_repo.get_by_id(mcp.data_subject_id)
        if not ds:
            yield {"type": "error", "message": "找不到對應的 DataSubject"}
            return

        ds_api_config = (
            _j(ds.api_config) if isinstance(ds.api_config, str) else (ds.api_config or {})
        )
        endpoint_url = ds_api_config.get("endpoint_url", "")

        if not endpoint_url:
            yield {"type": "error", "message": "DataSubject 缺少 endpoint_url"}
            return

        if not mcp.processing_script:
            yield {
                "type": "error",
                "message": "此 MCP 尚未生成腳本，請先在 MCP Builder 完成設定",
            }
            return

        yield {"type": "thinking", "message": f"🔍 正在查詢 {mcp.name} 資料..."}

        try:
            raw_data = await EventPipelineService._fetch_ds_data(endpoint_url, params, base_url)
        except Exception as exc:
            yield {"type": "error", "message": f"資料查詢失敗：{exc}"}
            return

        raw_count = len(raw_data) if isinstance(raw_data, list) else f"non-list({type(raw_data).__name__})"
        print(f"[MCP DEBUG] {mcp.name}  raw_data rows={raw_count}  params={params}  url={endpoint_url}", flush=True)

        try:
            output_data = await execute_script(mcp.processing_script, raw_data)
        except Exception as exc:
            yield {"type": "error", "message": f"腳本執行失敗：{exc}"}
            return

        ds_count = len(output_data.get("dataset", [])) if isinstance(output_data, dict) else "?"
        has_chart = bool(isinstance(output_data, dict) and
                         output_data.get("ui_render", {}).get("chart_data"))
        print(f"[MCP DEBUG] {mcp.name}  script→ dataset_rows={ds_count}  has_chart={has_chart}", flush=True)

        llm_schema = _j(mcp.output_schema) if hasattr(mcp, "output_schema") else None
        output_data = _normalize_output(output_data, llm_schema)

        # Auto-generate chart when script produced no chart_data but dataset is available
        if not output_data.get("ui_render", {}).get("chart_data") and output_data.get("dataset"):
            ui_cfg = _j(mcp.ui_render_config) if isinstance(mcp.ui_render_config, str) else (mcp.ui_render_config or {})
            if ui_cfg.get("chart_type", "table") not in ("table", "", None):
                from app.services.mcp_definition_service import _auto_chart  # noqa: PLC0415
                chart = _auto_chart(output_data["dataset"], ui_cfg)
                if chart:
                    output_data = {
                        **output_data,
                        "ui_render": {**(output_data.get("ui_render") or {}), "chart_data": chart, "charts": [chart], "type": "chart"},
                    }
                    print(f"[MCP DEBUG] {mcp.name}  auto_chart generated from dataset", flush=True)

        # Attach raw DS data (before MCP script processing) + call params
        raw_list = raw_data if isinstance(raw_data, list) else (
            list(raw_data.values())[0] if isinstance(raw_data, dict) and raw_data else [raw_data]
        )
        output_data = {**output_data, "_raw_dataset": raw_list, "_call_params": params}

        ui = output_data.get("ui_render") or {}
        logger.warning(
            "【後端準備發送的圖表 Payload】mcp=%s  charts=%s  chart_data_len=%s  dataset_rows=%s  raw_dataset_rows=%s",
            mcp.name,
            ui.get("charts"),
            len(ui.get("chart_data") or ""),
            len(output_data.get("dataset") or []),
            len(output_data.get("_raw_dataset") or []),
        )
        yield {
            "type": "mcp_result",
            "mcp_id": tool_id,
            "mcp_name": mcp.name,
            "mcp_output": output_data,
            "tab_title": tab_title or f"🔍 {mcp.name}",
        }

    # ── Skill Direct Execution ────────────────────────────────────

    async def _execute_skill(
        self,
        tool_id: int,
        params: Dict[str, Any],
        base_url: str,
        tab_title: str = "",
    ) -> AsyncIterator[Dict[str, Any]]:
        """Fetch DataSubject data, run MCP script, run LLM diagnosis, and yield skill_result SSE events."""
        skill = await self._skill_repo.get_by_id(tool_id)
        if not skill:
            yield {"type": "error", "message": f"找不到 Skill id={tool_id}"}
            return

        mcp_id_list = _j(skill.mcp_ids) or []
        if not mcp_id_list:
            yield {"type": "error", "message": "此 Skill 尚未綁定 MCP"}
            return

        mcp_id = mcp_id_list[0]
        mcp = await self._mcp_repo.get_by_id(mcp_id)
        if not mcp:
            yield {"type": "error", "message": f"找不到 MCP id={mcp_id}"}
            return

        ds = await self._ds_repo.get_by_id(mcp.data_subject_id)
        if not ds:
            yield {"type": "error", "message": "找不到對應的 DataSubject"}
            return

        ds_api_config = (
            _j(ds.api_config) if isinstance(ds.api_config, str) else (ds.api_config or {})
        )
        endpoint_url = ds_api_config.get("endpoint_url", "")

        if not endpoint_url or not mcp.processing_script:
            yield {"type": "error", "message": "MCP 設定不完整（缺少 endpoint 或腳本）"}
            return

        if not skill.diagnostic_prompt:
            yield {"type": "error", "message": "此 Skill 尚未設定 Diagnostic Prompt"}
            return

        yield {"type": "thinking", "message": f"🧠 正在執行 {skill.name} 診斷..."}

        try:
            raw_data = await EventPipelineService._fetch_ds_data(endpoint_url, params, base_url)
        except Exception as exc:
            yield {"type": "error", "message": f"資料查詢失敗：{exc}"}
            return

        try:
            output_data = await execute_script(mcp.processing_script, raw_data)
        except Exception as exc:
            yield {"type": "error", "message": f"腳本執行失敗：{exc}"}
            return

        llm_schema = _j(mcp.output_schema) if hasattr(mcp, "output_schema") else None
        output_data = _normalize_output(output_data, llm_schema)

        try:
            llm_svc = MCPBuilderService()
            llm_result = await llm_svc.try_diagnosis(
                diagnostic_prompt=skill.diagnostic_prompt,
                mcp_outputs={mcp.name: output_data},
            )
        except Exception as exc:
            yield {"type": "error", "message": f"LLM 診斷失敗：{exc}"}
            return

        raw_status = llm_result.get("status") or llm_result.get("severity") or ""
        status = "NORMAL" if raw_status.upper() == "NORMAL" else "ABNORMAL"

        icon = "✅" if status == "NORMAL" else "⚠️"
        yield {
            "type": "skill_result",
            "skill_id": tool_id,
            "skill_name": skill.name,
            "mcp_name": mcp.name,
            "status": status,
            "conclusion": llm_result.get("conclusion", ""),
            "evidence": llm_result.get("evidence", []),
            "summary": llm_result.get("summary", ""),
            "problem_object": llm_result.get("problem_object") or {},
            "human_recommendation": skill.human_recommendation or "",
            "mcp_output": output_data,
            "tab_title": tab_title or f"{icon} {skill.name}",
        }
