"""inspect_execution_node — semantic post-execution check.

Reads `state.dry_run_results` (populated by finalize_node) and scans
chart-block previews for semantic anti-patterns that the validator can't
catch ahead of time. POC scope (2026-05-13): 1 signal only —
**single-point chart**: when a time-series chart resolves to <3 distinct
eventTime points, the LLM almost certainly built the pipeline with an
unintended limit=1 or aggregate upstream.

If any issues are found, sets `inspection_issues` so the conditional edge
in graph.py routes to `reflect_plan`. Otherwise emits a clean SSE event
and returns no state delta — `_route_after_inspect` will fall through to
`layout`.

Future expansion (Phase 1.x):
  - verdict.value is numeric, not "error"/null
  - all node_results status == "success"
  - no orphan add_nodes in final_pipeline
"""
from __future__ import annotations

import logging
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState


logger = logging.getLogger(__name__)

# Minimum distinct x-axis values a time-series chart must have. Anything
# below this is the "single-point bug" the user complained about — chart
# renders as a lone dot with no trend information.
MIN_DISTINCT_X = 3


def _extract_chart_panels(preview: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull every chart panel out of a node's preview dict.

    Preview shape is dictated by _preview_output() in executor.py — chart
    blocks emit a dict (chart_spec) on output port "chart", which preview
    wraps as `{type:"dict", snapshot: <chart_spec>}`. Facet variants emit
    a python list which preview wraps as `{type:"list", sample:[...]}`.

    A "chart panel" here = anything with a non-empty `data` list and a
    `type` string — the two fields we need to call it a time-series chart
    and pull eventTime from.
    """
    panels: list[dict[str, Any]] = []
    for port, blob in (preview or {}).items():
        if not isinstance(blob, dict):
            continue
        # Non-facet: snapshot is the chart_spec dict itself
        snap = blob.get("snapshot")
        if isinstance(snap, dict) and isinstance(snap.get("data"), list):
            panels.append({"port": port, "panel_idx": None, **snap})
            # chart_spec may also nest facets at snapshot.facets[*].data
            facets = snap.get("facets")
            if isinstance(facets, list):
                for i, f in enumerate(facets):
                    if isinstance(f, dict) and isinstance(f.get("data"), list):
                        panels.append({"port": port, "panel_idx": i, **f})
        # Facet list shape: {type:"list", sample:[{type, data}, ...]}
        if blob.get("type") == "list" and isinstance(blob.get("sample"), list):
            for i, p in enumerate(blob["sample"]):
                if isinstance(p, dict) and isinstance(p.get("data"), list):
                    panels.append({"port": port, "panel_idx": i, **p})
    return panels


def _distinct_x(panel_data: list[Any], x_key: str = "eventTime") -> int:
    seen: set[Any] = set()
    for row in panel_data:
        if isinstance(row, dict):
            seen.add(row.get(x_key))
    return len(seen)


def inspect_execution_node(state: BuildGraphState) -> dict[str, Any]:
    dry = state.get("dry_run_results")
    if not dry or state.get("status") != "finished":
        # Nothing to inspect (skip case, side-effect blocks, or build failed
        # earlier). Pass through cleanly.
        logger.info("inspect_execution: skipped (no dry_run_results or status=%s)",
                    state.get("status"))
        return {"inspection_issues": []}

    node_results = (dry or {}).get("node_results") or {}
    issues: list[dict[str, Any]] = []

    for nid, info in node_results.items():
        if not isinstance(info, dict):
            continue
        if info.get("status") != "success":
            continue
        preview = info.get("preview") or {}
        panels = _extract_chart_panels(preview)
        for p in panels:
            data = p.get("data") or []
            if not data:
                continue
            chart_type = p.get("type") or "unknown"
            # Probe for any time-series-like x_key — fall back to "eventTime"
            x_key = p.get("x_key") or "eventTime"
            distinct = _distinct_x(data, x_key)
            if distinct < MIN_DISTINCT_X:
                issues.append({
                    "kind": "single_point_chart",
                    "node_id": nid,
                    "chart_type": chart_type,
                    "panel_idx": p.get("panel_idx"),
                    "distinct_x": distinct,
                    "n_points": len(data),
                    "hint": (
                        f"chart on node '{nid}' resolved to only {distinct} "
                        f"distinct {x_key} value(s) ({len(data)} data points). "
                        f"Likely an unintended upstream limit=1 or aggregate "
                        f"that collapsed the time series. Use limit>=50 on "
                        f"the source block, and don't put sort+limit=1 "
                        f"between the source and a chart block."
                    ),
                })

    sse_events: list[dict[str, Any]] = []
    if issues:
        logger.warning("inspect_execution: %d semantic issue(s) found", len(issues))
        sse_events.append({"event": "inspection_issues_found", "data": {
            "count": len(issues),
            "issues": issues[:5],
        }})
    else:
        logger.info("inspect_execution: clean (no semantic issues)")
        sse_events.append({"event": "inspection_clean", "data": {
            "node_count": len(node_results),
        }})

    return {"inspection_issues": issues, "sse_events": sse_events}
