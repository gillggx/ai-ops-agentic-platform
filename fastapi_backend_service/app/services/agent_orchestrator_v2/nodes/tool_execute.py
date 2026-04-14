"""tool_execute node — runs tools via the existing ToolDispatcher.

Handles:
  - Preflight validation (MISSING_MCP_NAME, MISSING_PARAMS, etc.)
  - Tool execution via dispatcher.execute()
  - Programmatic data distillation
  - Render card building (for SSE tool_done events)
  - Chart rendered notification (sets chart_already_rendered flag)
  - Result trimming for LLM context (large results truncated)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from langchain_core.runnables import RunnableConfig

from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)


async def tool_execute_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Execute all tool_calls from the last AIMessage.

    Returns tool result messages + updated state (tools_used, render_cards, flags).
    """
    db = config["configurable"]["db"]
    base_url = config["configurable"]["base_url"]
    auth_token = config["configurable"]["auth_token"]
    user_id = config["configurable"]["user_id"]

    # Import here to avoid circular imports at module level
    from app.services.agent_orchestrator_v2.helpers import (
        _preflight_validate,
        _is_spc_result,
        _result_summary,
    )
    from app.services.agent_orchestrator_v2.render_card import _build_render_card
    from app.services.data_distillation_service import DataDistillationService
    from app.services.tool_dispatcher import ToolDispatcher

    # Get the last AI message's tool_calls
    messages = state["messages"]
    last_msg = messages[-1] if messages else None
    if not last_msg or not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return {}

    dispatcher = ToolDispatcher(
        db=db,
        base_url=base_url,
        auth_token=auth_token,
        user_id=user_id,
    )
    distill_svc = DataDistillationService()

    tool_messages: List[ToolMessage] = []
    new_tools_used: List[Dict[str, Any]] = []
    new_render_cards: List[Dict[str, Any]] = []
    chart_rendered = state.get("chart_already_rendered", False)
    last_spc = state.get("last_spc_result")
    force_synth = False

    for tc in last_msg.tool_calls:
        tool_name = tc["name"]
        tool_input = tc.get("args", {})
        tc_id = tc.get("id", "")

        # Preflight validation
        preflight_err = await _preflight_validate(db, tool_name, tool_input)
        if preflight_err:
            result = preflight_err
        else:
            # Inject flat_data into execute_analysis so sandbox can read it directly
            if tool_name == "execute_analysis" and state.get("flat_data"):
                tool_input = {**tool_input, "_flat_data": state["flat_data"]}
            result = await dispatcher.execute(tool_name, tool_input)

        # Track SPC results for auto-contract fallback
        if (tool_name == "execute_mcp" and isinstance(result, dict)
                and _is_spc_result(result)):
            last_spc = (result.get("mcp_name", tool_name), result)

        # Distillation for execute_mcp results
        if tool_name == "execute_mcp" and isinstance(result, dict) and result.get("status") == "success":
            result = await distill_svc.distill_mcp_result(result)

            # Inject data overview so LLM knows the full picture even when raw data is truncated.
            # get_process_info returns {total, events:[...]} wrapped in dataset list.
            od = result.get("output_data") or {}
            ds = od.get("dataset") or od.get("_raw_dataset") or []
            if isinstance(ds, list) and len(ds) == 1 and isinstance(ds[0], dict):
                inner = ds[0]
                events = inner.get("events")
                if isinstance(events, list) and len(events) > 5:
                    ooc_n = sum(1 for e in events if isinstance(e, dict) and e.get("spc_status") == "OOC")
                    ooc_steps: dict = {}
                    for e in events:
                        if isinstance(e, dict) and e.get("spc_status") == "OOC":
                            s = e.get("step", "?")
                            ooc_steps[s] = ooc_steps.get(s, 0) + 1
                    step_summary = ", ".join(f"{s}:{n}" for s, n in sorted(ooc_steps.items(), key=lambda x: -x[1])[:5])
                    overview = (
                        f"\n═══ DATA OVERVIEW ═══\n"
                        f"total_events: {len(events)}, ooc_count: {ooc_n}, ooc_rate: {ooc_n/len(events)*100:.1f}%\n"
                        f"ooc_by_step: {step_summary or 'none'}\n"
                        f"═════════════════════\n"
                    )
                    # Prepend to llm_readable_data
                    lrd = result.get("llm_readable_data")
                    if isinstance(lrd, str):
                        result["llm_readable_data"] = overview + lrd
                    elif isinstance(lrd, dict):
                        result["llm_readable_data"] = {**lrd, "_data_overview": overview}
                    else:
                        result["_data_overview"] = overview

        # Handle query_data: stash flat_data in state + build render_card with ui_config
        if tool_name == "query_data" and isinstance(result, dict) and result.get("_flat_data"):
            _flat_data = result.get("_flat_data")
            _flat_meta = result.get("_flat_metadata")
            _viz_hint = result.get("_visualization_hint")
            # Build UI config from viz_hint
            _ui_config = None
            if _viz_hint and isinstance(_viz_hint, dict):
                _ui_config = {
                    "ui_component": "ChartExplorer",
                    "initial_view": _viz_hint,
                    "available_datasets": _flat_meta.get("available_datasets", []) if _flat_meta else [],
                }
            # Build render card for SSE
            # Build query info for frontend display
            _query_params = tool_input.get("params", {})
            _total = _flat_meta.get("total_events", 0) if _flat_meta else 0
            _ooc = _flat_meta.get("ooc_count", 0) if _flat_meta else 0
            _ooc_rate = _flat_meta.get("ooc_rate", 0) if _flat_meta else 0
            card = {
                "type": "query_data",
                "mcp_name": result.get("mcp_name", ""),
                "flat_data": _flat_data,
                "flat_metadata": _flat_meta,
                "ui_config": _ui_config,
                "query_info": {
                    "mcp": result.get("mcp_name", ""),
                    "params": _query_params,
                    "result_summary": f"{_total} events, {_ooc} OOC ({_ooc_rate}%)",
                },
            }
            new_render_cards.append(card)
        else:
            # Build render card (for SSE events)
            render_card = _build_render_card(tool_name, tool_input, result)
            if render_card:
                new_render_cards.append(render_card)

        # Check if chart was rendered (via _notify_chart_rendered side effect)
        if isinstance(result, dict) and result.get("_chart_rendered"):
            chart_rendered = True

        # Track successful tool uses (for memory lifecycle)
        if isinstance(result, dict) and result.get("status") == "success":
            try:
                result_text = json.dumps(result, ensure_ascii=False, default=str)[:20000]
            except Exception:
                result_text = str(result)[:20000]
            new_tools_used.append({
                "tool": tool_name,
                "mcp_name": tool_input.get("mcp_name", ""),
                "params": {k: v for k, v in tool_input.items()
                           if k not in ("mcp_id", "mcp_name", "python_code", "params")},
                "result_text": result_text,
            })

        # Force synthesis on unrecoverable MCP/skill errors
        if isinstance(result, dict) and result.get("status") == "error":
            if tool_name in ("execute_mcp", "execute_skill"):
                if result.get("code") != "MISSING_PARAMS":
                    force_synth = True

        # Convert result to ToolMessage (trimmed for LLM context)
        result_content = _trim_result_for_llm(result)
        tool_messages.append(ToolMessage(
            content=result_content,
            tool_call_id=tc_id,
            name=tool_name,
        ))

    # Collect flat_data/ui_config from query_data results
    _state_flat_data = None
    _state_flat_meta = None
    _state_ui_config = None
    for card in new_render_cards:
        if card.get("type") == "query_data":
            _state_flat_data = card.get("flat_data")
            _state_flat_meta = card.get("flat_metadata")
            _state_ui_config = card.get("ui_config")

    result_state: Dict[str, Any] = {
        "messages": tool_messages,
        "tools_used": new_tools_used,
        "render_cards": new_render_cards,
        "chart_already_rendered": chart_rendered,
        "last_spc_result": last_spc,
        "force_synthesis": force_synth or state.get("force_synthesis", False),
    }
    if _state_flat_data:
        result_state["flat_data"] = _state_flat_data
        result_state["flat_metadata"] = _state_flat_meta
    if _state_ui_config:
        result_state["ui_config"] = _state_ui_config

    return result_state


