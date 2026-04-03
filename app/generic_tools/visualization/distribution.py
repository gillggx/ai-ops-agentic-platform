"""Distribution & comparison chart tools (v15.3+).

Tools: plot_box, plot_violin, plot_heatmap, plot_radar, plot_error_bar,
       plot_qq, plot_kde, plot_ecdf, plot_probability_plot, plot_residuals,
       plot_ridge, plot_strip, plot_correlation_matrix, plot_scatter_matrix,
       plot_mean_ci, plot_bland_altman, plot_distribution_compare,
       plot_lollipop, plot_dumbbell, plot_diverging_bar
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _plotly_to_payload, _safe_float, _apply_tight_range

EDA_COLORS = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860", "#DA8BC3", "#8C8C8C"]


def _eda_layout(fig, title, n=None):
    """Apply standard EDA layout to a figure."""
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
        _apply_tight_range(fig, x_vals=x_vals, y_vals_list=[y_vals])
        return ToolResult.ok(f"Error bar: '{y_col}', {len(data)} points", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_error_bar failed: {exc}")


# ── NEW DISTRIBUTION TOOLS (v15.4) ────────────────────────────────────────────

def plot_qq(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Q-Q normality plot."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        title = params.get("title", "Q-Q Plot")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = sorted([_safe_float(row.get(value_col)) for row in data
                       if not math.isnan(_safe_float(row.get(value_col)))])
        n = len(vals)
        if n < 4:
            return ToolResult.err("Need at least 4 data points.")
        probs = [(i - 0.5) / n for i in range(1, n + 1)]
        theoretical = [math.sqrt(2) * _erfinv(2 * p - 1) for p in probs]
        mean_v, std_v = float(np.mean(vals)), float(np.std(vals, ddof=1))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=theoretical, y=vals, mode="markers",
                                 marker=dict(color=EDA_COLORS[0], size=5, opacity=0.7),
                                 name="Data quantiles"))
        lo = theoretical[0] * std_v + mean_v
        hi = theoretical[-1] * std_v + mean_v
        fig.add_trace(go.Scatter(x=[theoretical[0], theoretical[-1]], y=[lo, hi],
                                 mode="lines", line=dict(color="#CC0000", dash="dash"),
                                 name="Normal line"))
        _eda_layout(fig, title, n)
        fig.update_layout(xaxis_title="Theoretical Quantiles", yaxis_title="Sample Quantiles")
        return ToolResult.ok(f"Q-Q plot '{value_col}' (n={n})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_qq failed: {exc}")


def _erfinv(x):
    """Approximate inverse error function."""
    a = 0.147
    lnterm = math.log(1 - x * x + 1e-12)
    part1 = 2 / (math.pi * a) + lnterm / 2
    sign = 1 if x >= 0 else -1
    return sign * math.sqrt(math.sqrt(part1 ** 2 - lnterm / a) - part1)


def plot_kde(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Kernel density estimate with rug ticks."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        group_col = params.get("group_col")
        title = params.get("title", "KDE Plot")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")

        def _kde(arr, x_grid, bw=None):
            n = len(arr)
            bw = bw or (1.06 * float(np.std(arr, ddof=1)) * n ** (-0.2))
            kde = np.zeros(len(x_grid))
            for xi in arr:
                kde += np.exp(-0.5 * ((x_grid - xi) / bw) ** 2)
            kde /= (n * bw * math.sqrt(2 * math.pi))
            return kde

        fig = go.Figure()
        if group_col:
            groups = {}
            for row in data:
                g = str(row.get(group_col, ""))
                v = _safe_float(row.get(value_col))
                if not math.isnan(v):
                    groups.setdefault(g, []).append(v)
            for i, (g, vs) in enumerate(groups.items()):
                arr = np.array(vs)
                xg = np.linspace(arr.min(), arr.max(), 200)
                kde = _kde(arr, xg)
                color = EDA_COLORS[i % len(EDA_COLORS)]
                fig.add_trace(go.Scatter(x=xg, y=kde, mode="lines", name=g,
                                         line=dict(color=color, width=2),
                                         fill="tozeroy", fillcolor=f"rgba{tuple(int(color[1:][j:j+2],16) for j in (0,2,4))+(0.1,)}"))
        else:
            vals = [_safe_float(row.get(value_col)) for row in data]
            arr = np.array([v for v in vals if not math.isnan(v)])
            xg = np.linspace(arr.min(), arr.max(), 200)
            kde = _kde(arr, xg)
            fig.add_trace(go.Scatter(x=xg, y=kde, mode="lines", name="KDE",
                                     line=dict(color=EDA_COLORS[0], width=2),
                                     fill="tozeroy", fillcolor="rgba(76,114,176,0.15)"))
            fig.add_trace(go.Scatter(x=list(arr), y=[0] * len(arr), mode="markers",
                                     marker=dict(symbol="line-ns-open", size=8,
                                                 color=EDA_COLORS[0], opacity=0.5),
                                     name="Rug"))
        _eda_layout(fig, title, len(data))
        return ToolResult.ok(f"KDE plot '{value_col}' (n={len(data)})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_kde failed: {exc}")


def plot_ecdf(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Empirical CDF plot."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        group_col = params.get("group_col")
        title = params.get("title", "ECDF")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        fig = go.Figure()
        if group_col:
            groups = {}
            for row in data:
                g = str(row.get(group_col, ""))
                v = _safe_float(row.get(value_col))
                if not math.isnan(v):
                    groups.setdefault(g, []).append(v)
            for i, (g, vs) in enumerate(groups.items()):
                arr = sorted(vs)
                ecdf = [(j + 1) / len(arr) for j in range(len(arr))]
                fig.add_trace(go.Scatter(x=arr, y=ecdf, mode="lines",
                                         name=g, line=dict(color=EDA_COLORS[i % len(EDA_COLORS)])))
        else:
            vals = sorted([_safe_float(row.get(value_col)) for row in data
                           if not math.isnan(_safe_float(row.get(value_col)))])
            n = len(vals)
            ecdf = [(i + 1) / n for i in range(n)]
            fig.add_trace(go.Scatter(x=vals, y=ecdf, mode="lines",
                                     line=dict(color=EDA_COLORS[0], width=2), name="ECDF"))
        _eda_layout(fig, title, len(data))
        fig.update_layout(yaxis_title="Cumulative Probability", xaxis_title=value_col)
        return ToolResult.ok(f"ECDF '{value_col}' (n={len(data)})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_ecdf failed: {exc}")


def plot_probability_plot(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Normal probability plot."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        title = params.get("title", "Normal Probability Plot")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = sorted([_safe_float(row.get(value_col)) for row in data
                       if not math.isnan(_safe_float(row.get(value_col)))])
        n = len(vals)
        if n < 3:
            return ToolResult.err("Need at least 3 data points.")
        probs = [(i - 0.375) / (n + 0.25) for i in range(1, n + 1)]
        mean_v, std_v = float(np.mean(vals)), float(np.std(vals, ddof=1))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=vals, y=probs, mode="markers",
                                  marker=dict(color=EDA_COLORS[0], size=6),
                                  name="Data"))
        line_x = [min(vals), max(vals)]
        line_y = [(v - mean_v) / std_v * 0.25 + 0.5 for v in line_x]
        line_y = [min(max(p, 0.001), 0.999) for p in line_y]
        fig.add_trace(go.Scatter(x=line_x, y=line_y, mode="lines",
                                  line=dict(color="#CC0000", dash="dash"), name="Normal"))
        _eda_layout(fig, title, n)
        fig.update_layout(xaxis_title=value_col, yaxis_title="Probability")
        return ToolResult.ok(f"Probability plot '{value_col}' (n={n})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_probability_plot failed: {exc}")


def plot_residuals(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Residuals vs fitted scatter + histogram."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        value_col = params.get("value_col") or params.get("column")
        fitted_col = params.get("fitted_col")
        title = params.get("title", "Residual Analysis")
        if not (value_col and fitted_col):
            return ToolResult.err("'value_col' and 'fitted_col' required.")
        pairs = [(row.get(value_col), row.get(fitted_col)) for row in data]
        pairs = [(y, yh) for y, yh in pairs
                 if not (math.isnan(_safe_float(y)) or math.isnan(_safe_float(yh)))]
        actual = np.array([_safe_float(p[0]) for p in pairs])
        fitted = np.array([_safe_float(p[1]) for p in pairs])
        residuals = actual - fitted
        n = len(residuals)
        fig = make_subplots(rows=1, cols=2,
                             subplot_titles=["Residuals vs Fitted", "Residual Distribution"])
        fig.add_trace(go.Scatter(x=list(fitted), y=list(residuals), mode="markers",
                                  marker=dict(color=EDA_COLORS[0], size=5, opacity=0.7),
                                  name="Residuals"), row=1, col=1)
        fig.add_hline(y=0, line_dash="dash", line_color="#CC0000", row=1, col=1)
        fig.add_trace(go.Histogram(x=list(residuals), nbinsx=20,
                                    marker_color=EDA_COLORS[0], opacity=0.7,
                                    name="Distribution"), row=1, col=2)
        fig.update_layout(template="plotly_white",
                           title=dict(text=f"{title} (n={n})", font=dict(size=14)),
                           font=dict(family="Arial, sans-serif", size=11),
                           margin=dict(l=60, r=30, t=60, b=60))
        rmse = float(np.sqrt(np.mean(residuals ** 2)))
        return ToolResult.ok(f"Residual plot '{value_col}' (n={n}, RMSE={rmse:.4f})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_residuals failed: {exc}")


def plot_ridge(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Ridge/joy plot showing distributions for multiple groups."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        group_col = params.get("group_col")
        title = params.get("title", "Ridge Plot")
        if not (value_col and group_col):
            return ToolResult.err("'value_col' and 'group_col' required.")
        groups = {}
        for row in data:
            g = str(row.get(group_col, ""))
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                groups.setdefault(g, []).append(v)

        def _kde(arr, x_grid):
            n = len(arr)
            bw = 1.06 * float(np.std(arr, ddof=1)) * n ** (-0.2) + 1e-9
            kde = np.zeros(len(x_grid))
            for xi in arr:
                kde += np.exp(-0.5 * ((x_grid - xi) / bw) ** 2)
            return kde / (n * bw * math.sqrt(2 * math.pi))

        all_vals = [v for vs in groups.values() for v in vs]
        x_min, x_max = min(all_vals), max(all_vals)
        x_grid = np.linspace(x_min, x_max, 200)
        fig = go.Figure()
        for i, (g, vs) in enumerate(groups.items()):
            arr = np.array(vs)
            kde = _kde(arr, x_grid)
            kde_scaled = kde / (kde.max() + 1e-12) * 0.8
            fig.add_trace(go.Scatter(
                x=list(x_grid), y=[float(k) + i for k in kde_scaled],
                fill="toself", name=g,
                fillcolor=f"rgba({int(EDA_COLORS[i % len(EDA_COLORS)][1:3], 16)},"
                           f"{int(EDA_COLORS[i % len(EDA_COLORS)][3:5], 16)},"
                           f"{int(EDA_COLORS[i % len(EDA_COLORS)][5:7], 16)},0.4)",
                line=dict(color=EDA_COLORS[i % len(EDA_COLORS)], width=1.5),
            ))
        _eda_layout(fig, title, len(data))
        fig.update_layout(yaxis=dict(tickvals=list(range(len(groups))),
                                      ticktext=list(groups.keys())))
        return ToolResult.ok(f"Ridge plot '{value_col}' ({len(groups)} groups)",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_ridge failed: {exc}")


def plot_strip(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Strip/jitter plot with group mean markers."""
    try:
        import numpy as np
        import random
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        group_col = params.get("group_col")
        title = params.get("title", "Strip Plot")
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
                jitter_x = [i + rng.uniform(-0.25, 0.25) for _ in vs]
                fig.add_trace(go.Scatter(x=jitter_x, y=vs, mode="markers",
                                          marker=dict(color=EDA_COLORS[i % len(EDA_COLORS)],
                                                      size=5, opacity=0.6),
                                          name=g))
                mean_v = float(np.mean(vs))
                fig.add_shape(type="line", x0=i - 0.3, x1=i + 0.3, y0=mean_v, y1=mean_v,
                               line=dict(color="black", width=2))
        else:
            vals = [_safe_float(row.get(value_col)) for row in data
                    if not math.isnan(_safe_float(row.get(value_col)))]
            jitter_x = [rng.uniform(-0.25, 0.25) for _ in vals]
            fig.add_trace(go.Scatter(x=jitter_x, y=vals, mode="markers",
                                      marker=dict(color=EDA_COLORS[0], size=5, opacity=0.6),
                                      name=value_col))
            mean_v = float(np.mean(vals))
            fig.add_shape(type="line", x0=-0.3, x1=0.3, y0=mean_v, y1=mean_v,
                           line=dict(color="black", width=2))
        _eda_layout(fig, title, len(data))
        return ToolResult.ok(f"Strip plot '{value_col}' (n={len(data)})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_strip failed: {exc}")


