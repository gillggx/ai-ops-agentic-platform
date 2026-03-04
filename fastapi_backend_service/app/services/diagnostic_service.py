"""Diagnostic Agent Service — MCP tool-calling loop with SSE streaming.

Two public interfaces
---------------------
``run(issue_description)``
    Classic async method → returns a ``DiagnoseResponse`` object.
    Used by unit tests that patch the Anthropic client directly.

``stream(issue_description)``
    Async generator → yields SSE-formatted strings in real time.
    Used by ``POST /api/v1/diagnose/`` (StreamingResponse).

SSE event schema
----------------
Every yielded string follows RFC 8895 SSE format::

    event: <event_type>\\n
    data: <json>\\n
    \\n

Event types (in order):

``session_start``
    Emitted once at the start.  Payload: ``{"issue": str}``.

``tool_call``
    Emitted before each skill execution.
    Payload: ``{"tool_name": str, "tool_input": dict}``.

``tool_result``
    Emitted after each skill execution.
    Payload: ``{"tool_name": str, "tool_result": dict, "is_error": bool}``.

``report``
    Emitted once when the agent produces its final Markdown report.
    Payload: ``{"content": str, "total_turns": int, "tools_invoked": list}``.

``error``
    Emitted if an unhandled exception escapes the loop.
    Payload: ``{"message": str}``.

``done``
    Always emitted last (via ``finally``).  Payload: ``{"status": "complete"}``.

Constraints (PRD)
-----------------
- No write-back / auto-remediation: strictly read-only.
- No domain hardcoding: routing decisions delegated to the LLM.
- ``mcp_event_triage`` MUST be the first tool called (enforced by System Prompt).
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import anthropic

from app.config import get_settings
from app.schemas.diagnostic import DiagnoseResponse, ToolCallRecord
from app.skills import SKILL_REGISTRY

logger = logging.getLogger(__name__)
_MODEL = get_settings().LLM_MODEL

# ---------------------------------------------------------------------------
# System Prompt — triage-first constraint is explicit and non-negotiable
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """你是一位台積電資深蝕刻製程工程師（Process Engineer, PE），\
擁有豐富的 SPC OOC 排障經驗。

**執行鐵律（必須嚴格遵守，違者視為錯誤）：**
1. 收到製程工程師描述的症狀後，**第一步且唯一的第一步**必須呼叫 `mcp_event_triage`，
   並以使用者的完整原始症狀作為 `user_symptom` 參數。
2. 取得 Event Object 後，依照其中 `recommended_skills` 清單，**依序**呼叫後續診斷工具。
3. **在取得 mcp_event_triage 的回傳結果之前，絕對禁止呼叫任何其他工具。**

**半導體蝕刻製程排障推理規則：**
- 若 `mcp_check_recipe_offset` 顯示 `has_human_modification: true`，
  根因歸咎**配方人為失誤**，立即通報配方管理員恢復 golden 版本。
- 若 `mcp_check_equipment_constants` 顯示 `hardware_aging_risk: HIGH` 或
  `out_of_spec_count > 0`，根因歸咎**機台硬體老化**，必須通報設備工程師（EE）
  安排 PM / 感測器校準 / 消耗品更換。
- 若前兩者均正常，但 `mcp_check_apc_params` 顯示 `saturation_flag: true`，
  根因歸咎 **APC 補償飽和**（蝕刻速率基準線漂移），建議安排 **Chamber Wet Clean**，
  完成後重新執行 Recipe 標定使 APC 模型恢復正常補償範圍。

蒐集完所有工具資料後，輸出 Markdown 格式的診斷報告，包含：
- ## 問題摘要
- ## 事件分類 (Event Object)
- ## 觸發的工具與資料
- ## 根因分析
- ## 建議處置

