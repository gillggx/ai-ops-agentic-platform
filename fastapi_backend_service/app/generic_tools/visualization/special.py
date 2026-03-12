"""Special chart tools (v15.3+).

Tools: plot_candlestick, plot_network, plot_parallel_coords,
       plot_wordcloud, plot_summary_card,
       plot_missing_heatmap, plot_data_profile, plot_boxplot_with_stats,
       plot_correlation_network, plot_value_counts, plot_time_heatmap,
       plot_rank_change, plot_stacked_pct, plot_bullet_chart,
       plot_control_plan, plot_contribution_waterfall, plot_timeline,
       plot_funnel_conversion, plot_spc_dashboard, plot_eda_overview
"""
from __future__ import annotations

import math
import random
from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _plotly_to_payload, _safe_float, _apply_tight_range

EDA_COLORS = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860", "#DA8BC3", "#8C8C8C"]


def _eda_layout(fig, title, n=None):
    title_text = f"{title} (n={n})" if n is not None else title
    fig.update_layout(
        template="plotly_white",
        title=dict(text=title_text, font=dict(size=14)),
        font=dict(family="Arial, sans-serif", size=11),
        margin=dict(l=60, r=30, t=60, b=60),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(showgrid=True, gridcolor="#f0f0f0", linecolor="#cccccc"),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0", linecolor="#cccccc"),
    )
    return fig


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
        _apply_tight_range(fig, x_vals=x_vals)
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


# ── NEW SPECIAL / EDA PROFILING TOOLS (v15.4) ─────────────────────────────────

