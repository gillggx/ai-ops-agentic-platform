"""Agent Orchestrator — Agentic OS v14.0

Five-stage transparent loop with Anthropic tool_use:

  Stage 1: Context Load      — Soul + UserPref + RAG + Prompt Caching
  Stage 2: Intent & Planning — LLM outputs <plan> tag before any tools
  Stage 3: Tool Execution    — Sandbox distillation + HITL safety gate
  Stage 4: Reasoning         — LLM synthesises from distilled data
  Stage 5: Memory Write      — Conflict-aware RAG persistence

v14 New Features:
  - stage_update SSE (1-5) for full transparency
  - Sequential Planning: LLM must output <plan> before tool calls
  - Programmatic Distillation: Pandas stats summary via DataDistillationService
  - HITL: is_destructive tools pause and emit approval_required SSE
  - Token Compaction: compact history when cumulative tokens > 60k
  - Prompt Caching: stable blocks (Soul) get cache_control: ephemeral
  - Memory Conflict Resolution: UPDATE instead of ADD on contradicting entries
  - Workspace Sync: canvas_overrides injected as highest-priority context

SSE events emitted:
  stage_update     — Stage 1-5 transitions (status: running|complete)
  context_load     — Stage 1 metadata (soul, rag, cache stats)
  thinking         — LLM <thinking> blocks
  llm_usage        — Per-iteration token usage (includes cache_read_tokens)
  token_usage      — Cumulative session tokens (triggers compaction notice)
  tool_start       — Before each tool execution
  tool_done        — After each tool execution (+ render_card)
  approval_required — HITL: destructive tool awaiting user approval
  synthesis        — Final answer text
  memory_write     — After conflict-aware memory persistence
  error            — Any error or MAX_ITERATIONS hit
  done             — Stream end
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import uuid
from datetime import timedelta, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Phase 2-A: LangSmith tracing — no-op when LANGSMITH_API_KEY is unset.
try:
    from langsmith import traceable
except ImportError:
    def traceable(*args, **kwargs):  # type: ignore[no-redef]
        def _decorator(fn):
            return fn
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return _decorator

from app.config import get_settings
from app.utils.llm_client import get_llm_client
from app.models.agent_session import AgentSessionModel
from app.models.mcp_definition import MCPDefinitionModel
from app.models.skill_definition import SkillDefinitionModel
from app.services.agent_memory_service import AgentMemoryService
from app.services.context_loader import ContextLoader
from app.services.data_distillation_service import DataDistillationService
from app.services.task_context_extractor import extract as extract_task_context
from app.services.tool_dispatcher import TOOL_SCHEMAS, ToolDispatcher

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 12
_SESSION_TTL_HOURS = 24
_SESSION_MAX_MESSAGES = 12
_TOOL_RESULT_MAX_CHARS = 6000   # cap for history; live results use _LLM_RESULT_MAX_CHARS
_LLM_RESULT_MAX_CHARS  = 8000   # cap applied to every tool_result before adding to messages
_SOFT_COMPACT_THRESHOLD = 40_000   # v16: LLM-summarise oldest turns
_HARD_COMPACT_THRESHOLD = 60_000   # v16: keep last 3 turns + summary
_COMPACTION_TOKEN_THRESHOLD = _HARD_COMPACT_THRESHOLD  # back-compat alias

# v14: Tools that require human approval before execution
_DESTRUCTIVE_TOOLS = frozenset({
    "patch_skill_raw",   # modifies skill code directly
    "draft_routine_check",  # creates scheduled automation
    "draft_event_skill_link",  # links skill to event type (side-effects)
})

# v14: HITL approval registry — maps approval_token → asyncio.Event
# Single-process (uvicorn) safe. For multi-process, use Redis.
_pending_approvals: Dict[str, Optional[bool]] = {}  # token → True/False/None(pending)
_approval_events: Dict[str, asyncio.Event] = {}


def set_approval(token: str, approved: bool) -> bool:
    """Called by the /agent/approve/{token} endpoint. Returns False if token unknown."""
    if token not in _approval_events:
        return False
    _pending_approvals[token] = approved
    _approval_events[token].set()
    return True


# ── Pre-flight Validation ──────────────────────────────────────────────────────

async def _preflight_validate(
    db: AsyncSession,
    tool_name: str,
    tool_input: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Pre-flight validation — intercept ambiguous/missing params before execution."""
    if tool_name == "execute_mcp":
        mcp_name = tool_input.get("mcp_name")
        if not mcp_name:
            # mcp_id is no longer accepted — reject immediately with clear guidance
            return {
                "status": "error", "code": "MISSING_MCP_NAME",
                "message": (
                    "⚠️ execute_mcp 必須提供 mcp_name。"
                    "請從 <mcp_catalog> 中找到正確的 name 欄位填入，例如 'get_tool_trajectory'。"
                    "禁止使用 mcp_id（整數 ID 已棄用）。"
                ),
            }
        result = await db.execute(
            select(MCPDefinitionModel).where(MCPDefinitionModel.name == mcp_name)
        )
        mcp = result.scalar_one_or_none()
        if not mcp:
            return {
                "status": "error", "code": "MCP_NOT_FOUND",
                "message": (
                    f"⚠️ 找不到名為 '{mcp_name}' 的 MCP。"
                    "請確認 <mcp_catalog> 中的 name 欄位是否正確。"
                ),
            }
        # Custom MCP: only validate against its own input_schema (never inherit parent's)
        mcp_type = getattr(mcp, "mcp_type", "custom") or "custom"
        if mcp_type == "system":
            schema_src = mcp
        else:
            schema_src = mcp if getattr(mcp, "input_schema", None) else None

        if schema_src and schema_src.input_schema:
            try:
                schema = json.loads(schema_src.input_schema) if isinstance(schema_src.input_schema, str) else schema_src.input_schema
                fields = schema.get("fields", [])
                required = [f["name"] for f in fields if f.get("required")]
                all_field_names = [f["name"] for f in fields]
                provided = tool_input.get("params") or {}
                # For get_process_context: accept common aliases and auto-fillable params
                if mcp.name == "get_process_context":
                    provided = dict(provided)
                    if "lot_id" in provided and "targetID" not in provided:
                        provided["targetID"] = provided["lot_id"]
                    if "event_time" in provided and "eventTime" not in provided:
                        provided["eventTime"] = provided["event_time"]
                    # objectName defaults to DC; eventTime is auto-fetched by mcp_definition_service
                    provided.setdefault("objectName", "DC")
                    # Remove lot_id alias from params (already mapped to targetID)
                    provided.pop("lot_id", None)
                    # Write normalised params back so the actual MCP call uses them
                    tool_input["params"] = provided
                missing = [k for k in required if k not in provided or not provided[k]]
                if not provided and all_field_names and not required:
                    return {
                        "status": "error", "code": "MISSING_PARAMS",
                        "message": (
                            f"⛔ [STOP — 禁止再次呼叫 execute_mcp] MCP「{mcp.name}」有以下可用查詢參數：{all_field_names}。"
                            f"你必須立即停止工具呼叫，直接以文字訊息向用戶詢問他想查詢的值，等待用戶回答後才能繼續。"
                        ),
                        "available_params": all_field_names,
                    }
                if missing:
                    return {
                        "status": "error", "code": "MISSING_PARAMS",
                        "message": (
                            f"MCP「{mcp.name}」缺少必填查詢參數：{missing}。"
                            f"請先嘗試透過其他工具（如 list_recent_events）取得所需數值，"
                            f"若確實無法取得再向用戶詢問。"
                        ),
                        "missing_params": missing,
                        "required_params": required,
                    }
            except Exception:
                pass

    elif tool_name == "execute_skill":
        skill_id = tool_input.get("skill_id")
        if not skill_id:
            return {
                "status": "error", "code": "MISSING_SKILL_ID",
                "message": "⚠️ execute_skill 缺少 skill_id。請先呼叫 list_skills 確認正確的 Skill ID 後再重試。",
            }
        result = await db.execute(select(SkillDefinitionModel).where(SkillDefinitionModel.id == skill_id))
        skill = result.scalar_one_or_none()
        if not skill:
            return {
                "status": "error", "code": "SKILL_NOT_FOUND",
                "message": f"⚠️ Skill #{skill_id} 不存在。請呼叫 list_skills 取得有效的 Skill 列表後重試。",
            }

    return None


# ── History Utilities ──────────────────────────────────────────────────────────

def _sanitize_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cap oversized tool_result content in loaded history."""
    cleaned = []
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            new_content = []
            for item in msg["content"]:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    raw = item.get("content", "")
                    if isinstance(raw, str) and len(raw) > _TOOL_RESULT_MAX_CHARS:
                        try:
                            parsed = json.loads(raw)
                            for key in ("output_data", "ui_render_payload", "_raw_dataset"):
                                parsed.pop(key, None)
                            if "llm_readable_data" not in parsed:
                                parsed["_truncated"] = f"[已截斷，原始 {len(raw)} 字元]"
                            raw = json.dumps(parsed, ensure_ascii=False)[:_TOOL_RESULT_MAX_CHARS]
                        except Exception:
                            raw = raw[:_TOOL_RESULT_MAX_CHARS] + "…[截斷]"
                        item = {**item, "content": raw}
                new_content.append(item)
            cleaned.append({**msg, "content": new_content})
        else:
            cleaned.append(msg)
    return cleaned


def _clean_history_boundary(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove orphaned tool_result messages from trimmed history front."""
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "user":
            content = msg.get("content", "")
            is_tool_result = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
            if not is_tool_result:
                break
            i += 1
            if i < len(messages) and messages[i].get("role") == "assistant":
                i += 1
        else:
            i += 1
    return messages[i:]


