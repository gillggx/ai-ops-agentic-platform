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


# 9-Stage Pipeline mapping
# Stage 1: Context Load
# Stage 2: LLM Planning
# Stage 3~6: Data Pipeline (emitted as pipeline_stage events from tool_execute)
# Stage 7: Synthesis
# Stage 8: Self-Critique
# Stage 9: Memory
_STAGE_MAP = {
    "load_context": 1,
    "llm_call": 2,
    "tool_execute": 2,     # pipeline stages 3-6 are emitted separately
    "synthesis": 7,
    "self_critique": 8,
    "memory_lifecycle": 9,
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
                            # Phase 2-A: cache visibility
                            "cache_creation_input_tokens": resp_meta.get("cache_creation_input_tokens", 0),
                            "cache_read_input_tokens": resp_meta.get("cache_read_input_tokens", 0),
                            "iteration": output.get("current_iteration", 0),
                            "source": "v2_chat",
                        }
                    # Emit <plan> if present in LLM text — shows agent's reasoning in console
                    _text = last.content if hasattr(last, "content") and isinstance(last.content, str) else ""
                    import re as _re
                    _plan_match = _re.search(r"<plan>(.*?)</plan>", _text, _re.DOTALL)
                    if _plan_match:
                        yield {
                            "type": "plan",
                            "text": _plan_match.group(1).strip(),
                            "iteration": output.get("current_iteration", 0),
                        }
                    # Emit tool_start for each tool_call — with human-readable params_summary
                    if hasattr(last, "tool_calls") and last.tool_calls:
                        for tc in last.tool_calls:
                            _tool_start_count += 1
                            args = tc.get("args", {})
                            tool_name = tc.get("name", "")
                            # Build params_summary: "get_process_info(step=STEP_001, since=7d)"
                            if tool_name in ("execute_mcp", "query_data"):
                                mcp = args.get("mcp_name") or args.get("data_source", "")
                                params = args.get("params") or {}
                                if isinstance(params, dict):
                                    parts = [f"{k}={v}" for k, v in params.items() if v and k != "_flat_data"]
                                else:
                                    parts = [str(params)[:40]]
                                ps = f"{mcp}({', '.join(parts)})" if parts else mcp
                            elif tool_name == "execute_skill":
                                ps = f"skill_id={args.get('skill_id', '?')}"
                            elif tool_name == "execute_analysis":
                                ps = f"mode={args.get('mode','auto')}, title={str(args.get('title',''))[:40]}"
                            else:
                                safe_args = {k: v for k, v in args.items() if k != "_flat_data" and not isinstance(v, (dict, list))}
                                parts = [f"{k}={str(v)[:20]}" for k, v in list(safe_args.items())[:4]]
                                ps = ", ".join(parts) if parts else ""
                            # Strip _flat_data from SSE (too large for frontend)
                            safe_input = {k: v for k, v in args.items() if k != "_flat_data"} if isinstance(args, dict) else args
                            yield {
                                "type": "tool_start",
                                "tool": tool_name,
                                "input": safe_input,
                                "params_summary": ps,
                                "iteration": output.get("current_iteration", 0),
                            }

            elif ev_name == "tool_execute":
                output = ev_data.get("output") or {}
                # Emit tool_done for each render_card in this node's output.
                # NOTE: on_chain_end output contains only THIS invocation's new cards,
                # not the accumulated state (reducer merge happens at state level).
                new_cards = output.get("render_cards") or []
                for card in new_cards:
                    tool_label = card.get("mcp_name") or card.get("tool_name") or card.get("skill_name", "")
                    summary = card.get("summary", "")

                    # Build data_shape for console visibility
                    data_shape = {}
                    if card and card.get("type") == "mcp":
                        mcp_out = card.get("mcp_output") or {}
                        ds = mcp_out.get("_raw_dataset") or mcp_out.get("dataset") or []
                        # Unwrap [{total, events:[...]}] envelope
                        if isinstance(ds, list) and len(ds) == 1 and isinstance(ds[0], dict):
                            inner = ds[0]
                            if isinstance(inner.get("events"), list):
                                evts = inner["events"]
                                ooc_n = sum(1 for e in evts if isinstance(e, dict) and e.get("spc_status") == "OOC")
                                data_shape = {"total": inner.get("total", len(evts)), "ooc_count": ooc_n}
                                summary = f"{data_shape['total']} events ({ooc_n} OOC)"
                            elif isinstance(inner.get("data"), list):
                                data_shape = {"total_points": inner.get("total_points", len(inner["data"]))}
                                summary = f"{data_shape['total_points']} data points"
                            elif inner.get("total_events") is not None:
                                data_shape = {k: v for k, v in inner.items() if isinstance(v, (int, float, str, bool))}
                                summary = f"status snapshot"
                            else:
                                data_shape = {"row_count": 1}
                        elif isinstance(ds, list):
                            data_shape = {"row_count": len(ds)}
                            summary = f"{len(ds)} rows"
                    elif card and card.get("type") == "analysis":
                        contract = card.get("contract") or {}
                        charts = contract.get("charts") or []
                        data_shape = {"charts": len(charts), "steps": len(contract.get("evidence_chain") or [])}
                        if charts:
                            summary = f"{len(charts)} chart(s)"

                    # Build render_decision summary for console
                    rd = (card.get("contract") or {}).get("render_decision") or {}
                    rd_kind = rd.get("kind")
                    rd_charts = len((rd.get("primary") or {}).get("charts") or [])
                    rd_alts = len(rd.get("alternatives") or rd.get("options") or [])
                    if rd_kind:
                        data_shape["render"] = f"{rd_kind}({rd_charts} charts, {rd_alts} alts)"

                    done_event = {
                        "type": "tool_done",
                        "tool": tool_label,
                        "result_summary": summary,
                        "data_shape": data_shape,
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

                    # Emit pipeline stage events (Generative UI)
                    if card and card.get("type") == "pipeline":
                        # Emit each pipeline stage as its own event
                        for pc in card.get("pipeline_cards", []):
                            yield {
                                "type": "pipeline_stage",
                                "stage": pc.get("stage"),
                                "name": pc.get("name"),
                                "icon": pc.get("icon"),
                                "status": pc.get("status"),
                                "elapsed": pc.get("elapsed"),
                                "summary": pc.get("summary"),
                                "detail": pc.get("detail"),
                            }
                        # Emit flat_data + ui_config
                        flat_data = card.get("flat_data")
                        flat_meta = card.get("flat_metadata")
                        ui_config = card.get("ui_config")
                        if flat_data and flat_meta:
                            yield {
                                "type": "flat_data",
                                "flat_data": flat_data,
                                "metadata": flat_meta,
                            }
                        if ui_config:
                            yield {
                                "type": "ui_config",
                                "config": ui_config,
                            }

                    elif card and card.get("type") == "query_data":
                        # Legacy query_data path
                        flat_data = card.get("flat_data")
                        flat_meta = card.get("flat_metadata")
                        ui_config = card.get("ui_config")
                        if flat_data and flat_meta:
                            yield {
                                "type": "flat_data",
                                "flat_data": flat_data,
                                "metadata": flat_meta,
                                "query_info": card.get("query_info"),
                            }
                        if ui_config:
                            yield {
                                "type": "ui_config",
                                "config": ui_config,
                            }

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
                    from python_ai_sidecar.agent_orchestrator_v2.nodes.tool_execute import _chart_intent_to_vega_lite
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
