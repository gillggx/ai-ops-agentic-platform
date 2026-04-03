"""Copilot Chat Service.

Handles intent parsing (LLM), interactive slot filling, and direct
MCP / Skill invocation — without requiring an Event Type binding.
"""

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from app.config import get_settings
from app.ontology.repositories.data_subject import DataSubjectRepository
from app.ontology.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.ontology.repositories.skill_definition_repository import SkillDefinitionRepository
from app.services.event_pipeline_service import EventPipelineService
from app.services.mcp_builder_service import MCPBuilderService, _extract_json
from app.services.mcp_definition_service import _normalize_output
from app.services.sandbox_service import execute_diagnose_fn, execute_script
from app.utils.llm_client import get_llm_client

logger = logging.getLogger(__name__)

from app.prompts.catalog import COPILOT_CODE_GEN_SYSTEM as _ANALYSIS_CODE_GEN_SYSTEM


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
        self._llm = get_llm_client()

    async def stream_chat(
        self,
        message: str,
        slot_context: Dict[str, Any],
        history: List[Dict[str, str]],
        base_url: str = "",
        user_id: int = 1,
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
          {type: "draft_ready", draft_type, draft_id, deep_link_data, message}
          {type: "error", message}
          {type: "done"}
        """
        return self._stream_chat_impl(message, slot_context, history, base_url, user_id)

    async def _stream_chat_impl(
        self,
        message: str,
        slot_context: Dict[str, Any],
        history: List[Dict[str, str]],
        base_url: str,
        user_id: int = 1,
    ) -> AsyncIterator[Dict[str, Any]]:
        # 1. Load tool catalog
        mcps = await self._mcp_repo.get_all()
        skills = await self._skill_repo.get_all()
        all_ds = await self._ds_repo.get_all()

        # Build lookup dicts
        mcp_lookup: Dict[int, Any] = {m.id: m for m in mcps}
        ds_lookup: Dict[int, Any] = {d.id: d for d in all_ds}
        # system MCP lookup (mcp_type='system' rows)
        sys_mcp_lookup: Dict[int, Any] = {
            m.id: m for m in mcps if getattr(m, 'mcp_type', 'custom') == 'system'
        }

        def _required_from_input_schema(obj) -> List[str]:
            """Extract required field names from an object's input_schema attribute."""
            schema = _j(obj.input_schema) if isinstance(obj.input_schema, str) else (getattr(obj, 'input_schema', None) or {})
            return [
                f["name"] for f in (schema or {}).get("fields", [])
                if f.get("required") and f.get("name")
            ]

        def _get_data_source(mcp) -> Any:
            """Return the system MCP or DataSubject for a custom MCP."""
            system_mcp_id = getattr(mcp, 'system_mcp_id', None)
            if system_mcp_id:
                return sys_mcp_lookup.get(system_mcp_id)
            return ds_lookup.get(mcp.data_subject_id)

        # Build required-param map per MCP
        # Priority: explicit skill param_mappings → data source input_schema (ground truth)
        mcp_params_map: Dict[int, List[str]] = {}
        for skill in skills:
            for mapping in (_j(skill.param_mappings) or []):
                mid = mapping.get("mcp_id")
                pname = mapping.get("mcp_param")
                if mid and pname:
                    mcp_params_map.setdefault(mid, [])
                    if pname not in mcp_params_map[mid]:
                        mcp_params_map[mid].append(pname)
        # For MCPs with no param mappings, fall back to their data source's input_schema
        for mcp in mcps:
            if mcp.id not in mcp_params_map:
                source = _get_data_source(mcp)
                if source:
                    required = _required_from_input_schema(source)
                    if required:
                        mcp_params_map[mcp.id] = required

        # Also build required params for skills directly
        skill_params_map: Dict[int, List[str]] = {}
        for skill in skills:
            params = []
            for mapping in (_j(skill.param_mappings) or []):
                pname = mapping.get("mcp_param")
                if pname and pname not in params:
                    params.append(pname)

            # Fallback chain (when param_mappings is empty):
            # 1. MCP input_definition.params (required=true, source != data_subject)
            # 2. data source input_schema.fields (required=true)  ← ground truth
            if not params:
                mcp_id_list = _j(skill.mcp_ids) or []
                if mcp_id_list:
                    bound_mcp = mcp_lookup.get(mcp_id_list[0])
                    if bound_mcp:
                        # Try MCP input_definition first
                        input_def = _j(bound_mcp.input_definition) if hasattr(bound_mcp, "input_definition") else None
                        for p in (input_def or {}).get("params", []):
                            # Skip params sourced from data_subject — they are fetched internally
                            if p.get("required") and p.get("name") and p.get("source") != "data_subject" and p["name"] not in params:
                                params.append(p["name"])
                        # If still empty, fall back to data source input_schema (most authoritative)
                        if not params:
                            source = _get_data_source(bound_mcp)
                            if source:
                                params = _required_from_input_schema(source)

            skill_params_map[skill.id] = params
            if params:
                logger.debug("skill_params_map[%s]=%s", skill.id, params)

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
        analysis_request = intent_result.get("analysis_request", "")

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
        _BUILD_INTENTS = ("build_mcp", "build_skill", "build_schedule", "build_event")
        if intent in _BUILD_INTENTS:
            async for event in self._handle_build_intent(intent, intent_result, base_url, user_id):
                yield event
            yield {"type": "done"}
            return

        if intent == "general_chat" or intent not in (
            "execute_mcp", "execute_skill", "analyze_mcp", "mcp_call", "skill_call"
        ):
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

        if intent == "analyze_mcp":
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

            async for event in self._analyze_mcp_with_code(
                tool_id, merged_params, base_url,
                analysis_request=analysis_request or message,
                tab_title=tab_title,
            ):
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
**is_ready = true 的條件：** 所有必填參數的值都能從以下任一來源取得：
  (a) 使用者在當前訊息中明確提供（如「用 EQP-01」「lot_id L12345」）
  (b) Slot Context 中已存在（之前對話收集到的參數）
若以上兩種來源都能覆蓋所有必填參數 → **必須** 設 is_ready=true，直接執行，不要再追問。

**is_ready = false 的條件：** 有必填參數缺失（未在訊息中提及，且不在 Slot Context 中）。
此時 MUST set is_ready=false，在 reply_message 中追問缺少的參數（一次最多問 2 個）。

**禁止：** 自行捏造或用預設值替換缺失參數。使用者沒提供的參數不能假設。

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
  "intent": "execute_mcp | execute_skill | analyze_mcp | build_mcp | build_skill | build_schedule | build_event | general_chat",
  "tool_id": <整數 ID 或 null>,
  "tool_type": "mcp | skill | null",
  "extracted_params": {{}},
  "missing_params": [],
  "is_ready": false,
  "reply_message": "給使用者看的話（追問缺少的參數、播報執行進度、或一般回覆）",
  "tab_title": "若 is_ready=true，生成一個簡短頁籤標題（如 '🔍 APC: L12345' 或 '🧠 CD 異常診斷'）",
  "analysis_request": "（僅 analyze_mcp 時填寫）使用者要做的具體分析內容，例如：計算各參數平均值並找出最異常的參數"
}}