def _compact_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Hard compaction (60k): keep last 3 turns + keyword summary. No LLM call."""
    return _hard_compact(messages)


def _hard_compact(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep last 6 messages (3 turns) + plain-text archive of the rest."""
    if len(messages) <= 6:
        return messages

    old_messages = messages[:-6]
    recent_messages = messages[-6:]

    archive_lines: List[str] = []
    for msg in old_messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            archive_lines.append(f"[{role}] {content[:200]}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        archive_lines.append(f"[{role}] {block.get('text', '')[:200]}")
                    elif block.get("type") == "tool_result":
                        archive_lines.append(f"[tool_result] {str(block.get('content', ''))[:150]}")

    archive_text = (
        "<archive_summary>\n"
        "以下為本 Session 早期對話摘要（已自動壓縮以節省 Token）：\n"
        + "\n".join(archive_lines[:20])
        + "\n</archive_summary>"
    )
    cleaned_recent = _clean_history_boundary(recent_messages)
    if not cleaned_recent:
        return [{"role": "user", "content": archive_text}]
    return [{"role": "user", "content": archive_text}] + cleaned_recent


async def _soft_compact(
    messages: List[Dict[str, Any]],
    llm: Any,
    settings: Any,
) -> List[Dict[str, Any]]:
    """Soft compaction (40k): LLM-summarises oldest turns into a context block.

    Summarises the oldest half of the conversation with a lightweight LLM call,
    preserving key facts (lots queried, tools used, anomalies found).
    Keeps the most recent 8 messages (4 turns) intact.
    """
    if len(messages) <= 8:
        return messages

    old_messages = messages[:-8]
    recent_messages = messages[-8:]

    # Build plain text of old turns for LLM to summarise
    raw_lines: List[str] = []
    for msg in old_messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            raw_lines.append(f"[{role}] {content[:300]}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    raw_lines.append(f"[{role}] {block.get('text', '')[:300]}")

    raw_text = "\n".join(raw_lines[:30])

    summary_prompt = (
        "以下是一段 AI 診斷對話的早期內容。請產出一段 150 字以內的情境摘要，"
        "保留：已查詢的 lot ID / tool ID / step、已確認的異常、已執行的 MCP/Skill 名稱、用戶的重要指示。"
        "丟棄：禮貌語、重複分析過程、工具原始資料。\n\n"
        f"對話內容：\n{raw_text}"
    )

    try:
        resp = await asyncio.wait_for(
            llm.messages.create(
                model=settings.LLM_MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": summary_prompt}],
            ),
            timeout=15.0,
        )
        summary_text = resp.content[0].text if resp.content else raw_text[:500]
    except Exception as exc:
        logger.warning("Soft compaction LLM call failed (%s) — using keyword summary", exc)
        summary_text = raw_text[:500]

    archive_text = (
        "<session_summary>\n"
        "本 Session 早期對話摘要（LLM 自動壓縮）：\n"
        + summary_text
        + "\n</session_summary>"
    )
    cleaned_recent = _clean_history_boundary(recent_messages)
    if not cleaned_recent:
        return [{"role": "user", "content": archive_text}]
    return [{"role": "user", "content": archive_text}] + cleaned_recent


# ── Data Helpers ───────────────────────────────────────────────────────────────

def _dataset_summary(dataset: List[Any]) -> Dict[str, Any]:
    n = len(dataset)
    stats_parts: List[str] = [f"總共 {n} 筆資料"]
    if n > 0 and isinstance(dataset[0], dict):
        columns = list(dataset[0].keys())
        stats_parts.append(f"欄位: {', '.join(columns[:10])}")
        for key, val in dataset[0].items():
            if isinstance(val, (int, float)):
                vals = [r.get(key) for r in dataset if isinstance(r.get(key), (int, float))]
                if vals:
                    avg = sum(vals) / len(vals)
                    stats_parts.append(f"{key} 平均值 {avg:.3f}")
                    break
    return {"dataset_summary": "。".join(stats_parts) + "。"}


def _trim_for_llm(tool_name: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Strip large rendering payloads before sending to LLM."""
    if tool_name == "execute_skill":
        return {k: result[k] for k in ("skill_name", "llm_readable_data", "status") if k in result}
    if tool_name == "execute_mcp":
        od = result.get("output_data") or {}
        dataset = od.get("dataset") or od.get("_raw_dataset") or []
        trimmed: Dict[str, Any] = {k: result[k] for k in ("status", "mcp_id", "mcp_name", "llm_readable_data") if k in result}
        trimmed.update(_dataset_summary(dataset) if dataset else {"dataset_summary": "(無資料)"})
        # Provide schema_sample (5 rows) so Agent can understand columns for writing execute_jit code
        if isinstance(dataset, list) and dataset:
            trimmed["schema_sample"] = dataset[:5]
            trimmed["schema_note"] = (
                f"共 {len(dataset)} 筆資料，schema_sample 為前 5 筆。"
                "如需統計/視覺化/回歸分析，優先呼叫 analyze_data(mcp_id=..., template='linear_regression'|'spc_chart'|'boxplot'|'stats_summary'|'correlation', params={value_col:...}) "
                "（模板已處理 datetime 回歸與 Y 軸）；複雜自定義邏輯才改用 execute_jit。"
            )
        return trimmed
    if tool_name in ("list_skills", "list_mcps", "list_system_mcps"):
        _HEAVY_FIELDS = ("last_diagnosis_result", "diagnostic_prompt", "param_mappings",
                         "processing_script", "api_config", "generated_code", "check_output_schema",
                         "sample_output", "ui_render_config", "input_definition")
        items = result.get("data") or result.get("items") or []
        if not isinstance(items, list):
            return result
        trimmed_items = []
        for item in items[:12]:
            if isinstance(item, dict):
                clean = {k: v for k, v in item.items() if k not in _HEAVY_FIELDS}
                for field in ("processing_intent", "description"):
                    if isinstance(clean.get(field), str) and len(clean[field]) > 300:
                        clean[field] = clean[field][:300] + "…"
                trimmed_items.append(clean)
            else:
                trimmed_items.append(item)
        base = {k: v for k, v in result.items() if k not in ("data", "items")}
        if "data" in result:
            base["data"] = trimmed_items
        else:
            base["items"] = trimmed_items
        if len(items) > 12:
            base["_truncated"] = True
        return base
    if "data" in result and isinstance(result.get("data"), list) and len(result["data"]) > 8:
        return {**result, "data": result["data"][:8], "_truncated": True}
    return result


# ── Content Block Helpers ──────────────────────────────────────────────────────

def _extract_text(content: List[Any]) -> str:
    parts = []
    for block in content:
        if hasattr(block, "type") and block.type == "text":
            parts.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _extract_thinking(content: List[Any]) -> List[str]:
    parts = []
    for block in content:
        if hasattr(block, "type") and block.type == "thinking":
            parts.append(block.thinking)
        elif isinstance(block, dict) and block.get("type") == "thinking":
            parts.append(block.get("thinking", ""))
    return parts


def _extract_tool_calls(content: List[Any]) -> List[Any]:
    return [
        b for b in content
        if (hasattr(b, "type") and b.type == "tool_use")
        or (isinstance(b, dict) and b.get("type") == "tool_use")
    ]


def _content_to_list(content: List[Any]) -> List[Dict]:
    result = []
    for block in content:
        if hasattr(block, "type"):
            if block.type == "text":
                result.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                result.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            elif block.type == "thinking":
                result.append({"type": "thinking", "thinking": block.thinking})
        elif isinstance(block, dict):
            result.append(block)
    return result


def _result_summary(result: Dict[str, Any]) -> str:
    if "error" in result:
        return f"ERROR: {result['error']}"
    if "llm_readable_data" in result:
        lrd = result["llm_readable_data"]
        if isinstance(lrd, dict):
            status = lrd.get("status", "?")
            msg = lrd.get("diagnosis_message", "")[:80]
            return f"status={status} | {msg}"
        if "output_data" in result and isinstance(result.get("output_data"), dict):
            ds = result["output_data"].get("dataset")
            count = len(ds) if isinstance(ds, list) else result.get("row_count", 0)
            name = result.get("mcp_name") or f"MCP #{result.get('mcp_id', '?')}"
            return f"{name} 回傳 {count} 筆資料"
    if "memories" in result:
        return f"{result['count']} 條記憶"
    if "draft_id" in result:
        return f"draft_id={result['draft_id']}"
    if "data" in result and isinstance(result["data"], list):
        return f"{len(result['data'])} 筆資料"
    return json.dumps(result, ensure_ascii=False)[:100]


# P3: ID hallucination detection — catches cases where LLM invents lotID/step
# that never appeared in any tool result. Regex-only, zero LLM cost.
_ID_PATTERNS = [
    re.compile(r"\bLOT-\d{4}\b"),       # LOT-0001, LOT-0123
    re.compile(r"\bSTEP_\d{3}\b"),      # STEP_001, STEP_091
    re.compile(r"\bEQP-\d{2}\b"),       # EQP-01, EQP-10
    re.compile(r"\bAPC-\d{3}\b"),       # APC-005, APC-092
    re.compile(r"\bRCP-\d{3}\b"),       # RCP-018
]

# Phase 1: Memory attribution — agent wraps cited memories as [memory:<id>]
# so we know which memories influenced this decision and can score them.
_MEMORY_CITATION_PATTERN = re.compile(r"\[memory:(\d+)\]")


def _extract_memory_citations(text: str) -> List[int]:
    """Return list of unique memory ids cited in the text via [memory:<id>] tags."""
    if not text:
        return []
    seen: set = set()
    ids: List[int] = []
    for m in _MEMORY_CITATION_PATTERN.finditer(text):
        try:
            mid = int(m.group(1))
            if mid not in seen:
                seen.add(mid)
                ids.append(mid)
        except ValueError:
            continue
    return ids


def _detect_id_hallucinations(
    final_text: str,
    tools_used: List[Dict[str, Any]],
) -> List[str]:
    """Return list of IDs that appear in final_text but not in any tool result.

    Supports LOT-xxxx / STEP_xxx / EQP-xx / APC-xxx / RCP-xxx formats.
    Returns unique IDs, preserving first-seen order from final_text.
    """
    if not final_text or not tools_used:
        return []

    # Combine all tool result texts into a single haystack (lower-cased for safety)
    haystack = ""
    for t in tools_used:
        rt = t.get("result_text") or ""
        if isinstance(rt, str):
            haystack += rt + "\n"
    if not haystack:
        return []

    hallucinated: List[str] = []
    seen: set = set()
    for pattern in _ID_PATTERNS:
        for match in pattern.finditer(final_text):
            ident = match.group(0)
            if ident in seen:
                continue
            seen.add(ident)
            if ident not in haystack:
                hallucinated.append(ident)
    return hallucinated


def _notify_chart_rendered(result: Dict[str, Any], chart_intents: List[Dict[str, Any]]) -> None:
    """Inject a strongly-worded notice into tool result telling the LLM that charts
    have already been rendered to the user's screen.

    Why: LLM only sees text, not side effects. Without this notice it keeps calling
    more plotting tools ("I haven't shown the chart yet") and embeds duplicate
    Vega-Lite specs in synthesis. The notice + _chart_rendered flag stops both.

    Mutates `result` in place.
    """
    if not chart_intents:
        return

    # Build human-readable chart list for the notice
    chart_lines: List[str] = []
    for intent in chart_intents:
        title = intent.get("title", "(untitled)")
        data_len = len(intent.get("data", [])) if isinstance(intent.get("data"), list) else 0
        chart_lines.append(f"  • {title}（{data_len} 點）")
    chart_list = "\n".join(chart_lines)

    notice = (
        "═══════════════════════════════════════════════\n"
        "✅ CHART RENDERED — 以下圖表已自動渲染至使用者畫面，使用者已看到：\n"
        f"{chart_list}\n"
        "\n"
        "⛔ 禁止再呼叫繪圖工具（execute_jit / analyze_data / plotly）畫同樣的圖\n"
        "⛔ synthesis 的 contract.visualization 必須為空陣列 []\n"
        "✅ 你的唯一任務：用 **文字** 說明觀察結論（OOC 點位、趨勢、建議），不要重畫圖\n"
        "═══════════════════════════════════════════════\n\n"
    )

    # Prepend notice to llm_readable_data so LLM sees it first (primacy effect)
    existing = result.get("llm_readable_data", "")
    if isinstance(existing, str):
        result["llm_readable_data"] = notice + existing
    elif isinstance(existing, dict):
        # Wrap as JSON string with notice prefix
        result["llm_readable_data"] = notice + json.dumps(existing, ensure_ascii=False)
    else:
        result["llm_readable_data"] = notice

    # Machine-readable flag + titles list (used by synthesis stage)
    result["_chart_rendered"] = True
    result["_chart_rendered_titles"] = [intent.get("title", "") for intent in chart_intents]


def _is_spc_result(result: Dict[str, Any]) -> bool:
    """Return True when an execute_mcp result contains SPC chart data.

    Two paths:
    - System MCP: dataset[0].data[] has raw rows with value/ucl/lcl/is_ooc
    - Custom MCP: output_data.ui_render.chart_data is present (Plotly JSON)
    """
    try:
        od = result.get("output_data", {})
        # Path A — system MCP raw data rows
        ds = od.get("dataset", [])
        if ds:
            inner = ds[0].get("data", [])
            if inner and isinstance(inner, list):
                sample = inner[0]
                if all(k in sample for k in ("value", "ucl", "lcl", "is_ooc")):
                    return True
        # Path B — custom MCP with Plotly chart_data
        if od.get("ui_render", {}).get("chart_data"):
            return True
        return False
    except Exception:
        return False


def _build_spc_contract(mcp_name: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Auto-build an AIOpsReportContract from a get_step_spc_chart MCP result.

    Called as fallback when the LLM synthesis does not include a <contract> block.
    Generates a Vega-Lite layered SPC X-bar chart from the raw data points.
    """
    try:
        ds = result.get("output_data", {}).get("dataset", [])
        if not ds:
            return None
        summary = ds[0]
        points  = summary.get("data", [])
        if not points:
            # Custom MCP path: no raw rows, but may have Plotly chart_data
            chart_data = result.get("output_data", {}).get("ui_render", {}).get("chart_data")
            if not chart_data:
                return None
            step      = summary.get("step", "")
            chart     = summary.get("chart_name", "SPC")
            pass_rate = summary.get("pass_rate", 0)
            ooc_count = summary.get("ooc_count", 0)
            trend     = summary.get("trend", "")
            total     = summary.get("total_points", 0)
            return {
                "$schema": "aiops-report/v1",
                "summary": (
                    f"{step} {chart} — 良率 {pass_rate}%，OOC {ooc_count} 筆，"
                    f"趨勢 {trend}，共 {total} 筆量測。"
                ),
                "evidence_chain": [
                    {"step": 1, "tool": mcp_name,
                     "finding": f"共 {total} 筆，OOC={ooc_count}，Pass rate={pass_rate}%，trend={trend}",
                     "viz_ref": "spc_chart"},
                ],
                "visualization": [
                    {"id": "spc_chart", "type": "plotly",
                     "spec": {"chart_data": chart_data}},
                ],
                "suggested_actions": [
                    {"label": "查看其他管制圖", "trigger": "agent",
                     "message": f"請顯示 {step} 的 r_chart 和 s_chart"},
                ],
            }

        ucl = points[0].get("ucl", 0)
        lcl = points[0].get("lcl", 0)
        cl  = round((ucl + lcl) / 2, 4)

        # Build flat values for Vega-Lite
        values = [
            {
                "x":      p.get("eventTime", "")[:19].replace("T", " "),
                "lot":    p.get("lotID", ""),
                "tool":   p.get("toolID", ""),
                "value":  round(p.get("value", 0), 4),
                "status": "OOC" if p.get("is_ooc") else "PASS",
            }
            for p in points
        ]

        step      = summary.get("step", "")
        chart     = summary.get("chart_name", "xbar_chart")
        pass_rate = summary.get("pass_rate", 0)
        ooc_count = summary.get("ooc_count", 0)
        trend     = summary.get("trend", "")

        vega_spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "background": "white",
            "width": "container",
            "height": 280,
            "data": {"values": values},
            "layer": [
                # 折線
                {
                    "mark": {"type": "line", "color": "#4299e1", "strokeWidth": 1.5},
                    "encoding": {
                        "x": {"field": "x", "type": "ordinal", "title": "時間",
                              "axis": {"labelAngle": -35, "labelFontSize": 9}},
                        "y": {"field": "value", "type": "quantitative", "title": chart,
                              "scale": {"zero": False}},
                    },
                },
                # 數據點（PASS / OOC 顏色）
                {
                    "mark": {"type": "point", "size": 70, "filled": True},
                    "encoding": {
                        "x": {"field": "x", "type": "ordinal"},
                        "y": {"field": "value", "type": "quantitative"},
                        "color": {
                            "field": "status", "type": "nominal",
                            "scale": {"domain": ["PASS", "OOC"], "range": ["#38a169", "#e53e3e"]},
                            "legend": {"title": "狀態"},
                        },
                        "tooltip": [
                            {"field": "x",      "title": "時間"},
                            {"field": "lot",    "title": "批次"},
                            {"field": "tool",   "title": "機台"},
                            {"field": "value",  "title": "量測值"},
                            {"field": "status", "title": "狀態"},
                        ],
                    },
                },
                # UCL
                {"mark": {"type": "rule", "color": "#e53e3e", "strokeDash": [6, 4], "strokeWidth": 1.5},
                 "encoding": {"y": {"datum": ucl}}},
                # LCL
                {"mark": {"type": "rule", "color": "#e53e3e", "strokeDash": [6, 4], "strokeWidth": 1.5},
                 "encoding": {"y": {"datum": lcl}}},
                # CL
                {"mark": {"type": "rule", "color": "#a0aec0", "strokeDash": [3, 3], "strokeWidth": 1},
                 "encoding": {"y": {"datum": cl}}},
                # UCL 標籤
                {"mark": {"type": "text", "align": "right", "dx": -4, "dy": -6,
                          "fontSize": 9, "color": "#e53e3e", "fontWeight": "bold"},
                 "encoding": {"y": {"datum": ucl}, "text": {"value": f"UCL={ucl}"}, "x": {"value": 0}}},
                # LCL 標籤
                {"mark": {"type": "text", "align": "right", "dx": -4, "dy": 10,
                          "fontSize": 9, "color": "#e53e3e", "fontWeight": "bold"},
                 "encoding": {"y": {"datum": lcl}, "text": {"value": f"LCL={lcl}"}, "x": {"value": 0}}},
            ],
        }

        return {
            "$schema": "aiops-report/v1",
            "summary": (
                f"{step} {chart} — 良率 {pass_rate}%，OOC {ooc_count} 筆，趨勢 {trend}。"
                f"管制界限 UCL={ucl} / LCL={lcl}。"
            ),
            "evidence_chain": [
                {"step": 1, "tool": mcp_name,
                 "finding": f"共 {len(values)} 筆量測，OOC={ooc_count}，Pass rate={pass_rate}%",
                 "viz_ref": "spc_chart"},
            ],
            "visualization": [
                {"id": "spc_chart", "type": "vega-lite", "spec": vega_spec}
            ],
            "suggested_actions": [
                {"label": "深入分析 OOC 批次",  "trigger": "agent",
                 "message": f"請分析 {step} 的 {ooc_count} 筆 OOC 批次的根因"},
                {"label": "查看其他管制圖",      "trigger": "agent",
                 "message": f"請顯示 {step} 的所有管制圖（range_chart, sigma_chart 等）"},
            ],
        }
    except Exception as exc:
        logger.warning("_build_spc_contract failed: %s", exc)
        return None


def _resolve_contract(
    text: str,
    last_spc_result: Optional[tuple],
    chart_already_rendered: bool = False,
) -> Optional[Dict[str, Any]]:
    """Return the best contract for a synthesis response.

    CHART 鐵律 — visualization 只能來自 tool（chart_intents / SPC auto-build）。
    LLM 若自行在 <contract> 的 visualization 欄位塞 Vega-Lite/Plotly spec，一律丟棄。

    Priority:
    1. LLM-generated <contract> block (parse from text) — visualization 永遠被清空
    2. Auto-built SPC contract from last MCP result (backend-generated, allowed)
    """
    parsed = _parse_contract(text)
    auto   = _build_spc_contract(*last_spc_result) if last_spc_result else None

    # ★ CHART 鐵律：永遠丟棄 LLM 自行生成的 visualization
    # 圖的唯一合法來源是 tool（chart_intents 透過 render_card 顯示，或 SPC auto-build）
    if parsed is not None:
        llm_viz = parsed.get("visualization") or []
        if llm_viz:
            logger.warning(
                "LLM embedded %d visualization items in <contract> — discarded per CHART 鐵律. "
                "Use execute_skill / execute_jit to render charts via chart_intents instead.",
                len(llm_viz),
            )
        parsed["visualization"] = []

    # Chart already rendered via chart_intents path → no contract-level viz needed
    if chart_already_rendered:
        return parsed  # visualization already [] above

    if parsed is None:
        return auto

    # Backend-generated SPC auto-contract is the ONLY allowed source of contract
    # visualization (and even then, chart_intents path is preferred).
    if auto and not parsed.get("visualization"):
        parsed["visualization"] = auto.get("visualization", [])

    return parsed


def _parse_contract(text: str) -> Optional[Dict[str, Any]]:
    """Extract and parse <contract>...</contract> block from synthesis text.

    Returns the parsed dict if valid (has $schema == 'aiops-report/v1'),
    otherwise None. Logs a warning on malformed JSON so issues are visible.
    """
    match = re.search(r"<contract>([\s\S]*?)</contract>", text)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("_parse_contract: invalid JSON in <contract> block: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    if data.get("$schema") != "aiops-report/v1":
        logger.warning("_parse_contract: unknown $schema=%r, ignoring", data.get("$schema"))
        return None
    # Ensure required keys exist with safe defaults so frontend doesn't crash
    data.setdefault("evidence_chain", [])
    data.setdefault("visualization", [])
    data.setdefault("suggested_actions", [])
    data.setdefault("summary", "")
    return data


def _build_render_card(
    tool_name: str,
    tool_input: Dict[str, Any],
    result: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if tool_name == "execute_skill" and isinstance(result, dict) and "ui_render_payload" in result:
        lrd = result.get("llm_readable_data") or {}
        urp = result.get("ui_render_payload") or {}

        # Modern path: _chart DSL → chart_intents (notify LLM + render directly)
        chart_intents = result.get("charts") or urp.get("chart_intents")
        if chart_intents:
            _notify_chart_rendered(result, chart_intents)

        card: Dict[str, Any] = {
            "type": "skill",
            "skill_name": result.get("skill_name", f"Skill #{tool_input.get('skill_id')}"),
            "status": lrd.get("status", "UNKNOWN"),
            "conclusion": lrd.get("summary", "") or lrd.get("diagnosis_message", ""),
            "summary": lrd.get("summary", ""),
            "problem_object": lrd.get("impacted_lots", []) or lrd.get("problematic_targets", []),
            "mcp_output": {
                "ui_render": {
                    "chart_data": urp.get("chart_data"),
                    "charts": [urp["chart_data"]] if urp.get("chart_data") else [],
                },
                "dataset": urp.get("dataset"),
                "_raw_dataset": urp.get("dataset"),
                "_call_params": tool_input.get("params", {}),
            },
        }
        if chart_intents:
            card["chart_intents"] = chart_intents
        return card

    if tool_name == "execute_mcp" and isinstance(result, dict) and result.get("status") == "success":
        od = result.get("output_data") or {}
        mcp_id = tool_input.get("mcp_id")
        mcp_name = result.get("mcp_name") or f"MCP #{mcp_id}"
        dataset = od.get("dataset")
        raw_dataset = od.get("_raw_dataset") or dataset

        card: Dict[str, Any] = {
            "type": "mcp",
            "mcp_name": mcp_name,
            "mcp_output": {
                "ui_render": od.get("ui_render") or {},
                "dataset": dataset,
                "_raw_dataset": raw_dataset,
                "_call_params": tool_input.get("params", {}),
                "_is_processed": od.get("_is_processed", True),
            },
        }

        # Auto-charts from get_process_info(objectName=SPC) → build contract
        mcp_charts = od.get("_charts") or result.get("_charts")
        if mcp_charts and isinstance(mcp_charts, list):
            from app.services.agent_orchestrator_v2.nodes.tool_execute import _chart_intent_to_vega_lite
            _notify_chart_rendered(result, mcp_charts)
            visualization = []
            for i, chart in enumerate(mcp_charts):
                try:
                    vega_spec = _chart_intent_to_vega_lite(chart)
                    visualization.append({
                        "id": f"chart_{i}",
                        "type": "vega-lite",
                        "title": chart.get("title", f"Chart {i+1}"),
                        "spec": vega_spec,
                    })
                except Exception:
                    pass
            if visualization:
                card["chart_intents"] = mcp_charts
                card["contract"] = {
                    "$schema": "aiops-report/v1",
                    "summary": f"{mcp_name} — {len(visualization)} 張管制圖",
                    "evidence_chain": [],
                    "visualization": visualization,
                    "suggested_actions": [],
                }

        return card

    _DRAFT_TOOL_TYPE_MAP = {
        "draft_skill": "skill",
        "draft_mcp": "mcp",
        "draft_routine_check": "routine_check",
        "draft_event_skill_link": "event_skill_link",
    }
    if tool_name in _DRAFT_TOOL_TYPE_MAP and isinstance(result, dict) and "draft_id" in result:
        draft_type = _DRAFT_TOOL_TYPE_MAP[tool_name]
        deep_link = result.get("deep_link_data") or {}
        return {
            "type": "draft",
            "draft_type": draft_type,
            "draft_id": result["draft_id"],
            "auto_fill": deep_link.get("auto_fill") or {},
        }

    # navigate tool → emit navigation action to frontend
    if tool_name == "navigate" and isinstance(result, dict) and result.get("action") == "navigate":
        return {
            "type": "navigate",
            "target": result.get("target"),
            "id": result.get("id"),
            "message": result.get("message", ""),
        }

    # [v15.3] execute_utility → chart or stats panel
    if tool_name == "execute_utility" and isinstance(result, dict):
        # Unwrap StandardResponse envelope if present
        tool_result = result.get("data") if "data" in result else result
        if isinstance(tool_result, dict) and tool_result.get("status") == "success":
            payload = tool_result.get("payload") or {}
            return {
                "type": "utility",
                "tool_name": tool_input.get("tool_name", "utility"),
                "summary": tool_result.get("summary", ""),
                "payload": payload,
            }

    # [v15.6] analyze_data → chart + result table (pre-built template, MCP-standard output)
    if tool_name == "analyze_data" and isinstance(result, dict):
        if result.get("status") == "success":
            ad_data = result.get("data") or {}
            chart_json = ad_data.get("chart_json")
            payload: Dict[str, Any] = {}
            if chart_json:
                try:
                    payload["plotly"] = json.loads(chart_json) if isinstance(chart_json, str) else chart_json
                except Exception:
                    payload["chart_json"] = chart_json
            # Always attach result_table as rows (the per-point data table output)
            result_table = ad_data.get("result_table")
            if result_table and isinstance(result_table, list) and result_table:
                payload["rows"] = result_table
                payload["columns"] = list(result_table[0].keys())
            # If no chart (stats_summary), use stats as key-value fallback
            if not chart_json:
                stats = ad_data.get("stats") or {}
                if isinstance(stats, dict):
                    payload.update(stats)
            title = ad_data.get("title") or f"{ad_data.get('template', 'analyze_data')} 分析"

            # Build AIOpsReportContract when chart exists → AnalysisPanel renders it
            contract = None
            if payload.get("plotly"):
                _notify_chart_rendered(result, [payload["plotly"]])
                contract = {
                    "$schema": "aiops-report/v1",
                    "summary": title,
                    "evidence_chain": [],
                    "visualization": [{
                        "id": "analyze_chart",
                        "type": "plotly",
                        "title": title,
                        "spec": payload["plotly"],
                    }],
                    "suggested_actions": [],
                }

            card: Dict[str, Any] = {
                "type": "utility",
                "tool_name": title,
                "summary": title,
                "payload": payload,
                "row_count": ad_data.get("row_count", 0),
                "jit_mcp_id": tool_input.get("mcp_id"),
                "jit_run_params": tool_input.get("run_params", {}),
                "jit_python_code": "",  # template-based; promote via promote-analysis
                "jit_title": title,
                # [v15.6] Template context for promote-analysis endpoint
                "analyze_template": tool_input.get("template"),
                "analyze_params": tool_input.get("params", {}),
                "analyze_stats": ad_data.get("stats") or {},
            }
            if contract:
                card["contract"] = contract
            return card

    # ── execute_analysis → contract with visualization (analysis panel) ──
    if tool_name == "execute_analysis" and isinstance(result, dict):
        if result.get("status") == "success":
            data = result.get("data") or {}
            charts = data.get("charts") or []
            findings = data.get("findings") or {}

            # Convert _chart DSL objects to Vega-Lite specs for contract.visualization
            from app.services.agent_orchestrator_v2.nodes.tool_execute import _chart_intent_to_vega_lite
            visualization = []
            for i, chart in enumerate(charts):
                try:
                    vega_spec = _chart_intent_to_vega_lite(chart)
                    visualization.append({
                        "id": f"chart_{i}",
                        "type": "vega-lite",
                        "title": chart.get("title", f"Chart {i+1}"),
                        "spec": vega_spec,
                    })
                except Exception:
                    pass

            # Build promote action payload
            promote_payload = {
                "title": data.get("title", ""),
                "steps_mapping": data.get("steps_mapping", []),
                "input_schema": data.get("input_schema", []),
                "output_schema": data.get("output_schema", []),
            }

            contract = {
                "$schema": "aiops-report/v1",
                "summary": findings.get("summary", data.get("title", "")),
                "evidence_chain": [
                    {"step": i + 1, "tool": s.get("step_id", ""), "finding": s.get("nl_segment", "")}
                    for i, s in enumerate(data.get("steps_mapping", []))
                ],
                "visualization": visualization,
                "suggested_actions": [
                    {
                        "label": "⭐ 儲存為我的 Skill",
                        "trigger": "promote_analysis",
                        "payload": promote_payload,
                    },
                ],
            }

            if charts:
                _notify_chart_rendered(result, charts)

            return {
                "type": "analysis",
                "tool_name": data.get("title", "Ad-hoc 分析"),
                "summary": findings.get("summary", ""),
                "contract": contract,
            }

    # [v15.4] execute_jit → chart or stats panel (server-side sandbox result)
    # result is the raw StandardResponse: {"status": "success", "data": {...}}
    if tool_name == "execute_jit" and isinstance(result, dict):
        if result.get("status") == "success":
            jit_data = result.get("data") or {}
            chart_json = jit_data.get("chart_json")
            chart_intents = jit_data.get("chart_intents")
            jit_result = jit_data.get("jit_result") or {}
            payload: Dict[str, Any] = {}
            if chart_intents:
                # _chart DSL — lightweight chart intent, rendered by frontend
                payload["chart_intents"] = chart_intents
                # Notify LLM that chart is already on screen — prevents redundant calls
                _notify_chart_rendered(result, chart_intents)
            elif chart_json:
                try:
                    payload["plotly"] = json.loads(chart_json) if isinstance(chart_json, str) else chart_json
                except Exception:
                    payload["chart_json"] = chart_json
            else:
                # Stats-only: render as key-value pairs (exclude large values)
                payload = {k: v for k, v in jit_result.items()
                           if not isinstance(v, (list, dict)) or k == "summary"}
            return {
                "type": "utility",
                "tool_name": jit_data.get("title", "JIT 分析"),
                "summary": jit_data.get("title", "JIT 分析"),
                "payload": payload,
                "row_count": jit_data.get("row_count", 0),
                # [v15.5] Promote-to-MCP/Skill context — passed back to frontend for "固化 ↗" button
                "jit_mcp_id": tool_input.get("mcp_id"),
                "jit_run_params": tool_input.get("run_params", {}),
                "jit_python_code": tool_input.get("python_code", ""),
                "jit_title": tool_input.get("title", "JIT 分析"),
            }

    return None


# ── v14.1: Trap Rule Derivation ────────────────────────────────────────────────

def _derive_fix_rule(
    tool_name: str,
    error_code: str,
    tool_input: Dict[str, Any],
    error_msg: str,
    result: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Derive a human-readable fix rule from a tool error for Trap memory.

    Returns None if the error should not be persisted (transient / user-rejected).
    """
    if error_code in ("MISSING_MCP_ID", "MISSING_MCP_NAME"):
        return "呼叫 execute_mcp 必須提供 mcp_name（填入 <mcp_catalog> 中的 name 欄位），禁止使用 mcp_id 整數"
    if error_code == "MCP_NOT_FOUND":
        name_hint = tool_input.get("mcp_name") or tool_input.get("mcp_id")
        return f"MCP '{name_hint}' 不存在，請確認 <mcp_catalog> 中的 name 欄位拼寫是否正確"
    if error_code == "MISSING_PARAMS":
        # missing_params is in the preflight result dict, NOT in tool_input
        missing = (result or {}).get("missing_params") or []
        return f"呼叫 {tool_name} 缺少必填參數 {missing}，需先透過其他工具取得（如 eventTime 從 list_recent_events 取），無法取得再詢問用戶"
    if error_code == "SKILL_NOT_FOUND":
        skill_id = tool_input.get("skill_id")
        return f"Skill #{skill_id} 不存在，呼叫 execute_skill 前必須先用 list_skills 確認 ID"
    if error_code == "APPROVAL_REJECTED":
        return None  # User rejection — not a bug, no Trap needed
    # Generic: persist if substantive and not transient
    if len(error_msg) > 20 and "timeout" not in error_msg.lower():
        return f"工具 {tool_name} 回傳錯誤，下次注意：{error_msg[:150]}"
    return None


# ── Stage Labels ───────────────────────────────────────────────────────────────

_STAGE_LABELS = {
    1: "情境感知 (Context Load)",
    2: "意圖解析與規劃 (Planning)",
    3: "工具調用與安全審查 (Tool Execution)",
    4: "邏輯推理與彙整 (Reasoning)",
    5: "數據來源驗證 (Self-Critique)",
    6: "記憶寫入 (Memory Write)",
}


def _stage_event(stage: int, status: str = "running", **extra: Any) -> Dict[str, Any]:
    return {
        "type": "stage_update",
        "stage": stage,
        "label": _STAGE_LABELS.get(stage, f"Stage {stage}"),
        "status": status,
        **extra,
    }


# ── Main Orchestrator ──────────────────────────────────────────────────────────

class AgentOrchestrator:
    """v16 Six-stage agentic loop: adds async Self-Critique (Stage 5) and layered Token Compaction."""

    def __init__(
        self,
        db: AsyncSession,
        base_url: str,
        auth_token: str,
        user_id: int,
        canvas_overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._db = db
        self._base_url = base_url
        self._auth_token = auth_token
        self._user_id = user_id
        self._canvas_overrides = canvas_overrides
        self._llm = get_llm_client()
        self._memory_svc = AgentMemoryService(db)
        self._context_loader = ContextLoader(db)
        self._distill_svc = DataDistillationService()

    async def run(
        self,
        message: str,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        return self._run_impl(message, session_id)

    async def _run_memory_lifecycle_background(
        self,
        user_query: str,
        final_text: str,
        tool_chain: List[Dict[str, Any]],
        cited_memory_ids: List[int],
        session_id: Optional[str],
    ) -> None:
        """Fire-and-forget: score cited memories + abstract new experience memory.

        Runs in an isolated DB session since the request-scoped session is
        closed by the time this runs. Any exceptions are swallowed (logged
        only) because this must not break the user-facing flow.
        """
        from app.database import AsyncSessionLocal
        from app.services.experience_memory_service import ExperienceMemoryService
        from app.services.memory_abstraction import abstract_memory

        try:
            async with AsyncSessionLocal() as bg_db:
                svc = ExperienceMemoryService(bg_db)

                # 1. Feedback: memories cited in the answer → +success
                # (If the agent used them and we got this far, the task succeeded)
                for mem_id in cited_memory_ids:
                    try:
                        await svc.record_feedback(mem_id, outcome="success")
                    except Exception as exc:
                        logger.warning(
                            "Memory feedback failed for id=%d: %s", mem_id, exc
                        )

                # 2. LLM abstraction: turn this successful interaction into
                # a new (intent, action) pair (or skip if not worth saving)
                try:
                    abstraction = await abstract_memory(
                        llm_client=self._llm,
                        user_query=user_query,
                        agent_final_text=final_text,
                        tool_chain=tool_chain,
                    )
                except Exception as exc:
                    logger.warning("Memory abstraction errored: %s", exc)
                    abstraction = None

                if abstraction is not None:
                    try:
                        await svc.write(
                            user_id=self._user_id,
                            intent_summary=abstraction["intent_summary"],
                            abstract_action=abstraction["abstract_action"],
                            source="auto",
                            source_session_id=session_id,
                        )
                        logger.info(
                            "Memory lifecycle: wrote new experience memory "
                            "for user=%d", self._user_id
                        )
                    except Exception as exc:
                        logger.warning("Memory write failed: %s", exc)
        except Exception as exc:
            logger.warning("Memory lifecycle background task failed: %s", exc)

    async def _run_reflection(
        self,
        final_text: str,
        tools_used: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Stage 5: Self-Critique — verify every concrete value in final_text
        is traceable to an executed tool call.

        Returns:
          {"pass": True}  — all values sourced
          {"pass": False, "issues": [...], "amended_text": str}
        """
        if not final_text or len(final_text) < 50:
            return {"pass": True}

        # Short-circuit: zero successful tool calls = 100% hallucination, no LLM needed
        if not tools_used:
            return {
                "pass": False,
                "issues": [{"text": "（所有工具呼叫均失敗）", "reason": "本輪無任何成功的工具呼叫，所有具體數值均無法追溯來源"}],
                "amended_text": "⚠️ 所有工具呼叫均未成功取得資料，無法提供分析。請補充必要的查詢參數後重試。",
            }

        # P3: Deterministic ID hallucination check (runs before LLM reflection).
        # Faster + more reliable than LLM-based checks for ID-like tokens.
        hallucinated_ids = _detect_id_hallucinations(final_text, tools_used)
        if hallucinated_ids:
            logger.warning(
                "Self-Critique: detected %d hallucinated IDs in Agent answer: %s",
                len(hallucinated_ids), hallucinated_ids[:10],
            )
            # Amend text: flag each hallucinated ID inline
            amended = final_text
            for bad_id in hallucinated_ids:
                amended = amended.replace(bad_id, f"{bad_id}⚠️[捏造]")
            return {
                "pass": False,
                "issues": [
                    {"text": bad_id, "reason": f"ID 未在任何工具回傳中出現，疑為捏造"}
                    for bad_id in hallucinated_ids
                ],
                "amended_text": (
                    amended
                    + "\n\n⚠️ Self-Critique 警告：以上標記的 ID（"
                    + ", ".join(hallucinated_ids[:5])
                    + ("..." if len(hallucinated_ids) > 5 else "")
                    + "）在本次工具回傳中找不到，可能是 AI 捏造，請以工具原始資料為準。"
                ),
            }

        tools_summary = ", ".join(
            f"{t['tool']}({t['mcp_name']})" if t.get("mcp_name") else t["tool"]
            for t in tools_used
        ) if tools_used else "（無工具呼叫）"

        reflection_prompt = (
            "你是數據品質審查員。以下是 AI Agent 剛輸出的答案，以及本次對話中實際執行過的工具清單。\n\n"
            f"【已執行的工具】\n{tools_summary}\n\n"
            f"【Agent 答案】\n{final_text[:2000]}\n\n"
            "請逐句檢查答案中每個具體數值（感測器讀數、時間戳記、UCL/LCL、百分比、ID 等）：\n"
            "- 若數值可追溯到上方工具清單的回傳 → 標記 OK\n"
            "- 若數值無法追溯（可能是 LLM 推測/捏造）→ 標記 ISSUE，說明原因\n\n"
            "若全部 OK，回傳：{\"pass\": true}\n"
            "若有 ISSUE，回傳：{\"pass\": false, \"issues\": [{\"text\": \"問題句子\", \"reason\": \"原因\"}], "
            "\"amended_text\": \"修訂後答案（用[查無資料]替換無來源的數值）\"}\n"
            "只回傳 JSON，不要任何說明文字。"
        )

        try:
            resp = await asyncio.wait_for(
                self._llm.create(
                    system="你是數據品質審查員。",
                    messages=[{"role": "user", "content": reflection_prompt}],
                    max_tokens=800,
                ),
                timeout=12.0,
            )
            raw = (resp.text or "").strip()
            # Strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
            if not raw:
                return {"pass": True}
            result = json.loads(raw)
            return result
        except Exception as exc:
            logger.warning("Self-critique reflection failed (non-blocking): %s", exc)
            return {"pass": True}  # fail open — don't block on reflection error

    @traceable(run_type="chain", name="agent_chat_turn")
    async def _run_impl(
        self,
        message: str,
        session_id: Optional[str],
    ) -> AsyncIterator[Dict[str, Any]]:

        # ══════════════════════════════════════════════════════════════
        # Stage 1: Context Load & Hybrid Retrieval
        # ══════════════════════════════════════════════════════════════
        yield _stage_event(1, "running")

        # v14.1: Extract task context for metadata pre-filtering (no LLM call)
        _tc_type, _tc_subject, _tc_tool = extract_task_context(message, self._canvas_overrides)
        _task_context: Dict[str, Optional[str]] = {
            "task_type": _tc_type,
            "data_subject": _tc_subject,
            "tool_name": _tc_tool,
        }

        system_blocks, context_meta = await self._context_loader.build(
            user_id=self._user_id,
            query=message,
            top_k_memories=5,
            canvas_overrides=self._canvas_overrides,
            task_context=_task_context,   # v14.1: pre-filtered memory retrieval
        )
        session_id, history, cumulative_tokens = await self._load_session(session_id)
        context_meta["history_turns"] = len(history) // 2
        context_meta["cumulative_tokens"] = cumulative_tokens

        # Phase 1: track retrieved experience memory ids for feedback fallback
        # (if agent fails to cite them via [memory:X] tag, we still credit them
        # with use/success counts because they did influence the context)
        _retrieved_memory_ids: List[int] = [
            int(h["id"]) for h in context_meta.get("rag_hits", [])
            if h.get("_source") == "experience" and isinstance(h.get("id"), int)
        ]

        yield _stage_event(1, "complete")
        yield {"type": "context_load", **context_meta}

        # v14: Emit workspace_update if canvas_overrides are active
        if self._canvas_overrides:
            yield {"type": "workspace_update", "canvas_overrides": self._canvas_overrides}

        messages: List[Dict[str, Any]] = history + [{"role": "user", "content": message}]

        dispatcher = ToolDispatcher(
            db=self._db,
            base_url=self._base_url,
            auth_token=self._auth_token,
            user_id=self._user_id,
        )

        final_text = ""
        iteration = 0
        _new_diagnosis: Optional[Dict] = None
        _plan_extracted = False
        _session_input_tokens = cumulative_tokens
        _tools_used: list = []   # Phase B: track successful tool calls for success pattern memory
        _last_spc_result: Optional[tuple] = None  # (mcp_name, result) — auto-contract fallback
        _chart_already_rendered: bool = False  # True once any tool result injected chart_intents via _notify_chart_rendered
        _analysis_contract: Optional[Dict[str, Any]] = None  # contract from execute_analysis render card (has visualization)

        # ══════════════════════════════════════════════════════════════
        # v16: Layered Token Compaction
        # ══════════════════════════════════════════════════════════════
        if _session_input_tokens > _HARD_COMPACT_THRESHOLD and len(messages) > 6:
            logger.info("Hard compaction triggered: %d tokens", _session_input_tokens)
            messages = _hard_compact(messages)
            yield {
                "type": "token_usage",
                "cumulative_tokens": _session_input_tokens,
                "compaction": "hard",
                "message": f"Session 已累積 {_session_input_tokens:,} tokens，已進行強制壓縮（保留最近 3 輪）。",
            }
        elif _session_input_tokens > _SOFT_COMPACT_THRESHOLD and len(messages) > 8:
            logger.info("Soft compaction triggered: %d tokens", _session_input_tokens)
            messages = await _soft_compact(messages, self._llm, get_settings())
            yield {
                "type": "token_usage",
                "cumulative_tokens": _session_input_tokens,
                "compaction": "soft",
                "message": f"Session 已累積 {_session_input_tokens:,} tokens，已進行智慧摘要壓縮。",
            }

        # ══════════════════════════════════════════════════════════════
        # Stage 2-4: Tool Use Loop
        # ══════════════════════════════════════════════════════════════
        yield _stage_event(2, "running")

        while iteration < MAX_ITERATIONS:
            iteration += 1
            logger.info("AgentOrchestrator v14: iteration=%d user=%d", iteration, self._user_id)
            logger.info("[DBG] messages_count=%d", len(messages))

            try:
                response = await self._llm.create(
                    system=system_blocks if isinstance(system_blocks, str) else
                           "\n".join(b.get("text", "") for b in system_blocks if isinstance(b, dict)),
                    max_tokens=8192,
                    tools=TOOL_SCHEMAS,
                    messages=messages,
                )
            except Exception as exc:
                logger.exception("LLM call failed")
                yield {"type": "error", "message": f"LLM 呼叫失敗: {exc}"}
                yield {"type": "done"}
                return

            # Emit token usage
            iter_input = response.input_tokens
            iter_output = response.output_tokens
            _session_input_tokens += iter_input
            yield {
                "type": "llm_usage",
                "input_tokens": iter_input,
                "output_tokens": iter_output,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "cumulative_tokens": _session_input_tokens,
                "iteration": iteration,
            }

            # Stream thinking blocks
            for thinking_text in _extract_thinking(response.content):
                yield {"type": "thinking", "text": thinking_text}

            # ── end_turn: extract plan then synthesize ─────────────────
            if response.stop_reason == "end_turn":
                final_text = _extract_text(response.content)
                import sys as _sys
                print(f"[ORCH-DBG] iter={iteration} stop=end_turn text_len={len(final_text)} preview={final_text[:200]!r}", file=_sys.stderr, flush=True)

                # Qwen3 / local-model fix: model outputs only a <plan> block, or outputs
                # a garbage tool-call fragment in text mode (filtered to empty string).
                # In both cases, nudge the model to use function calling properly.
                _plan_only = bool(
                    final_text
                    and re.match(r"^\s*<plan>[\s\S]*?</plan>\s*$", final_text.strip())
                )
                _empty_no_tools = not final_text and not response.content

                _MAX_FC_NUDGES = 2  # avoid wasting tokens if model consistently ignores function calling
                if (_plan_only or _empty_no_tools) and iteration <= _MAX_FC_NUDGES:
                    if _plan_only:
                        plan_match = re.search(r"<plan>([\s\S]*?)</plan>", final_text)
                        if plan_match and not _plan_extracted:
                            _plan_extracted = True
                            yield _stage_event(2, "complete", plan=plan_match.group(1).strip())
                        # Only add assistant message when content is non-empty
                        messages.append({"role": "assistant", "content": response.content})
                    # For empty response: don't add empty assistant message —
                    # just add a direct nudge to use function calling.
                    messages.append({"role": "user", "content": "請直接使用 function calling 呼叫工具執行任務，不要用文字描述工具呼叫。"})
                    continue

                # Phase B: Planning depth validation.
                # If the model returned a <plan> shorter than 50 chars (shallow planning),
                # nudge it once to produce a more detailed plan before executing tools.
                if not _plan_extracted and iteration == 1:
                    plan_match = re.search(r"<plan>([\s\S]*?)</plan>", final_text)
                    if plan_match:
                        plan_text = plan_match.group(1).strip()
                        if len(plan_text) < 50 and iteration < MAX_ITERATIONS - 1:
                            # Shallow plan — ask for more detail before proceeding
                            messages.append({"role": "assistant", "content": response.content})
                            messages.append({"role": "user", "content": "請詳細列出每個步驟的工具名稱和參數，然後立即開始執行。"})
                            continue

                # v14: Extract <plan> from first assistant response
                if not _plan_extracted:
                    plan_match = re.search(r"<plan>([\s\S]*?)</plan>", final_text)
                    if plan_match:
                        _plan_extracted = True
                        yield _stage_event(2, "complete", plan=plan_match.group(1).strip())
                    else:
                        yield _stage_event(2, "complete")

                yield _stage_event(4, "running")
                _synth_contract = _resolve_contract(final_text, _last_spc_result, _chart_already_rendered)
                # execute_analysis / analyze_data contract has visualization — use it when _resolve_contract doesn't
                if _analysis_contract and (not _synth_contract or not _synth_contract.get("visualization")):
                    _synth_contract = _analysis_contract
                # Strip raw <contract> block from user-visible text when chart already rendered
                _synth_text = final_text
                if _chart_already_rendered:
                    _synth_text = re.sub(r"<contract>[\s\S]*?</contract>", "", _synth_text).strip()
                yield {"type": "synthesis", "text": _synth_text, "contract": _synth_contract}
                yield _stage_event(4, "complete")
                messages.append({"role": "assistant", "content": response.content})
                break

            # ── tool_use: Execute tools ────────────────────────────────
            if response.stop_reason == "tool_use":
                tool_calls = _extract_tool_calls(response.content)
                import sys as _sys
                print(f"[ORCH-DBG] iter={iteration} stop=tool_use tools={[t['name'] for t in tool_calls]}", file=_sys.stderr, flush=True)
                messages.append({"role": "assistant", "content": response.content})

                # v14: Extract <plan> from tool_use response text
                if not _plan_extracted:
                    resp_text = _extract_text(response.content)
                    plan_match = re.search(r"<plan>([\s\S]*?)</plan>", resp_text)
                    if plan_match:
                        _plan_extracted = True
                        yield _stage_event(2, "complete", plan=plan_match.group(1).strip())
                    else:
                        yield _stage_event(2, "complete")

                yield _stage_event(3, "running")

                tool_results = []
                _force_synthesis = False
                _profiles_this_round: list = []  # [P0 v15] DataProfiles collected this iteration

                for tc in tool_calls:
                    tool_id = tc.id if hasattr(tc, "id") else tc.get("id", "")
                    tool_name = tc.name if hasattr(tc, "name") else tc.get("name", "")
                    tool_input = tc.input if hasattr(tc, "input") else tc.get("input", {})

                    yield {
                        "type": "tool_start",
                        "tool": tool_name,
                        "input": tool_input,
                        "iteration": iteration,
                    }

                    # ── v14: HITL — destructive tool gate ─────────────────
                    if tool_name in _DESTRUCTIVE_TOOLS:
                        approval_token = str(uuid.uuid4())[:8]
                        _approval_events[approval_token] = asyncio.Event()
                        _pending_approvals[approval_token] = None

                        yield {
                            "type": "approval_required",
                            "approval_token": approval_token,
                            "tool": tool_name,
                            "input": tool_input,
                            "message": f"⚠️ 工具「{tool_name}」會修改系統設定，需要您的批准。請點擊「批准」或「拒絕」。",
                            "timeout_seconds": 60,
                        }

                        # Wait for approval (60s timeout)
                        try:
                            await asyncio.wait_for(
                                _approval_events[approval_token].wait(),
                                timeout=60.0,
                            )
                            approved = _pending_approvals.get(approval_token, False)
                        except asyncio.TimeoutError:
                            approved = False
                        finally:
                            _approval_events.pop(approval_token, None)
                            _pending_approvals.pop(approval_token, None)

                        if not approved:
                            result = {
                                "status": "error",
                                "code": "APPROVAL_REJECTED",
                                "message": f"用戶拒絕或超時未批准「{tool_name}」操作，已取消執行。",
                            }
                            _force_synthesis = True
                        else:
                            # Proceed with execution
                            preflight_err = await _preflight_validate(self._db, tool_name, tool_input)
                            result = preflight_err if preflight_err else await dispatcher.execute(tool_name, tool_input)
                    else:
                        # ── Pre-flight validation ──────────────────────────
                        preflight_err = await _preflight_validate(self._db, tool_name, tool_input)
                        if preflight_err:
                            result = preflight_err
                        else:
                            result = await dispatcher.execute(tool_name, tool_input)

                    # ── Auto-contract: track last SPC MCP result ──────────
                    if (tool_name == "execute_mcp" and isinstance(result, dict)
                            and _is_spc_result(result)):
                        _last_spc_result = (result.get("mcp_name", tool_name), result)

                    # Trap memory RAG DISABLED — trap memories are no longer written,
                    # so querying them would return stale/incorrect rules.

                    # ── v14: Programmatic Distillation for data tools ──────
                    if tool_name == "execute_mcp" and isinstance(result, dict) and result.get("status") == "success":
                        result = await self._distill_svc.distill_mcp_result(result)

                        # [P1 v15] Auto-persistence: fire-and-forget reusability evaluation
                        _jit_script = (
                            result.get("output_data", {}).get("_script") or
                            result.get("_script") or ""
                        )
                        if not _jit_script:
                            # Fallback: fetch processing_script from MCP record
                            _mcp_id = tool_input.get("mcp_id")
                            if _mcp_id:
                                try:
                                    from app.repositories.mcp_definition_repository import MCPDefinitionRepository
                                    _mcp_repo = MCPDefinitionRepository(self._db)
                                    _mcp_obj = await _mcp_repo.get_by_id(_mcp_id)
                                    _jit_script = getattr(_mcp_obj, "processing_script", "") or ""
                                except Exception:
                                    pass
                        if _jit_script:
                            asyncio.create_task(
                                self._maybe_persist_tool(
                                    code=_jit_script,
                                    context=f"execute_mcp id={tool_input.get('mcp_id')} params={json.dumps(tool_input.get('params', {}), ensure_ascii=False)[:200]}",
                                )
                            )

                    # [v15.4] Auto-persist execute_jit code → Agent Tool Chest
                    if tool_name == "execute_jit" and isinstance(result, dict) and result.get("status") == "success":
                        _jit_code = tool_input.get("python_code", "")
                        if _jit_code:
                            asyncio.create_task(
                                self._maybe_persist_tool(
                                    code=_jit_code,
                                    context=(
                                        f"execute_jit title={tool_input.get('title', '')} "
                                        f"mcp_id={tool_input.get('mcp_id')} "
                                        f"row_count={result.get('data', {}).get('row_count', '?')}"
                                    ),
                                )
                            )

                    # ── Force synthesis on unrecoverable errors ────────────
                    # MISSING_PARAMS is recoverable (agent can call prerequisite tools first)
                    if isinstance(result, dict) and result.get("status") == "error":
                        if tool_name in ("execute_mcp", "execute_skill"):
                            if result.get("code") != "MISSING_PARAMS":
                                _force_synthesis = True

                    # Trap memory auto-write DISABLED — tool routing stability
                    # should come from MCP catalog descriptions, not runtime memory.
                    # Auto-generated trap rules from transient errors tend to
                    # corrupt future sessions more than they help.

                    # Capture ABNORMAL diagnosis for memory
                    if tool_name == "execute_skill" and isinstance(result, dict):
                        lrd = result.get("llm_readable_data", {})
                        if isinstance(lrd, dict) and lrd.get("status") == "ABNORMAL":
                            _new_diagnosis = {
                                "skill_id": tool_input.get("skill_id"),
                                "skill_name": result.get("skill_name", ""),
                                "targets": lrd.get("problematic_targets", []),
                                "message": lrd.get("diagnosis_message", ""),
                            }

                    # Phase B: track successful tool calls for success pattern memory
                    # + raw result text for hallucination detection (P3)
                    if isinstance(result, dict) and result.get("status") == "success":
                        try:
                            _result_text = json.dumps(result, ensure_ascii=False, default=str)[:20000]
                        except Exception:
                            _result_text = str(result)[:20000]
                        _tools_used.append({
                            "tool": tool_name,
                            "mcp_name": tool_input.get("mcp_name", ""),
                            "params": {k: v for k, v in tool_input.items()
                                       if k not in ("mcp_id", "mcp_name", "python_code", "params")},
                            "result_text": _result_text,
                        })

                    render_card = _build_render_card(tool_name, tool_input, result)

                    # ── Chart rendered flag: _build_render_card may have injected
                    # _chart_rendered=True via _notify_chart_rendered (for execute_jit
                    # and execute_skill chart_intents paths). Check AFTER the call so
                    # the flag is visible when synthesis runs later.
                    if isinstance(result, dict) and result.get("_chart_rendered"):
                        _chart_already_rendered = True
                    # Capture contract from any tool render card (analysis, utility w/ chart)
                    if render_card and render_card.get("contract"):
                        _analysis_contract = render_card["contract"]
                    done_event: Dict[str, Any] = {
                        "type": "tool_done",
                        "tool": tool_name,
                        "result_summary": _result_summary(result),
                        "iteration": iteration,
                    }
                    if render_card:
                        # [v15.2] Attach data_profile to MCP render_card → frontend fires shadow analysis
                        if render_card.get("type") == "mcp" and isinstance(result, dict):
                            _pre_profile = result.get("_data_profile")
                            if _pre_profile:
                                render_card["data_profile"] = _pre_profile
                                render_card["row_count"] = _pre_profile.get("row_count", 0)
                        done_event["render_card"] = render_card
                    yield done_event

                    # [P0 v15] Extract DataProfile before trimming (trim drops _data_profile key)
                    _profile = result.pop("_data_profile", None) if isinstance(result, dict) else None
                    if _profile:
                        _profiles_this_round.append(_profile)

                    _tr_content = json.dumps(_trim_for_llm(tool_name, result), ensure_ascii=False)
                    _cap = _LLM_RESULT_MAX_CHARS
                    if len(_tr_content) > _cap:
                        try:
                            _tr_parsed = json.loads(_tr_content)
                            for _drop in ("output_data", "ui_render_payload", "_raw_dataset", "dataset"):
                                _tr_parsed.pop(_drop, None)
                            # Trim schema_sample to fewer rows if still over limit
                            if tool_name == "execute_mcp" and "schema_sample" in _tr_parsed:
                                while len(json.dumps(_tr_parsed, ensure_ascii=False)) > _cap and _tr_parsed["schema_sample"]:
                                    _tr_parsed["schema_sample"] = _tr_parsed["schema_sample"][:-1]
                            _tr_content = json.dumps(_tr_parsed, ensure_ascii=False)[:_cap]
                        except Exception:
                            _tr_content = _tr_content[:_cap] + "…[截斷]"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": _tr_content,
                    })

                yield _stage_event(3, "complete")
                messages.append({"role": "user", "content": tool_results})

                # [P0 v15] Inject DataProfiles as hidden context for next LLM call
                if _profiles_this_round:
                    try:
                        from app.services.data_profile_service import build_profile_injection_text
                        _profile_text = build_profile_injection_text(_profiles_this_round)
                        messages.append({
                            "role": "user",
                            "content": f"<hidden_data_profile>\n{_profile_text}\n</hidden_data_profile>",
                        })
                        yield {
                            "type": "context_load",
                            "source": "data_profile",
                            "profiles": len(_profiles_this_round),
                            "columns": [list(p.get("meta", {}).keys()) for p in _profiles_this_round],
                        }
                    except Exception as _dp_exc:
                        logger.warning("DataProfile injection failed (non-blocking): %s", _dp_exc)

                # ── Force synthesis ────────────────────────────────────────
                if _force_synthesis:
                    yield _stage_event(4, "running")
                    try:
                        _sys_str = (
                            system_blocks if isinstance(system_blocks, str)
                            else "\n".join(
                                b.get("text", "") for b in system_blocks
                                if isinstance(b, dict)
                            )
                        )
                        # If no tools succeeded, inject a hard anti-hallucination constraint
                        _synthesis_messages = list(messages)
                        if not _tools_used:
                            _synthesis_messages.append({
                                "role": "user",
                                "content": (
                                    "⛔ 系統通知：本輪所有工具呼叫均失敗，無任何真實資料可用。"
                                    "你只能說明失敗原因並請用戶補充缺少的參數。"
                                    "嚴禁輸出任何具體數值、感測器讀數、百分比或分析結論。"
                                    "嚴禁使用任何 XML 標籤（如 <execute_mcp>、<analyze_data>）表示工具呼叫，只能輸出純文字說明。"
                                ),
                            })
                        synth_resp = await self._llm.create(
                            system=_sys_str,
                            max_tokens=512,
                            messages=_synthesis_messages,
                        )
                        final_text = _extract_text(synth_resp.content)
                        _fc = _resolve_contract(final_text, _last_spc_result, _chart_already_rendered)
                        if _analysis_contract and (not _fc or not _fc.get("visualization")):
                            _fc = _analysis_contract
                        yield {"type": "synthesis", "text": final_text, "contract": _fc}
                        # Also strip LLM-generated visualization from final_text when chart_already_rendered
                        messages.append({"role": "assistant", "content": synth_resp.content})
                    except Exception as exc:
                        yield {"type": "synthesis", "text": f"執行失敗，請確認參數後再試一次。（{exc}）"}
                    yield _stage_event(4, "complete")
                    break

                continue

            # Fallback: treat any non-tool_use stop as end_turn
            # (handles OpenRouter/Qwen3 returning non-standard finish_reason like "stop")
            logger.warning("AgentOrchestrator: unexpected stop_reason=%r, treating as end_turn", response.stop_reason)
            final_text = _extract_text(response.content)
            if not _plan_extracted:
                yield _stage_event(2, "complete")
            yield _stage_event(4, "running")
            _fb_contract = _resolve_contract(final_text, _last_spc_result, _chart_already_rendered)
            if _analysis_contract and (not _fb_contract or not _fb_contract.get("visualization")):
                _fb_contract = _analysis_contract
            yield {"type": "synthesis", "text": final_text, "contract": _fb_contract}
            yield _stage_event(4, "complete")
            messages.append({"role": "assistant", "content": response.content})
            break

        else:
            yield {
                "type": "error",
                "message": f"Agent 已達最大迭代上限 ({MAX_ITERATIONS})，強制中斷。請人工協助或簡化請求。",
                "iteration": iteration,
            }

        # ══════════════════════════════════════════════════════════════
        # Stage 5: Async Self-Critique — fire-and-forget, non-blocking
        # ══════════════════════════════════════════════════════════════
        yield _stage_event(5, "running")
        _reflection_task: Optional[asyncio.Task] = None
        if final_text and len(final_text) > 50:
            _reflection_task = asyncio.create_task(
                self._run_reflection(final_text, _tools_used)
            )
            yield {"type": "reflection_running", "message": "驗證數據來源中..."}

        # ══════════════════════════════════════════════════════════════
        # Stage 6: Memory Write (conflict-aware)
        # ══════════════════════════════════════════════════════════════
        yield _stage_event(6, "running")

        if _new_diagnosis:
            try:
                mem = await self._memory_svc.write_diagnosis_with_conflict_check(
                    user_id=self._user_id,
                    skill_name=_new_diagnosis["skill_name"],
                    targets=_new_diagnosis["targets"],
                    diagnosis_message=_new_diagnosis["message"],
                    skill_id=_new_diagnosis["skill_id"],
                )
                if mem:
                    yield {
                        "type": "memory_write",
                        "source": mem.source,
                        "memory_type": "diagnosis",
                        "content": mem.content[:100],
                        "memory_id": mem.id,
                        "conflict_resolved": getattr(mem, "_conflict_resolved", False),
                        "skill_name": _new_diagnosis.get("skill_name", ""),
                        "targets": _new_diagnosis.get("targets", []),
                    }
            except Exception as exc:
                logger.warning("Memory auto-write failed: %s", exc)

        # v14.1: HITL Preference Write — persist canvas_overrides as user preference
        if self._canvas_overrides:
            try:
                pref_mem = await self._memory_svc.write_preference(
                    user_id=self._user_id,
                    canvas_overrides=self._canvas_overrides,
                    task_type=_task_context.get("task_type"),
                    data_subject=_task_context.get("data_subject"),
                )
                yield {
                    "type": "memory_write",
                    "source": "hitl_preference",
                    "memory_type": "preference",
                    "content": pref_mem.content[:100],
                    "memory_id": pref_mem.id,
                    "overrides": list(self._canvas_overrides.keys()),
                    "conflict_resolved": False,
                }
            except Exception as exc:
                logger.warning("Preference memory write failed: %s", exc)

        # ── Phase 1 Memory Lifecycle: feedback + abstraction ────────────────
        # 1. Extract [memory:<id>] tags from final_text → record_feedback(success)
        #    on cited memories.
        # 2. If this was a meaningful multi-tool task → schedule async LLM
        #    abstraction + write new experience memory.
        # Both run via asyncio.create_task (fire-and-forget, doesn't block SSE).
        if _tools_used and len(_tools_used) >= 2 and final_text:
            cited_memory_ids = _extract_memory_citations(final_text)
            # Fallback (decision 4 "B+A"): if agent didn't cite anything but
            # RAG did retrieve memories, credit the retrieved ones as "passively used"
            feedback_memory_ids = cited_memory_ids or _retrieved_memory_ids
            asyncio.create_task(self._run_memory_lifecycle_background(
                user_query=message,
                final_text=final_text,
                tool_chain=list(_tools_used),
                cited_memory_ids=feedback_memory_ids,
                session_id=session_id,
            ))
            yield {
                "type": "memory_write",
                "source": "experience_lifecycle_scheduled",
                "cited_memory_ids": cited_memory_ids,
                "feedback_memory_ids": feedback_memory_ids,
                "feedback_source": "citation" if cited_memory_ids else "passive_retrieval",
                "tool_count": len(_tools_used),
            }

        yield _stage_event(6, "complete")

        # ── Await reflection result (usually already done) ────────────────────
        if _reflection_task is not None:
            try:
                reflection_result = await asyncio.wait_for(_reflection_task, timeout=15.0)
                if reflection_result.get("pass"):
                    yield {"type": "reflection_pass"}
                    yield _stage_event(5, "complete")
                else:
                    issues = reflection_result.get("issues", [])
                    amended = reflection_result.get("amended_text", "")
                    yield {
                        "type": "reflection_amendment",
                        "issues": issues,
                        "amended_text": amended,
                        "issue_count": len(issues),
                    }
                    yield _stage_event(5, "complete", issue_count=len(issues))
                    logger.warning(
                        "Self-critique found %d issue(s) in final answer", len(issues)
                    )
            except asyncio.TimeoutError:
                logger.warning("Self-critique timed out — skipping amendment")
                yield {"type": "reflection_pass"}
                yield _stage_event(5, "complete")
            except Exception as exc:
                logger.warning("Self-critique await failed: %s", exc)
                yield _stage_event(5, "complete")
        else:
            yield _stage_event(5, "complete")

        # Save session with cumulative token count
        # Strip ephemeral hidden_data_profile injections before saving — they are
        # single-turn context only and cause consecutive-user-message issues on reload.
        persistable = [
            m for m in messages
            if not (
                m.get("role") == "user"
                and isinstance(m.get("content"), str)
                and m["content"].startswith("<hidden_data_profile>")
            )
        ]
        trimmed = _clean_history_boundary(persistable[-_SESSION_MAX_MESSAGES:])
        await self._save_session(session_id, trimmed, _session_input_tokens)
        yield {"type": "done", "session_id": session_id}

    # ── Session Helpers ───────────────────────────────────────────────────────

    async def _load_session(
        self, session_id: Optional[str]
    ) -> tuple[str, List[Dict], int]:
        """Load or create a session. Returns (session_id, messages, cumulative_tokens)."""
        if session_id:
            result = await self._db.execute(
                select(AgentSessionModel).where(
                    AgentSessionModel.session_id == session_id,
                    AgentSessionModel.user_id == self._user_id,
                )
            )
            row = result.scalar_one_or_none()
            if row:
                expires = row.expires_at
                if expires:
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                    if expires < datetime.datetime.now(tz=timezone.utc):
                        await self._db.delete(row)
                        await self._db.commit()
                    else:
                        try:
                            raw_history = json.loads(row.messages)
                            cumulative = getattr(row, "cumulative_tokens", None) or 0
                            return session_id, _sanitize_history(raw_history), cumulative
                        except Exception:
                            pass

        new_id = str(uuid.uuid4())
        return new_id, [], 0

    async def _save_session(
        self,
        session_id: str,
        messages: List[Dict],
        cumulative_tokens: int = 0,
    ) -> None:
        """Upsert session with 24h TTL and cumulative token count."""
        try:
            result = await self._db.execute(
                select(AgentSessionModel).where(AgentSessionModel.session_id == session_id)
            )
            row = result.scalar_one_or_none()
            expires = datetime.datetime.now(tz=timezone.utc) + timedelta(hours=_SESSION_TTL_HOURS)
            serialized = json.dumps(messages, ensure_ascii=False)

            if row:
                row.messages = serialized
                row.expires_at = expires
                if hasattr(row, "cumulative_tokens"):
                    row.cumulative_tokens = cumulative_tokens
            else:
                kwargs: Dict[str, Any] = {
                    "session_id": session_id,
                    "user_id": self._user_id,
                    "messages": serialized,
                    "created_at": datetime.datetime.now(tz=timezone.utc),
                    "expires_at": expires,
                }
                if hasattr(AgentSessionModel, "cumulative_tokens"):
                    kwargs["cumulative_tokens"] = cumulative_tokens
                row = AgentSessionModel(**kwargs)
                self._db.add(row)
            await self._db.commit()
        except Exception as exc:
            logger.warning("Session save failed: %s", exc)

    async def _maybe_persist_tool(self, code: str, context: str = "") -> None:
        """[P1 v15] Fire-and-forget: evaluate JIT script and optionally save to Agent Tool Chest."""
        try:
            from app.services.agent_tool_service import AgentToolService
            svc = AgentToolService(self._db)
            eval_result = await svc.evaluate_reusability(code, context)
            if eval_result.get("reusable"):
                await svc.create(
                    user_id=self._user_id,
                    name=eval_result.get("name", "Unnamed Tool"),
                    code=code,
                    description=eval_result.get("description", ""),
                )
                logger.info(
                    "AgentTool auto-saved: name=%s user_id=%s",
                    eval_result.get("name"), self._user_id,
                )
        except Exception as exc:
            logger.warning("_maybe_persist_tool failed (non-blocking): %s", exc)