約束：
- 絕對不能對任何系統執行寫入操作或重啟服務。
- 所有結論僅供製程工程師參考，不能自動修復。
"""


# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------


def _sse(event_type: str, data: dict) -> str:
    """Format a single Server-Sent Event string."""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _serialize_content(blocks: list) -> list[dict]:
    """Convert Anthropic SDK content blocks to plain API-compatible dicts.

    ``anthropic >= 0.40`` returns typed Pydantic v2 objects (TextBlock,
    ToolUseBlock, …) that carry extra fields (``citations``, ``caller``, …).
    Passing those objects directly back to ``messages.create()`` causes a
    ``model_dump(by_alias=None)`` crash in pydantic-core.  Serialising only
    the fields the API actually expects avoids the issue.
    """
    result = []
    for block in blocks:
        t = getattr(block, "type", None)
        if t == "text":
            result.append({"type": "text", "text": block.text})
        elif t == "tool_use":
            result.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": dict(block.input),
            })
        # skip thinking / other block types silently
    return result


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class DiagnosticService:
    """Orchestrates the MCP agentic loop; exposes both batch and streaming APIs."""

    def __init__(self, max_turns: int = 10) -> None:
        settings = get_settings()
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._max_turns = max_turns
        self._tools = [skill.to_anthropic_tool() for skill in SKILL_REGISTRY.values()]

    # ------------------------------------------------------------------
    # Internal: execute one tool_use block, return (record, result_dict)
    # ------------------------------------------------------------------

    async def _execute_skill(
        self, block: Any
    ) -> tuple[ToolCallRecord | None, dict, bool]:
        """Dispatch one tool_use block to the matching skill.

        Returns:
            (record, result_dict, is_error)
            ``record`` is ``None`` for unknown tools.
        """
        skill = SKILL_REGISTRY.get(block.name)
        if skill is None:
            error_result = {"error": f"Unknown tool: {block.name}"}
            logger.warning("Unknown tool requested: %s", block.name)
            return None, error_result, True

        try:
            result = await skill.execute(**block.input)
            is_error = False
        except Exception as exc:  # noqa: BLE001
            result = {"error": str(exc)}
            is_error = True
            logger.exception("Skill %s raised an exception", block.name)

        record = ToolCallRecord(
            tool_name=block.name,
            tool_input=dict(block.input),
            tool_result=result,
        )
        return record, result, is_error

    # ------------------------------------------------------------------
    # Batch interface (used by unit tests)
    # ------------------------------------------------------------------

    async def run(self, issue_description: str) -> DiagnoseResponse:
        """Execute the full agent loop and return a structured response.

        Args:
            issue_description: Free-text problem description from the user.

        Returns:
            A ``DiagnoseResponse`` with the report, tool records, and turn count.
        """
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": issue_description},
        ]
        tool_calls_log: list[ToolCallRecord] = []
        turns = 0
        diagnosis_report = ""
        max_turns_reached = True

        for _ in range(self._max_turns):
            turns += 1
            response = await self._client.messages.create(
                model=_MODEL,
                max_tokens=get_settings().LLM_MAX_TOKENS_DIAGNOSTIC,
                system=_SYSTEM_PROMPT,
                tools=self._tools,
                messages=messages,
            )

            logger.debug(
                "Agent turn %d — stop_reason=%s blocks=%d",
                turns, response.stop_reason, len(response.content),
            )

            messages.append({"role": "assistant", "content": _serialize_content(response.content)})

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if block.type == "text":
                        diagnosis_report = block.text
                        break
                max_turns_reached = False
                break

            if response.stop_reason != "tool_use":
                for block in response.content:
                    if block.type == "text":
                        diagnosis_report = block.text
                        break
                logger.warning("Unexpected stop_reason=%s", response.stop_reason)
                max_turns_reached = False
                break

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                record, result, is_error = await self._execute_skill(block)
                if record:
                    tool_calls_log.append(record)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                    **({"is_error": True} if is_error else {}),
                })

            messages.append({"role": "user", "content": tool_results})

        if max_turns_reached:
            logger.warning("Reached max_turns=%d — requesting final summary", self._max_turns)
            messages.append({
                "role": "user",
                "content": (
                    "已達最大診斷迴圈次數。請根據目前蒐集到的所有資料，"
                    "立即輸出 Markdown 格式的診斷報告。"
                ),
            })
            final_resp = await self._client.messages.create(
                model=_MODEL,
                max_tokens=get_settings().LLM_MAX_TOKENS_DIAGNOSTIC,
                system=_SYSTEM_PROMPT,
                messages=messages,
            )
            for block in final_resp.content:
                if block.type == "text":
                    diagnosis_report = block.text
                    break
            turns += 1

        return DiagnoseResponse(
            issue_description=issue_description,
            tools_invoked=tool_calls_log,
            diagnosis_report=diagnosis_report or "（診斷引擎未產生報告）",
            total_turns=turns,
        )

    # ------------------------------------------------------------------
    # Streaming interface (used by the SSE router endpoint)
    # ------------------------------------------------------------------

    async def stream(self, issue_description: str) -> AsyncGenerator[str, None]:
        """Async generator that yields SSE-formatted events for the agent loop.

        Yields one SSE string per event.  Each string ends with ``\\n\\n``
        as required by the SSE specification.

        Args:
            issue_description: Free-text problem description from the user.
        """
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": issue_description},
        ]
        tool_calls_log: list[ToolCallRecord] = []
        turns = 0
        max_turns_reached = True

        yield _sse("session_start", {"issue": issue_description})

        try:
            for _ in range(self._max_turns):
                turns += 1
                response = await self._client.messages.create(
                    model=_MODEL,
                    max_tokens=get_settings().LLM_MAX_TOKENS_DIAGNOSTIC,
                    system=_SYSTEM_PROMPT,
                    tools=self._tools,
                    messages=messages,
                )

                logger.debug(
                    "Stream turn %d — stop_reason=%s blocks=%d",
                    turns, response.stop_reason, len(response.content),
                )

                messages.append({"role": "assistant", "content": _serialize_content(response.content)})

                if response.stop_reason == "end_turn":
                    for block in response.content:
                        if block.type == "text":
                            yield _sse("report", {
                                "content": block.text,
                                "total_turns": turns,
                                "tools_invoked": [r.model_dump() for r in tool_calls_log],
                            })
                            break
                    max_turns_reached = False
                    break

                if response.stop_reason != "tool_use":
                    for block in response.content:
                        if block.type == "text":
                            yield _sse("report", {
                                "content": block.text,
                                "total_turns": turns,
                                "tools_invoked": [r.model_dump() for r in tool_calls_log],
                            })
                            break
                    logger.warning("Unexpected stop_reason=%s", response.stop_reason)
                    max_turns_reached = False
                    break

                # --- Handle tool_use blocks ---
                tool_results: list[dict[str, Any]] = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    yield _sse("tool_call", {
                        "tool_name": block.name,
                        "tool_input": dict(block.input),
                    })

                    record, result, is_error = await self._execute_skill(block)
                    if record:
                        tool_calls_log.append(record)

                    yield _sse("tool_result", {
                        "tool_name": block.name,
                        "tool_result": result,
                        "is_error": is_error,
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False),
                        **({"is_error": True} if is_error else {}),
                    })

                messages.append({"role": "user", "content": tool_results})

            if max_turns_reached:
                logger.warning("Stream: max_turns=%d reached", self._max_turns)
                messages.append({
                    "role": "user",
                    "content": (
                        "已達最大診斷迴圈次數。請根據目前蒐集到的所有資料，"
                        "立即輸出 Markdown 格式的診斷報告。"
                    ),
                })
                final_resp = await self._client.messages.create(
                    model=_MODEL,
                    max_tokens=get_settings().LLM_MAX_TOKENS_DIAGNOSTIC,
                    system=_SYSTEM_PROMPT,
                    messages=messages,
                )
                for block in final_resp.content:
                    if block.type == "text":
                        yield _sse("report", {
                            "content": block.text,
                            "total_turns": turns + 1,
                            "tools_invoked": [r.model_dump() for r in tool_calls_log],
                        })
                        break

        except Exception as exc:  # noqa: BLE001
            logger.exception("Stream error: %s", exc)
            yield _sse("error", {"message": str(exc)})

        finally:
            yield _sse("done", {"status": "complete"})
