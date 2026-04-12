"""Render card builder — converts tool execution results into UI render cards.

Migrated from v1 agent_orchestrator.py. Each tool type produces a specific
card type that the frontend uses to render the result (chart_intents,
contract for AnalysisPanel, table, etc.).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from app.services.agent_orchestrator_v2.helpers import _notify_chart_rendered

logger = logging.getLogger(__name__)


def _build_render_card(
    tool_name: str,
    tool_input: Dict[str, Any],
    result: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Build a render card dict for SSE tool_done events.

    Returns None for tools that don't need UI rendering (e.g. internal tools).
    """
    # ── execute_skill ──
    if tool_name == "execute_skill" and isinstance(result, dict) and "ui_render_payload" in result:
        lrd = result.get("llm_readable_data") or {}
        urp = result.get("ui_render_payload") or {}

        chart_intents = result.get("charts") or urp.get("chart_intents")
        if chart_intents:
            _notify_chart_rendered(result, chart_intents)

        card: Dict[str, Any] = {
            "type": "skill",
            "skill_name": result.get("skill_name", f"Skill #{tool_input.get('skill_id')}"),
            "status": lrd.get("status", "UNKNOWN"),
            "conclusion": lrd.get("summary", "") or lrd.get("diagnosis_message", ""),
            "summary": lrd.get("summary", ""),
            "problem_object": lrd.get("impacted_lots", []) or lrd.get("problematic_targets", []),
            "mcp_output": {
                "ui_render": {
                    "chart_data": urp.get("chart_data"),
                    "charts": [urp["chart_data"]] if urp.get("chart_data") else [],
                },
                "dataset": urp.get("dataset"),
                "_raw_dataset": urp.get("dataset"),
                "_call_params": tool_input.get("params", {}),
            },
        }
        if chart_intents:
            card["chart_intents"] = chart_intents
            # Build contract for AnalysisPanel rendering (no promote — already a Skill)
            from app.services.agent_orchestrator_v2.nodes.tool_execute import _chart_intent_to_vega_lite
            visualization = []
            for i, ci in enumerate(chart_intents):
                try:
                    vega_spec = _chart_intent_to_vega_lite(ci)
                    visualization.append({
                        "id": f"chart_{i}",
                        "type": "vega-lite",
                        "title": ci.get("title", ""),
                        "spec": vega_spec,
                    })
                except Exception:
                    pass
            if visualization:
                skill_name = result.get("skill_name", f"Skill #{tool_input.get('skill_id')}")
                card["contract"] = {
                    "$schema": "aiops-report/v1",
                    "summary": lrd.get("summary", f"{skill_name} 執行結果"),
                    "evidence_chain": [],
                    "visualization": visualization,
                    "suggested_actions": [],  # No promote — already a Skill
                }
        return card

    # ── execute_mcp ──
    if tool_name == "execute_mcp" and isinstance(result, dict) and result.get("status") == "success":
        od = result.get("output_data") or {}
        mcp_id = tool_input.get("mcp_id")
        mcp_name = result.get("mcp_name") or f"MCP #{mcp_id}"
        dataset = od.get("dataset")
        raw_dataset = od.get("_raw_dataset") or dataset

        # ── Render intent classifier: decide how to present this MCP result ──
        # Principle: structure-driven, not keyword-driven. Classifier inspects
        # raw_dataset shape and returns a primary render + alternatives.
        # The contract carries everything the frontend needs to render instantly
        # AND switch between alternative renders without re-calling the MCP.
        contract = None
        try:
            from app.services.render_intent_classifier import classify_render_intent, build_outputs
            from app.services.chart_middleware import process as chart_process

            # Use the unwrapped raw response (single dict, not the dataset wrapper list)
            classify_input = raw_dataset[0] if isinstance(raw_dataset, list) and len(raw_dataset) == 1 else raw_dataset
            decision = classify_render_intent(classify_input, mcp_name=mcp_name or "")

            def _opt_to_render(opt):
                """Apply transform → chart_middleware → return frontend-ready render block."""
                outputs = build_outputs(opt, classify_input)
                charts = chart_process(outputs, opt.output_schema) if outputs and opt.output_schema else []
                return {
                    "id": opt.id,
                    "label": opt.label,
                    "kind": opt.kind,
                    "output_schema": opt.output_schema,
                    "outputs": outputs,
                    "charts": charts,
                    "recommended": opt.recommended,
                }

            primary_block = _opt_to_render(decision.primary) if decision.primary else None
            alt_blocks = [_opt_to_render(o) for o in decision.alternatives]

            if decision.kind.value == "ask_user":
                # Multi-choice: no primary chart, frontend renders a choice card
                contract = {
                    "$schema": "aiops-report/v1",
                    "summary": decision.question or f"取得 {mcp_name} 的資料，要怎麼呈現？",
                    "evidence_chain": [],
                    "visualization": [],
                    "suggested_actions": [],
                    "render_decision": {
                        "kind": "ask_user",
                        "question": decision.question,
                        "options": alt_blocks,
                    },
                }
            elif primary_block:
                # Auto render: primary + switchable alternatives
                contract = {
                    "$schema": "aiops-report/v1",
                    "summary": f"已取得 {mcp_name} 的資料",
                    "evidence_chain": [],
                    "visualization": [],
                    "suggested_actions": [],
                    "findings": {
                        "condition_met": False,
                        "summary": "",
                        "outputs": primary_block["outputs"],
                    },
                    "output_schema": primary_block["output_schema"],
                    "charts": primary_block["charts"],
                    "render_decision": {
                        "kind": decision.kind.value,
                        "primary": primary_block,
                        "alternatives": alt_blocks,
                    },
                }
                if primary_block["charts"]:
                    _notify_chart_rendered(result, primary_block["charts"])
                logger.warning(
                    "[render_card execute_mcp] mcp=%r kind=%s primary_charts=%d alts=%d",
                    mcp_name, decision.kind.value, len(primary_block["charts"]), len(alt_blocks),
                )
        except Exception as exc:
            logger.exception("render_card execute_mcp classifier failed: %s", exc)
            contract = None

        card = {
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
        if contract:
            card["contract"] = contract
        return card

    # ── draft_* tools ──
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

    # ── navigate ──
    if tool_name == "navigate" and isinstance(result, dict) and result.get("action") == "navigate":
        return {
            "type": "navigate",
            "target": result.get("target"),
            "id": result.get("id"),
            "message": result.get("message", ""),
        }

    # ── execute_analysis ──
    if tool_name == "execute_analysis" and isinstance(result, dict):
        if result.get("status") == "success":
            data = result.get("data") or {}
            charts = data.get("charts") or []
            findings = data.get("findings") or {}
            steps_mapping = data.get("steps_mapping") or []
            step_results = data.get("step_results") or []

            # Index step_results by step_id for quick join with steps_mapping
            sr_by_id: Dict[str, Dict[str, Any]] = {
                (sr.get("step_id") or ""): sr for sr in step_results if isinstance(sr, dict)
            }

            # Build evidence_chain — DR/AP-style, includes python_code + output + status
            evidence_chain = []
            for i, s in enumerate(steps_mapping):
                step_id = s.get("step_id", "")
                sr = sr_by_id.get(step_id, {})
                evidence_chain.append({
                    "step": i + 1,
                    "step_id": step_id,
                    "tool": step_id,                            # back-compat
                    "finding": s.get("nl_segment", ""),         # back-compat
                    "nl_segment": s.get("nl_segment", ""),
                    "python_code": s.get("python_code", ""),
                    "status": sr.get("status", "ok"),
                    "output": sr.get("output"),
                    "error": sr.get("error"),
                })

            # Visualization: passthrough ChartMiddleware DSL — no vega-lite re-conversion
            visualization = [
                {
                    "id": f"chart_{i}",
                    "type": "chart-dsl",  # frontend renders via ChartListRenderer
                    "title": chart.get("title", f"Chart {i+1}"),
                    "chart": chart,
                }
                for i, chart in enumerate(charts)
            ]

            promote_payload = {
                "title": data.get("title", ""),
                "steps_mapping": steps_mapping,
                "input_schema": data.get("input_schema", []),
                "output_schema": data.get("output_schema", []),
            }

            contract = {
                "$schema": "aiops-report/v1",
                "summary": findings.get("summary", data.get("title", "")),
                "findings": findings,                              # full findings → enables RenderMiddleware
                "output_schema": data.get("output_schema", []),    # needed by RenderMiddleware
                "evidence_chain": evidence_chain,
                "visualization": visualization,
                "charts": charts,                                  # raw chart DSL list
                "suggested_actions": [
                    {
                        "label": "⭐ 儲存為我的 Skill",
                        "trigger": "promote_analysis",
                        "payload": promote_payload,
                    },
                ],
            }

            if charts:
                _notify_chart_rendered(result, charts)
                logger.warning(
                    "[render_card] execute_analysis: %d step(s), %d chart(s), summary=%r",
                    len(steps_mapping), len(charts), (findings.get("summary") or "")[:80],
                )
                _first = charts[0] if isinstance(charts[0], dict) else None
                _data = (_first or {}).get("data") if _first else None
                logger.warning(
                    "[render_card ↳] first chart title=%r data_rows=%s sample=%s",
                    (_first or {}).get("title") if _first else None,
                    len(_data) if isinstance(_data, list) else "?",
                    str(_data[0])[:200] if isinstance(_data, list) and _data else None,
                )
            else:
                logger.warning(
                    "[render_card] execute_analysis: %d step(s) but NO charts in data['charts'] — "
                    "raw data keys=%s, output_schema=%s",
                    len(steps_mapping),
                    list(data.keys()),
                    [(s.get("key"), s.get("type")) for s in (data.get("output_schema") or [])],
                )

            return {
                "type": "analysis",
                "tool_name": data.get("title", "Ad-hoc 分析"),
                "summary": findings.get("summary", ""),
                "contract": contract,
            }

    return None
