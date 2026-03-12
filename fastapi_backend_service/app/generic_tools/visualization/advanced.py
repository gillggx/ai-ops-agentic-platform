"""Advanced chart tools (v15.3+).

Tools: plot_sankey, plot_treemap, plot_sunburst, plot_waterfall,
       plot_funnel, plot_gauge, plot_bubble, plot_dual_axis,
       plot_xbar_r, plot_imr, plot_cusum, plot_ewma_chart,
       plot_pareto, plot_capability_hist, plot_acf_pacf,
       plot_rolling_stats, plot_seasonal_decompose, plot_forecast_band,
       plot_event_markers, plot_multi_vari, plot_run_chart,
       plot_hexbin, plot_contour, plot_3d_scatter, plot_marginal_scatter,
       plot_slope_chart, plot_benchmark, plot_outlier_flags
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _plotly_to_payload, _safe_float

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


# ── NEW ADVANCED CHART TOOLS (v15.4) ─────────────────────────────────────────

def plot_xbar_r(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """X-bar and R control chart for subgroups."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        value_col = params.get("value_col") or params.get("column")
        subgroup_col = params.get("subgroup_col")
        title = params.get("title", "X-bar & R Chart")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        if subgroup_col:
            groups = {}
            for row in data:
                g = str(row.get(subgroup_col, ""))
                v = _safe_float(row.get(value_col))
                if not math.isnan(v):
                    groups.setdefault(g, []).append(v)
            subgroup_labels = list(groups.keys())
            subgroups = [np.array(v) for v in groups.values()]
        else:
            vals = [_safe_float(row.get(value_col)) for row in data if not math.isnan(_safe_float(row.get(value_col)))]
            sg_size = max(2, min(5, len(vals) // 10))
            subgroups = [np.array(vals[i:i+sg_size]) for i in range(0, len(vals), sg_size) if len(vals[i:i+sg_size]) == sg_size]
            subgroup_labels = [str(i+1) for i in range(len(subgroups))]
        if len(subgroups) < 2:
            return ToolResult.err("Need at least 2 subgroups.")
        xbar = [float(np.mean(sg)) for sg in subgroups]
        ranges = [float(np.ptp(sg)) for sg in subgroups]
        xbar_mean = float(np.mean(xbar))
        r_mean = float(np.mean(ranges))
        n_sg = len(subgroups[0])
        d2_map = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326}
        A2_map = {2: 1.880, 3: 1.023, 4: 0.729, 5: 0.577}
        D3_map = {2: 0, 3: 0, 4: 0, 5: 0}
        D4_map = {2: 3.267, 3: 2.574, 4: 2.282, 5: 2.114}
        A2 = A2_map.get(n_sg, 0.577)
        D3 = D3_map.get(n_sg, 0)
        D4 = D4_map.get(n_sg, 2.114)
        ucl_x = xbar_mean + A2 * r_mean
        lcl_x = xbar_mean - A2 * r_mean
        ucl_r = D4 * r_mean
        lcl_r = D3 * r_mean
        fig = make_subplots(rows=2, cols=1, subplot_titles=["X-bar Chart", "R Chart"])
        fig.add_trace(go.Scatter(x=subgroup_labels, y=xbar, mode="lines+markers",
                                  marker=dict(color=EDA_COLORS[0]), name="X-bar"), row=1, col=1)
        for val, label, color in [(ucl_x, "UCL", "#CC0000"), (xbar_mean, "CL", "#00AA00"), (lcl_x, "LCL", "#CC0000")]:
            fig.add_hline(y=val, line_color=color, line_dash="dash", row=1, col=1,
                           annotation_text=f"{label}={val:.3f}")
        fig.add_trace(go.Scatter(x=subgroup_labels, y=ranges, mode="lines+markers",
                                  marker=dict(color=EDA_COLORS[1]), name="R"), row=2, col=1)
        for val, label, color in [(ucl_r, "UCL_R", "#CC0000"), (r_mean, "R̄", "#00AA00"), (lcl_r, "LCL_R", "#CC0000")]:
            fig.add_hline(y=val, line_color=color, line_dash="dash", row=2, col=1,
                           annotation_text=f"{label}={val:.3f}")
        fig.update_layout(template="plotly_white", title=dict(text=f"{title} (k={len(subgroups)}, n={n_sg})", font=dict(size=14)),
                           font=dict(family="Arial, sans-serif", size=11), margin=dict(l=60, r=30, t=60, b=60))
        return ToolResult.ok(f"X-bar R chart: {len(subgroups)} subgroups, n={n_sg}", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_xbar_r failed: {exc}")


def plot_imr(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Individuals (I) and Moving Range (MR) control chart."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        value_col = params.get("value_col") or params.get("column")
        title = params.get("title", "I-MR Chart")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data if not math.isnan(_safe_float(row.get(value_col)))]
        n = len(vals)
        if n < 3:
            return ToolResult.err("Need at least 3 data points.")
        arr = np.array(vals)
        mr = [abs(arr[i] - arr[i-1]) for i in range(1, n)]
        cl = float(np.mean(arr))
        mr_bar = float(np.mean(mr))
        d2 = 1.128
        sigma = mr_bar / d2
        ucl_i = cl + 3 * sigma
        lcl_i = cl - 3 * sigma
        ucl_mr = 3.267 * mr_bar
        idx = list(range(n))
        fig = make_subplots(rows=2, cols=1, subplot_titles=["Individuals Chart", "Moving Range Chart"])
        fig.add_trace(go.Scatter(x=idx, y=list(arr), mode="lines+markers",
                                  marker=dict(color=EDA_COLORS[0], size=5), name="I"), row=1, col=1)
        for val, lbl, color in [(ucl_i, "UCL", "#CC0000"), (cl, "CL", "#00AA00"), (lcl_i, "LCL", "#CC0000")]:
            fig.add_hline(y=val, line_color=color, line_dash="dash", row=1, col=1,
                           annotation_text=f"{lbl}={val:.3f}")
        fig.add_trace(go.Scatter(x=list(range(1, n)), y=mr, mode="lines+markers",
                                  marker=dict(color=EDA_COLORS[1], size=5), name="MR"), row=2, col=1)
        for val, lbl, color in [(ucl_mr, "UCL_MR", "#CC0000"), (mr_bar, "MR̄", "#00AA00")]:
            fig.add_hline(y=val, line_color=color, line_dash="dash", row=2, col=1,
                           annotation_text=f"{lbl}={val:.3f}")
        ooc = sum(1 for v in arr if v > ucl_i or v < lcl_i)
        fig.update_layout(template="plotly_white", title=dict(text=f"{title} (n={n}, OOC={ooc})", font=dict(size=14)),
                           font=dict(family="Arial, sans-serif", size=11), margin=dict(l=60, r=30, t=60, b=60))
        return ToolResult.ok(f"I-MR chart '{value_col}' (n={n}, OOC={ooc})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_imr failed: {exc}")


def plot_cusum(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """CUSUM control chart."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        k = float(params.get("k", 0.5))
        h = float(params.get("h", 5))
        title = params.get("title", "CUSUM Chart")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data if not math.isnan(_safe_float(row.get(value_col)))]
        arr = np.array(vals)
        n = len(arr)
        target = float(params.get("target", np.mean(arr)))
        sigma = float(np.std(arr, ddof=1)) or 1.0
        k_abs = k * sigma
        h_abs = h * sigma
        cu, cl = np.zeros(n), np.zeros(n)
        for i in range(1, n):
            cu[i] = max(0, cu[i-1] + arr[i] - target - k_abs)
            cl[i] = max(0, cl[i-1] - (arr[i] - target) - k_abs)
        signals_up = [i for i in range(n) if cu[i] > h_abs]
        signals_dn = [i for i in range(n) if cl[i] > h_abs]
        idx = list(range(n))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=idx, y=list(cu), mode="lines+markers",
                                  marker=dict(color=EDA_COLORS[0], size=4), name="CUSUM+"))
        fig.add_trace(go.Scatter(x=idx, y=list(-cl), mode="lines+markers",
                                  marker=dict(color=EDA_COLORS[1], size=4), name="CUSUM-"))
        fig.add_hline(y=h_abs, line_color="#CC0000", line_dash="dash",
                       annotation_text=f"H={h_abs:.3f}")
        fig.add_hline(y=-h_abs, line_color="#CC0000", line_dash="dash")
        fig.add_hline(y=0, line_color="#888888", line_width=1)
        _eda_layout(fig, title, n)
        return ToolResult.ok(
            f"CUSUM chart '{value_col}': {len(signals_up)+len(signals_dn)} signals",
            _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_cusum failed: {exc}")


def plot_ewma_chart(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """EWMA control chart."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        lam = float(params.get("lambda_", 0.2))
        L = float(params.get("L", 3.0))
        title = params.get("title", "EWMA Chart")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data if not math.isnan(_safe_float(row.get(value_col)))]
        arr = np.array(vals)
        n = len(arr)
        mu = float(np.mean(arr))
        sigma = float(np.std(arr, ddof=1)) or 1.0
        ewma = [mu]
        for v in arr[1:]:
            ewma.append(lam * v + (1 - lam) * ewma[-1])
        idx = list(range(n))
        ucl = [mu + L * sigma * math.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * (i + 1)))) for i in range(n)]
        lcl = [mu - L * sigma * math.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * (i + 1)))) for i in range(n)]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=idx, y=list(arr), mode="markers",
                                  marker=dict(color="#aaaaaa", size=4), name="Raw data", opacity=0.5))
        fig.add_trace(go.Scatter(x=idx, y=ewma, mode="lines+markers",
                                  marker=dict(color=EDA_COLORS[0], size=5), name="EWMA"))
        fig.add_trace(go.Scatter(x=idx, y=ucl, mode="lines",
                                  line=dict(color="#CC0000", dash="dash"), name="UCL"))
        fig.add_trace(go.Scatter(x=idx, y=lcl, mode="lines",
                                  line=dict(color="#CC0000", dash="dash"), name="LCL"))
        fig.add_hline(y=mu, line_color="#00AA00", line_dash="dash", annotation_text=f"CL={mu:.3f}")
        ooc = sum(1 for e, u, l in zip(ewma, ucl, lcl) if e > u or e < l)
        _eda_layout(fig, title, n)
        return ToolResult.ok(f"EWMA chart '{value_col}' (λ={lam}, L={L}, OOC={ooc})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_ewma_chart failed: {exc}")