def _trim_result_for_llm(result: Any, max_chars: int = 4000) -> str:
    """Trim tool result for LLM context — keep llm_readable_data, drop heavy payloads."""
    if not isinstance(result, dict):
        return str(result)[:max_chars]

    # Prefer llm_readable_data (designed for LLM consumption)
    lrd = result.get("llm_readable_data")
    if lrd:
        if isinstance(lrd, str):
            return lrd[:max_chars]
        try:
            return json.dumps(lrd, ensure_ascii=False, default=str)[:max_chars]
        except Exception:
            pass

    # Fallback: strip heavy keys, serialize the rest
    trimmed = dict(result)
    for key in ("output_data", "ui_render_payload", "_raw_dataset", "dataset", "_data_profile"):
        trimmed.pop(key, None)
    try:
        text = json.dumps(trimmed, ensure_ascii=False, default=str)
        return text[:max_chars]
    except Exception:
        return str(result)[:max_chars]


# ── Chart DSL → Vega-Lite converter (Python port of ChartIntentRenderer) ──

_SERIES_COLORS = ["#4299e1", "#38a169", "#d69e2e", "#9f7aea", "#ed8936", "#e53e3e"]
_RULE_COLORS = {"danger": "#e53e3e", "warning": "#dd6b20", "center": "#718096"}


