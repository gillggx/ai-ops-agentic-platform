"""Agent Orchestrator — the v13 Real Agentic Loop.

Implements a 5-stage stateful while loop using Anthropic tool_use:

  Stage 1: Context Load  — assemble Soul + UserPref + RAG
  Stage 2: LLM Call      — send messages + tools to Anthropic
  Stage 3: Tool Execute  — intercept tool_use blocks, dispatch, append results
  Stage 4: Synthesis     — LLM produces final end_turn text
  Stage 5: Memory Write  — auto-persist ABNORMAL diagnoses to RAG

MAX_ITERATIONS = 5 (hard guardrail, configurable via SystemParameter)

SSE events emitted:
  context_load   — Stage 1 complete
  thinking       — LLM <thinking> blocks (if extended thinking enabled)
  tool_start     — before each tool execution
  tool_done      — after each tool execution
  synthesis      — final answer text
  memory_write   — after auto-persistence
  error          — any error or MAX_ITERATIONS hit
  done           — stream end
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
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
from app.services.tool_dispatcher import TOOL_SCHEMAS, ToolDispatcher

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
_SESSION_TTL_HOURS = 24
_SESSION_MAX_MESSAGES = 12  # keep last 12 messages (~6 turns) to limit tokens


async def _preflight_validate(
    db: AsyncSession,
    tool_name: str,
    tool_input: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Pre-flight validation (spec §3-A) — intercept ambiguous/missing params before execution.

    Returns an error dict (injected as tool_result) when validation fails so the LLM
    is forced to ask the user for clarification instead of proceeding blindly.
    Returns None when the call is safe to execute.
    """
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
        # Resolve input_schema: system MCP uses its own schema; custom MCP uses parent system MCP's
        mcp_type = getattr(mcp, "mcp_type", "custom") or "custom"
        if mcp_type == "system":
            schema_src = mcp  # the called MCP IS the system MCP
        else:
            sys_id = getattr(mcp, "system_mcp_id", None) or getattr(mcp, "data_subject_id", None)
            if sys_id:
                sys_result = await db.execute(
                    select(MCPDefinitionModel).where(MCPDefinitionModel.id == sys_id)
                )
                schema_src = sys_result.scalar_one_or_none()
            else:
                schema_src = None

        if schema_src and schema_src.input_schema:
            try:
                schema = json.loads(schema_src.input_schema) if isinstance(schema_src.input_schema, str) else schema_src.input_schema
                fields = schema.get("fields", [])
                required = [f["name"] for f in fields if f.get("required")]
                all_field_names = [f["name"] for f in fields]
                provided = tool_input.get("params") or {}
                missing = [k for k in required if k not in provided or not provided[k]]
                # Also block calls with completely empty params when there ARE input fields defined
                if not provided and all_field_names and not required:
                    # optional-only fields: still ask user rather than silently returning full dataset
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

    return None  # validation passed


_TOOL_RESULT_MAX_CHARS = 1500  # hard cap per tool_result when stored/loaded