def plot_pareto(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Pareto chart: bars + cumulative percentage line."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        value_col = params.get("value_col") or params.get("column")
        label_col = params.get("label_col")
        title = params.get("title", "Pareto Chart")
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
        total = sum(v for v in values if not math.isnan(v))
        cumulative = []
        cum = 0
        for v in values:
            cum += v / total * 100 if total > 0 else 0
            cumulative.append(round(cum, 2))
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(x=labels, y=values, name="Count",
                              marker_color=EDA_COLORS[0]), secondary_y=False)
        fig.add_trace(go.Scatter(x=labels, y=cumulative, mode="lines+markers",
                                  name="Cumulative %",
                                  line=dict(color=EDA_COLORS[3], width=2),
                                  marker=dict(size=6)), secondary_y=True)
        fig.add_hline(y=80, line_dash="dash", line_color="#888888", secondary_y=True,
                       annotation_text="80%")
        fig.update_layout(template="plotly_white",
                           title=dict(text=f"{title} (n={len(data)})", font=dict(size=14)),
                           font=dict(family="Arial, sans-serif", size=11),
                           margin=dict(l=60, r=60, t=60, b=60))
        fig.update_yaxes(title_text="Count", secondary_y=False)
        fig.update_yaxes(title_text="Cumulative %", range=[0, 110], secondary_y=True)
        return ToolResult.ok(f"Pareto chart '{value_col}' (n={len(data)})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_pareto failed: {exc}")