def _chart_intent_to_vega_lite(intent: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a _chart DSL dict to a Vega-Lite spec.

    Python equivalent of the frontend ChartIntentRenderer.intentToVegaLite().
    Used by execute_analysis to embed charts in contract.visualization.
    """
    chart_type = intent.get("type", "line")
    title = intent.get("title", "")
    data = intent.get("data", [])
    x = intent.get("x", "index")
    y = intent.get("y", ["value"])
    rules = intent.get("rules", [])
    highlight = intent.get("highlight")
    x_label = intent.get("x_label", x)
    y_label = intent.get("y_label", y[0] if y else "value")

    layers: List[Dict[str, Any]] = []

    # Main data series
    for i, y_field in enumerate(y):
        color = _SERIES_COLORS[i % len(_SERIES_COLORS)]

        if chart_type == "line":
            layers.append({
                "mark": {"type": "line", "color": color, "strokeWidth": 1.5},
                "encoding": {
                    "x": {"field": x, "type": "ordinal", "title": x_label,
                          "axis": {"labelAngle": -60, "labelFontSize": 7}},
                    "y": {"field": y_field, "type": "quantitative", "title": y_label,
                          "scale": {"zero": False}},
                },
            })
            # Point overlay
            point_encoding: Dict[str, Any] = {
                "x": {"field": x, "type": "ordinal"},
                "y": {"field": y_field, "type": "quantitative"},
            }
            if highlight:
                point_encoding["color"] = {
                    "condition": {
                        "test": f"datum.{highlight['field']} === {json.dumps(highlight['eq'])}",
                        "value": "#e53e3e",
                    },
                    "value": color,
                }
            else:
                point_encoding["color"] = {"value": color}
            layers.append({
                "mark": {"type": "point", "size": 50, "filled": True},
                "encoding": point_encoding,
            })
        elif chart_type == "bar":
            layers.append({
                "mark": {"type": "bar", "color": color},
                "encoding": {
                    "x": {"field": x, "type": "nominal", "title": x_label,
                          "axis": {"labelAngle": -45, "labelFontSize": 8}},
                    "y": {"field": y_field, "type": "quantitative", "title": y_label,
                          "scale": {"zero": False}},
                },
            })
        else:  # scatter
            layers.append({
                "mark": {"type": "point", "size": 60, "filled": True, "color": color},
                "encoding": {
                    "x": {"field": x, "type": "ordinal", "title": x_label},
                    "y": {"field": y_field, "type": "quantitative", "title": y_label,
                          "scale": {"zero": False}},
                },
            })

    # Rule lines (UCL, LCL, CL)
    for rule in rules:
        rule_color = _RULE_COLORS.get(rule.get("style", "danger"), "#e53e3e")
        dash = [3, 3] if rule.get("style") == "center" else [6, 4]
        layers.append({
            "mark": {"type": "rule", "color": rule_color, "strokeDash": dash, "strokeWidth": 1.5},
            "encoding": {"y": {"datum": rule["value"]}},
        })
        layers.append({
            "mark": {"type": "text", "align": "right", "dx": -2, "fontSize": 9,
                     "color": rule_color, "fontWeight": "bold"},
            "encoding": {
                "y": {"datum": rule["value"]},
                "text": {"value": f"{rule.get('label', '')}={rule['value']}"},
                "x": {"value": 0},
            },
        })

    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": "container",
        "height": 280,
        "title": {"text": title, "fontSize": 13, "anchor": "start"},
        "data": {"values": data},
        "layer": layers,
    }
