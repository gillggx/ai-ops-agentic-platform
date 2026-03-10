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

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agent_session import AgentSessionModel
from app.models.mcp_definition import MCPDefinitionModel
from app.models.skill_definition import SkillDefinitionModel
from app.services.agent_memory_service import AgentMemoryService
from app.services.context_loader import ContextLoader
from app.services.data_distillation_service import DataDistillationService
from app.services.tool_dispatcher import TOOL_SCHEMAS, ToolDispatcher

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
_SESSION_TTL_HOURS = 24
_SESSION_MAX_MESSAGES = 12
_TOOL_RESULT_MAX_CHARS = 6000   # cap for history; live results use _LLM_RESULT_MAX_CHARS
_LLM_RESULT_MAX_CHARS  = 8000   # cap applied to every tool_result before adding to messages
_COMPACTION_TOKEN_THRESHOLD = 60_000  # v14: compact history when exceeded

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
        mcp_id = tool_input.get("mcp_id")
        if not mcp_id:
            return {
                "status": "error", "code": "MISSING_MCP_ID",
                "message": "⚠️ execute_mcp 缺少 mcp_id。請先呼叫 list_mcps 確認正確的 MCP ID 後再重試。",
            }
        result = await db.execute(select(MCPDefinitionModel).where(MCPDefinitionModel.id == mcp_id))
        mcp = result.scalar_one_or_none()
        if not mcp:
            return {
                "status": "error", "code": "MCP_NOT_FOUND",
                "message": f"⚠️ MCP #{mcp_id} 不存在。請呼叫 list_mcps 取得有效的 MCP 列表後重試。",
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
                            f"⛔ [STOP — 禁止再次呼叫 execute_mcp] MCP「{mcp.name}」缺少必填查詢參數：{missing}。"
                            f"你必須立即停止工具呼叫，直接以文字訊息向用戶詢問這些參數的值，等待用戶回答後才能繼續。"
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
    """v14: Replace old messages with an <archive_summary> when token budget exceeded.

    Keeps the last 4 messages (2 turns) intact; summarises the rest into a
    single user message. No LLM call — fast keyword extraction for dev.
    """
    if len(messages) <= 4:
        return messages

    old_messages = messages[:-4]
    recent_messages = messages[-4:]

    # Build a plain-text archive from old messages
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

    compacted = [{"role": "user", "content": archive_text}] + recent_messages
    return _clean_history_boundary(compacted)


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
        dataset = od.get("dataset") or []
        trimmed: Dict[str, Any] = {k: result[k] for k in ("status", "mcp_id", "llm_readable_data") if k in result}
        trimmed.update(_dataset_summary(dataset) if dataset else {"dataset_summary": "(無資料)"})
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


def _build_render_card(
    tool_name: str,
    tool_input: Dict[str, Any],
    result: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if tool_name == "execute_skill" and isinstance(result, dict) and "ui_render_payload" in result:
        lrd = result.get("llm_readable_data") or {}
        urp = result.get("ui_render_payload") or {}
        chart_data = urp.get("chart_data")
        return {
            "type": "skill",
            "skill_name": result.get("skill_name", f"Skill #{tool_input.get('skill_id')}"),
            "status": lrd.get("status", "UNKNOWN"),
            "conclusion": lrd.get("diagnosis_message", ""),
            "summary": lrd.get("summary", ""),
            "problem_object": lrd.get("problematic_targets", []),
            "mcp_output": {
                "ui_render": {
                    "chart_data": chart_data,
                    "charts": [chart_data] if chart_data else [],
                },
                "dataset": urp.get("dataset"),
                "_raw_dataset": urp.get("dataset"),
                "_call_params": tool_input.get("params", {}),
            },
        }

    if tool_name == "execute_mcp" and isinstance(result, dict) and result.get("status") == "success":
        od = result.get("output_data") or {}
        mcp_id = tool_input.get("mcp_id")
        mcp_name = result.get("mcp_name") or f"MCP #{mcp_id}"
        dataset = od.get("dataset")
        raw_dataset = od.get("_raw_dataset") or dataset
        return {
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

    return None


# ── Stage Labels ───────────────────────────────────────────────────────────────

_STAGE_LABELS = {
    1: "情境感知 (Context Load)",
    2: "意圖解析與規劃 (Planning)",
    3: "工具調用與安全審查 (Tool Execution)",
    4: "邏輯推理與彙整 (Reasoning)",
    5: "回覆與記憶寫入 (Memory Write)",
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
    """v14 Five-stage agentic loop with full observability and safety features."""

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
        settings = get_settings()
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._model = settings.LLM_MODEL
        self._memory_svc = AgentMemoryService(db)
        self._context_loader = ContextLoader(db)
        self._distill_svc = DataDistillationService()

    async def run(
        self,
        message: str,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        return self._run_impl(message, session_id)

    async def _run_impl(
        self,
        message: str,
        session_id: Optional[str],
    ) -> AsyncIterator[Dict[str, Any]]:

        # ══════════════════════════════════════════════════════════════
        # Stage 1: Context Load
        # ══════════════════════════════════════════════════════════════
        yield _stage_event(1, "running")

        system_blocks, context_meta = await self._context_loader.build(
            user_id=self._user_id,
            query=message,
            top_k_memories=5,
            canvas_overrides=self._canvas_overrides,
        )
        session_id, history, cumulative_tokens = await self._load_session(session_id)
        context_meta["history_turns"] = len(history) // 2
        context_meta["cumulative_tokens"] = cumulative_tokens

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

        # ══════════════════════════════════════════════════════════════
        # v14: Token Compaction — compact before we start if already over threshold
        # ══════════════════════════════════════════════════════════════
        if _session_input_tokens > _COMPACTION_TOKEN_THRESHOLD and len(messages) > 5:
            logger.info("Token compaction triggered: %d tokens", _session_input_tokens)
            messages = _compact_history(messages)
            yield {
                "type": "token_usage",
                "cumulative_tokens": _session_input_tokens,
                "compaction": True,
                "message": f"Session 已累積 {_session_input_tokens:,} tokens，已壓縮歷史對話。",
            }

        # ══════════════════════════════════════════════════════════════
        # Stage 2-4: Tool Use Loop
        # ══════════════════════════════════════════════════════════════
        yield _stage_event(2, "running")

        while iteration < MAX_ITERATIONS:
            iteration += 1
            logger.info("AgentOrchestrator v14: iteration=%d user=%d", iteration, self._user_id)

            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    system=system_blocks,   # v14: List[Dict] with cache_control
                    tools=TOOL_SCHEMAS,
                    messages=messages,
                )
            except Exception as exc:
                logger.exception("LLM call failed")
                yield {"type": "error", "message": f"LLM 呼叫失敗: {exc}"}
                yield {"type": "done"}
                return

            # Emit token usage (v14: includes cache stats)
            if hasattr(response, "usage") and response.usage:
                usage = response.usage
                iter_input = getattr(usage, "input_tokens", 0)
                iter_output = getattr(usage, "output_tokens", 0)
                cache_read = getattr(usage, "cache_read_input_tokens", 0)
                cache_create = getattr(usage, "cache_creation_input_tokens", 0)
                _session_input_tokens += iter_input
                yield {
                    "type": "llm_usage",
                    "input_tokens": iter_input,
                    "output_tokens": iter_output,
                    "cache_read_tokens": cache_read,
                    "cache_creation_tokens": cache_create,
                    "cumulative_tokens": _session_input_tokens,
                    "iteration": iteration,
                }

            # Stream thinking blocks
            for thinking_text in _extract_thinking(response.content):
                yield {"type": "thinking", "text": thinking_text}

            # ── end_turn: extract plan then synthesize ─────────────────
            if response.stop_reason == "end_turn":
                final_text = _extract_text(response.content)

                # v14: Extract <plan> from first assistant response
                if not _plan_extracted:
                    plan_match = re.search(r"<plan>([\s\S]*?)</plan>", final_text)
                    if plan_match:
                        _plan_extracted = True
                        yield _stage_event(2, "complete", plan=plan_match.group(1).strip())
                    else:
                        yield _stage_event(2, "complete")

                yield _stage_event(4, "running")
                yield {"type": "synthesis", "text": final_text}
                yield _stage_event(4, "complete")
                messages.append({"role": "assistant", "content": _content_to_list(response.content)})
                break

            # ── tool_use: Execute tools ────────────────────────────────
            if response.stop_reason == "tool_use":
                tool_calls = _extract_tool_calls(response.content)
                messages.append({"role": "assistant", "content": _content_to_list(response.content)})

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

                    # ── v14: Programmatic Distillation for data tools ──────
                    if tool_name == "execute_mcp" and isinstance(result, dict) and result.get("status") == "success":
                        result = await self._distill_svc.distill_mcp_result(result)

                    # ── Force synthesis on unrecoverable errors ────────────
                    if isinstance(result, dict) and result.get("status") == "error":
                        if tool_name in ("execute_mcp", "execute_skill"):
                            _force_synthesis = True
                    if isinstance(result, dict) and result.get("code") == "MISSING_PARAMS":
                        _force_synthesis = True

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

                    render_card = _build_render_card(tool_name, tool_input, result)
                    done_event: Dict[str, Any] = {
                        "type": "tool_done",
                        "tool": tool_name,
                        "result_summary": _result_summary(result),
                        "iteration": iteration,
                    }
                    if render_card:
                        done_event["render_card"] = render_card
                    yield done_event

                    _tr_content = json.dumps(_trim_for_llm(tool_name, result), ensure_ascii=False)
                    if len(_tr_content) > _LLM_RESULT_MAX_CHARS:
                        try:
                            _tr_parsed = json.loads(_tr_content)
                            for _drop in ("output_data", "ui_render_payload", "_raw_dataset", "dataset"):
                                _tr_parsed.pop(_drop, None)
                            _tr_content = json.dumps(_tr_parsed, ensure_ascii=False)[:_LLM_RESULT_MAX_CHARS]
                        except Exception:
                            _tr_content = _tr_content[:_LLM_RESULT_MAX_CHARS] + "…[截斷]"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": _tr_content,
                    })

                yield _stage_event(3, "complete")
                messages.append({"role": "user", "content": tool_results})

                # ── Force synthesis ────────────────────────────────────────
                if _force_synthesis:
                    yield _stage_event(4, "running")
                    try:
                        synth_resp = await self._client.messages.create(
                            model=self._model,
                            max_tokens=512,
                            system=system_blocks,
                            tool_choice={"type": "none"},
                            tools=TOOL_SCHEMAS,
                            messages=messages,
                        )
                        final_text = _extract_text(synth_resp.content)
                        yield {"type": "synthesis", "text": final_text}
                        messages.append({"role": "assistant", "content": _content_to_list(synth_resp.content)})
                    except Exception as exc:
                        yield {"type": "synthesis", "text": f"執行失敗，請確認參數後再試一次。（{exc}）"}
                    yield _stage_event(4, "complete")
                    break

                continue

            # Unexpected stop reason
            yield {"type": "error", "message": f"意外的 stop_reason: {response.stop_reason}"}
            break

        else:
            yield {
                "type": "error",
                "message": f"Agent 已達最大迭代上限 ({MAX_ITERATIONS})，強制中斷。請人工協助或簡化請求。",
                "iteration": iteration,
            }

        # ══════════════════════════════════════════════════════════════
        # Stage 5: Memory Write (conflict-aware)
        # ══════════════════════════════════════════════════════════════
        yield _stage_event(5, "running")

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
                        "content": mem.content[:100],
                        "source": mem.source,
                        "memory_id": mem.id,
                        "conflict_resolved": getattr(mem, "_conflict_resolved", False),
                    }
            except Exception as exc:
                logger.warning("Memory auto-write failed: %s", exc)

        yield _stage_event(5, "complete")

        # Save session with cumulative token count
        trimmed = _clean_history_boundary(messages[-_SESSION_MAX_MESSAGES:])
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
