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

# SPEC_glassbox_continuation — when MAX_TURNS hits, instead of failing, ask
# the user whether to continue. Each "再給 N 步" budgets +N turns up to
# ABSOLUTE_MAX_TURNS, after which we hard-fail (loops shouldn't get unlimited
# extensions).
MAX_TURNS_PER_CONTINUATION = 20
ABSOLUTE_MAX_TURNS = 120


# In-memory paused-session registry. Keyed by session_id. Lives only in the
# sidecar process — if the sidecar restarts, paused sessions are lost (user
# has to start over). This is a deliberate v1 simplification; SPEC §1.1 leaves
# Java-backed persistence for a future iteration.
_PAUSED_SESSIONS: dict[str, AgentBuilderSession] = {}


def park_paused_session(session: AgentBuilderSession) -> None:
    """Register a session in the paused registry."""
    _PAUSED_SESSIONS[session.session_id] = session


def take_paused_session(session_id: str) -> Optional[AgentBuilderSession]:
    """Pop a paused session out of the registry (returns None if not found
    or already taken — keep idempotent semantics for retry-tolerant clients)."""
    return _PAUSED_SESSIONS.pop(session_id, None)


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

    # SPEC_glassbox_continuation: when the run is resumed (continuation_count > 0),
    # restore the previous messages list verbatim instead of re-seeding from
    # user_prompt. Skip the opening chat too — that already fired in turn 1.
    if session.continuation_count > 0 and session.messages_snapshot:
        messages: list[dict[str, Any]] = list(session.messages_snapshot)
        _emit_opening = False
        # Continuation budget = base + N × per-continuation
        turn_budget = MAX_TURNS + session.continuation_count * MAX_TURNS_PER_CONTINUATION
        # Hard cap so a stuck loop can't be extended indefinitely
        turn_budget = min(turn_budget, ABSOLUTE_MAX_TURNS)
        # Continue counting from where the previous run left off (messages
        # already reflects len(operations) turns)
        turn = MAX_TURNS + (session.continuation_count - 1) * MAX_TURNS_PER_CONTINUATION
    else:
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
        _emit_opening = True
        turn_budget = MAX_TURNS
        turn = 0

    last_tool_key: Optional[str] = None
    same_tool_streak = 0

    # Opening chat
    opening = "規劃中…分析需求、挑選適合的 blocks。"
    session.record_chat_msg = lambda msg: None  # noqa: E731 — dummy for type pre-check

    while turn < turn_budget:
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
        # SPEC_glassbox_continuation: hit turn budget. Two cases:
        #   (a) total used == ABSOLUTE_MAX_TURNS → hard-fail, no more chances
        #   (b) total used < ABSOLUTE_MAX_TURNS → pause + ask user to continue
        if turn >= ABSOLUTE_MAX_TURNS:
            session.mark_failed(
                f"Reached ABSOLUTE_MAX_TURNS={ABSOLUTE_MAX_TURNS} after "
                f"{session.continuation_count} continuation(s) without calling finish()"
            )
        else:
            assessment = await _self_assess_progress(client, model, system_blocks, messages)
            session.messages_snapshot = list(messages)
            session.mark_paused(reason=f"Hit turn budget ({turn}/{turn_budget}); asked user")
            park_paused_session(session)
            yield StreamEvent(
                type="continuation_request",
                data={
                    "session_id": session.session_id,
                    "turns_used": turn,
                    "ops_count": len(session.operations),
                    "completed": assessment.get("completed", []),
                    "remaining": assessment.get("remaining", []),
                    "estimate": assessment.get("estimate", 10),
                    "options": [
                        {"id": "continue", "label": f"再給 {assessment.get('estimate', 10)} 步",
                         "additional_turns": min(MAX_TURNS_PER_CONTINUATION, max(5, assessment.get("estimate", 10)))},
                        {"id": "takeover", "label": "我自己接手"},
                        {"id": "stop", "label": "停手用現有結果"},
                    ],
                    "ts": 0.0,
                },
            )

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


async def _self_assess_progress(
    client: "anthropic.AsyncAnthropic",
    model: str,
    system_blocks: list[dict[str, Any]],
    conversation: list[dict[str, Any]],
) -> dict[str, Any]:
    """Ask the LLM to summarize what's done + what's left + how many more
    turns it needs. Result feeds the ContinuationCard.

    Returns {"completed": [...], "remaining": [...], "estimate": int}.
    Failure-tolerant: any error → generic fallback so the user still sees
    something useful instead of an empty card.
    """
    import json as _json

    fallback = {
        "completed": ["建構過程進行中（自評失敗）"],
        "remaining": ["呼叫 finish() 收尾"],
        "estimate": 10,
    }

    # Build a tiny one-shot follow-up: re-use the cached system + tools but
    # append a self-assessment user prompt. Keep messages context so the LLM
    # actually knows where it is.
    probe_messages = list(conversation) + [{
        "role": "user",
        "content": (
            "你已經跑完 turn 預算還沒呼叫 finish。請以**JSON 純文字**回答（不要 markdown / 不要 ```fence```）：\n"
            '{"completed": ["最多 6 個 ≤20 字的已完成項目（例如「加 STEP_001 source」/「設定 xbar chart」）"],\n'
            '"remaining": ["最多 4 個 ≤20 字的剩餘步驟（例如「驗證 pipeline」/「呼 finish」）"],\n'
            '"estimate": 5-20 之間的整數，估還需幾 turn 才能 finish}'
        ),
    }]

    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=300,
            system=system_blocks,
            messages=probe_messages,
        )
        text = ""
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text = block.text
                break
        text = (text or "").strip()
        # Strip code fences if the model ignored "no markdown" hint
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        decision = _json.loads(text)
        # Clamp estimate to [5, MAX_TURNS_PER_CONTINUATION]
        try:
            est = int(decision.get("estimate", 10))
            decision["estimate"] = max(5, min(MAX_TURNS_PER_CONTINUATION, est))
        except (TypeError, ValueError):
            decision["estimate"] = 10
        # Clamp list lengths
        decision["completed"] = (decision.get("completed") or [])[:6]
        decision["remaining"] = (decision.get("remaining") or [])[:4]
        return decision
    except Exception as e:  # noqa: BLE001
        logger.warning("self-assess failed (%s) — using fallback summary", e)
        return fallback
