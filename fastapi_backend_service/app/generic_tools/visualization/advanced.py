"""Advanced chart tools (v15.3).

Tools: plot_sankey, plot_treemap, plot_sunburst, plot_waterfall,
       plot_funnel, plot_gauge, plot_bubble, plot_dual_axis
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _plotly_to_payload, _safe_float


def plot_sankey(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        nodes = params.get("nodes", [])
        links = params.get("links", [])
        title = params.get("title", "Sankey Diagram")

        if not (nodes and links) and data:
            # Auto-build from data with source/target columns
            src_col = params.get("source", "source")
            tgt_col = params.get("target", "target")
            val_col = params.get("value", "value")
            all_names = list({str(row.get(src_col, "")) for row in data} |
                             {str(row.get(tgt_col, "")) for row in data})
            idx = {n: i for i, n in enumerate(all_names)}
            nodes = [{"label": n} for n in all_names]
            links = [{"source": idx[str(r.get(src_col, ""))],
                      "target": idx[str(r.get(tgt_col, ""))],
                      "value": _safe_float(r.get(val_col, 1))} for r in data]

        node_labels = [n.get("label", str(i)) for i, n in enumerate(nodes)]
        fig = go.Figure(data=[go.Sankey(
            node={"label": node_labels},
            link={"source": [l["source"] for l in links],
                  "target": [l["target"] for l in links],
                  "value": [l.get("value", 1) for l in links]},
        )], layout=go.Layout(title=title))
        return ToolResult.ok(f"Sankey: {len(nodes)} nodes, {len(links)} links",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_sankey failed: {exc}")


def plot_treemap(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        label_col = params.get("label") or params.get("labels")
        parent_col = params.get("parent") or params.get("parents")
        value_col = params.get("value") or params.get("values")
        title = params.get("title", "Treemap")

        if not (label_col and value_col) and data:
            sample = data[0]
            str_cols = [k for k, v in sample.items() if isinstance(v, str)]
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            label_col = label_col or (str_cols[0] if str_cols else None)
            value_col = value_col or (num_cols[0] if num_cols else None)

        if not (label_col and value_col):
            return ToolResult.err("Need 'label' and 'value' columns.")

        labels = [str(row.get(label_col, "")) for row in data]
        values = [_safe_float(row.get(value_col, 0)) for row in data]
        parents = [str(row.get(parent_col, "")) for row in data] if parent_col else [""] * len(data)

        fig = go.Figure(data=[go.Treemap(labels=labels, parents=parents, values=values)],
                        layout=go.Layout(title=title))
        return ToolResult.ok(f"Treemap: {len(labels)} nodes", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_treemap failed: {exc}")


def plot_sunburst(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        label_col = params.get("label") or params.get("labels")
        parent_col = params.get("parent") or params.get("parents")
        value_col = params.get("value") or params.get("values")
        title = params.get("title", "Sunburst Chart")

        if not label_col and data:
            sample = data[0]
            str_cols = [k for k, v in sample.items() if isinstance(v, str)]
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            label_col = str_cols[0] if str_cols else None
            value_col = value_col or (num_cols[0] if num_cols else None)

        if not label_col:
            return ToolResult.err("Need 'label' column.")

        labels = [str(row.get(label_col, "")) for row in data]
        values = [_safe_float(row.get(value_col, 1)) for row in data] if value_col else [1] * len(data)
        parents = [str(row.get(parent_col, "")) for row in data] if parent_col else [""] * len(data)

        fig = go.Figure(data=[go.Sunburst(labels=labels, parents=parents, values=values)],
                        layout=go.Layout(title=title))
        return ToolResult.ok(f"Sunburst: {len(labels)} nodes", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_sunburst failed: {exc}")


def plot_waterfall(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        x_col = params.get("x") or params.get("steps")
        y_col = params.get("y") or params.get("values")
        title = params.get("title", "Waterfall Chart")

        if not (x_col and y_col) and data:
            sample = data[0]
            str_cols = [k for k, v in sample.items() if isinstance(v, str)]
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            x_col = x_col or (str_cols[0] if str_cols else None)
            y_col = y_col or (num_cols[0] if num_cols else None)

        x_vals = [row.get(x_col) for row in data] if x_col else list(range(len(data)))
        y_vals = [_safe_float(row.get(y_col, 0)) for row in data] if y_col else []
        measures = ["relative"] * len(y_vals)
        if measures:
            measures[-1] = "total"

        fig = go.Figure(data=[go.Waterfall(x=x_vals, y=y_vals, measure=measures,
                                            connector={"line": {"color": "#636efa"}})],
                        layout=go.Layout(title=title))
        return ToolResult.ok(f"Waterfall: {len(x_vals)} steps", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_waterfall failed: {exc}")


def plot_funnel(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        stage_col = params.get("stages") or params.get("x")
        value_col = params.get("values") or params.get("y")
        title = params.get("title", "Funnel Chart")

        if not (stage_col and value_col) and data:
            sample = data[0]
            str_cols = [k for k, v in sample.items() if isinstance(v, str)]
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            stage_col = stage_col or (str_cols[0] if str_cols else None)
            value_col = value_col or (num_cols[0] if num_cols else None)

        stages = [str(row.get(stage_col, "")) for row in data] if stage_col else []
        values = [_safe_float(row.get(value_col, 0)) for row in data] if value_col else []

        fig = go.Figure(data=[go.Funnel(y=stages, x=values)],
                        layout=go.Layout(title=title))
        return ToolResult.ok(f"Funnel: {len(stages)} stages", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_funnel failed: {exc}")


def plot_gauge(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        value = params.get("value")
        min_val = float(params.get("min", 0))
        max_val = float(params.get("max", 100))
        title = params.get("title", "Gauge")
        threshold = params.get("threshold")

        if value is None and data:
            col = params.get("column")
            if not col:
                sample = data[0]
                col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
            if col:
                import numpy as np
                value = float(np.mean([_safe_float(r.get(col)) for r in data]))

        if value is None:
            return ToolResult.err("'value' param required.")

        gauge_dict = {
            "axis": {"range": [min_val, max_val]},
            "bar": {"color": "#636efa"},
            "steps": [
                {"range": [min_val, (max_val - min_val) * 0.6 + min_val], "color": "#d4efdf"},
                {"range": [(max_val - min_val) * 0.6 + min_val,
                           (max_val - min_val) * 0.8 + min_val], "color": "#fdebd0"},
                {"range": [(max_val - min_val) * 0.8 + min_val, max_val], "color": "#fadbd8"},
            ],
        }
        if threshold is not None:
            gauge_dict["threshold"] = {
                "line": {"color": "red", "width": 4},
                "thickness": 0.75, "value": threshold,
            }

        fig = go.Figure(data=[go.Indicator(
            mode="gauge+number+delta", value=float(value),
            title={"text": title}, gauge=gauge_dict,
        )])
        return ToolResult.ok(f"Gauge: value={value:.4f} / range [{min_val}, {max_val}]",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_gauge failed: {exc}")


def plot_bubble(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        x_col = params.get("x")
        y_col = params.get("y")
        size_col = params.get("size")
        color_col = params.get("color")
        title = params.get("title", "Bubble Chart")

        if not (x_col and y_col):
            sample = data[0] if data else {}
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if len(num_cols) < 2:
                return ToolResult.err("Need at least 2 numeric columns.")
            x_col = x_col or num_cols[0]
            y_col = y_col or num_cols[1]
            size_col = size_col or (num_cols[2] if len(num_cols) > 2 else None)

        x_vals = [_safe_float(r.get(x_col)) for r in data]
        y_vals = [_safe_float(r.get(y_col)) for r in data]
        size_vals = [max(5, _safe_float(r.get(size_col, 10)) * 2) for r in data] if size_col else None

        marker = {"size": size_vals or 10}
        if color_col:
            marker["color"] = [_safe_float(r.get(color_col)) for r in data]
            marker["colorscale"] = "Viridis"
            marker["showscale"] = True

        fig = go.Figure(
            data=[go.Scatter(x=x_vals, y=y_vals, mode="markers",
                             marker=marker, name=title)],
            layout=go.Layout(title=title, xaxis_title=x_col, yaxis_title=y_col),
        )
        return ToolResult.ok(f"Bubble: '{x_col}' vs '{y_col}', {len(data)} bubbles",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_bubble failed: {exc}")


def plot_dual_axis(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        x_col = params.get("x")
        y1_col = params.get("y1")
        y2_col = params.get("y2")
        title = params.get("title", "Dual Axis Chart")

        if not (y1_col and y2_col):
            sample = data[0] if data else {}
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if len(num_cols) < 2:
                return ToolResult.err("Need 2 numeric columns for dual axis.")
            y1_col = y1_col or num_cols[0]
            y2_col = y2_col or num_cols[1]

        x_vals = [row.get(x_col) for row in data] if x_col else list(range(len(data)))

        fig = go.Figure()
        fig.add_trace(go.Bar(x=x_vals, y=[_safe_float(r.get(y1_col)) for r in data],
                             name=y1_col))
        fig.add_trace(go.Scatter(x=x_vals, y=[_safe_float(r.get(y2_col)) for r in data],
                                 name=y2_col, yaxis="y2", mode="lines+markers"))
        fig.update_layout(
            title=title,
            yaxis={"title": y1_col},
            yaxis2={"title": y2_col, "overlaying": "y", "side": "right"},
        )
        return ToolResult.ok(f"Dual axis: '{y1_col}' (bar) + '{y2_col}' (line)",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_dual_axis failed: {exc}")
