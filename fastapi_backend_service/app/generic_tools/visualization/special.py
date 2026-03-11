"""Special chart tools (v15.3).

Tools: plot_candlestick, plot_network, plot_parallel_coords,
       plot_wordcloud, plot_summary_card
"""
from __future__ import annotations

import math
import random
from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _plotly_to_payload, _safe_float


def plot_candlestick(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        time_col = params.get("time") or params.get("x")
        open_col = params.get("open", "open")
        high_col = params.get("high", "high")
        low_col = params.get("low", "low")
        close_col = params.get("close", "close")
        title = params.get("title", "Candlestick Chart")

        if not time_col:
            sample = data[0] if data else {}
            time_col = next(
                (k for k in sample if "time" in k.lower() or "date" in k.lower()), None
            )

        x_vals = [row.get(time_col) for row in data] if time_col else list(range(len(data)))
        fig = go.Figure(data=[go.Candlestick(
            x=x_vals,
            open=[_safe_float(r.get(open_col)) for r in data],
            high=[_safe_float(r.get(high_col)) for r in data],
            low=[_safe_float(r.get(low_col)) for r in data],
            close=[_safe_float(r.get(close_col)) for r in data],
        )], layout=go.Layout(title=title))
        return ToolResult.ok(f"Candlestick: {len(data)} candles", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_candlestick failed: {exc}")


def plot_network(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Simple network graph using Scatter traces (no networkx needed)."""
    try:
        import plotly.graph_objects as go
        import math

        nodes = params.get("nodes", [])
        edges = params.get("edges", [])
        title = params.get("title", "Network Graph")

        if not nodes and data:
            src_col = params.get("source", "source")
            tgt_col = params.get("target", "target")
            all_names = list({str(r.get(src_col, "")) for r in data} |
                             {str(r.get(tgt_col, "")) for r in data})
            nodes = [{"id": n, "label": n} for n in all_names]
            edges = [{"source": str(r.get(src_col, "")),
                      "target": str(r.get(tgt_col, ""))} for r in data]

        # Circular layout
        n = len(nodes)
        pos = {
            node.get("id", str(i)): (
                math.cos(2 * math.pi * i / n),
                math.sin(2 * math.pi * i / n),
            )
            for i, node in enumerate(nodes)
        }

        # Edge traces
        edge_x, edge_y = [], []
        for e in edges:
            src, tgt = e.get("source", ""), e.get("target", "")
            if src in pos and tgt in pos:
                edge_x += [pos[src][0], pos[tgt][0], None]
                edge_y += [pos[src][1], pos[tgt][1], None]

        edge_trace = go.Scatter(x=edge_x, y=edge_y, mode="lines",
                                line={"width": 1, "color": "#888"}, hoverinfo="none")

        node_x = [pos[nd.get("id", "")][0] for nd in nodes if nd.get("id", "") in pos]
        node_y = [pos[nd.get("id", "")][1] for nd in nodes if nd.get("id", "") in pos]
        node_text = [nd.get("label", nd.get("id", "")) for nd in nodes if nd.get("id", "") in pos]

        node_trace = go.Scatter(x=node_x, y=node_y, mode="markers+text",
                                text=node_text, textposition="top center",
                                marker={"size": 12, "color": "#636efa"})

        fig = go.Figure(data=[edge_trace, node_trace],
                        layout=go.Layout(title=title,
                                         showlegend=False,
                                         xaxis={"showgrid": False, "zeroline": False},
                                         yaxis={"showgrid": False, "zeroline": False}))
        return ToolResult.ok(f"Network: {n} nodes, {len(edges)} edges", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_network failed: {exc}")


def plot_parallel_coords(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    try:
        import plotly.graph_objects as go

        axes = params.get("axes")
        color_col = params.get("color")
        title = params.get("title", "Parallel Coordinates")

        if not axes:
            sample = data[0] if data else {}
            axes = [k for k, v in sample.items() if isinstance(v, (int, float))][:6]

        dimensions = [
            {
                "label": ax,
                "values": [_safe_float(row.get(ax, 0)) for row in data],
            }
            for ax in axes
        ]

        color_vals = [_safe_float(row.get(color_col, 0)) for row in data] if color_col else list(range(len(data)))

        fig = go.Figure(data=go.Parcoords(
            line={"color": color_vals, "colorscale": "Viridis"},
            dimensions=dimensions,
        ), layout=go.Layout(title=title))
        return ToolResult.ok(f"Parallel coords: {len(axes)} axes, {len(data)} rows",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_parallel_coords failed: {exc}")


def plot_wordcloud(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Simulate a word cloud using scatter plot with text annotations (no wordcloud lib)."""
    try:
        import plotly.graph_objects as go

        words_dict = params.get("words")
        col = params.get("column")
        title = params.get("title", "Word Cloud")

        if not words_dict and col and data:
            from collections import Counter
            texts = " ".join(str(row.get(col, "")) for row in data).split()
            words_dict = dict(Counter(texts).most_common(60))

        if not words_dict:
            return ToolResult.err("Provide 'words' dict {word: freq} or a text 'column'.")

        max_freq = max(words_dict.values()) or 1
        items = sorted(words_dict.items(), key=lambda x: -x[1])[:60]

        # Random layout with seed for reproducibility
        rng = random.Random(42)
        xs = [rng.uniform(-1, 1) for _ in items]
        ys = [rng.uniform(-1, 1) for _ in items]
        sizes = [int(12 + 36 * (freq / max_freq)) for _, freq in items]
        words = [w for w, _ in items]

        fig = go.Figure(
            data=[go.Scatter(
                x=xs, y=ys, mode="text",
                text=words,
                textfont={"size": sizes,
                          "color": [f"hsl({i * 360 // len(items)},70%,45%)"
                                    for i in range(len(items))]},
            )],
            layout=go.Layout(
                title=title,
                xaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
                yaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
            ),
        )
        return ToolResult.ok(f"Word cloud: {len(items)} words", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_wordcloud failed: {exc}")


def plot_summary_card(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Big-number summary card with delta indicator."""
    try:
        import plotly.graph_objects as go

        title = params.get("title", "Summary")
        value = params.get("value")
        delta = params.get("delta")
        reference = params.get("reference")
        col = params.get("column")

        if value is None and col and data:
            import numpy as np
            vals = [_safe_float(r.get(col)) for r in data]
            vals = [v for v in vals if not math.isnan(v)]
            value = float(np.mean(vals)) if vals else 0

        if value is None and data:
            sample = data[0]
            num_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
            if num_col:
                value = _safe_float(sample[num_col])

        mode = "number"
        delta_dict = None
        if delta is not None:
            mode = "number+delta"
            delta_dict = {"reference": (float(value) - float(delta)) if reference is None else reference}

        fig = go.Figure(data=[go.Indicator(
            mode=mode,
            value=float(value or 0),
            title={"text": title, "font": {"size": 20}},
            delta=delta_dict,
            number={"font": {"size": 48}},
        )])
        fig.update_layout(height=250)
        return ToolResult.ok(f"Summary card: {title} = {value}", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_summary_card failed: {exc}")