def plot_capability_hist(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Process capability histogram with spec limits and Cp/Cpk."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        usl = params.get("usl")
        lsl = params.get("lsl")
        title = params.get("title", "Capability Histogram")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data if not math.isnan(_safe_float(row.get(value_col)))]
        arr = np.array(vals)
        n = len(arr)
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1)) or 1e-9
        fig = go.Figure()
        fig.add_trace(go.Histogram(x=vals, nbinsx=30, name="Data",
                                    marker_color=EDA_COLORS[0], opacity=0.7))
        if usl is not None:
            fig.add_vline(x=float(usl), line_color="#CC0000", line_width=2,
                           annotation_text=f"USL={usl}")
        if lsl is not None:
            fig.add_vline(x=float(lsl), line_color="#CC0000", line_width=2,
                           annotation_text=f"LSL={lsl}")
        fig.add_vline(x=mean, line_color="#00AA00", line_dash="dash",
                       annotation_text=f"Mean={mean:.3f}")
        cp_text = ""
        if usl is not None and lsl is not None:
            cp = (float(usl) - float(lsl)) / (6 * std)
            cpk = min((float(usl) - mean) / (3 * std), (mean - float(lsl)) / (3 * std))
            cp_text = f"Cp={cp:.3f}, Cpk={cpk:.3f}"
        _eda_layout(fig, f"{title} {cp_text}", n)
        return ToolResult.ok(f"Capability histogram '{value_col}' (n={n})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_capability_hist failed: {exc}")