## 規則
1. 若使用者描述需要查詢資料（只看/顯示資料）→ intent = "execute_mcp"，選擇最匹配的 MCP
2. 若使用者描述需要對資料進行計算、分析、找趨勢、統計、找異常值、比較、排行等 → intent = "analyze_mcp"，選擇最匹配的 MCP，並在 analysis_request 說明具體分析需求
3. 若使用者描述需要進行完整異常診斷（NORMAL/ABNORMAL 判定）→ intent = "execute_skill"，選擇最匹配的 Skill
4. 若使用者說「建立 MCP / 資料節點 / 資料處理」等建構意圖 → intent = "build_mcp"
5. 若使用者說「建立 Skill / 診斷技能 / 診斷管線」等建構意圖 → intent = "build_skill"
6. 若使用者說「定時 / 排程 / 每天 / 每小時執行」等排程意圖 → intent = "build_schedule"
7. 若使用者說「當異常發生時觸發 / 事件觸發」等事件意圖 → intent = "build_event"
8. 從使用者訊息中提取相關參數放入 extracted_params（名稱、MCP ID、診斷條件、cron 表達式等）
9. 已在 Slot Context 中的參數不算 missing_params
10. missing_params 只列必填且尚未收集的參數名稱（字串陣列）
11. 若所有必填參數齊全（含 Slot Context 中已有的，OR 使用者在當前訊息中明確提供）→ is_ready = true，同時生成 tab_title。參數只要有值就算齊全，不需要使用者特別「再確認一次」。
12. 若有 missing_params → is_ready = false，在 reply_message 中用繁體中文友善地追問（一次最多問 2 個）
13. 若是一般問候或聊天 → intent = "general_chat"，在 reply_message 回覆
14. lot ID 常見格式如 L12345 或 N97A45.00，operation number 是製程站點編號如 3200 或 24981
15. tab_title 要簡短（15 字以內），包含工具名稱與關鍵參數，例如 '🔍 APC: L12345@3200'
16. 若使用者詢問系統架構相關問題（如「有幾個 MCP？」「什麼是 Data Subject？」「你有哪些工具？」）→ intent = "general_chat"，在 reply_message 中用繁體中文友善回答。Data Subject 是底層資料連線抽象層（Agent 透過 MCP 間接存取，使用者無需直接操作）。
17. 任何情況下都必須回傳合法 JSON，不得輸出純文字或解釋性文字。"""

        messages: List[Dict[str, str]] = []
        for h in history[-6:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})

        response = await self._llm.create(
            system=system_prompt,
            messages=messages,
            max_tokens=1024,
        )
        return _extract_json(response.text)

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

        # Resolve data source: system_mcp_id first, fall back to data_subject_id
        system_mcp_id = getattr(mcp, 'system_mcp_id', None)
        if system_mcp_id:
            sys_mcp = await self._mcp_repo.get_by_id(system_mcp_id)
            if not sys_mcp:
                yield {"type": "error", "message": f"找不到 System MCP id={system_mcp_id}"}
                return
            ds_api_config = _j(sys_mcp.api_config) if isinstance(sys_mcp.api_config, str) else (sys_mcp.api_config or {})
        else:
            ds = await self._ds_repo.get_by_id(mcp.data_subject_id)
            if not ds:
                yield {"type": "error", "message": "找不到對應的 System MCP / DataSubject"}
                return
            ds_api_config = _j(ds.api_config) if isinstance(ds.api_config, str) else (ds.api_config or {})

        endpoint_url = ds_api_config.get("endpoint_url", "")

        if not endpoint_url:
            yield {"type": "error", "message": "System MCP / DataSubject 缺少 endpoint_url"}
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

        last_result = _j(skill.last_diagnosis_result) if hasattr(skill, "last_diagnosis_result") else None
        diagnose_code = (last_result or {}).get("generated_code") or ""
        if not diagnose_code:
            yield {"type": "error", "message": "此 Skill 尚未在 Skill Builder 完成模擬，缺少診斷腳本。請先在 Skill Builder 執行「試跑」。"}
            return

        try:
            diag_result = await execute_diagnose_fn(
                code=diagnose_code,
                mcp_outputs={mcp.name: output_data},
            )
        except Exception as exc:
            yield {"type": "error", "message": f"診斷腳本執行失敗：{exc}"}
            return

        raw_status = str(diag_result.get("status", "")).upper()
        status = "NORMAL" if raw_status == "NORMAL" else "ABNORMAL"

        icon = "✅" if status == "NORMAL" else "⚠️"
        yield {
            "type": "skill_result",
            "skill_id": tool_id,
            "skill_name": skill.name,
            "mcp_name": mcp.name,
            "status": status,
            "conclusion": diag_result.get("diagnosis_message", ""),
            "evidence": [],
            "summary": diag_result.get("diagnosis_message", ""),
            "problem_object": diag_result.get("problem_object") or {},
            "human_recommendation": skill.human_recommendation or "",
            "mcp_output": output_data,
            "tab_title": tab_title or f"{icon} {skill.name}",
        }

    # ── Raw Data Analysis (code-gen + sandbox) ────────────────────

    async def _analyze_mcp_with_code(
        self,
        tool_id: int,
        params: Dict[str, Any],
        base_url: str,
        analysis_request: str = "",
        tab_title: str = "",
    ) -> AsyncIterator[Dict[str, Any]]:
        """Fetch raw MCP data, generate Python analysis code via LLM, execute in sandbox.

        Yields analysis_result SSE events with text_result + optional chart.
        Uses _raw_dataset (before MCP processing_script transforms) for deeper analysis.
        """
        mcp = await self._mcp_repo.get_by_id(tool_id)
        if not mcp:
            yield {"type": "error", "message": f"找不到 MCP id={tool_id}"}
            return

        # Resolve data source
        system_mcp_id = getattr(mcp, 'system_mcp_id', None)
        if system_mcp_id:
            sys_mcp = await self._mcp_repo.get_by_id(system_mcp_id)
            if not sys_mcp:
                yield {"type": "error", "message": f"找不到 System MCP id={system_mcp_id}"}
                return
            ds_api_config = _j(sys_mcp.api_config) if isinstance(sys_mcp.api_config, str) else (sys_mcp.api_config or {})
        else:
            ds = await self._ds_repo.get_by_id(mcp.data_subject_id)
            if not ds:
                yield {"type": "error", "message": "找不到對應的 System MCP / DataSubject"}
                return
            ds_api_config = _j(ds.api_config) if isinstance(ds.api_config, str) else (ds.api_config or {})

        endpoint_url = ds_api_config.get("endpoint_url", "")
        if not endpoint_url:
            yield {"type": "error", "message": "System MCP / DataSubject 缺少 endpoint_url"}
            return

        yield {"type": "thinking", "message": f"📊 正在取得 {mcp.name} 原始資料..."}

        try:
            raw_data = await EventPipelineService._fetch_ds_data(endpoint_url, params, base_url)
        except Exception as exc:
            yield {"type": "error", "message": f"資料查詢失敗：{exc}"}
            return

        if not raw_data or (isinstance(raw_data, list) and len(raw_data) == 0):
            yield {"type": "error", "message": "資料查詢結果為空，無法進行分析"}
            return

        # Build schema sample (5 rows) for code generation — do NOT pass full dataset to LLM
        sample_rows = raw_data[:5] if isinstance(raw_data, list) else []
        if not sample_rows and isinstance(raw_data, dict):
            for v in raw_data.values():
                if isinstance(v, list):
                    sample_rows = v[:5]
                    break

        columns = list(sample_rows[0].keys()) if sample_rows else []
        row_count = len(raw_data) if isinstance(raw_data, list) else "unknown"

        yield {"type": "thinking", "message": f"🧠 正在生成分析程式碼（{row_count} 筆資料，{len(columns)} 個欄位）..."}

        # Generate analysis code
        schema_desc = json.dumps(sample_rows, ensure_ascii=False, indent=2)
        code_gen_prompt = f"""資料來源：{mcp.name}
