"""block_chart — 圖表輸出。

Output modes:
  - classic Vega-Lite (single y, line/bar/scatter/area without control lines)
  - ChartDSL (__dsl=true) — Plotly via ChartDSLRenderer, used for:
      * SPC mode (ucl/lcl/center/highlight columns)
      * multi-y (y is an array, or y_secondary provided → dual axis)
      * chart_type="boxplot" (group_by + value)
      * chart_type="heatmap"  (x / y / value)
"""

from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
import pandas as pd

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)


_CHART_TYPES = {"line", "bar", "scatter", "area", "boxplot", "heatmap", "distribution", "table"}
_COLOR_SCHEMES = {"tableau10", "set2", "blues", "reds", "greens"}
_DSL_TYPE_MAP = {"line": "line", "bar": "bar", "scatter": "scatter", "area": "line"}


_SIGMA_COLORS = {1: "#22c55e", 2: "#eab308", 3: "#f97316", 4: "#ef4444"}  # green → red escalation


def _require_col(df: pd.DataFrame, col: Optional[str], label: str) -> Optional[str]:
    if col is None or col == "":
        return None
    if col not in df.columns:
        raise BlockExecutionError(
            code="COLUMN_NOT_FOUND", message=f"{label} column '{col}' not in data"
        )
    return col


def _optional_col(df: pd.DataFrame, col: Optional[str]) -> Optional[str]:
    """Graceful variant — return None if missing instead of raising.
    For optional overlays (ucl/lcl/highlight/center) where chart should still
    render without them if the data doesn't have them."""
    if col is None or col == "":
        return None
    if col not in df.columns:
        return None
    return col