def plot_acf_pacf(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """ACF and PACF side-by-side."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        value_col = params.get("value_col") or params.get("column")
        max_lags = int(params.get("max_lags", 20))
        title = params.get("title", "ACF / PACF")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data if not math.isnan(_safe_float(row.get(value_col)))]
        arr = np.array(vals)
        n = len(arr)
        max_lags = min(max_lags, n // 2 - 1)
        arr_c = arr - arr.mean()
        var = float(np.var(arr_c)) + 1e-12
        acf = [1.0] + [float(np.sum(arr_c[k:] * arr_c[:-k])) / (var * n) for k in range(1, max_lags + 1)]
        # Yule-Walker PACF
        pacf = [1.0]
        for k in range(1, max_lags + 1):
            R = np.array([[acf[abs(i - j)] for j in range(k)] for i in range(k)])
            r = np.array([acf[i + 1] for i in range(k)])
            try:
                coeffs = np.linalg.solve(R, r)
                pacf.append(float(coeffs[-1]))
            except Exception:
                pacf.append(0.0)
        conf = 1.96 / math.sqrt(n)
        lags = list(range(max_lags + 1))
        fig = make_subplots(rows=1, cols=2, subplot_titles=["ACF", "PACF"])
        for i, (lag, val) in enumerate(zip(lags, acf)):
            color = "#CC0000" if abs(val) > conf and i > 0 else EDA_COLORS[0]
            fig.add_shape(type="line", x0=lag, x1=lag, y0=0, y1=val,
                           line=dict(color=color, width=2), row=1, col=1)
        for i, (lag, val) in enumerate(zip(lags, pacf)):
            color = "#CC0000" if abs(val) > conf and i > 0 else EDA_COLORS[1]
            fig.add_shape(type="line", x0=lag, x1=lag, y0=0, y1=val,
                           line=dict(color=color, width=2), row=1, col=2)
        fig.add_hline(y=conf, line_dash="dash", line_color="#888888", row=1, col=1)
        fig.add_hline(y=-conf, line_dash="dash", line_color="#888888", row=1, col=1)
        fig.add_hline(y=conf, line_dash="dash", line_color="#888888", row=1, col=2)
        fig.add_hline(y=-conf, line_dash="dash", line_color="#888888", row=1, col=2)
        fig.update_layout(template="plotly_white",
                           title=dict(text=f"{title} (n={n})", font=dict(size=14)),
                           font=dict(family="Arial, sans-serif", size=11),
                           margin=dict(l=60, r=30, t=60, b=60))
        return ToolResult.ok(f"ACF/PACF '{value_col}' (n={n}, lags={max_lags})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_acf_pacf failed: {exc}")


def plot_rolling_stats(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Rolling mean + std band chart."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        window = int(params.get("window", 10))
        title = params.get("title", "Rolling Statistics")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = np.array([_safe_float(row.get(value_col)) for row in data])
        n = len(vals)
        roll_mean = np.full(n, np.nan)
        roll_std = np.full(n, np.nan)
        for i in range(window - 1, n):
            seg = vals[i - window + 1:i + 1]
            roll_mean[i] = float(np.nanmean(seg))
            roll_std[i] = float(np.nanstd(seg, ddof=1))
        idx = list(range(n))
        upper = roll_mean + roll_std
        lower = roll_mean - roll_std
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=idx, y=list(vals), mode="lines",
                                  line=dict(color="#cccccc", width=1), name="Raw"))
        fig.add_trace(go.Scatter(x=idx + idx[::-1],
                                  y=list(upper) + list(lower[::-1]),
                                  fill="toself", fillcolor="rgba(76,114,176,0.2)",
                                  line=dict(color="rgba(255,255,255,0)"), name="±1σ band"))
        fig.add_trace(go.Scatter(x=idx, y=list(roll_mean), mode="lines",
                                  line=dict(color=EDA_COLORS[0], width=2), name="Rolling Mean"))
        _eda_layout(fig, title, n)
        return ToolResult.ok(f"Rolling stats '{value_col}' (window={window}, n={n})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_rolling_stats failed: {exc}")


def plot_seasonal_decompose(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Trend/seasonal/residual decomposition subplots."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        value_col = params.get("value_col") or params.get("column")
        period = int(params.get("period", 7))
        title = params.get("title", "Seasonal Decomposition")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array(vals)
        n = len(arr)
        if n < period * 2:
            return ToolResult.err(f"Need at least {period * 2} data points.")
        half = period // 2
        trend = np.full(n, np.nan)
        for i in range(half, n - half):
            trend[i] = float(np.nanmean(arr[i - half:i + half + 1]))
        deseason = arr - trend
        seasonal = np.full(n, np.nan)
        for pos in range(period):
            idxs = [i for i in range(pos, n, period) if not math.isnan(deseason[i])]
            if idxs:
                avg = float(np.nanmean(deseason[idxs]))
                for i in idxs:
                    seasonal[i] = avg
        residual = arr - trend - seasonal
        idx = list(range(n))
        fig = make_subplots(rows=4, cols=1, subplot_titles=["Original", "Trend", "Seasonal", "Residual"])
        for row_i, (series, name, color) in enumerate([
            (arr, "Original", EDA_COLORS[0]),
            (trend, "Trend", EDA_COLORS[1]),
            (seasonal, "Seasonal", EDA_COLORS[2]),
            (residual, "Residual", EDA_COLORS[3]),
        ], 1):
            y = [None if math.isnan(v) else float(v) for v in series]
            fig.add_trace(go.Scatter(x=idx, y=y, mode="lines",
                                      line=dict(color=color, width=1.5), name=name), row=row_i, col=1)
        fig.update_layout(template="plotly_white",
                           title=dict(text=f"{title} (n={n}, period={period})", font=dict(size=14)),
                           font=dict(family="Arial, sans-serif", size=11),
                           height=700, margin=dict(l=60, r=30, t=60, b=60), showlegend=False)
        return ToolResult.ok(f"Seasonal decompose '{value_col}' (n={n}, period={period})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_seasonal_decompose failed: {exc}")


def plot_forecast_band(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Line chart with upper/lower forecast confidence band."""
    try:
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        upper_col = params.get("upper_col")
        lower_col = params.get("lower_col")
        title = params.get("title", "Forecast with Confidence Band")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        n = len(data)
        idx = list(range(n))
        vals = [_safe_float(row.get(value_col)) for row in data]
        fig = go.Figure()
        if upper_col and lower_col:
            uppers = [_safe_float(row.get(upper_col)) for row in data]
            lowers = [_safe_float(row.get(lower_col)) for row in data]
            fig.add_trace(go.Scatter(x=idx + idx[::-1], y=uppers + lowers[::-1],
                                      fill="toself", fillcolor="rgba(76,114,176,0.2)",
                                      line=dict(color="rgba(255,255,255,0)"), name="CI band"))
            fig.add_trace(go.Scatter(x=idx, y=uppers, mode="lines",
                                      line=dict(color=EDA_COLORS[0], dash="dash", width=1), name="Upper"))
            fig.add_trace(go.Scatter(x=idx, y=lowers, mode="lines",
                                      line=dict(color=EDA_COLORS[0], dash="dash", width=1), name="Lower"))
        fig.add_trace(go.Scatter(x=idx, y=vals, mode="lines+markers",
                                  marker=dict(color=EDA_COLORS[0], size=5),
                                  line=dict(color=EDA_COLORS[0], width=2), name=value_col))
        _eda_layout(fig, title, n)
        return ToolResult.ok(f"Forecast band '{value_col}' (n={n})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_forecast_band failed: {exc}")


def plot_event_markers(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Time series with vertical event marker lines."""
    try:
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        time_col = params.get("time_col")
        event_col = params.get("event_col")
        title = params.get("title", "Time Series with Events")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        n = len(data)
        x_vals = [row.get(time_col) for row in data] if time_col else list(range(n))
        y_vals = [_safe_float(row.get(value_col)) for row in data]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x_vals, y=y_vals, mode="lines+markers",
                                  marker=dict(color=EDA_COLORS[0], size=4),
                                  line=dict(color=EDA_COLORS[0], width=1.5), name=value_col))
        if event_col:
            event_rows = [(i, x, row.get(event_col)) for i, (x, row) in enumerate(zip(x_vals, data))
                          if row.get(event_col)]
            for idx, x, evt in event_rows[:20]:
                # Use integer index as x position to avoid type mismatch with string dates
                fig.add_vline(x=idx, line_color="#CC0000", line_dash="dot",
                               annotation_text=str(evt), annotation_font_size=9)
        _eda_layout(fig, title, n)
        return ToolResult.ok(f"Event markers '{value_col}' (n={n})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_event_markers failed: {exc}")


def plot_multi_vari(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Multi-vari chart showing within/between variation."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        part_col = params.get("part_col")
        operator_col = params.get("operator_col")
        title = params.get("title", "Multi-Vari Chart")
        if not (value_col and part_col):
            return ToolResult.err("'value_col' and 'part_col' required.")
        parts = {}
        for row in data:
            part = str(row.get(part_col, ""))
            op = str(row.get(operator_col, "Op1")) if operator_col else "Op1"
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                parts.setdefault(part, {}).setdefault(op, []).append(v)
        fig = go.Figure()
        part_idx = 0
        for part, ops in parts.items():
            part_means = []
            for i, (op, vals) in enumerate(ops.items()):
                arr = np.array(vals)
                mean = float(np.mean(arr))
                mn, mx = float(arr.min()), float(arr.max())
                color = EDA_COLORS[i % len(EDA_COLORS)]
                fig.add_shape(type="line", x0=part_idx - 0.2, x1=part_idx + 0.2,
                               y0=mn, y1=mn, line=dict(color=color, width=1.5))
                fig.add_shape(type="line", x0=part_idx - 0.2, x1=part_idx + 0.2,
                               y0=mx, y1=mx, line=dict(color=color, width=1.5))
                fig.add_shape(type="line", x0=part_idx, x1=part_idx, y0=mn, y1=mx,
                               line=dict(color=color, width=1))
                fig.add_trace(go.Scatter(x=[part_idx], y=[mean], mode="markers",
                                          marker=dict(color=color, size=10, symbol="diamond"),
                                          name=op, showlegend=(part_idx == 0)))
                part_means.append(mean)
                part_idx += 1
        _eda_layout(fig, title, len(data))
        fig.update_layout(xaxis=dict(showticklabels=False))
        return ToolResult.ok(f"Multi-vari chart '{value_col}' ({len(parts)} parts)", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_multi_vari failed: {exc}")


def plot_run_chart(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Run chart with mean line and run annotations."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        title = params.get("title", "Run Chart")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data if not math.isnan(_safe_float(row.get(value_col)))]
        n = len(vals)
        arr = np.array(vals)
        mean_v = float(np.mean(arr))
        idx = list(range(n))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=idx, y=list(arr), mode="lines+markers",
                                  marker=dict(color=EDA_COLORS[0], size=5),
                                  line=dict(color=EDA_COLORS[0], width=1.5), name=value_col))
        fig.add_hline(y=mean_v, line_color="#00AA00", line_dash="dash",
                       annotation_text=f"Mean={mean_v:.3f}")
        # Count runs
        above = arr >= mean_v
        runs = 1 + sum(1 for i in range(1, n) if above[i] != above[i-1])
        expected_runs = (2 * n - 1) / 3
        _eda_layout(fig, title, n)
        fig.add_annotation(xref="paper", yref="paper", x=0.01, y=0.99,
                            text=f"Runs={runs}  Expected≈{expected_runs:.0f}  mean={mean_v:.3f}",
                            showarrow=False, font=dict(size=9, color="#666"),
                            align="left", bgcolor="rgba(255,255,255,0.8)")
        return ToolResult.ok(f"Run chart '{value_col}' (n={n}, runs={runs})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_run_chart failed: {exc}")


def plot_hexbin(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Hexagonal binning density scatter."""
    try:
        import plotly.figure_factory as ff
        import plotly.graph_objects as go
        col_x = params.get("col_x") or params.get("x")
        col_y = params.get("col_y") or params.get("y")
        title = params.get("title", "Hexbin Density")
        if not (col_x and col_y):
            sample = data[0] if data else {}
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if len(num_cols) < 2:
                return ToolResult.err("Need 2 numeric columns.")
            col_x, col_y = num_cols[0], num_cols[1]
        x_vals = [_safe_float(row.get(col_x)) for row in data if not math.isnan(_safe_float(row.get(col_x)))]
        y_vals = [_safe_float(row.get(col_y)) for row in data if not math.isnan(_safe_float(row.get(col_y)))]
        n = min(len(x_vals), len(y_vals))
        # Use scatter with density color approximation
        fig = go.Figure(go.Histogram2d(
            x=x_vals[:n], y=y_vals[:n],
            colorscale="Blues", nbinsx=20, nbinsy=20,
        ))
        _eda_layout(fig, title, n)
        fig.update_layout(xaxis_title=col_x, yaxis_title=col_y)
        return ToolResult.ok(f"Hexbin '{col_x}' vs '{col_y}' (n={n})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_hexbin failed: {exc}")


def plot_contour(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Filled contour density chart."""
    try:
        import plotly.graph_objects as go
        col_x = params.get("col_x") or params.get("x")
        col_y = params.get("col_y") or params.get("y")
        title = params.get("title", "Contour Density")
        if not (col_x and col_y):
            sample = data[0] if data else {}
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if len(num_cols) < 2:
                return ToolResult.err("Need 2 numeric columns.")
            col_x, col_y = num_cols[0], num_cols[1]
        x_vals = [_safe_float(row.get(col_x)) for row in data if not math.isnan(_safe_float(row.get(col_x)))]
        y_vals = [_safe_float(row.get(col_y)) for row in data if not math.isnan(_safe_float(row.get(col_y)))]
        n = min(len(x_vals), len(y_vals))
        fig = go.Figure(go.Histogram2dContour(
            x=x_vals[:n], y=y_vals[:n],
            colorscale="Blues", contours=dict(showlabels=True),
        ))
        fig.add_trace(go.Scatter(x=x_vals[:n], y=y_vals[:n], mode="markers",
                                  marker=dict(color=EDA_COLORS[0], size=3, opacity=0.3),
                                  name="Points"))
        _eda_layout(fig, title, n)
        fig.update_layout(xaxis_title=col_x, yaxis_title=col_y)
        return ToolResult.ok(f"Contour density '{col_x}' vs '{col_y}' (n={n})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_contour failed: {exc}")


def plot_3d_scatter(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """3D scatter plot."""
    try:
        import plotly.graph_objects as go
        col_x = params.get("col_x") or params.get("x")
        col_y = params.get("col_y") or params.get("y")
        col_z = params.get("col_z") or params.get("z")
        color_col = params.get("color_col")
        title = params.get("title", "3D Scatter")
        if not (col_x and col_y and col_z):
            sample = data[0] if data else {}
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if len(num_cols) < 3:
                return ToolResult.err("Need at least 3 numeric columns.")
            col_x, col_y, col_z = num_cols[0], num_cols[1], num_cols[2]
        x_vals = [_safe_float(row.get(col_x)) for row in data]
        y_vals = [_safe_float(row.get(col_y)) for row in data]
        z_vals = [_safe_float(row.get(col_z)) for row in data]
        marker = dict(size=4, opacity=0.7, color=EDA_COLORS[0])
        if color_col:
            marker["color"] = [_safe_float(row.get(color_col)) for row in data]
            marker["colorscale"] = "Viridis"
            marker["showscale"] = True
        fig = go.Figure(data=go.Scatter3d(x=x_vals, y=y_vals, z=z_vals,
                                           mode="markers", marker=marker))
        fig.update_layout(template="plotly_white",
                           title=dict(text=f"{title} (n={len(data)})", font=dict(size=14)),
                           scene=dict(xaxis_title=col_x, yaxis_title=col_y, zaxis_title=col_z))
        return ToolResult.ok(f"3D scatter '{col_x}' / '{col_y}' / '{col_z}' (n={len(data)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_3d_scatter failed: {exc}")


def plot_marginal_scatter(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Scatter with marginal histograms."""
    try:
        import plotly.express as px
        import pandas as pd
        col_x = params.get("col_x") or params.get("x")
        col_y = params.get("col_y") or params.get("y")
        color_col = params.get("color_col")
        title = params.get("title", "Marginal Scatter")
        if not (col_x and col_y):
            sample = data[0] if data else {}
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if len(num_cols) < 2:
                return ToolResult.err("Need 2 numeric columns.")
            col_x, col_y = num_cols[0], num_cols[1]
        cols = [col_x, col_y] + ([color_col] if color_col else [])
        df = pd.DataFrame(data)[cols].dropna()
        fig = px.scatter(df, x=col_x, y=col_y,
                          color=color_col if color_col else None,
                          marginal_x="histogram", marginal_y="histogram",
                          title=f"{title} (n={len(df)})",
                          template="plotly_white",
                          color_discrete_sequence=EDA_COLORS)
        return ToolResult.ok(f"Marginal scatter '{col_x}' vs '{col_y}' (n={len(df)})",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_marginal_scatter failed: {exc}")


def plot_slope_chart(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Slope/bump chart for before-after rank changes."""
    try:
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        time_col = params.get("time_col")
        group_col = params.get("group_col")
        title = params.get("title", "Slope Chart")
        if not (value_col and time_col and group_col):
            return ToolResult.err("'value_col', 'time_col', and 'group_col' required.")
        periods = sorted(set(str(row.get(time_col, "")) for row in data))
        if len(periods) < 2:
            return ToolResult.err("Need at least 2 time periods.")
        groups_data = {}
        for row in data:
            g = str(row.get(group_col, ""))
            t = str(row.get(time_col, ""))
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                groups_data.setdefault(g, {})[t] = v
        fig = go.Figure()
        for i, (g, time_vals) in enumerate(groups_data.items()):
            xs = [periods.index(t) for t in periods if t in time_vals]
            ys = [time_vals[t] for t in periods if t in time_vals]
            color = EDA_COLORS[i % len(EDA_COLORS)]
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers+text",
                                      text=[g if j == len(ys) - 1 else "" for j in range(len(ys))],
                                      textposition="middle right",
                                      line=dict(color=color, width=2),
                                      marker=dict(color=color, size=8), name=g))
        _eda_layout(fig, title, len(data))
        fig.update_layout(xaxis=dict(tickvals=list(range(len(periods))), ticktext=periods))
        return ToolResult.ok(f"Slope chart '{value_col}' (n={len(data)})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_slope_chart failed: {exc}")


def plot_benchmark(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Actual vs benchmark/target comparison chart."""
    try:
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        benchmark_col = params.get("benchmark_col")
        label_col = params.get("label_col")
        title = params.get("title", "Actual vs Benchmark")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        n = len(data)
        idx = list(range(n))
        labels = [str(row.get(label_col, i)) for i, row in enumerate(data)] if label_col else [str(i) for i in idx]
        actuals = [_safe_float(row.get(value_col)) for row in data]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=labels, y=actuals, name="Actual",
                              marker_color=EDA_COLORS[0], opacity=0.8))
        if benchmark_col:
            benchmarks = [_safe_float(row.get(benchmark_col)) for row in data]
            fig.add_trace(go.Scatter(x=labels, y=benchmarks, mode="lines+markers",
                                      line=dict(color=EDA_COLORS[3], width=2, dash="dash"),
                                      marker=dict(size=8, symbol="diamond"),
                                      name="Benchmark"))
        _eda_layout(fig, title, n)
        return ToolResult.ok(f"Benchmark chart '{value_col}' (n={n})", _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_benchmark failed: {exc}")


def plot_outlier_flags(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Line chart with outlier points highlighted in red."""
    try:
        import numpy as np
        import plotly.graph_objects as go
        value_col = params.get("value_col") or params.get("column")
        time_col = params.get("time_col")
        threshold = float(params.get("threshold", 3.0))
        title = params.get("title", "Outlier Detection")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = np.array([_safe_float(row.get(value_col)) for row in data])
        n = len(vals)
        x_vals = [row.get(time_col) for row in data] if time_col else list(range(n))
        mean = float(np.nanmean(vals))
        std = float(np.nanstd(vals, ddof=1)) or 1.0
        z_scores = np.abs((vals - mean) / std)
        outlier_mask = z_scores > threshold
        normal_x = [x_vals[i] for i in range(n) if not outlier_mask[i]]
        normal_y = [vals[i] for i in range(n) if not outlier_mask[i]]
        out_x = [x_vals[i] for i in range(n) if outlier_mask[i]]
        out_y = [vals[i] for i in range(n) if outlier_mask[i]]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=list(x_vals), y=list(vals), mode="lines",
                                  line=dict(color="#cccccc", width=1), name="Series"))
        fig.add_trace(go.Scatter(x=normal_x, y=normal_y, mode="markers",
                                  marker=dict(color=EDA_COLORS[0], size=5), name="Normal"))
        if out_x:
            fig.add_trace(go.Scatter(x=out_x, y=out_y, mode="markers",
                                      marker=dict(color="#CC0000", size=10, symbol="x"),
                                      name=f"Outliers ({len(out_x)})"))
        _eda_layout(fig, title, n)
        fig.add_annotation(xref="paper", yref="paper", x=0.01, y=0.99,
                            text=f"threshold={threshold}σ  outliers={len(out_x)}/{n}  mean={mean:.3f}",
                            showarrow=False, font=dict(size=9, color="#666"),
                            align="left", bgcolor="rgba(255,255,255,0.8)")
        return ToolResult.ok(f"Outlier flags '{value_col}' (n={n}, {len(out_x)} outliers)",
                             _plotly_to_payload(fig))
    except Exception as exc:
        return ToolResult.err(f"plot_outlier_flags failed: {exc}")