資料欄位：{columns}
資料筆數：{row_count}
前 5 筆範例資料：
{schema_desc}

使用者的分析需求：{analysis_request}

請撰寫 process(raw_data) 函式，針對上述需求進行分析，並在 text_result 中用繁體中文條列說明分析結果。"""

        try:
            code_resp = await self._llm.create(
                system=_ANALYSIS_CODE_GEN_SYSTEM,
                messages=[{"role": "user", "content": code_gen_prompt}],
                max_tokens=2048,
            )
            python_code = code_resp.text.strip()
            # Strip accidental markdown fences
            if python_code.startswith("```"):
                lines = python_code.splitlines()
                python_code = "\n".join(
                    ln for ln in lines if not ln.strip().startswith("```")
                ).strip()
        except Exception as exc:
            yield {"type": "error", "message": f"分析程式碼生成失敗：{exc}"}
            return

        yield {"type": "thinking", "message": "⚙️ 正在沙盒執行分析..."}

        # Execute in sandbox with FULL raw data
        analysis_input = raw_data if isinstance(raw_data, list) else list(raw_data.values())[0] if isinstance(raw_data, dict) else []
        try:
            sandbox_result = await execute_script(python_code, analysis_input)
        except (ValueError, TimeoutError) as exc:
            yield {"type": "error", "message": f"分析沙盒執行失敗：{exc}"}
            return
        except Exception as exc:
            yield {"type": "error", "message": f"分析執行未預期錯誤：{exc}"}
            return

        # Extract chart if present
        chart_json: Optional[str] = None
        ui_render = sandbox_result.get("ui_render") or {}
        charts = ui_render.get("charts") or []
        if charts and charts[0]:
            chart_json = charts[0]
        elif ui_render.get("chart_data"):
            chart_json = ui_render["chart_data"]

        text_result = sandbox_result.get("text_result", "分析完成，請查看下方結果。")
        dataset = sandbox_result.get("dataset") or []

        yield {
            "type": "analysis_result",
            "mcp_id": tool_id,
            "mcp_name": mcp.name,
            "analysis_request": analysis_request,
            "text_result": text_result,
            "dataset": dataset,
            "chart_json": chart_json,
            "has_chart": bool(chart_json),
            "row_count": row_count,
            "tab_title": tab_title or f"📊 {mcp.name} 分析",
        }

    # ── Build Intent Handling ─────────────────────────────────────

    async def _handle_build_intent(
        self,
        intent: str,
        intent_result: Dict[str, Any],
        base_url: str,
        user_id: int = 1,
    ):
        """Handle build_mcp / build_skill / build_schedule / build_event intents.

        Calls the appropriate /agent/draft/* endpoint and yields draft_ready SSE.
        Falls back to a helpful chat message if parameters are insufficient.
        """
        import httpx  # noqa: PLC0415

        build_params = intent_result.get("extracted_params") or {}
        reply_message = intent_result.get("reply_message", "")

        # If still missing key info, ask user first
        if not build_params and not reply_message:
            yield {
                "type": "chat",
                "message": "請描述您想建立的內容，例如：名稱、要監控的資料、診斷條件等。",
            }
            return

        # If LLM replied with a question (missing params), relay it
        if reply_message and not build_params:
            yield {"type": "chat", "message": reply_message}
            return

        intent_map = {
            "build_mcp": "mcp",
            "build_skill": "skill",
            "build_schedule": "schedule",
            "build_event": "event",
        }
        draft_type = intent_map.get(intent, "skill")

        yield {"type": "thinking", "message": f"📝 正在準備 {draft_type} 草稿..."}

        try:
            draft_result = await self._create_draft_directly(draft_type, build_params, user_id)
        except Exception as exc:
            logger.exception("_handle_build_intent: draft creation failed")
            yield {"type": "error", "message": f"草稿建立失敗：{exc}"}
            return

        draft_id = draft_result.get("draft_id", "")
        display_type_map = {
            "mcp": "MCP 資料節點",
            "skill": "診斷技能",
            "schedule": "排程巡檢",
            "event": "事件觸發器",
        }
        display_type = display_type_map.get(draft_type, draft_type)

        yield {
            "type": "draft_ready",
            "draft_type": draft_type,
            "draft_id": draft_id,
            "deep_link_data": draft_result.get("deep_link_data", {}),
            "message": f"{display_type}草稿已準備完畢！請點擊下方按鈕開啟建構器進行確認與試跑。",
        }

    async def _create_draft_directly(self, draft_type: str, params: Dict[str, Any], user_id: int = 1) -> Dict[str, Any]:
        """Create an agent draft directly via DB (avoids HTTP round-trip auth complexity)."""
        import uuid as _uuid  # noqa: PLC0415
        from sqlalchemy.ext.asyncio import AsyncSession  # noqa: PLC0415
        from app.api.dependencies import get_db  # noqa: PLC0415
        from app.ontology.models.agent_draft import AgentDraftModel  # noqa: PLC0415

        draft_id = str(_uuid.uuid4())
        payload_str = json.dumps(params, ensure_ascii=False)

        # Use a fresh DB session for this internal operation
        async for db in get_db():
            draft = AgentDraftModel(
                id=draft_id,
                draft_type=draft_type,
                payload=payload_str,
                user_id=user_id,
                status="pending",
            )
            db.add(draft)
            await db.commit()
            break

        view_map = {"mcp": "mcp-builder", "skill": "skill-builder"}
        return {
            "draft_id": draft_id,
            "draft_type": draft_type,
            "status": "pending",
            "deep_link_data": {
                "view": view_map.get(draft_type, "nested-builder"),
                "draft_id": draft_id,
                "auto_fill": params,
            },
        }