def plot_correlation_matrix(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Annotated correlation heatmap."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        feature_cols = params.get("feature_cols") or params.get("columns")
        title = params.get("title", "Correlation Matrix")
        if not feature_cols:
            sample = data[0] if data else {}
            feature_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
        if len(feature_cols) < 2:
            return ToolResult.err("Need at least 2 numeric columns.")
        matrix = {c: [_safe_float(row.get(c)) for row in data] for c in feature_cols}
        corr = np.zeros((len(feature_cols), len(feature_cols)))
        for i, ca in enumerate(feature_cols):
            for j, cb in enumerate(feature_cols):
                a = np.array([v for v in matrix[ca] if not math.isnan(v)])
                b = np.array([v for v in matrix[cb] if not math.isnan(v)])
                min_len = min(len(a), len(b))
                if min_len > 1:
                    corr[i, j] = float(np.corrcoef(a[:min_len], b[:min_len])[0, 1])
        annotations = []
        for i in range(len(feature_cols)):
            for j in range(len(feature_cols)):
                annotations.append(dict(x=j, y=i, text=f"{corr[i,j]:.2f}",
                                        showarrow=False, font=dict(size=10)))
        fig = go.Figure(data=go.Heatmap(
            z=corr.tolist(), x=feature_cols, y=feature_cols,
            colorscale="RdBu", zmid=0, zmin=-1, zmax=1,
            text=[[f"{corr[i,j]:.2f}" for j in range(len(feature_cols))]
                  for i in range(len(feature_cols))],
            texttemplate="%{text}",
        ))
        _eda_layout(fig, title, len(data))
        return ToolResult.ok(f"Correlation matrix ({len(feature_cols)}×{len(feature_cols)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_correlation_matrix failed: {exc}")


def plot_scatter_matrix(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Pair plot scatter matrix."""
    try:
        import plotly.graph_objects as go
        import plotly.express as px
        import pandas as pd
        feature_cols = params.get("feature_cols") or params.get("columns")
        color_col = params.get("color_col")
        title = params.get("title", "Scatter Matrix")
        if not feature_cols:
            sample = data[0] if data else {}
            feature_cols = [k for k, v in sample.items() if isinstance(v, (int, float))][:5]
        if len(feature_cols) < 2:
            return ToolResult.err("Need at least 2 columns.")
        df = pd.DataFrame(data)[feature_cols + ([color_col] if color_col else [])]
        fig = px.scatter_matrix(df, dimensions=feature_cols,
                                color=color_col if color_col else None,
                                title=f"{title} (n={len(data)})")
        fig.update_traces(marker=dict(size=4, opacity=0.6))
        fig.update_layout(template="plotly_white", font=dict(family="Arial, sans-serif", size=10))
        return ToolResult.ok(f"Scatter matrix ({len(feature_cols)} features, n={len(data)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_scatter_matrix failed: {exc}")


def plot_mean_ci(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Mean + 95% CI comparison bar across groups."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        group_col = params.get("group_col")
        title = params.get("title", "Mean ± 95% CI")
        if not (value_col and group_col):
            return ToolResult.err("'value_col' and 'group_col' required.")
        groups = {}
        for row in data:
            g = str(row.get(group_col, ""))
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                groups.setdefault(g, []).append(v)
        labels, means, cis = [], [], []
        for g, vs in groups.items():
            arr = np.array(vs)
            n = len(arr)
            mean = float(np.mean(arr))
            se = float(np.std(arr, ddof=1)) / math.sqrt(n) if n > 1 else 0.0
            ci = 1.96 * se
            labels.append(g)
            means.append(mean)
            cis.append(ci)
        fig = go.Figure(data=go.Bar(
            x=labels, y=means, error_y=dict(type="data", array=cis, visible=True),
            marker_color=EDA_COLORS[:len(labels)],
        ))
        _eda_layout(fig, title, len(data))
        fig.update_layout(xaxis_title=group_col, yaxis_title=f"Mean {value_col}")
        return ToolResult.ok(f"Mean CI plot '{value_col}' by '{group_col}' ({len(groups)} groups)",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_mean_ci failed: {exc}")


def plot_bland_altman(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Bland-Altman agreement plot."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        method1_col = params.get("method1_col")
        method2_col = params.get("method2_col")
        title = params.get("title", "Bland-Altman Plot")
        if not (method1_col and method2_col):
            return ToolResult.err("'method1_col' and 'method2_col' required.")
        pairs = [(row.get(method1_col), row.get(method2_col)) for row in data]
        pairs = [(m1, m2) for m1, m2 in pairs
                 if not (math.isnan(_safe_float(m1)) or math.isnan(_safe_float(m2)))]
        m1 = np.array([_safe_float(p[0]) for p in pairs])
        m2 = np.array([_safe_float(p[1]) for p in pairs])
        means = (m1 + m2) / 2
        diffs = m1 - m2
        n = len(diffs)
        bias = float(np.mean(diffs))
        std_diff = float(np.std(diffs, ddof=1))
        loa_upper = bias + 1.96 * std_diff
        loa_lower = bias - 1.96 * std_diff
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=list(means), y=list(diffs), mode="markers",
                                  marker=dict(color=EDA_COLORS[0], size=6, opacity=0.7),
                                  name="Differences"))
        for val, label, dash in [(bias, f"Bias={bias:.3f}", "solid"),
                                   (loa_upper, f"+1.96σ={loa_upper:.3f}", "dash"),
                                   (loa_lower, f"-1.96σ={loa_lower:.3f}", "dash")]:
            fig.add_hline(y=val, line_dash=dash, line_color="#CC0000",
                           annotation_text=label)
        _eda_layout(fig, title, n)
        fig.update_layout(xaxis_title="Mean of methods", yaxis_title="Difference (M1-M2)")
        _apply_tight_range(fig, x_vals=list(means), y_vals_list=[list(diffs)])
        return ToolResult.ok(
            f"Bland-Altman '{method1_col}' vs '{method2_col}' (n={n}): bias={bias:.4f}",
            _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_bland_altman failed: {exc}")


def plot_distribution_compare(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Overlay multiple group distributions (histogram)."""
    try:
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        group_col = params.get("group_col")
        title = params.get("title", "Distribution Comparison")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        fig = go.Figure()
        if group_col:
            groups = {}
            for row in data:
                g = str(row.get(group_col, ""))
                v = _safe_float(row.get(value_col))
                if not math.isnan(v):
                    groups.setdefault(g, []).append(v)
            for i, (g, vs) in enumerate(groups.items()):
                fig.add_trace(go.Histogram(x=vs, name=g, opacity=0.6,
                                            marker_color=EDA_COLORS[i % len(EDA_COLORS)],
                                            nbinsx=20))
            fig.update_layout(barmode="overlay")
        else:
            vals = [_safe_float(row.get(value_col)) for row in data
                    if not math.isnan(_safe_float(row.get(value_col)))]
            fig.add_trace(go.Histogram(x=vals, name=value_col, nbinsx=20,
                                        marker_color=EDA_COLORS[0], opacity=0.7))
        _eda_layout(fig, title, len(data))
        return ToolResult.ok(f"Distribution comparison '{value_col}' (n={len(data)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_distribution_compare failed: {exc}")


def plot_lollipop(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Sorted lollipop ranking chart."""
    try:
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        label_col = params.get("label_col")
        title = params.get("title", "Lollipop Chart")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        if not label_col:
            sample = data[0] if data else {}
            label_col = next((k for k, v in sample.items() if isinstance(v, str)), None)
        rows = sorted(data, key=lambda r: _safe_float(r.get(value_col, 0)), reverse=True)
        labels = [str(row.get(label_col, i)) for i, row in enumerate(rows)]
        values = [_safe_float(row.get(value_col)) for row in rows]
        fig = go.Figure()
        for i, (lbl, val) in enumerate(zip(labels, values)):
            fig.add_shape(type="line", x0=0, x1=val, y0=i, y1=i,
                           line=dict(color=EDA_COLORS[0], width=1.5))
        fig.add_trace(go.Scatter(x=values, y=labels, mode="markers",
                                  marker=dict(color=EDA_COLORS[0], size=10),
                                  name=value_col))
        _eda_layout(fig, title, len(data))
        return ToolResult.ok(f"Lollipop chart '{value_col}' (n={len(data)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_lollipop failed: {exc}")


def plot_dumbbell(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Before-after dumbbell chart."""
    try:
        import plotly.graph_objects as go
        before_col = params.get("before_col")
        after_col = params.get("after_col")
        label_col = params.get("label_col")
        title = params.get("title", "Dumbbell Chart")
        if not (before_col and after_col):
            return ToolResult.err("'before_col' and 'after_col' required.")
        fig = go.Figure()
        for i, row in enumerate(data):
            bv = _safe_float(row.get(before_col))
            av = _safe_float(row.get(after_col))
            lbl = str(row.get(label_col, i)) if label_col else str(i)
            if not (math.isnan(bv) or math.isnan(av)):
                fig.add_shape(type="line", x0=bv, x1=av, y0=i, y1=i,
                               line=dict(color="#aaaaaa", width=2))
        befores = [_safe_float(r.get(before_col)) for r in data if not math.isnan(_safe_float(r.get(before_col)))]
        afters = [_safe_float(r.get(after_col)) for r in data if not math.isnan(_safe_float(r.get(after_col)))]
        labels = [str(r.get(label_col, i)) for i, r in enumerate(data)]
        fig.add_trace(go.Scatter(x=befores, y=list(range(len(befores))),
                                  mode="markers", name="Before",
                                  marker=dict(color=EDA_COLORS[0], size=10)))
        fig.add_trace(go.Scatter(x=afters, y=list(range(len(afters))),
                                  mode="markers", name="After",
                                  marker=dict(color=EDA_COLORS[1], size=10)))
        _eda_layout(fig, title, len(data))
        fig.update_layout(yaxis=dict(tickvals=list(range(len(data))), ticktext=labels))
        return ToolResult.ok(f"Dumbbell chart '{before_col}' → '{after_col}' (n={len(data)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_dumbbell failed: {exc}")


def plot_diverging_bar(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Diverging bar chart from a baseline value."""
    try:
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        label_col = params.get("label_col")
        baseline = float(params.get("baseline", 0))
        title = params.get("title", "Diverging Bar Chart")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        rows = sorted(data, key=lambda r: _safe_float(r.get(value_col, 0)))
        labels = [str(row.get(label_col, i)) for i, row in enumerate(rows)] if label_col else \
                 [str(i) for i in range(len(rows))]
        values = [_safe_float(row.get(value_col)) - baseline for row in rows]
        colors = [EDA_COLORS[0] if v >= 0 else EDA_COLORS[3] for v in values]
        fig = go.Figure(data=go.Bar(
            x=values, y=labels, orientation="h",
            marker_color=colors, name=value_col,
        ))
        fig.add_vline(x=0, line_color="black", line_width=1)
        _eda_layout(fig, title, len(data))
        fig.update_layout(xaxis_title=f"{value_col} (vs baseline={baseline})")
        return ToolResult.ok(f"Diverging bar '{value_col}' (baseline={baseline}, n={len(data)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_diverging_bar failed: {exc}")
