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
from app.services.agent_memory_service import AgentMemoryService
from app.services.context_loader import ContextLoader
from app.services.tool_dispatcher import TOOL_SCHEMAS, ToolDispatcher

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
_SESSION_TTL_HOURS = 24


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
        status = lrd.get("status", "?")
        msg = lrd.get("diagnosis_message", "")[:80]
        return f"status={status} | {msg}"
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
        return {
            "type": "mcp",
            "mcp_name": f"MCP #{mcp_id}",
            "mcp_output": {
                "ui_render": od.get("ui_render") or {},
                "dataset": od.get("dataset"),
                "_raw_dataset": od.get("dataset"),
                "_call_params": tool_input.get("params", {}),
                "_is_processed": True,
            },
        }

    if tool_name in ("draft_skill", "draft_mcp") and isinstance(result, dict) and "draft_id" in result:
        draft_type = "skill" if tool_name == "draft_skill" else "mcp"
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
        yield {"type": "context_load", **context_meta}

        # Load session history
        session_id, history = await self._load_session(session_id)
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

                    result = await dispatcher.execute(tool_name, tool_input)

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
                        "content": json.dumps(result, ensure_ascii=False),
                    })

                messages.append({"role": "user", "content": tool_results})
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

        # Save session
        await self._save_session(session_id, messages)
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
                            return session_id, json.loads(row.messages)
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