def _normalize_y(raw: Any) -> list[str]:
    """Accept y as string or list of strings; return list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list) and all(isinstance(s, str) for s in raw):
        return list(raw)
    raise BlockExecutionError(
        code="INVALID_PARAM", message="y must be a string or array of strings"
    )


def _scalar_mean(df: pd.DataFrame, col: Optional[str]) -> Optional[float]:
    if col is None:
        return None
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.mean())


def _records(df: pd.DataFrame, keep: list[str]) -> list[dict[str, Any]]:
    trimmed = df[keep].astype(object).where(df[keep].notna(), None)
    return trimmed.to_dict(orient="records")


def _build_boxplot(df: pd.DataFrame, params: dict[str, Any], title: Optional[str]) -> dict[str, Any]:
    value_col = _require_col(df, params.get("y") or params.get("value_column"), "value (y)")
    group_col = _require_col(df, params.get("group_by") or params.get("x"), "group_by (x)")
    if not value_col:
        raise BlockExecutionError(
            code="MISSING_PARAM", message="boxplot requires y (value_column)"
        )
    keep = [c for c in (group_col, value_col) if c is not None]
    return {
        "__dsl": True,
        "type": "boxplot",
        "title": title or f"{value_col} by {group_col or 'all'}",
        "x": group_col or "_all",
        "y": [value_col],
        "data": _records(df, keep) if keep else df.to_dict(orient="records"),
    }


def _build_distribution(df: pd.DataFrame, params: dict[str, Any], title: Optional[str]) -> dict[str, Any]:
    """chart_type='distribution' — histogram + fitted normal PDF + σ markers + USL/LSL.

    The frontend renders:
      - Bar trace for histogram bin counts
      - Line trace for normal PDF (scaled to bar height)
      - Vertical dotted lines at μ ± kσ for k in show_sigma_lines
      - USL / LSL if given
      - μ / σ / n / skewness annotation
    """
    value_col: Optional[str] = params.get("value_column") or (params.get("y") if isinstance(params.get("y"), str) else None)
    if value_col is None:
        raise BlockExecutionError(
            code="MISSING_PARAM", message="distribution requires value_column (numeric)"
        )
    value_col = _require_col(df, value_col, "value_column")
    assert value_col is not None

    values = pd.to_numeric(df[value_col], errors="coerce").dropna().to_numpy(dtype=float)
    n = int(len(values))
    if n < 2:
        raise BlockExecutionError(
            code="INSUFFICIENT_DATA", message=f"distribution needs n>=2 (got {n})"
        )

    bins_raw = params.get("bins", 20)
    try:
        bins = int(bins_raw)
    except (TypeError, ValueError):
        bins = 20
    if bins < 2:
        bins = 20

    counts, edges = np.histogram(values, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2.0
    bar_data = [
        {"bin_center": float(c), "count": int(cnt), "bin_left": float(l), "bin_right": float(r)}
        for c, cnt, l, r in zip(centers, counts, edges[:-1], edges[1:])
    ]

    mu = float(np.mean(values))
    sigma = float(np.std(values, ddof=1)) if n > 1 else 0.0
    # PDF scaled so peak ≈ max bar count (keeps both on same y-axis)
    pdf_data: list[dict[str, Any]] = []
    max_count = int(counts.max()) if len(counts) > 0 else 0
    if sigma > 0 and max_count > 0:
        xs = np.linspace(float(edges[0]), float(edges[-1]), 120)
        bin_width = float(edges[1] - edges[0]) if len(edges) > 1 else 1.0
        pdf = (1.0 / (sigma * math.sqrt(2 * math.pi))) * np.exp(-0.5 * ((xs - mu) / sigma) ** 2)
        # Scale so area matches histogram count (pdf * n * bin_width ≈ count)
        scaled = pdf * n * bin_width
        pdf_data = [{"x": float(x), "y": float(y)} for x, y in zip(xs, scaled)]

    # σ markers
    show_sigmas = params.get("show_sigma_lines")
    if show_sigmas is None:
        show_sigmas = [1, 2, 3]
    if not isinstance(show_sigmas, list):
        raise BlockExecutionError(
            code="INVALID_PARAM", message="show_sigma_lines must be a list of integers"
        )

    rules: list[dict[str, Any]] = []
    if sigma > 0:
        # center
        rules.append({"value": mu, "label": "μ", "style": "center"})
        for k in show_sigmas:
            try:
                k_int = int(k)
            except (TypeError, ValueError):
                continue
            if k_int < 1 or k_int > 6:
                continue
            color = _SIGMA_COLORS.get(k_int, "#94a3b8")
            rules.append({"value": mu + k_int * sigma, "label": f"+{k_int}σ", "style": "sigma", "color": color})
            rules.append({"value": mu - k_int * sigma, "label": f"-{k_int}σ", "style": "sigma", "color": color})

    # USL / LSL
    usl = params.get("usl")
    lsl = params.get("lsl")
    if usl is not None:
        rules.append({"value": float(usl), "label": "USL", "style": "danger"})
    if lsl is not None:
        rules.append({"value": float(lsl), "label": "LSL", "style": "danger"})

    # skewness (simple moment)
    skewness = 0.0
    if sigma > 0 and n > 2:
        skewness = float(np.mean(((values - mu) / sigma) ** 3))

    return {
        "__dsl": True,
        "type": "distribution",
        "title": title or f"{value_col} 常態分佈 (n={n})",
        "x": "bin_center",
        "y": ["count"],
        "data": bar_data,
        "pdf_data": pdf_data,
        "rules": rules,
        "stats": {
            "mu": mu,
            "sigma": sigma,
            "n": n,
            "skewness": skewness,
        },
    }


def _build_heatmap(df: pd.DataFrame, params: dict[str, Any], title: Optional[str]) -> dict[str, Any]:
    x_col = _require_col(df, params.get("x"), "x")
    y_col = _require_col(df, params.get("y"), "y")
    z_col = _require_col(df, params.get("value_column"), "value_column")
    if x_col is None or y_col is None or z_col is None:
        raise BlockExecutionError(
            code="MISSING_PARAM", message="heatmap requires x, y, and value_column"
        )
    keep = [x_col, y_col, z_col]
    return {
        "__dsl": True,
        "type": "heatmap",
        "title": title or f"{z_col}",
        "x": x_col,
        "y": [y_col],
        "value_key": z_col,
        "data": _records(df, keep),
    }


def _build_spc_or_multi_line(
    df: pd.DataFrame,
    chart_type: str,
    x: str,
    y_list: list[str],
    y_secondary: list[str],
    title: Optional[str],
    ucl_col: Optional[str],
    lcl_col: Optional[str],
    center_col: Optional[str],
    highlight_col: Optional[str],
    sigma_zones: Optional[list[int]] = None,
) -> dict[str, Any]:
    """ChartDSL spec for SPC / multi-y / dual-axis modes."""
    rules: list[dict[str, Any]] = []
    ucl_val = _scalar_mean(df, ucl_col)
    lcl_val = _scalar_mean(df, lcl_col)
    # Center line: explicit center_col if given, otherwise mean of first y (SPC convention).
    center_basis = center_col if center_col is not None else (y_list[0] if y_list else None)
    center_val = _scalar_mean(df, center_basis) if center_basis else None
    if ucl_val is not None:
        rules.append({"value": ucl_val, "label": "UCL", "style": "danger"})
    if lcl_val is not None:
        rules.append({"value": lcl_val, "label": "LCL", "style": "danger"})
    if center_val is not None and (center_col is not None or ucl_val is not None or lcl_val is not None):
        rules.append({"value": center_val, "label": "Center", "style": "center"})

    # Additional σ zone lines (e.g. ±1σ / ±2σ for Nelson A/B/C zones).
    # σ is derived from UCL + Center: σ = (UCL - Center) / 3  (SPC convention).
    if sigma_zones and ucl_val is not None and center_val is not None:
        sigma = (ucl_val - center_val) / 3.0
        if sigma > 0:
            for k in sigma_zones:
                try:
                    k_int = int(k)
                except (TypeError, ValueError):
                    continue
                if k_int < 1 or k_int > 6:
                    continue
                color = _SIGMA_COLORS.get(k_int, "#94a3b8")
                rules.append({
                    "value": center_val + k_int * sigma,
                    "label": f"+{k_int}σ",
                    "style": "sigma",
                    "color": color,
                })
                rules.append({
                    "value": center_val - k_int * sigma,
                    "label": f"-{k_int}σ",
                    "style": "sigma",
                    "color": color,
                })

    # Trim payload to x + y + y_secondary + highlight
    keep: list[str] = []
    for col in (x, *y_list, *y_secondary, highlight_col):
        if col and col not in keep:
            keep.append(col)
    spec: dict[str, Any] = {
        "__dsl": True,
        "type": _DSL_TYPE_MAP.get(chart_type, "line"),
        "title": title or (f"{y_list[0]} over {x}" if y_list else x),
        "x": x,
        "y": y_list,
        "data": _records(df, keep),
        "rules": rules,
    }
    if y_secondary:
        spec["y_secondary"] = y_secondary
    if highlight_col is not None:
        spec["highlight"] = {"field": highlight_col, "eq": True}
    return spec


class ChartBlockExecutor(BlockExecutor):
    block_id = "block_chart"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        df = inputs.get("data")
        if not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(code="INVALID_INPUT", message="'data' must be DataFrame")

        chart_type = params.get("chart_type", "line")
        if chart_type not in _CHART_TYPES:
            raise BlockExecutionError(
                code="INVALID_PARAM", message=f"chart_type must be one of {sorted(_CHART_TYPES)}"
            )
        title = params.get("title") or None

        # PR-A: empty upstream df → placeholder spec instead of raising.
        # Keeps downstream Pipeline Results panel rendering (empty-state card)
        # rather than erroring out the whole run.
        if df.empty:
            return {
                "chart_spec": {
                    "__dsl": True,
                    "type": "empty",
                    "title": title or "No data",
                    "message": "上游資料為空 — 可能是 logic 沒觸發或 filter 篩光",
                    "data": [],
                }
            }

        # Route boxplot / heatmap / distribution directly.
        if chart_type == "boxplot":
            return {"chart_spec": _build_boxplot(df, params, title)}
        if chart_type == "heatmap":
            return {"chart_spec": _build_heatmap(df, params, title)}
        if chart_type == "distribution":
            return {"chart_spec": _build_distribution(df, params, title)}
        if chart_type == "table":
            # Table mode — no axes. Optionally pick a subset of columns.
            columns_param = params.get("columns")
            if isinstance(columns_param, list) and columns_param:
                missing = [c for c in columns_param if c not in df.columns]
                if missing:
                    raise BlockExecutionError(
                        code="COLUMN_NOT_FOUND",
                        message=f"columns not in data: {missing}",
                    )
                keep = list(columns_param)
            else:
                keep = list(df.columns)
            max_rows = int(params.get("max_rows") or 500)
            trimmed = df[keep].head(max_rows)
            return {
                "chart_spec": {
                    "__dsl": True,
                    "type": "table",
                    "title": title or "Table",
                    "columns": keep,
                    "data": _records(trimmed, keep),
                    "total_rows": int(len(df)),
                }
            }

        # Common path: require x + at least one y (string or array).
        x = self.require(params, "x")
        if x not in df.columns:
            # PR-F runtime-QA: x col missing → try eventTime, else first string col
            if "eventTime" in df.columns:
                x = "eventTime"
            else:
                str_cols = [c for c in df.columns if df[c].dtype == object]
                if str_cols:
                    x = str_cols[0]
                else:
                    raise BlockExecutionError(
                        code="COLUMN_NOT_FOUND", message=f"Column '{x}' not in data"
                    )
        y_list = _normalize_y(self.require(params, "y"))
        y_secondary = _normalize_y(params.get("y_secondary"))
        # Graceful: drop any y/y_secondary columns that don't exist.
        y_list = [c for c in y_list if c in df.columns]
        y_secondary = [c for c in y_secondary if c in df.columns]
        if not y_list:
            # PR-F runtime-QA: fall back to first numeric column so chart still renders
            numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            if numeric_cols:
                y_list = [numeric_cols[0]]
            else:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message="No numeric column found to use as y-axis",
                )

        # PR-F runtime-QA: optional overlay cols are now soft — missing ones drop.
        ucl_col = _optional_col(df, params.get("ucl_column"))
        lcl_col = _optional_col(df, params.get("lcl_column"))
        center_col = _optional_col(df, params.get("center_column"))
        highlight_col = _optional_col(df, params.get("highlight_column"))

        spc_mode = any(c is not None for c in (ucl_col, lcl_col, center_col, highlight_col))
        multi_y = len(y_list) > 1 or bool(y_secondary)
        sigma_zones = params.get("sigma_zones")
        if sigma_zones is not None and not isinstance(sigma_zones, list):
            raise BlockExecutionError(
                code="INVALID_PARAM", message="sigma_zones must be a list of integers (e.g. [1, 2])"
            )

        if spc_mode or multi_y or sigma_zones:
            return {
                "chart_spec": _build_spc_or_multi_line(
                    df, chart_type, x, y_list, y_secondary, title,
                    ucl_col, lcl_col, center_col, highlight_col,
                    sigma_zones=sigma_zones,
                )
            }

        # ── Classic Vega-Lite (single y, no control lines) ───────────────────
        y = y_list[0]
        color = params.get("color") or None
        if color is not None and color not in df.columns:
            raise BlockExecutionError(
                code="COLUMN_NOT_FOUND", message=f"Color column '{color}' not in data"
            )

        color_scheme = params.get("color_scheme") or None
        if color_scheme and color_scheme not in _COLOR_SCHEMES:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=f"color_scheme must be one of {sorted(_COLOR_SCHEMES)}",
            )
        show_legend = bool(params.get("show_legend", True))

        def _vl_type(col: str) -> str:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                return "temporal"
            if pd.api.types.is_numeric_dtype(df[col]):
                return "quantitative"
            return "nominal"

        encoding: dict[str, Any] = {
            "x": {"field": x, "type": _vl_type(x)},
            "y": {"field": y, "type": _vl_type(y)},
        }
        if color:
            color_enc: dict[str, Any] = {"field": color, "type": "nominal"}
            if color_scheme:
                color_enc["scale"] = {"scheme": color_scheme}
            if not show_legend:
                color_enc["legend"] = None
            encoding["color"] = color_enc

        mark = {"line": "line", "bar": "bar", "scatter": "point", "area": "area"}[chart_type]
        spec: dict[str, Any] = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "mark": mark,
            "encoding": encoding,
            "data": {"values": df.astype(object).where(df.notna(), None).to_dict(orient="records")},
            "width": params.get("width", 600),
            "height": params.get("height", 300),
        }
        if title:
            spec["title"] = title
        return {"chart_spec": spec}
