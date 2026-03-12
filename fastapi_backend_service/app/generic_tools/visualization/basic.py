"""Basic chart tools (v15.3).

Tools: plot_line, plot_bar, plot_scatter, plot_histogram,
       plot_pie, plot_area, plot_step_line
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _plotly_to_payload, _safe_float


def _extract_col(data: List[Dict], col: str) -> List:
    return [row.get(col) for row in data]


def plot_line(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        x_col = params.get("x")
        y_cols = params.get("y") or params.get("y_cols")
        title = params.get("title", "Line Chart")

        if isinstance(y_cols, str):
            y_cols = [y_cols]
        if not y_cols:
            sample = data[0] if data else {}
            y_cols = [k for k, v in sample.items() if isinstance(v, (int, float))][:3]

        x_vals = _extract_col(data, x_col) if x_col else list(range(len(data)))
        traces = [go.Scatter(x=x_vals, y=_extract_col(data, y), mode="lines+markers",
                             name=y) for y in y_cols]
        fig = go.Figure(data=traces, layout=go.Layout(title=title))
        return ToolResult.ok(f"Line chart: {len(y_cols)} series, {len(data)} points",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_line failed: {exc}")


def plot_bar(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        x_col = params.get("x") or params.get("labels")
        y_cols = params.get("y") or params.get("values")
        title = params.get("title", "Bar Chart")
        barmode = params.get("barmode", "group")  # group | stack

        if isinstance(y_cols, str):
            y_cols = [y_cols]
        if not y_cols:
            sample = data[0] if data else {}
            y_cols = [k for k, v in sample.items() if isinstance(v, (int, float))][:3]

        x_vals = _extract_col(data, x_col) if x_col else list(range(len(data)))
        traces = [go.Bar(x=x_vals, y=_extract_col(data, y), name=y) for y in y_cols]
        fig = go.Figure(data=traces, layout=go.Layout(title=title, barmode=barmode))
        return ToolResult.ok(f"Bar chart: {len(y_cols)} series, {len(data)} bars",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_bar failed: {exc}")


def plot_scatter(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        x_col = params.get("x") or params.get("x_axis")
        y_col = params.get("y") or params.get("y_axis")
        color_col = params.get("color")
        size_col = params.get("size")
        title = params.get("title", "Scatter Plot")

        if not (x_col and y_col):
            sample = data[0] if data else {}
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if len(num_cols) < 2:
                return ToolResult.err("Need 2 numeric columns for scatter plot.")
            x_col, y_col = num_cols[0], num_cols[1]

        x_vals = _extract_col(data, x_col)
        y_vals = _extract_col(data, y_col)

        if color_col:
            # Group by color column to create separate traces (handles categorical)
            groups: dict = {}
            for row, xv, yv in zip(data, x_vals, y_vals):
                key = str(row.get(color_col, ""))
                groups.setdefault(key, ([], []))[0].append(xv)
                groups[key][1].append(yv)
            traces = [go.Scatter(x=gx, y=gy, mode="markers", name=k)
                      for k, (gx, gy) in groups.items()]
        else:
            marker = {}
            if size_col:
                marker["size"] = [max(4, _safe_float(v) or 4)
                                  for v in _extract_col(data, size_col)]
            traces = [go.Scatter(x=x_vals, y=y_vals, mode="markers",
                                 name=f"{x_col} vs {y_col}", marker=marker)]

        fig = go.Figure(data=traces,
                        layout=go.Layout(title=title,
                                         xaxis_title=x_col, yaxis_title=y_col))
        return ToolResult.ok(f"Scatter: '{x_col}' vs '{y_col}', {len(data)} points",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_scatter failed: {exc}")


def plot_histogram(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        col = params.get("column") or params.get("x")
        bins = params.get("bins", 20)
        title = params.get("title", "Histogram")

        if not col:
            sample = data[0] if data else {}
            col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not col:
            return ToolResult.err("No numeric column found.")

        vals = [_safe_float(v) for v in _extract_col(data, col)]
        fig = go.Figure(data=[go.Histogram(x=vals, nbinsx=bins, name=col)],
                        layout=go.Layout(title=title, xaxis_title=col))
        return ToolResult.ok(f"Histogram of '{col}', {len(vals)} values, {bins} bins",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_histogram failed: {exc}")


def plot_pie(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        label_col = params.get("labels") or params.get("label_col")
        value_col = params.get("values") or params.get("value_col")
        title = params.get("title", "Pie Chart")
        hole = float(params.get("hole", 0))  # 0=pie, 0.4=donut

        if not (label_col and value_col):
            sample = data[0] if data else {}
            str_cols = [k for k, v in sample.items() if isinstance(v, str)]
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if not (str_cols and num_cols):
                return ToolResult.err("Need a label column and a value column.")
            label_col, value_col = str_cols[0], num_cols[0]

        labels = _extract_col(data, label_col)
        values = [_safe_float(v) for v in _extract_col(data, value_col)]
        fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=hole)],
                        layout=go.Layout(title=title))
        return ToolResult.ok(f"Pie chart: {len(labels)} slices", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_pie failed: {exc}")


def plot_area(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        x_col = params.get("x")
        y_col = params.get("y")
        title = params.get("title", "Area Chart")

        if not y_col:
            sample = data[0] if data else {}
            y_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not y_col:
            return ToolResult.err("No numeric column found.")

        x_vals = _extract_col(data, x_col) if x_col else list(range(len(data)))
        y_vals = _extract_col(data, y_col)
        fig = go.Figure(data=[go.Scatter(x=x_vals, y=y_vals, fill="tozeroy",
                                         mode="lines", name=y_col)],
                        layout=go.Layout(title=title))
        return ToolResult.ok(f"Area chart: '{y_col}', {len(data)} points", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_area failed: {exc}")


def plot_step_line(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        x_col = params.get("x")
        y_col = params.get("y")
        title = params.get("title", "Step Line Chart")

        if not y_col:
            sample = data[0] if data else {}
            y_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not y_col:
            return ToolResult.err("No numeric column found.")

        x_vals = _extract_col(data, x_col) if x_col else list(range(len(data)))
        y_vals = _extract_col(data, y_col)
        fig = go.Figure(
            data=[go.Scatter(x=x_vals, y=y_vals, mode="lines", line={"shape": "hv"},
                             name=y_col)],
            layout=go.Layout(title=title),
        )
        return ToolResult.ok(f"Step line: '{y_col}', {len(data)} steps", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_step_line failed: {exc}")