def plot_missing_heatmap(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Missing value matrix heatmap."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        columns = params.get("columns")
        title = params.get("title", "Missing Value Heatmap")
        if not columns and data:
            columns = list(data[0].keys())
        n = len(data)
        matrix = []
        for row in data:
            row_missing = [1 if (row.get(c) is None or (isinstance(row.get(c), float) and math.isnan(row.get(c)))) else 0
                           for c in columns]
            matrix.append(row_missing)
        missing_pcts = [round(sum(r[i] for r in matrix) / n * 100, 1) for i in range(len(columns))]
        fig = go.Figure(go.Heatmap(
            z=list(zip(*matrix))[:50],  # limit to 50 columns
            x=list(range(min(n, 200))),
            y=[f"{c} ({missing_pcts[i]}%)" for i, c in enumerate(columns[:50])],
            colorscale=[[0, "#e8f4f8"], [1, "#CC0000"]],
            showscale=False,
        ))
        _eda_layout(fig, title, n)
        total_missing = sum(sum(r) for r in matrix)
        total_cells = n * len(columns)
        return ToolResult.ok(
            f"Missing heatmap: {total_missing}/{total_cells} missing ({total_missing/total_cells*100:.1f}%)",
            _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_missing_heatmap failed: {exc}")


def plot_data_profile(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Multi-stat summary cards grid (one card per column)."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        columns = params.get("columns")
        title = params.get("title", "Data Profile")
        if not columns and data:
            columns = list(data[0].keys())[:12]  # cap at 12
        n = len(data)
        n_cols_display = min(len(columns), 12)
        n_rows_grid = (n_cols_display + 3) // 4
        n_cols_grid = min(4, n_cols_display)
        fig = make_subplots(rows=n_rows_grid, cols=n_cols_grid,
                             subplot_titles=columns[:n_cols_display])
        for idx, col in enumerate(columns[:n_cols_display]):
            row_i = idx // n_cols_grid + 1
            col_i = idx % n_cols_grid + 1
            vals = [row.get(col) for row in data]
            null_count = sum(1 for v in vals if v is None)
            num_vals = [_safe_float(v) for v in vals if v is not None]
            num_vals = [v for v in num_vals if not math.isnan(v)]
            if num_vals:
                fig.add_trace(go.Histogram(x=num_vals, nbinsx=10, name=col,
                                            marker_color=EDA_COLORS[idx % len(EDA_COLORS)],
                                            showlegend=False), row=row_i, col=col_i)
            else:
                str_vals = [str(v) for v in vals if v is not None]
                from collections import Counter
                counts = Counter(str_vals).most_common(5)
                fig.add_trace(go.Bar(x=[c[0] for c in counts], y=[c[1] for c in counts],
                                      name=col, showlegend=False,
                                      marker_color=EDA_COLORS[idx % len(EDA_COLORS)]),
                               row=row_i, col=col_i)
        fig.update_layout(template="plotly_white",
                           title=dict(text=f"{title} (n={n})", font=dict(size=14)),
                           font=dict(family="Arial, sans-serif", size=10),
                           height=200 * n_rows_grid + 80,
                           margin=dict(l=40, r=20, t=80, b=40), showlegend=False)
        return ToolResult.ok(f"Data profile: {len(columns)} columns, n={n}", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_data_profile failed: {exc}")


def plot_boxplot_with_stats(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Box + jitter + mean diamond + outlier labels."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        group_col = params.get("group_col")
        title = params.get("title", "Box Plot with Stats")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        fig = go.Figure()
        rng = random.Random(42)
        if group_col:
            groups = {}
            for row in data:
                g = str(row.get(group_col, ""))
                v = _safe_float(row.get(value_col))
                if not math.isnan(v):
                    groups.setdefault(g, []).append(v)
            for i, (g, vs) in enumerate(groups.items()):
                arr = np.array(vs)
                q1, q3 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75))
                iqr = q3 - q1
                outliers = [v for v in vs if v < q1 - 1.5 * iqr or v > q3 + 1.5 * iqr]
                fig.add_trace(go.Box(y=vs, name=g, boxpoints="outliers",
                                      marker_color=EDA_COLORS[i % len(EDA_COLORS)],
                                      boxmean="sd"))
        else:
            vals = [_safe_float(row.get(value_col)) for row in data
                    if not math.isnan(_safe_float(row.get(value_col)))]
            arr = np.array(vals)
            mean_v = float(np.mean(arr))
            fig.add_trace(go.Box(y=vals, name=value_col, boxpoints="outliers",
                                  marker_color=EDA_COLORS[0], boxmean="sd"))
            fig.add_trace(go.Scatter(y=[mean_v], x=[value_col], mode="markers",
                                      marker=dict(color="#CC0000", size=12, symbol="diamond"),
                                      name="Mean"))
        _eda_layout(fig, title, len(data))
        return ToolResult.ok(f"Box with stats '{value_col}' (n={len(data)})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_boxplot_with_stats failed: {exc}")


def plot_correlation_network(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Network graph of high correlations between features."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        feature_cols = params.get("feature_cols") or params.get("columns")
        threshold = float(params.get("threshold", 0.5))
        title = params.get("title", "Correlation Network")
        if not feature_cols:
            sample = data[0] if data else {}
            feature_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
        if len(feature_cols) < 2:
            return ToolResult.err("Need at least 2 features.")
        matrix = {c: [_safe_float(row.get(c)) for row in data] for c in feature_cols}
        n_feat = len(feature_cols)
        corrs = []
        for i, ca in enumerate(feature_cols):
            for j, cb in enumerate(feature_cols):
                if i < j:
                    a = np.array([v for v in matrix[ca] if not math.isnan(v)])
                    b = np.array([v for v in matrix[cb] if not math.isnan(v)])
                    min_len = min(len(a), len(b))
                    if min_len > 1:
                        r = float(np.corrcoef(a[:min_len], b[:min_len])[0, 1])
                        if abs(r) >= threshold:
                            corrs.append((ca, cb, r))
        pos = {c: (math.cos(2 * math.pi * i / n_feat), math.sin(2 * math.pi * i / n_feat))
               for i, c in enumerate(feature_cols)}
        edge_x, edge_y, edge_colors = [], [], []
        for ca, cb, r in corrs:
            edge_x += [pos[ca][0], pos[cb][0], None]
            edge_y += [pos[ca][1], pos[cb][1], None]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines",
                                  line=dict(color="#aaaaaa", width=1), hoverinfo="none"))
        fig.add_trace(go.Scatter(
            x=[pos[c][0] for c in feature_cols],
            y=[pos[c][1] for c in feature_cols],
            mode="markers+text", text=feature_cols,
            textposition="top center",
            marker=dict(size=12, color=EDA_COLORS[0]),
        ))
        _eda_layout(fig, title, len(data))
        fig.update_layout(xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                           yaxis=dict(showgrid=False, zeroline=False, showticklabels=False))
        return ToolResult.ok(
            f"Correlation network: {len(corrs)} edges (threshold={threshold})",
            _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_correlation_network failed: {exc}")


def plot_value_counts(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Horizontal bar of top-N value counts."""
    try:
        import plotly.graph_objects as go
        from collections import Counter
        cat_col = params.get("cat_col") or params.get("column")
        top_n = int(params.get("top_n", 15))
        title = params.get("title", "Value Counts")
        if not cat_col:
            sample = data[0] if data else {}
            cat_col = next((k for k, v in sample.items() if isinstance(v, str)), None)
        if not cat_col:
            return ToolResult.err("No categorical column found.")
        counts = Counter(str(row.get(cat_col, "")) for row in data).most_common(top_n)
        labels = [c[0] for c in counts][::-1]
        values = [c[1] for c in counts][::-1]
        total = sum(c[1] for c in counts)
        fig = go.Figure(go.Bar(
            x=values, y=labels, orientation="h",
            marker_color=EDA_COLORS[0],
            text=[f"{v} ({v/total*100:.1f}%)" for v in values],
            textposition="outside",
        ))
        _eda_layout(fig, title, len(data))
        fig.update_layout(xaxis_title="Count", yaxis_title=cat_col)
        return ToolResult.ok(f"Value counts '{cat_col}' top-{top_n} (n={len(data)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_value_counts failed: {exc}")


def plot_time_heatmap(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Calendar/time-of-day heatmap grid."""
    try:
        import pandas as pd
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        time_col = params.get("time_col")
        title = params.get("title", "Time Heatmap")
        if not (value_col and time_col):
            return ToolResult.err("'value_col' and 'time_col' required.")
        df = pd.DataFrame(data)
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        df = df.dropna(subset=[time_col, value_col])
        df["hour"] = df[time_col].dt.hour
        df["dayofweek"] = df[time_col].dt.day_name()
        days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        pivot = df.groupby(["dayofweek", "hour"])[value_col].mean().unstack(fill_value=0)
        pivot = pivot.reindex([d for d in days_order if d in pivot.index])
        fig = go.Figure(go.Heatmap(
            z=pivot.values.tolist(),
            x=[str(h) for h in pivot.columns.tolist()],
            y=pivot.index.tolist(),
            colorscale="YlOrRd",
            text=[[f"{v:.2f}" for v in row] for row in pivot.values],
        ))
        _eda_layout(fig, title, len(df))
        fig.update_layout(xaxis_title="Hour of Day", yaxis_title="Day of Week")
        return ToolResult.ok(f"Time heatmap '{value_col}' (n={len(df)})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_time_heatmap failed: {exc}")


def plot_rank_change(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Rank change over time for multiple groups (bump chart)."""
    try:
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        time_col = params.get("time_col")
        group_col = params.get("group_col")
        title = params.get("title", "Rank Change Over Time")
        if not (value_col and time_col and group_col):
            return ToolResult.err("'value_col', 'time_col', and 'group_col' required.")
        periods = sorted(set(str(row.get(time_col, "")) for row in data))
        group_time = {}
        for row in data:
            g = str(row.get(group_col, ""))
            t = str(row.get(time_col, ""))
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                group_time.setdefault(g, {})[t] = v
        fig = go.Figure()
        for i, (g, time_vals) in enumerate(group_time.items()):
            xs, ys = [], []
            for t in periods:
                if t in time_vals:
                    vals_at_t = {gg: tv.get(t, 0) for gg, tv in group_time.items() if t in tv}
                    sorted_groups = sorted(vals_at_t.items(), key=lambda x: -x[1])
                    rank = next((r + 1 for r, (gg, _) in enumerate(sorted_groups) if gg == g), None)
                    if rank:
                        xs.append(periods.index(t))
                        ys.append(rank)
            color = EDA_COLORS[i % len(EDA_COLORS)]
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers+text",
                                      text=[g if j == len(ys) - 1 else "" for j in range(len(ys))],
                                      textposition="middle right",
                                      line=dict(color=color, width=2),
                                      marker=dict(size=8, color=color), name=g))
        _eda_layout(fig, title, len(data))
        fig.update_layout(
            xaxis=dict(tickvals=list(range(len(periods))), ticktext=periods),
            yaxis=dict(autorange="reversed", title="Rank"),
        )
        return ToolResult.ok(f"Rank change '{value_col}' (n={len(data)})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_rank_change failed: {exc}")


def plot_stacked_pct(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """100% stacked bar chart."""
    try:
        import plotly.graph_objects as go
        from collections import defaultdict
        value_col = params.get("value_col") or params.get("column")
        group_col = params.get("group_col")
        time_col = params.get("time_col")
        title = params.get("title", "100% Stacked Bar")
        if not (group_col and time_col):
            return ToolResult.err("'group_col' and 'time_col' required.")
        periods = sorted(set(str(row.get(time_col, "")) for row in data))
        groups = sorted(set(str(row.get(group_col, "")) for row in data))
        time_group = defaultdict(lambda: defaultdict(float))
        for row in data:
            t = str(row.get(time_col, ""))
            g = str(row.get(group_col, ""))
            v = _safe_float(row.get(value_col, 1))
            if not math.isnan(v):
                time_group[t][g] += v
        fig = go.Figure()
        for i, g in enumerate(groups):
            raw = [time_group[t].get(g, 0) for t in periods]
            totals = [sum(time_group[t].values()) or 1 for t in periods]
            pcts = [v / tot * 100 for v, tot in zip(raw, totals)]
            fig.add_trace(go.Bar(x=periods, y=pcts, name=g,
                                  marker_color=EDA_COLORS[i % len(EDA_COLORS)]))
        _eda_layout(fig, title, len(data))
        fig.update_layout(barmode="stack", yaxis_title="Percentage (%)")
        return ToolResult.ok(f"100% stacked bar '{group_col}' by '{time_col}' (n={len(data)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_stacked_pct failed: {exc}")


def plot_bullet_chart(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Bullet chart: actual vs target vs range."""
    try:
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        target_col = params.get("target_col")
        label_col = params.get("label_col")
        title = params.get("title", "Bullet Chart")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        fig = go.Figure()
        for i, row in enumerate(data[:15]):
            actual = _safe_float(row.get(value_col))
            target = _safe_float(row.get(target_col)) if target_col else None
            label = str(row.get(label_col, f"Item {i+1}")) if label_col else f"Item {i+1}"
            y_pos = i
            fig.add_shape(type="rect", x0=0, x1=actual, y0=y_pos - 0.3, y1=y_pos + 0.3,
                           fillcolor=EDA_COLORS[0], opacity=0.8, line_width=0)
            if target and not math.isnan(target):
                fig.add_shape(type="line", x0=target, x1=target,
                               y0=y_pos - 0.4, y1=y_pos + 0.4,
                               line=dict(color="#CC0000", width=3))
            fig.add_annotation(x=0, y=y_pos, text=f" {label}",
                                showarrow=False, xanchor="left", font=dict(size=10))
        _eda_layout(fig, title, len(data))
        fig.update_layout(
            xaxis_title=value_col,
            yaxis=dict(showticklabels=False, showgrid=False),
            height=max(200, len(data[:15]) * 45 + 80),
        )
        return ToolResult.ok(f"Bullet chart '{value_col}' (n={min(len(data), 15)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_bullet_chart failed: {exc}")


def plot_control_plan(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Control chart matrix for multiple metrics (subplots)."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        value_cols = params.get("value_cols") or params.get("columns")
        ucl_cols = params.get("ucl_cols", [])
        title = params.get("title", "Control Plan Dashboard")
        if not value_cols:
            sample = data[0] if data else {}
            value_cols = [k for k, v in sample.items() if isinstance(v, (int, float))][:4]
        n_metrics = len(value_cols)
        fig = make_subplots(rows=n_metrics, cols=1,
                             subplot_titles=[f"{c} Control Chart" for c in value_cols])
        for i, col in enumerate(value_cols, 1):
            vals = np.array([_safe_float(row.get(col)) for row in data])
            cl = float(np.nanmean(vals))
            sigma = float(np.nanstd(vals, ddof=1)) or 1.0
            ucl = cl + 3 * sigma
            lcl = cl - 3 * sigma
            if ucl_cols and len(ucl_cols) >= i:
                ucl_vals = [_safe_float(row.get(ucl_cols[i-1])) for row in data]
                fig.add_trace(go.Scatter(x=list(range(len(ucl_vals))), y=ucl_vals,
                                          mode="lines", line=dict(color="#CC0000", dash="dash"),
                                          name="UCL"), row=i, col=1)
            else:
                fig.add_hline(y=ucl, line_color="#CC0000", line_dash="dash", row=i, col=1,
                               annotation_text=f"UCL={ucl:.3f}")
                fig.add_hline(y=lcl, line_color="#CC0000", line_dash="dash", row=i, col=1)
                fig.add_hline(y=cl, line_color="#00AA00", line_dash="dot", row=i, col=1,
                               annotation_text=f"CL={cl:.3f}")
            fig.add_trace(go.Scatter(x=list(range(len(vals))), y=list(vals),
                                      mode="lines+markers",
                                      marker=dict(color=EDA_COLORS[i % len(EDA_COLORS)], size=4),
                                      name=col), row=i, col=1)
        fig.update_layout(template="plotly_white",
                           title=dict(text=f"{title} (n={len(data)})", font=dict(size=14)),
                           font=dict(family="Arial, sans-serif", size=10),
                           height=250 * n_metrics + 80,
                           margin=dict(l=60, r=30, t=60, b=40), showlegend=False)
        return ToolResult.ok(f"Control plan: {n_metrics} metrics (n={len(data)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_control_plan failed: {exc}")


def plot_contribution_waterfall(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Waterfall showing each group's contribution."""
    try:
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        group_col = params.get("group_col")
        title = params.get("title", "Contribution Waterfall")
        if not (value_col and group_col):
            return ToolResult.err("'value_col' and 'group_col' required.")
        groups = {}
        for row in data:
            g = str(row.get(group_col, ""))
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                groups[g] = groups.get(g, 0.0) + v
        sorted_groups = sorted(groups.items(), key=lambda x: -abs(x[1]))
        labels = [g for g, _ in sorted_groups] + ["Total"]
        values = [v for _, v in sorted_groups] + [sum(v for _, v in sorted_groups)]
        measures = ["relative"] * len(sorted_groups) + ["total"]
        colors = [EDA_COLORS[0] if v >= 0 else EDA_COLORS[3] for v in values]
        fig = go.Figure(go.Waterfall(
            x=labels, y=values, measure=measures,
            increasing=dict(marker_color=EDA_COLORS[0]),
            decreasing=dict(marker_color=EDA_COLORS[3]),
            totals=dict(marker_color=EDA_COLORS[2]),
            connector=dict(line=dict(color="#aaaaaa")),
        ))
        _eda_layout(fig, title, len(data))
        return ToolResult.ok(f"Contribution waterfall '{value_col}' (n={len(data)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_contribution_waterfall failed: {exc}")


def plot_timeline(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Horizontal timeline with events."""
    try:
        import plotly.graph_objects as go
        event_col = params.get("event_col")
        start_col = params.get("start_col")
        end_col = params.get("end_col")
        title = params.get("title", "Timeline")
        if not (event_col and start_col):
            return ToolResult.err("'event_col' and 'start_col' required.")
        fig = go.Figure()
        for i, row in enumerate(data):
            event = str(row.get(event_col, f"Event {i}"))
            start = row.get(start_col)
            end = row.get(end_col, start)
            color = EDA_COLORS[i % len(EDA_COLORS)]
            fig.add_trace(go.Scatter(
                x=[start, end], y=[i, i],
                mode="lines+markers+text",
                text=[event, ""],
                textposition="top center",
                line=dict(color=color, width=4),
                marker=dict(color=color, size=10),
                name=event, showlegend=False,
            ))
        _eda_layout(fig, title, len(data))
        fig.update_layout(
            yaxis=dict(showticklabels=False, showgrid=False),
            xaxis_title="Time",
        )
        return ToolResult.ok(f"Timeline: {len(data)} events", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_timeline failed: {exc}")


def plot_funnel_conversion(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Funnel conversion chart with % drop labels (EDA version)."""
    try:
        import plotly.graph_objects as go
        stage_col = params.get("stage_col") or params.get("stage")
        count_col = params.get("count_col") or params.get("count")
        title = params.get("title", "Funnel Conversion")
        if not (stage_col and count_col):
            sample = data[0] if data else {}
            str_cols = [k for k, v in sample.items() if isinstance(v, str)]
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            stage_col = stage_col or (str_cols[0] if str_cols else None)
            count_col = count_col or (num_cols[0] if num_cols else None)
        if not (stage_col and count_col):
            return ToolResult.err("'stage_col' and 'count_col' required.")
        stages = [str(row.get(stage_col, "")) for row in data]
        counts = [_safe_float(row.get(count_col, 0)) for row in data]
        texts = []
        for i, (s, c) in enumerate(zip(stages, counts)):
            if i == 0:
                texts.append(f"{int(c)}")
            else:
                prev = counts[i - 1]
                drop_pct = round((prev - c) / prev * 100, 1) if prev > 0 else 0
                texts.append(f"{int(c)} (-{drop_pct}%)")
        fig = go.Figure(go.Funnel(
            y=stages, x=counts,
            text=texts, textposition="inside",
            marker=dict(color=EDA_COLORS[:len(stages)]),
        ))
        _eda_layout(fig, title, len(data))
        return ToolResult.ok(f"Funnel conversion '{stage_col}' ({len(data)} stages)",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_funnel_conversion failed: {exc}")


def plot_spc_dashboard(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """4-panel SPC dashboard: run chart / histogram / box / stats table."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        value_col = params.get("value_col") or params.get("column")
        ucl = params.get("ucl")
        lcl = params.get("lcl")
        title = params.get("title", "SPC Dashboard")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data if not math.isnan(_safe_float(row.get(value_col)))]
        arr = np.array(vals)
        n = len(arr)
        cl = float(np.mean(arr))
        sigma = float(np.std(arr, ddof=1)) or 1.0
        ucl_val = float(ucl) if ucl else cl + 3 * sigma
        lcl_val = float(lcl) if lcl else cl - 3 * sigma
        idx = list(range(n))
        ooc = [i for i in range(n) if arr[i] > ucl_val or arr[i] < lcl_val]
        fig = make_subplots(rows=2, cols=2,
                             specs=[[{"type": "xy"}, {"type": "xy"}],
                                    [{"type": "xy"}, {"type": "table"}]],
                             subplot_titles=["Run Chart", "Histogram", "Box Plot", "Statistics"])
        # Run chart
        fig.add_trace(go.Scatter(x=idx, y=list(arr), mode="lines+markers",
                                  marker=dict(size=4, color=EDA_COLORS[0]), name="Values"), row=1, col=1)
        for val, clr, dash in [(ucl_val, "#CC0000", "dash"), (cl, "#00AA00", "dot"), (lcl_val, "#CC0000", "dash")]:
            fig.add_hline(y=val, line_color=clr, line_dash=dash, row=1, col=1)
        if ooc:
            ooc_y = [arr[i] for i in ooc]
            fig.add_trace(go.Scatter(x=ooc, y=ooc_y, mode="markers",
                                      marker=dict(color="#CC0000", size=8, symbol="x"),
                                      name="OOC"), row=1, col=1)
        # Histogram
        fig.add_trace(go.Histogram(x=list(arr), nbinsx=20, name="Dist",
                                    marker_color=EDA_COLORS[0], opacity=0.7), row=1, col=2)
        for val, clr in [(ucl_val, "#CC0000"), (lcl_val, "#CC0000"), (cl, "#00AA00")]:
            fig.add_vline(x=val, line_color=clr, line_dash="dash", row=1, col=2)
        # Box
        fig.add_trace(go.Box(y=list(arr), name=value_col, boxmean="sd",
                              marker_color=EDA_COLORS[0], boxpoints="outliers"), row=2, col=1)
        # Stats table
        p25, p50, p75, p95 = float(np.percentile(arr, 25)), float(np.percentile(arr, 50)), float(np.percentile(arr, 75)), float(np.percentile(arr, 95))
        cp = (ucl_val - lcl_val) / (6 * sigma) if sigma > 0 else 0
        cpk = min((ucl_val - cl) / (3 * sigma), (cl - lcl_val) / (3 * sigma)) if sigma > 0 else 0
        stat_labels = ["N", "Mean", "Std", "P25", "P50", "P75", "P95", "UCL", "LCL", "OOC", "Cp", "Cpk"]
        stat_vals = [str(n), f"{cl:.4f}", f"{sigma:.4f}", f"{p25:.4f}", f"{p50:.4f}", f"{p75:.4f}",
                     f"{p95:.4f}", f"{ucl_val:.4f}", f"{lcl_val:.4f}", str(len(ooc)),
                     f"{cp:.3f}", f"{cpk:.3f}"]
        fig.add_trace(go.Table(
            header=dict(values=["Statistic", "Value"],
                        fill_color=EDA_COLORS[0], font=dict(color="white", size=11)),
            cells=dict(values=[stat_labels, stat_vals],
                       fill_color=[["white", "#f8f8f8"] * 6],
                       font=dict(size=10)),
        ), row=2, col=2)
        fig.update_layout(template="plotly_white",
                           title=dict(text=f"{title} '{value_col}' (n={n})", font=dict(size=14)),
                           font=dict(family="Arial, sans-serif", size=10),
                           height=600, margin=dict(l=60, r=30, t=60, b=40), showlegend=False)
        return ToolResult.ok(f"SPC dashboard '{value_col}' (n={n}, OOC={len(ooc)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_spc_dashboard failed: {exc}")


def plot_eda_overview(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Full EDA overview: distribution + box + QQ + stats in one figure."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        value_col = params.get("value_col") or params.get("column")
        title = params.get("title", "EDA Overview")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data if not math.isnan(_safe_float(row.get(value_col)))]
        arr = np.array(vals)
        n = len(arr)
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1)) or 1.0
        median = float(np.median(arr))
        fig = make_subplots(rows=2, cols=2,
                             specs=[[{"type": "xy"}, {"type": "xy"}],
                                    [{"type": "xy"}, {"type": "table"}]],
                             subplot_titles=["Distribution", "Box Plot", "Q-Q Plot", "Statistics"])
        # Histogram
        fig.add_trace(go.Histogram(x=list(arr), nbinsx=25, name="Distribution",
                                    marker_color=EDA_COLORS[0], opacity=0.7), row=1, col=1)
        fig.add_vline(x=mean, line_color="#CC0000", line_dash="dash",
                       annotation_text=f"μ={mean:.3f}", row=1, col=1)
        fig.add_vline(x=median, line_color="#00AA00", line_dash="dot",
                       annotation_text=f"M={median:.3f}", row=1, col=1)
        # Box plot
        fig.add_trace(go.Box(y=list(arr), name=value_col, boxmean="sd",
                              marker_color=EDA_COLORS[0], boxpoints="outliers"), row=1, col=2)
        # Q-Q plot
        sorted_vals = sorted(vals)
        probs = [(i - 0.5) / n for i in range(1, n + 1)]
        try:
            theoretical = [math.sqrt(2) * _erfinv_approx(2 * p - 1) for p in probs]
        except Exception:
            theoretical = list(range(n))
        fig.add_trace(go.Scatter(x=theoretical, y=sorted_vals, mode="markers",
                                  marker=dict(color=EDA_COLORS[0], size=3), name="Q-Q"), row=2, col=1)
        if len(theoretical) >= 2:
            slope = (sorted_vals[-1] - sorted_vals[0]) / (theoretical[-1] - theoretical[0] + 1e-9)
            intercept = sorted_vals[0] - slope * theoretical[0]
            line_y = [slope * t + intercept for t in [theoretical[0], theoretical[-1]]]
            fig.add_trace(go.Scatter(x=[theoretical[0], theoretical[-1]], y=line_y,
                                      mode="lines", line=dict(color="#CC0000", dash="dash"),
                                      name="Normal line"), row=2, col=1)
        # Stats table
        skew = float(np.mean(((arr - mean) / std) ** 3))
        kurt = float(np.mean(((arr - mean) / std) ** 4)) - 3
        p25, p75, p95 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75)), float(np.percentile(arr, 95))
        stat_labels = ["N", "Mean", "Median", "Std", "Min", "Max", "P25", "P75", "P95", "Skewness", "Kurtosis"]
        stat_vals = [str(n), f"{mean:.4f}", f"{median:.4f}", f"{std:.4f}",
                     f"{float(arr.min()):.4f}", f"{float(arr.max()):.4f}",
                     f"{p25:.4f}", f"{p75:.4f}", f"{p95:.4f}", f"{skew:.3f}", f"{kurt:.3f}"]
        fig.add_trace(go.Table(
            header=dict(values=["Statistic", "Value"],
                        fill_color=EDA_COLORS[0], font=dict(color="white", size=11)),
            cells=dict(values=[stat_labels, stat_vals],
                       fill_color=[["white", "#f8f8f8"] * 6], font=dict(size=10)),
        ), row=2, col=2)
        fig.update_layout(template="plotly_white",
                           title=dict(text=f"{title}: '{value_col}' (n={n})", font=dict(size=14)),
                           font=dict(family="Arial, sans-serif", size=10),
                           height=600, margin=dict(l=60, r=30, t=60, b=40), showlegend=False)
        return ToolResult.ok(f"EDA overview '{value_col}' (n={n})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_eda_overview failed: {exc}")


def _erfinv_approx(x):
    """Approximate inverse error function."""
    a = 0.147
    try:
        lnterm = math.log(max(1 - x * x, 1e-12))
        part1 = 2 / (math.pi * a) + lnterm / 2
        sign = 1 if x >= 0 else -1
        return sign * math.sqrt(max(0, math.sqrt(part1 ** 2 - lnterm / a) - part1))
    except Exception:
        return 0.0
