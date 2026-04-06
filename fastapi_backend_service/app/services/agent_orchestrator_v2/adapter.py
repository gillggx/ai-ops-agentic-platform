"""Event Adapter — translates LangGraph astream_events into v1 SSE format.

The frontend (AICopilot.tsx) expects specific event types:
  context_load, stage_update, llm_usage, tool_start, tool_done,
  synthesis, reflection_pass, reflection_amendment, memory_write, done

LangGraph's astream_events(version="v2") emits generic events like:
  on_chain_start, on_chain_end, on_chat_model_stream, etc.

This adapter maps between the two, so the frontend doesn't need any changes.

Strategy:
  - Node name-based mapping (load_context → stage 1, llm_call → stage 3, etc.)
  - Tool call events mapped 1:1
  - State snapshots used for render_cards and final text
  - Anything unmapped is silently dropped (logged at DEBUG)
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)


# v1 stage numbers
_STAGE_MAP = {
    "load_context": 1,
    "llm_call": 3,
    "tool_execute": 3,
    "synthesis": 4,
    "self_critique": 5,
    "memory_lifecycle": 6,
}


def _stage_event(stage: int, status: str, **extra) -> Dict[str, Any]:
    """Build a v1 stage_update SSE event."""
    return {"type": "stage_update", "stage": stage, "status": status, **extra}


async def adapt_events(
    event_stream: AsyncIterator[Dict[str, Any]],
    initial_state: Dict[str, Any],
) -> AsyncIterator[Dict[str, Any]]:
    """Transform LangGraph astream_events into v1 SSE events.

    Yields v1-format dicts that can be directly serialised as SSE data lines.
    """
    _seen_context_load = False
    _seen_synthesis = False
    _seen_self_critique = False
    _seen_memory = False
    _tool_start_count = 0
    _render_card_index = 0
    _current_state = dict(initial_state)

    # Opening stage events
    yield _stage_event(1, "running")

    async for event in event_stream:
        ev_type = event.get("event", "")
        ev_name = event.get("name", "")
        ev_data = event.get("data", {})

        # ── Node lifecycle events ──────────────────────────────────
        if ev_type == "on_chain_start":
            stage = _STAGE_MAP.get(ev_name)
            if stage:
                yield _stage_event(stage, "running")

        elif ev_type == "on_chain_end":
            stage = _STAGE_MAP.get(ev_name)

            if ev_name == "load_context" and not _seen_context_load:
                _seen_context_load = True
                # Extract context_meta from the node output
                output = ev_data.get("output") or {}
                meta = output.get("context_meta") or {}
                yield _stage_event(1, "complete")
                yield {
                    "type": "context_load",
                    **meta,
                    "history_turns": output.get("history_turns", 0),
                    "session_id": output.get("session_id"),
                }

            elif ev_name == "llm_call":
                output = ev_data.get("output") or {}
                # Emit llm_usage
                messages = output.get("messages", [])
                if messages:
                    last = messages[-1] if isinstance(messages, list) else messages
                    resp_meta = getattr(last, "response_metadata", {}) if hasattr(last, "response_metadata") else {}
                    if resp_meta:
                        yield {
                            "type": "llm_usage",
                            "input_tokens": resp_meta.get("input_tokens", 0),
                            "output_tokens": resp_meta.get("output_tokens", 0),
                            "iteration": output.get("current_iteration", 0),
                        }
                    # Emit tool_start for each tool_call
                    if hasattr(last, "tool_calls") and last.tool_calls:
                        for tc in last.tool_calls:
                            _tool_start_count += 1
                            yield {
                                "type": "tool_start",
                                "tool": tc.get("name", ""),
                                "input": tc.get("args", {}),
                                "iteration": output.get("current_iteration", 0),
                            }

            elif ev_name == "tool_execute":
                output = ev_data.get("output") or {}
                # Emit tool_done for each new render_card
                new_cards = output.get("render_cards") or []
                while _render_card_index < len(new_cards):
                    card = new_cards[_render_card_index]
                    _render_card_index += 1
                    done_event = {
                        "type": "tool_done",
                        "tool": card.get("mcp_name") or card.get("tool_name") or card.get("skill_name", ""),
                        "result_summary": "",
                        "iteration": _current_state.get("current_iteration", 0),
                    }
                    if card:
                        done_event["render_card"] = card
                    yield done_event
                if stage:
                    yield _stage_event(stage, "complete")

            elif ev_name == "synthesis" and not _seen_synthesis:
                _seen_synthesis = True
                output = ev_data.get("output") or {}
                yield _stage_event(4, "running")
                yield {
                    "type": "synthesis",
                    "text": output.get("final_text", ""),
                    "contract": output.get("contract"),
                }
                yield _stage_event(4, "complete")

            elif ev_name == "self_critique":
                output = ev_data.get("output") or {}
                reflection = output.get("reflection_result") or {}
                yield _stage_event(5, "running")
                if reflection.get("pass", True):
                    yield {"type": "reflection_pass"}
                else:
                    yield {
                        "type": "reflection_amendment",
                        "issues": reflection.get("issues", []),
                        "amended_text": reflection.get("amended_text", ""),
                        "issue_count": len(reflection.get("issues", [])),
                    }
                yield _stage_event(5, "complete")
                _seen_self_critique = True

            elif ev_name == "memory_lifecycle":
                output = ev_data.get("output") or {}
                yield _stage_event(6, "running")
                yield {
                    "type": "memory_write",
                    "source": "experience_lifecycle_scheduled",
                    "cited_memory_ids": output.get("cited_memory_ids", []),
                    "memory_write_scheduled": output.get("memory_write_scheduled", False),
                    "tool_count": len(_current_state.get("tools_used", [])),
                }
                yield _stage_event(6, "complete")
                _seen_memory = True

            elif stage:
                yield _stage_event(stage, "complete")

        # ── Update current state from any output ───────────────────
        if ev_type == "on_chain_end":
            output = ev_data.get("output")
            if isinstance(output, dict):
                _current_state.update(output)

    # ── Final fallback events (in case nodes didn't fire) ──────────
    if not _seen_self_critique:
        yield _stage_event(5, "running")
        yield {"type": "reflection_pass"}
        yield _stage_event(5, "complete")

    if not _seen_memory:
        yield _stage_event(6, "running")
        yield {
            "type": "memory_write",
            "source": "skipped",
            "tool_count": len(_current_state.get("tools_used", [])),
        }
        yield _stage_event(6, "complete")

    yield {
        "type": "done",
        "session_id": _current_state.get("session_id"),
    }
