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
    _current_state = dict(initial_state)
    _analysis_contract = None  # stashed when any tool produces charts for analysis panel
    _all_chart_intents: list = []  # accumulated from ALL tools (skill, analysis, mcp)
    _last_analysis_payload: dict = {}  # steps_mapping etc for promote

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
                # Emit tool_done for each render_card in this node's output.
                # NOTE: on_chain_end output contains only THIS invocation's new cards,
                # not the accumulated state (reducer merge happens at state level).
                new_cards = output.get("render_cards") or []
                for card in new_cards:
                    done_event = {
                        "type": "tool_done",
                        "tool": card.get("mcp_name") or card.get("tool_name") or card.get("skill_name", ""),
                        "result_summary": card.get("summary", ""),
                        "iteration": _current_state.get("current_iteration", 0),
                    }
                    if card:
                        done_event["render_card"] = card

                    # Collect chart_intents from ANY tool (skill, analysis, mcp)
                    # → all charts go to the analysis panel (center), not copilot (right)
                    card_charts = None
                    if card:
                        if card.get("contract"):
                            _analysis_contract = card["contract"]
                        if card.get("chart_intents"):
                            card_charts = card["chart_intents"]
                        elif card.get("type") == "skill":
                            # execute_skill may have charts in mcp_output.ui_render
                            ui = (card.get("mcp_output") or {}).get("ui_render") or {}
                            if ui.get("chart_intents"):
                                card_charts = ui["chart_intents"]

                    if card_charts:
                        _all_chart_intents.extend(card_charts)

                    # Capture analysis payload for promote
                    if card and card.get("type") == "analysis":
                        data = card.get("data") or card.get("result") or {}
                        if isinstance(data, dict) and data.get("steps_mapping"):
                            _last_analysis_payload = {
                                "title": data.get("title", ""),
                                "steps_mapping": data.get("steps_mapping", []),
                                "input_schema": data.get("input_schema", []),
                                "output_schema": data.get("output_schema", []),
                            }

                    yield done_event
                if stage:
                    yield _stage_event(stage, "complete")

            elif ev_name == "synthesis" and not _seen_synthesis:
                _seen_synthesis = True
                output = ev_data.get("output") or {}
                yield _stage_event(4, "running")

                # Build contract for analysis panel:
                # Priority: explicit analysis contract > auto-built from chart_intents > LLM contract
                contract = _analysis_contract
                if not contract and _all_chart_intents:
                    # Auto-build contract from accumulated chart_intents
                    from app.services.agent_orchestrator_v2.nodes.tool_execute import _chart_intent_to_vega_lite
                    visualization = []
                    for i, chart in enumerate(_all_chart_intents):
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
                        contract = {
                            "$schema": "aiops-report/v1",
                            "summary": output.get("final_text", "")[:200],
                            "evidence_chain": [],
                            "visualization": visualization,
                            "suggested_actions": [{
                                "label": "儲存為我的 Skill",
                                "trigger": "promote_analysis",
                            }],
                        }
                if not contract:
                    contract = output.get("contract")

                # Add promote action ONLY for execute_analysis results (has _last_analysis_payload).
                # execute_skill results already ARE a Skill — no need to promote again.
                if contract and isinstance(contract, dict) and contract.get("visualization") and _last_analysis_payload:
                    actions = contract.get("suggested_actions", [])
                    has_promote = any(a.get("trigger") == "promote_analysis" for a in actions if isinstance(a, dict))
                    if not has_promote:
                        promote_action: dict = {"label": "儲存為我的 Skill", "trigger": "promote_analysis"}
                        promote_action["payload"] = _last_analysis_payload
                        actions.append(promote_action)
                        contract["suggested_actions"] = actions

                yield {
                    "type": "synthesis",
                    "text": output.get("final_text", ""),
                    "contract": contract,
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
