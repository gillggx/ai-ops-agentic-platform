"""Shared agent-adjustable chart style params (2026-07-07, chart-style wave 1).

Every chart block accepts two OPTIONAL params and passes them through into
chart_spec so the SVG engine can render them:

  style: {
    spc_zones: bool     — σ Zone A/B/C bands (only meaningful with control
                          limits; default follows the chart's convention)
    line_style: 'solid'|'dash'|'step'
    show_markers: bool
    marker_size: 'small'|'medium'|'large'
    show_values: bool   — value labels (bar/pareto family)
    x_label / y_label: str — axis titles
    legend: 'none'|'top'|'right'
  }
  tooltip_fields: [str] — extra row columns shown in the hover tooltip
                          (max 5; validated against the input dataframe so the
                          agent gets a deterministic, self-correctable error)

Design rules (per CLAUDE.md):
  - fail-soft on unknown style keys (dropped, never crash the chart)
  - fail-LOUD on invalid tooltip_fields with the available columns listed —
    deterministic feedback the agent can act on (same philosophy as the
    verifier's reject reasons)
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import BlockExecutionError

TOOLTIP_FIELDS_MAX = 5

_STYLE_KEYS = {
    "spc_zones": bool,
    "line_style": ("solid", "dash", "step"),
    "show_markers": bool,
    "marker_size": ("small", "medium", "large"),
    "show_values": bool,
    "x_label": str,
    "y_label": str,
    "legend": ("none", "top", "right"),
}


def parse_style(params: dict[str, Any]) -> dict[str, Any]:
    """Sanitise the `style` param. Unknown keys / wrong-typed values are
    DROPPED (fail-soft) — a style mistake must never kill the chart."""
    raw = params.get("style")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, rule in _STYLE_KEYS.items():
        if key not in raw:
            continue
        v = raw[key]
        if rule is bool:
            if isinstance(v, bool):
                out[key] = v
        elif rule is str:
            if isinstance(v, str) and v.strip():
                out[key] = v.strip()[:60]
        elif isinstance(rule, tuple):
            if isinstance(v, str) and v in rule:
                out[key] = v
    return out


def parse_tooltip_fields(
    params: dict[str, Any], df: pd.DataFrame | None,
) -> list[str]:
    """Validate `tooltip_fields` against the input dataframe.

    Invalid column → BlockExecutionError naming the available columns, so the
    build-loop agent can self-correct instead of guessing (this mirrors how
    highlight_field already fails)."""
    raw = params.get("tooltip_fields")
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise BlockExecutionError(
            code="INVALID_PARAM",
            message="tooltip_fields must be a list of column names",
        )
    fields = [str(f).strip() for f in raw if str(f).strip()][:TOOLTIP_FIELDS_MAX]
    if df is not None and not df.empty:
        missing = [f for f in fields if f not in df.columns]
        if missing:
            available = ", ".join(list(df.columns)[:30])
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND",
                message=(
                    f"tooltip_fields {missing} not in data. "
                    f"Available columns: {available}"
                ),
            )
    return fields


def apply_chart_style(
    spec: dict[str, Any],
    params: dict[str, Any],
    df: pd.DataFrame | None,
    *,
    default_style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge style/tooltip params into a chart_spec (in place + returned).

    default_style: chart-convention defaults (e.g. xbar_r turns spc_zones on
    by default) — the agent's explicit values always win."""
    style = dict(default_style or {})
    style.update(parse_style(params))
    if style:
        spec["style"] = style
    fields = parse_tooltip_fields(params, df)
    if fields:
        spec["tooltip_fields"] = fields
    return spec