def _sanitize_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Retroactively trim oversized tool_result content in loaded session history.

    Old sessions (pre-v13.3) may have full datasets stored. Cap any single
    tool_result content to _TOOL_RESULT_MAX_CHARS to prevent 400k token floods.
    """
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
                            # Strip heavy fields
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
    """Remove orphaned tool_result messages from the front of a trimmed history slice.

    When history is trimmed to the last N messages, the slice may start with a
    user(tool_result) message whose corresponding assistant(tool_use) was cut off.
    Anthropic API rejects such requests with 400 invalid_request_error.

    Strategy: skip any leading user(tool_result) + the following assistant response
    until we reach a clean user(text) turn.
    """
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
                break  # found a clean user text turn
            # Orphaned tool_result — skip it and the assistant turn that follows
            i += 1
            if i < len(messages) and messages[i].get("role") == "assistant":
                i += 1
        else:
            # History starts with assistant — invalid pair, skip
            i += 1
    return messages[i:]


def _dataset_summary(dataset: List[Any]) -> Dict[str, Any]:
    """Build a compact summary for large datasets — no raw rows sent to LLM."""
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
    """Strip large rendering payloads from tool results before sending to LLM (v13.3 §1.1).

    execute_skill → only llm_readable_data (structured status/targets)
    execute_mcp   → llm_readable_data + dataset_summary (count + columns + avg)
    list_*        → keep first 12 items, strip heavy fields
    others        → passthrough
    """
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
                # Truncate long text fields to keep catalog compact
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
    """Convert Anthropic content blocks to serializable list."""
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
            # skip other types (redacted_thinking, etc.)
        elif isinstance(block, dict):
            result.append(block)
    return result


def _result_summary(result: Dict[str, Any]) -> str:
    """Build a short human-readable summary of a tool result for the SSE event."""
    if "error" in result:
        return f"ERROR: {result['error']}"
    if "llm_readable_data" in result:
        lrd = result["llm_readable_data"]
        if isinstance(lrd, dict):
            status = lrd.get("status", "?")
            msg = lrd.get("diagnosis_message", "")[:80]
            return f"status={status} | {msg}"
        # execute_mcp: llm_readable_data is a JSON string of dataset preview
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
    """Build a frontend render_card for execute_skill / execute_mcp tool results."""
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

    return None


class AgentOrchestrator:
    """Five-stage agentic loop with SSE streaming."""

    def __init__(
        self,
        db: AsyncSession,
        base_url: str,
        auth_token: str,
        user_id: int,
    ) -> None:
        self._db = db
        self._base_url = base_url
        self._auth_token = auth_token
        self._user_id = user_id
        settings = get_settings()
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._model = settings.LLM_MODEL
        self._memory_svc = AgentMemoryService(db)
        self._context_loader = ContextLoader(db)

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

        # ── Stage 1: Context Load ──────────────────────────────────────────
        system_prompt, context_meta = await self._context_loader.build(
            user_id=self._user_id,
            query=message,
            top_k_memories=5,
        )
        # Load session history before emitting context_load so we can report turn count
        session_id, history = await self._load_session(session_id)
        context_meta["history_turns"] = len(history) // 2  # user+assistant pairs
        yield {"type": "context_load", **context_meta}

        messages: List[Dict[str, Any]] = history + [{"role": "user", "content": message}]

        dispatcher = ToolDispatcher(
            db=self._db,
            base_url=self._base_url,
            auth_token=self._auth_token,
            user_id=self._user_id,
        )

        final_text = ""
        iteration = 0
        _new_diagnosis: Optional[Dict] = None  # for Stage 5 memory write

        # ── Stage 2–4: Tool Use Loop ────────────────────────────────────────
        while iteration < MAX_ITERATIONS:
            iteration += 1
            logger.info("AgentOrchestrator: iteration=%d user=%d", iteration, self._user_id)

            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    system=system_prompt,
                    tools=TOOL_SCHEMAS,
                    messages=messages,
                )
            except Exception as exc:
                logger.exception("LLM call failed")
                yield {"type": "error", "message": f"LLM 呼叫失敗: {exc}"}
                yield {"type": "done"}
                return

            # Emit token usage
            if hasattr(response, "usage") and response.usage:
                yield {
                    "type": "llm_usage",
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "iteration": iteration,
                }

            # Stream thinking blocks (if present)
            for thinking_text in _extract_thinking(response.content):
                yield {"type": "thinking", "text": thinking_text}

            # ── end_turn: Synthesis ────────────────────────────────────────
            if response.stop_reason == "end_turn":
                final_text = _extract_text(response.content)
                yield {"type": "synthesis", "text": final_text}
                messages.append({"role": "assistant", "content": _content_to_list(response.content)})
                break

            # ── tool_use: Execute tools ────────────────────────────────────
            if response.stop_reason == "tool_use":
                tool_calls = _extract_tool_calls(response.content)
                messages.append({"role": "assistant", "content": _content_to_list(response.content)})

                tool_results = []
                _force_synthesis = False  # set when an error requires user action
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

                    # ── Pre-flight validation (spec §3-A) ─────────────────
                    preflight_err = await _preflight_validate(self._db, tool_name, tool_input)
                    if preflight_err:
                        result = preflight_err
                    else:
                        result = await dispatcher.execute(tool_name, tool_input)

                    # ── Detect unrecoverable errors → force synthesis ──────
                    # Any execute_mcp/execute_skill error cannot be resolved by
                    # the agent alone — it must ask the user or report the failure.
                    if isinstance(result, dict) and result.get("status") == "error":
                        if tool_name in ("execute_mcp", "execute_skill"):
                            _force_synthesis = True
                    # MISSING_PARAMS from preflight also requires force synthesis
                    if isinstance(result, dict) and result.get("code") == "MISSING_PARAMS":
                        _force_synthesis = True

                    # Capture ABNORMAL diagnosis for memory auto-write
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

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(_trim_for_llm(tool_name, result), ensure_ascii=False),
                    })

                messages.append({"role": "user", "content": tool_results})

                # ── Force synthesis: unrecoverable error → ask user, stop retrying ──
                if _force_synthesis:
                    try:
                        synth_resp = await self._client.messages.create(
                            model=self._model,
                            max_tokens=512,
                            system=system_prompt,
                            tool_choice={"type": "none"},
                            tools=TOOL_SCHEMAS,
                            messages=messages,
                        )
                        final_text = _extract_text(synth_resp.content)
                        yield {"type": "synthesis", "text": final_text}
                        messages.append({"role": "assistant", "content": _content_to_list(synth_resp.content)})
                    except Exception as exc:
                        yield {"type": "synthesis", "text": f"執行失敗，請確認參數後再試一次。（{exc}）"}
                    break

                continue

            # Unexpected stop reason
            yield {"type": "error", "message": f"意外的 stop_reason: {response.stop_reason}"}
            break

        else:
            # MAX_ITERATIONS exceeded
            yield {
                "type": "error",
                "message": f"Agent 已達最大迭代上限 ({MAX_ITERATIONS})，強制中斷。請人工協助或簡化請求。",
                "iteration": iteration,
            }

        # ── Stage 5: Memory Write ───────────────────────────────────────────
        if _new_diagnosis:
            try:
                mem = await self._memory_svc.write_diagnosis(
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
                    }
            except Exception as exc:
                logger.warning("Memory auto-write failed: %s", exc)

        # Save session (trim to last _SESSION_MAX_MESSAGES to bound token growth)
        # Then clean the boundary to prevent orphaned tool_result blocks (→ 400 error)
        trimmed = _clean_history_boundary(messages[-_SESSION_MAX_MESSAGES:])
        await self._save_session(session_id, trimmed)
        yield {"type": "done", "session_id": session_id}

    # ── Session Helpers ───────────────────────────────────────────────────────

    async def _load_session(self, session_id: Optional[str]) -> tuple[str, List[Dict]]:
        """Load or create a session. Returns (session_id, messages_list)."""
        if session_id:
            result = await self._db.execute(
                select(AgentSessionModel).where(
                    AgentSessionModel.session_id == session_id,
                    AgentSessionModel.user_id == self._user_id,
                )
            )
            row = result.scalar_one_or_none()
            if row:
                # Check TTL (normalise naive datetimes from SQLite to UTC-aware)
                expires = row.expires_at
                if expires:
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                    if expires < datetime.now(tz=timezone.utc):
                        await self._db.delete(row)
                        await self._db.commit()
                    else:
                        try:
                            raw_history = json.loads(row.messages)
                            return session_id, _sanitize_history(raw_history)
                        except Exception:
                            pass

        # New session
        new_id = str(uuid.uuid4())
        return new_id, []

    async def _save_session(self, session_id: str, messages: List[Dict]) -> None:
        """Upsert session with 24h TTL."""
        try:
            result = await self._db.execute(
                select(AgentSessionModel).where(AgentSessionModel.session_id == session_id)
            )
            row = result.scalar_one_or_none()
            expires = datetime.now(tz=timezone.utc) + timedelta(hours=_SESSION_TTL_HOURS)
            serialized = json.dumps(messages, ensure_ascii=False)

            if row:
                row.messages = serialized
                row.expires_at = expires
            else:
                row = AgentSessionModel(
                    session_id=session_id,
                    user_id=self._user_id,
                    messages=serialized,
                    created_at=datetime.now(tz=timezone.utc),
                    expires_at=expires,
                )
                self._db.add(row)
            await self._db.commit()
        except Exception as exc:
            logger.warning("Session save failed: %s", exc)
