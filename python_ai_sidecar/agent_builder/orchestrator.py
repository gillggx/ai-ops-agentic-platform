"""Orchestrator — runs the Claude tool-use loop as an async generator.

Yields StreamEvent objects as the Agent progresses:
  - chat       (Agent calls explain())
  - operation  (any tool call + result)
  - error      (a tool call failed — Agent may retry)
  - done       (finished / failed / cancelled, carries final pipeline_json)

Cancellation:
  Between tool-call batches we check `session.is_cancelled()`. If set, we yield
  a `done` event with status="cancelled" and return.

Turn limits:
  MAX_TURNS caps infinite loops. Same-args-same-tool repeat counter caps agent
  thrashing.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Optional

import anthropic

from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings
from python_ai_sidecar.agent_builder.prompt import build_system_prompt, claude_tool_defs
from python_ai_sidecar.agent_builder.session import (
    AgentBuilderSession,
    StreamEvent,
)
from python_ai_sidecar.agent_builder.tools import BuilderToolset, ToolError
from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry


logger = logging.getLogger(__name__)

MAX_TURNS = 50  # bumped 2026-04-26: complex builds (multi-tool overlay,
                # facet patterns) hit the old 30 cap before calling finish()
MAX_SAME_TOOL_RETRY = 3  # if Agent calls the same (tool, args) 3x in a row → refuse + hint
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 4096


async def stream_agent_build(
    session: AgentBuilderSession,
    registry: BlockRegistry,
    *,
    model: str = DEFAULT_MODEL,
) -> AsyncGenerator[StreamEvent, None]:
    """Drive one Agent run. Yields StreamEvent as the run progresses.

    This is the single source of truth. The SSE endpoint forwards these events
    to the wire. A batch endpoint (fallback) consumes them with async for and
    returns the final accumulation.
    """
    settings = get_settings()
    api_key = settings.ANTHROPIC_API_KEY or ""
    if not api_key:
        session.mark_failed("ANTHROPIC_API_KEY not configured")
        yield StreamEvent(
            type="error",
            data={"op": "orchestrator", "message": "ANTHROPIC_API_KEY not configured", "ts": 0.0},
        )
        yield StreamEvent(
            type="done",
            data={"status": "failed", "pipeline_json": session.pipeline_json.model_dump(by_alias=True),
                  "summary": session.summary},
        )
        return

    client = anthropic.AsyncAnthropic(api_key=api_key)
    toolset = BuilderToolset(session, registry)

    # Build cacheable system + tools
    system_text = build_system_prompt(registry)
    system_blocks = [
        {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
    ]
    tools = claude_tool_defs()
    if tools:
        # Mark last tool with cache_control so all tools get cached together
        tools[-1]["cache_control"] = {"type": "ephemeral"}

    # Build initial messages: user prompt + current state summary if base_pipeline was provided
    user_opening = session.user_prompt
    if session.pipeline_json.nodes:
        state_summary = await toolset.get_state()
        user_opening = (
            f"{session.user_prompt}\n\n"
            f"(Note: the pipeline is not empty — current state = {state_summary})"
        )
        # Phase 5-UX-6 fix: only pop if dispatch actually recorded something.
        # Direct get_state() calls bypass dispatch so ops stays empty → pop()
        # would raise IndexError.
        if session.operations:
            session.operations.pop()

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_opening}]

    last_tool_key: Optional[str] = None
    same_tool_streak = 0

    # Opening chat
    opening = "規劃中…分析需求、挑選適合的 blocks。"
    session.record_chat_msg = lambda msg: None  # noqa: E731 — dummy for type pre-check
    _emit_opening = True

    turn = 0
    while turn < MAX_TURNS:
        turn += 1

        # Cancel check
        if session.is_cancelled():
            session.mark_cancelled()
            yield StreamEvent(
                type="done",
                data={
                    "status": "cancelled",
                    "pipeline_json": session.pipeline_json.model_dump(by_alias=True),
                    "summary": "Cancelled by user",
                },
            )
            return

        # Call Claude
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=DEFAULT_MAX_TOKENS,
                system=system_blocks,
                tools=tools,
                messages=messages,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Claude call failed at turn %s", turn)
            session.mark_failed(f"LLM call failed: {type(e).__name__}: {e}")
            yield StreamEvent(
                type="error",
                data={"op": "claude", "message": f"{type(e).__name__}: {e}", "ts": 0.0},
            )
            break

        if _emit_opening:
            # After the first Claude response we can mark thinking as started for UI
            yield StreamEvent(type="chat", data={"content": opening, "highlight_nodes": [], "ts": 0.0})
            _emit_opening = False

        # Collect content blocks from response
        tool_use_blocks = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]

        # If Claude didn't call any tool, check whether the pipeline is actually
        # done — if validates cleanly and has ≥1 output node, auto-finish instead
        # of marking failed. This keeps the UX from calling a pipeline "failed"
        # just because Claude ended with a text acknowledgment.
        if not tool_use_blocks:
            text_content = "\n".join(
                getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text"
            ).strip()
            if text_content:
                yield StreamEvent(type="chat", data={"content": text_content, "highlight_nodes": [], "ts": 0.0})
            try:
                auto_finish_result = await toolset.finish(
                    summary=text_content or "Pipeline built."
                )
                yield StreamEvent(
                    type="operation",
                    data={
                        "op": "finish",
                        "args": {"summary": text_content or "Pipeline built."},
                        "result": auto_finish_result,
                        "elapsed_ms": 0.0,
                        "ts": 0.0,
                        "auto": True,
                    },
                )
            except Exception as e:  # noqa: BLE001
                logger.info("Auto-finish rejected: %s — marking failed.", e)
                session.mark_failed(
                    "Agent stopped without calling finish() and pipeline is not ready to finish."
                )
            break

        # Dispatch tool calls (sequentially, in order)
        assistant_response_blocks: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        finished = False

        # Re-add any text blocks to the assistant response (preserve thinking text)
        for b in resp.content:
            if getattr(b, "type", None) == "text":
                assistant_response_blocks.append({"type": "text", "text": b.text})
            elif getattr(b, "type", None) == "tool_use":
                assistant_response_blocks.append({
                    "type": "tool_use",
                    "id": b.id,
                    "name": b.name,
                    "input": b.input,
                })

        for tu in tool_use_blocks:
            # Repetition guard
            import json as _json
            tool_key = f"{tu.name}:{_json.dumps(tu.input, sort_keys=True, default=str)}"
            if tool_key == last_tool_key:
                same_tool_streak += 1
            else:
                same_tool_streak = 0
                last_tool_key = tool_key

            if same_tool_streak >= MAX_SAME_TOOL_RETRY:
                err_msg = (
                    f"Agent called {tu.name} with identical args {same_tool_streak + 1} times in a row — "
                    "abandoning to avoid infinite loop. Try a different approach."
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "is_error": True,
                    "content": err_msg,
                })
                yield StreamEvent(
                    type="error",
                    data={"op": tu.name, "message": err_msg, "ts": 0.0},
                )
                session.mark_failed(err_msg)
                finished = True  # break out
                break

            # Execute tool
            try:
                result = await toolset.dispatch(tu.name, dict(tu.input))
            except ToolError as e:
                # Emit structured error to stream + feed back to Claude as tool_result error
                yield StreamEvent(
                    type="error",
                    data={"op": tu.name, "message": e.message, "hint": e.hint, "ts": 0.0},
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "is_error": True,
                    "content": _format_tool_error(e),
                })
                continue
            except Exception as e:  # noqa: BLE001
                logger.exception("Unexpected tool error: %s", tu.name)
                yield StreamEvent(
                    type="error",
                    data={"op": tu.name, "message": f"{type(e).__name__}: {e}", "ts": 0.0},
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "is_error": True,
                    "content": f"Internal error: {type(e).__name__}: {e}",
                })
                continue

            # Success — emit appropriate event per tool semantics
            if tu.name == "explain":
                yield StreamEvent(
                    type="chat",
                    data={
                        "content": (tu.input or {}).get("message", ""),
                        "highlight_nodes": (tu.input or {}).get("highlight_nodes") or [],
                        "ts": 0.0,
                    },
                )
            elif tu.name == "suggest_action":
                # PR-E3b: emit as suggestion_card (frontend renders Apply/Dismiss UI)
                yield StreamEvent(
                    type="suggestion_card",
                    data={
                        "summary": (tu.input or {}).get("summary", ""),
                        "rationale": (tu.input or {}).get("rationale"),
                        "actions": (tu.input or {}).get("actions") or [],
                        "ts": 0.0,
                    },
                )
            elif tu.name == "update_plan" and isinstance(result, dict):
                # v1.4 Plan Panel — convert to plan / plan_update stream events
                # so AgentBuilderPanel can render the live checklist.
                if result.get("_plan_action") == "create":
                    yield StreamEvent(
                        type="plan",
                        data={"items": result.get("items") or [], "ts": 0.0},
                    )
                elif result.get("_plan_action") == "update":
                    yield StreamEvent(
                        type="plan_update",
                        data={
                            "id": result.get("id"),
                            "status": result.get("status_value"),
                            "note": result.get("note"),
                            "ts": 0.0,
                        },
                    )
            else:
                yield StreamEvent(
                    type="operation",
                    data={
                        "op": tu.name,
                        "args": dict(tu.input),
                        "result": result,
                        "elapsed_ms": session.operations[-1].elapsed_ms if session.operations else 0.0,
                        "ts": 0.0,
                    },
                )

            # finish tool → mark done
            if tu.name == "finish" and session.status == "finished":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": _json.dumps(result),
                })
                finished = True
                break

            # Pack result as tool_result
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": _json.dumps(result, ensure_ascii=False, default=str),
            })

        # Append assistant turn + our tool results to conversation
        messages.append({"role": "assistant", "content": assistant_response_blocks})
        messages.append({"role": "user", "content": tool_results})

        if finished:
            break

    # --- loop exit ---
    if session.status == "running":
        # Hit max turns
        session.mark_failed(f"Reached MAX_TURNS={MAX_TURNS} without calling finish()")

    # Emit final "done" event
    yield StreamEvent(
        type="done",
        data={
            "status": session.status,
            "pipeline_json": session.pipeline_json.model_dump(by_alias=True),
            "summary": session.summary,
        },
    )


def _format_tool_error(e: ToolError) -> str:
    payload = {"error": True, "code": e.code, "message": e.message}
    if e.hint:
        payload["hint"] = e.hint
    import json as _json
    return _json.dumps(payload, ensure_ascii=False)
