"""Distribution & comparison chart tools (v15.3).

Tools: plot_box, plot_violin, plot_heatmap, plot_radar, plot_error_bar
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _plotly_to_payload, _safe_float


def plot_box(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        cols = params.get("columns") or params.get("y")
        group_col = params.get("group_by")
        title = params.get("title", "Box Plot")

        if isinstance(cols, str):
            cols = [cols]
        if not cols:
            sample = data[0] if data else {}
            cols = [k for k, v in sample.items() if isinstance(v, (int, float))][:4]

        traces = []
        if group_col:
            groups = {}
            for row in data:
                g = str(row.get(group_col, "unknown"))
                groups.setdefault(g, []).append(row)
            for g, rows in groups.items():
                for col in cols:
                    vals = [_safe_float(r.get(col)) for r in rows]
                    traces.append(go.Box(y=vals, name=f"{col}/{g}", boxpoints="outliers"))
        else:
            for col in cols:
                vals = [_safe_float(r.get(col)) for r in data]
                traces.append(go.Box(y=vals, name=col, boxpoints="outliers"))

        fig = go.Figure(data=traces, layout=go.Layout(title=title))
        return ToolResult.ok(f"Box plot: {len(cols)} columns, {len(data)} rows",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_box failed: {exc}")


def plot_violin(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        col = params.get("column") or params.get("y")
        group_col = params.get("group_by")
        title = params.get("title", "Violin Plot")

        if not col:
            sample = data[0] if data else {}
            col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not col:
            return ToolResult.err("No numeric column found.")

        if group_col:
            groups = {}
            for row in data:
                g = str(row.get(group_col, "all"))
                groups.setdefault(g, []).append(_safe_float(row.get(col)))
            traces = [go.Violin(y=vals, name=g, box_visible=True, meanline_visible=True)
                      for g, vals in groups.items()]
        else:
            vals = [_safe_float(r.get(col)) for r in data]
            traces = [go.Violin(y=vals, name=col, box_visible=True, meanline_visible=True)]

        fig = go.Figure(data=traces, layout=go.Layout(title=title))
        return ToolResult.ok(f"Violin plot: '{col}', {len(data)} rows", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_violin failed: {exc}")


def plot_heatmap(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go
        import numpy as np

        matrix = params.get("matrix")
        x_labels = params.get("x_labels")
        y_labels = params.get("y_labels")
        title = params.get("title", "Heatmap")
        auto_corr = params.get("correlation", False)

        if auto_corr or not matrix:
            # Compute correlation matrix from data
            import pandas as pd
            df = pd.DataFrame(data).select_dtypes(include="number")
            corr = df.corr()
            matrix = corr.values.tolist()
            x_labels = x_labels or list(corr.columns)
            y_labels = y_labels or list(corr.index)

        fig = go.Figure(
            data=go.Heatmap(z=matrix, x=x_labels, y=y_labels,
                            colorscale="RdBu", zmid=0),
            layout=go.Layout(title=title),
        )
        return ToolResult.ok(f"Heatmap: {len(matrix)}×{len(matrix[0] if matrix else [])} matrix",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_heatmap failed: {exc}")


def plot_radar(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        metrics = params.get("metrics")
        values = params.get("values")
        title = params.get("title", "Radar Chart")
        name_col = params.get("name_col")

        if not (metrics and values) and data:
            # Use numeric columns as metrics, rows as series
            sample = data[0]
            metrics = metrics or [k for k, v in sample.items() if isinstance(v, (int, float))]
            traces = []
            for row in data[:5]:  # cap at 5 series
                name = str(row.get(name_col, "")) if name_col else str(list(row.values())[0])
                vals = [_safe_float(row.get(m, 0)) for m in metrics]
                traces.append(go.Scatterpolar(
                    r=vals + [vals[0]], theta=metrics + [metrics[0]],
                    fill="toself", name=name,
                ))
        else:
            if isinstance(values[0], list):
                traces = [go.Scatterpolar(r=v + [v[0]], theta=metrics + [metrics[0]],
                                          fill="toself") for v in values]
            else:
                traces = [go.Scatterpolar(r=values + [values[0]],
                                          theta=metrics + [metrics[0]], fill="toself")]

        fig = go.Figure(data=traces,
                        layout=go.Layout(title=title,
                                         polar={"radialaxis": {"visible": True}}))
        return ToolResult.ok(f"Radar chart: {len(metrics)} axes", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_radar failed: {exc}")


def plot_error_bar(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        x_col = params.get("x")
        y_col = params.get("y")
        error_col = params.get("error")
        title = params.get("title", "Error Bar Chart")

        if not y_col:
            sample = data[0] if data else {}
            y_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not y_col:
            return ToolResult.err("No numeric column found.")

        x_vals = [row.get(x_col) for row in data] if x_col else list(range(len(data)))
        y_vals = [_safe_float(row.get(y_col)) for row in data]
        err_vals = [_safe_float(row.get(error_col)) for row in data] if error_col else None

        error_y = {"type": "data", "array": err_vals, "visible": True} if err_vals else None
        fig = go.Figure(
            data=[go.Scatter(x=x_vals, y=y_vals, mode="markers+lines",
                             error_y=error_y, name=y_col)],
            layout=go.Layout(title=title),
        )
        return ToolResult.ok(f"Error bar: '{y_col}', {len(data)} points", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_error_bar failed: {exc}")
