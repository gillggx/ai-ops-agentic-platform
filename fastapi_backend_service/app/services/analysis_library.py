"""Analysis Library — pre-built, server-side verified analysis functions.

Agent calls analyze_data(template=..., mcp_id=..., params=...) instead of writing
raw Python. These implementations are always correct; the agent only maps column names.

Available templates:
  linear_regression  — time-series linear regression with trend line
  spc_chart          — SPC run chart with UCL/LCL/CL control lines
  boxplot            — grouped box plot by category
  stats_summary      — descriptive statistics by optional group
  correlation        — scatter plot + Pearson correlation between two columns
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# ── Template registry ─────────────────────────────────────────────────────────

TEMPLATES: Dict[str, Dict[str, Any]] = {
    "linear_regression": {
        "description": "時間序列線性回歸分析 — 繪製散點圖、趨勢線、UCL/LCL 控制線，輸出 slope/intercept/r_squared/p_value",
        "required_params": ["value_col"],
        "optional_params": {
            "time_col":    "datetime 欄位名稱（可選，預設用 row index）",
            "group_col":   "分組欄位（可選，例如 tool_id）",
            "ucl":         "上控制線數值（可選）",
            "lcl":         "下控制線數值（可選）",
            "cl":          "中心線數值（可選）",
            "title":       "圖表標題",
        },
    },
    "per_group_regression": {
        "description": "各分組獨立線性回歸 — 每個分組（機台/lot）各自一個子圖，並排顯示 slope/R²，適合比較不同機台趨勢差異",
        "required_params": ["value_col", "group_col"],
        "optional_params": {
            "time_col":  "datetime 欄位（可選，預設用 row index）",
            "ucl":       "上控制線（可選）",
            "lcl":       "下控制線（可選）",
            "title":     "圖表標題",
            "cols":      "每行子圖數（可選，預設 4）",
        },
    },
    "spc_chart": {
        "description": "SPC 管制圖 — 繪製量測值走勢、UCL/LCL/CL，標注 OOC 點",
        "required_params": ["value_col", "ucl", "lcl"],
        "optional_params": {
            "time_col":  "datetime 欄位（可選）",
            "group_col": "分組欄位（機台）",
            "cl":        "中心線（可選，預設 mean）",
            "title":     "圖表標題",
        },
    },
    "boxplot": {
        "description": "分組箱型圖 — 比較不同群組的分佈",
        "required_params": ["value_col", "group_col"],
        "optional_params": {"title": "圖表標題"},
    },
    "stats_summary": {
        "description": "統計摘要 — mean/std/min/max/count，可選分組",
        "required_params": ["value_col"],
        "optional_params": {
            "group_col": "分組欄位（可選）",
            "title":     "表格標題",
        },
    },
    "correlation": {
        "description": "相關性分析 — 兩欄位散點圖 + Pearson 相關係數",
        "required_params": ["col_x", "col_y"],
        "optional_params": {
            "group_col": "分組欄位（可選）",
            "title":     "圖表標題",
        },
    },
}


# ── Helper ────────────────────────────────────────────────────────────────────

def _auto_detect_cols(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """Guess time / value / group columns by dtype and common names."""
    time_col = None
    value_col = None
    group_col = None

    for c in df.columns:
        lc = c.lower()
        if time_col is None and df[c].dtype in ("datetime64[ns]", "object"):
            try:
                pd.to_datetime(df[c].dropna().iloc[:3])
                time_col = c
            except Exception:
                pass
        if group_col is None and df[c].dtype == object and c != time_col:
            if df[c].nunique() < 20:
                group_col = c
        if value_col is None and pd.api.types.is_numeric_dtype(df[c]) and "id" not in lc:
            value_col = c

    return {"time_col": time_col, "value_col": value_col, "group_col": group_col}


def _yrange(series: pd.Series, pad: float = 0.02) -> List[float]:
    lo, hi = series.min(), series.max()
    span = (hi - lo) or 1.0
    return [lo - span * pad, hi + span * pad]


# ── Analysis implementations ──────────────────────────────────────────────────

def run_linear_regression(
    df: pd.DataFrame,
    value_col: str,
    time_col: Optional[str] = None,
    group_col: Optional[str] = None,
    ucl: Optional[float] = None,
    lcl: Optional[float] = None,
    cl: Optional[float] = None,
    title: str = "線性回歸分析",
) -> Dict[str, Any]:
    """Time-series linear regression. Returns chart_data + stats dict."""
    import plotly.graph_objects as go

    if value_col not in df.columns:
        raise ValueError(f"欄位 '{value_col}' 不存在，可用欄位：{list(df.columns)}")

    # Sort chronologically so trend line goes left→right (critical for reverse-ordered data)
    if time_col and time_col in df.columns:
        try:
            df = df.copy()
            df[time_col] = pd.to_datetime(df[time_col])
            df = df.sort_values(time_col).reset_index(drop=True)
        except Exception:
            pass

    vals = pd.to_numeric(df[value_col], errors="coerce")

    # X axis: use index for regression; convert time_col to elapsed minutes for display
    # (Using absolute datetime causes X-axis compression issues in Plotly.js for dense time-series)
    x_num = np.arange(len(df))
    x_label = time_col or "序號"
    if time_col and time_col in df.columns:
        try:
            t_series = pd.to_datetime(df[time_col])
            t0 = t_series.iloc[0]
            elapsed_min = (t_series - t0).dt.total_seconds() / 60.0
            x_display = elapsed_min
            t0_str = t0.strftime("%m/%d %H:%M") if hasattr(t0, "strftime") else str(t0)[:16]
            x_label = f"經過時間（分鐘，自 {t0_str}）"
        except Exception:
            x_display = pd.Series(x_num)
    else:
        x_display = pd.Series(x_num)

    # Linear regression on numeric index (never on datetime)
    mask = ~np.isnan(vals.values)
    coeffs = np.polyfit(x_num[mask], vals.values[mask], 1)
    slope, intercept = float(coeffs[0]), float(coeffs[1])
    trend_y = intercept + slope * x_num

    # R²
    y_mean = vals[mask].mean()
    ss_tot = float(np.sum((vals.values[mask] - y_mean) ** 2))
    ss_res = float(np.sum((vals.values[mask] - trend_y[mask]) ** 2))
    r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Simple t-test for slope significance
    n = int(mask.sum())
    se = float(np.sqrt(ss_res / max(n - 2, 1) / np.sum((x_num[mask] - x_num[mask].mean()) ** 2))) if n > 2 else 0
    t_stat = float(slope / se) if se > 0 else 0.0
    # p-value approximation (two-tailed, df=n-2)
    from math import erfc, sqrt
    p_value = float(erfc(abs(t_stat) / sqrt(2))) if n > 2 else 1.0

    fig = go.Figure()

    # Convert to plain Python lists to avoid Plotly 6.x binary bdata serialization
    # (bdata format causes rendering failures in some Plotly.js versions)
    x_list = [float(v) for v in x_display]
    y_list = [float(v) if not np.isnan(v) else None for v in vals]
    trend_list = [float(v) for v in trend_y]

    # Scatter by group if provided
    if group_col and group_col in df.columns:
        for grp, gdf in df.groupby(group_col):
            gvals = pd.to_numeric(gdf[value_col], errors="coerce")
            gx = [x_list[i] for i in gdf.index]
            gy = [float(v) if not np.isnan(v) else None for v in gvals]
            fig.add_trace(go.Scatter(
                x=gx, y=gy,
                mode="markers", name=str(grp), opacity=0.75,
            ))
    else:
        fig.add_trace(go.Scatter(
            x=x_list, y=y_list,
            mode="markers", name="量測值",
            marker=dict(color="#6366f1", size=5, opacity=0.7),
        ))

    # Trend line (use display x, but y computed from index)
    fig.add_trace(go.Scatter(
        x=x_list, y=trend_list,
        mode="lines", name=f"回歸線 (slope={slope:.4f}, R²={r_squared:.4f})",
        line=dict(color="#ef4444", width=2, dash="dash"),
    ))

    # Control lines
    x_for_lines = [x_list[0], x_list[-1]]
    if ucl is not None:
        fig.add_trace(go.Scatter(x=x_for_lines, y=[ucl, ucl], mode="lines",
                                  name=f"UCL={ucl}", line=dict(color="#f97316", dash="dot")))
    if lcl is not None:
        fig.add_trace(go.Scatter(x=x_for_lines, y=[lcl, lcl], mode="lines",
                                  name=f"LCL={lcl}", line=dict(color="#3b82f6", dash="dot")))
    if cl is not None:
        fig.add_trace(go.Scatter(x=x_for_lines, y=[cl, cl], mode="lines",
                                  name=f"CL={cl}", line=dict(color="#22c55e", dash="dot")))

    fig.update_layout(
        title=title,
        xaxis_title=x_label,
        yaxis_title=value_col,
        yaxis=dict(range=_yrange(vals.dropna())),
        legend=dict(orientation="h", y=-0.2),
        template="plotly_white",
        height=420,
    )

    stats = {
        "slope": round(slope, 6),
        "intercept": round(intercept, 4),
        "r_squared": round(r_squared, 4),
        "t_stat": round(t_stat, 4),
        "p_value": round(p_value, 4),
        "n": n,
        "mean": round(float(vals.mean()), 4),
        "std": round(float(vals.std()), 4),
    }
    llm_readable = (
        f"線性回歸結果：slope={slope:.4f}/pt，R²={r_squared:.4f}，"
        f"p={p_value:.4f}，n={n}。"
        f"{'趨勢顯著（p<0.05）' if p_value < 0.05 else '趨勢不顯著（p≥0.05）'}。"
    )

    # Result table: one row per data point
    result_table = []
    for i in range(len(df)):
        act = y_list[i]
        trn = trend_list[i]
        result_table.append({
            "序號": i + 1,
            "elapsed_min": round(x_list[i], 1),
            value_col: round(act, 4) if act is not None else None,
            "趨勢線": round(trn, 4),
            "殘差": round(act - trn, 4) if act is not None else None,
        })

    return {
        "stats": stats,
        "chart_data": fig.to_json(),
        "llm_readable_data": llm_readable,
        "result_table": result_table,
    }


def run_spc_chart(
    df: pd.DataFrame,
    value_col: str,
    ucl: float,
    lcl: float,
    time_col: Optional[str] = None,
    group_col: Optional[str] = None,
    cl: Optional[float] = None,
    title: str = "SPC 管制圖",
) -> Dict[str, Any]:
    import plotly.graph_objects as go

    if value_col not in df.columns:
        raise ValueError(f"欄位 '{value_col}' 不存在")

    # Sort chronologically so chart renders left→right
    if time_col and time_col in df.columns:
        try:
            df = df.copy()
            df[time_col] = pd.to_datetime(df[time_col])
            df = df.sort_values(time_col).reset_index(drop=True)
        except Exception:
            pass

    vals = pd.to_numeric(df[value_col], errors="coerce")
    x_display: Any
    x_label_spc = time_col or "序號"
    if time_col and time_col in df.columns:
        try:
            t_series = pd.to_datetime(df[time_col])
            t0 = t_series.iloc[0]
            x_display = (t_series - t0).dt.total_seconds() / 60.0
            t0_str = t0.strftime("%m/%d %H:%M") if hasattr(t0, "strftime") else str(t0)[:16]
            x_label_spc = f"經過時間（分鐘，自 {t0_str}）"
        except Exception:
            x_display = pd.Series(np.arange(len(df)))
    else:
        x_display = pd.Series(np.arange(len(df)))

    cl_val = cl if cl is not None else float(vals.mean())
    ooc_mask = (vals > ucl) | (vals < lcl)

    # Convert to plain Python lists to avoid Plotly 6.x binary bdata serialization
    x_list_spc = [float(v) for v in x_display]
    vals_list = [float(v) if not np.isnan(v) else None for v in vals]

    fig = go.Figure()

    if group_col and group_col in df.columns:
        for grp, gdf in df.groupby(group_col):
            gv = pd.to_numeric(gdf[value_col], errors="coerce")
            gx = [x_list_spc[i] for i in gdf.index]
            gy = [float(v) if not np.isnan(v) else None for v in gv]
            fig.add_trace(go.Scatter(x=gx, y=gy, mode="markers+lines",
                                      name=str(grp), opacity=0.6))
    else:
        fig.add_trace(go.Scatter(x=x_list_spc, y=vals_list, mode="markers+lines",
                                  name="量測值", marker=dict(color="#6366f1", size=5)))

    # OOC points
    ooc_idx = [i for i, m in enumerate(ooc_mask) if m]
    ooc_x_list = [x_list_spc[i] for i in ooc_idx]
    ooc_y_list = [float(vals.iloc[i]) for i in ooc_idx]
    fig.add_trace(go.Scatter(x=ooc_x_list, y=ooc_y_list, mode="markers",
                              name="OOC", marker=dict(color="red", size=10, symbol="x")))

    x_ends = [x_list_spc[0], x_list_spc[-1]]
    for val, label, color, dash in [
        (ucl, f"UCL={ucl}", "#f97316", "dot"),
        (lcl, f"LCL={lcl}", "#3b82f6", "dot"),
        (cl_val, f"CL={cl_val:.3f}", "#22c55e", "dash"),
    ]:
        fig.add_trace(go.Scatter(x=x_ends, y=[val, val], mode="lines",
                                  name=label, line=dict(color=color, dash=dash, width=1)))

    fig.update_layout(
        title=title,
        xaxis_title=x_label_spc,
        yaxis_title=value_col,
        yaxis=dict(range=_yrange(vals.dropna())),
        legend=dict(orientation="h", y=-0.25),
        template="plotly_white",
        height=420,
    )

    ooc_count = int(ooc_mask.sum())
    stats = {"ooc_count": ooc_count, "total": len(df), "ooc_rate": round(ooc_count / len(df), 4),
             "mean": round(float(vals.mean()), 4), "std": round(float(vals.std()), 4),
             "ucl": ucl, "lcl": lcl, "cl": cl_val}
    llm_readable = (
        f"SPC 管制圖：共 {len(df)} 點，OOC {ooc_count} 點（{ooc_count/len(df)*100:.1f}%），"
        f"mean={vals.mean():.4f}，UCL={ucl}，LCL={lcl}。"
    )

    # Result table: one row per data point with OOC status
    ooc_set = set(ooc_idx)
    result_table_spc = []
    for i in range(len(df)):
        v = vals_list[i]
        result_table_spc.append({
            "序號": i + 1,
            "elapsed_min": round(x_list_spc[i], 1),
            value_col: round(v, 4) if v is not None else None,
            "狀態": "OOC 🔴" if i in ooc_set else "NORMAL",
        })

    return {
        "stats": stats,
        "chart_data": fig.to_json(),
        "llm_readable_data": llm_readable,
        "result_table": result_table_spc,
    }


def run_boxplot(
    df: pd.DataFrame,
    value_col: str,
    group_col: str,
    title: str = "箱型圖分析",
) -> Dict[str, Any]:
    import plotly.graph_objects as go

    if value_col not in df.columns:
        raise ValueError(f"欄位 '{value_col}' 不存在")
    if group_col not in df.columns:
        raise ValueError(f"欄位 '{group_col}' 不存在")

    fig = go.Figure()
    groups = sorted(df[group_col].dropna().unique())
    # Convert to plain Python lists to avoid Plotly 6.x bdata serialization
    for grp in groups:
        vals = pd.to_numeric(df[df[group_col] == grp][value_col], errors="coerce").dropna()
        fig.add_trace(go.Box(y=[float(v) for v in vals], name=str(grp), boxmean=True))

    vals_all = pd.to_numeric(df[value_col], errors="coerce").dropna()
    fig.update_layout(
        title=title, yaxis_title=value_col,
        yaxis=dict(range=_yrange(vals_all)),
        template="plotly_white", height=420,
    )

    stats_by_group = {}
    for grp in groups:
        gv = pd.to_numeric(df[df[group_col] == grp][value_col], errors="coerce").dropna()
        stats_by_group[str(grp)] = {
            "mean": round(float(gv.mean()), 4), "std": round(float(gv.std()), 4),
            "min": round(float(gv.min()), 4), "max": round(float(gv.max()), 4),
            "count": int(len(gv)),
        }
    llm_readable = f"箱型圖 {value_col} by {group_col}：共 {len(groups)} 組。" + \
        " | ".join(f"{g}: mean={v['mean']}" for g, v in list(stats_by_group.items())[:5])

    # Result table: group summary statistics
    result_table_bp = [
        {group_col: grp, **sv}
        for grp, sv in stats_by_group.items()
    ]

    return {
        "stats": stats_by_group,
        "chart_data": fig.to_json(),
        "llm_readable_data": llm_readable,
        "result_table": result_table_bp,
    }


def run_stats_summary(
    df: pd.DataFrame,
    value_col: str,
    group_col: Optional[str] = None,
    title: str = "統計摘要",
) -> Dict[str, Any]:
    if value_col not in df.columns:
        raise ValueError(f"欄位 '{value_col}' 不存在")

    vals = pd.to_numeric(df[value_col], errors="coerce")

    if group_col and group_col in df.columns:
        desc = df.groupby(group_col)[value_col].describe().round(4)
        rows = [{"group": str(g), **{k: float(v) for k, v in row.items()}}
                for g, row in desc.iterrows()]
        llm = f"{value_col} 統計（by {group_col}）：{len(rows)} 組。" + \
              " | ".join(f"{r['group']}: mean={r.get('mean', '?')}" for r in rows[:5])
    else:
        d = vals.describe()
        rows = [{k: round(float(v), 4) for k, v in d.items()}]
        llm = (f"{value_col} 統計：count={int(d['count'])}, mean={d['mean']:.4f}, "
               f"std={d['std']:.4f}, min={d['min']:.4f}, max={d['max']:.4f}")

    return {"stats": rows, "chart_data": None, "llm_readable_data": llm, "result_table": rows}


def run_correlation(
    df: pd.DataFrame,
    col_x: str,
    col_y: str,
    group_col: Optional[str] = None,
    title: str = "相關性分析",
) -> Dict[str, Any]:
    import plotly.graph_objects as go

    for c in (col_x, col_y):
        if c not in df.columns:
            raise ValueError(f"欄位 '{c}' 不存在")

    x = pd.to_numeric(df[col_x], errors="coerce")
    y = pd.to_numeric(df[col_y], errors="coerce")
    mask = ~(np.isnan(x) | np.isnan(y))
    corr = float(np.corrcoef(x[mask], y[mask])[0, 1])

    # Convert to plain Python lists to avoid Plotly 6.x binary bdata serialization
    x_list_corr = [float(v) if not np.isnan(v) else None for v in x]
    y_list_corr = [float(v) if not np.isnan(v) else None for v in y]
    x_mask_list = [float(v) for v in x[mask]]
    y_mask_list = [float(v) for v in y[mask]]

    fig = go.Figure()
    if group_col and group_col in df.columns:
        for grp, gdf in df.groupby(group_col):
            gx = [float(v) if not np.isnan(v) else None for v in pd.to_numeric(gdf[col_x], errors="coerce")]
            gy = [float(v) if not np.isnan(v) else None for v in pd.to_numeric(gdf[col_y], errors="coerce")]
            fig.add_trace(go.Scatter(x=gx, y=gy, mode="markers", name=str(grp)))
    else:
        fig.add_trace(go.Scatter(x=x_list_corr, y=y_list_corr, mode="markers", name="資料點",
                                  marker=dict(color="#6366f1", size=5, opacity=0.7)))

    # Trend line
    coeffs = np.polyfit(x_mask_list, y_mask_list, 1)
    x_line = [float(v) for v in np.linspace(min(x_mask_list), max(x_mask_list), 50)]
    y_line = [float(coeffs[1] + coeffs[0] * v) for v in x_line]
    fig.add_trace(go.Scatter(x=x_line, y=y_line,
                              mode="lines", name=f"趨勢線 (r={corr:.3f})",
                              line=dict(color="#ef4444", dash="dash")))

    fig.update_layout(title=title, xaxis_title=col_x, yaxis_title=col_y,
                       template="plotly_white", height=420,
                       yaxis=dict(range=_yrange(y[mask])))

    stats = {"pearson_r": round(corr, 4), "r_squared": round(corr ** 2, 4),
             "n": int(mask.sum()), "col_x": col_x, "col_y": col_y}
    llm = (f"相關性 {col_x} vs {col_y}：Pearson r={corr:.4f}，R²={corr**2:.4f}，n={mask.sum()}。"
           f"{'強正相關' if corr > 0.7 else '強負相關' if corr < -0.7 else '弱相關/無相關'}。")

    # Result table: paired values (up to 200 rows to keep payload manageable)
    result_table_corr = []
    for i, (xv, yv) in enumerate(zip(x_list_corr, y_list_corr)):
        if xv is not None and yv is not None:
            result_table_corr.append({"序號": i + 1, col_x: round(xv, 4), col_y: round(yv, 4)})
        if len(result_table_corr) >= 200:
            break

    return {
        "stats": stats,
        "chart_data": fig.to_json(),
        "llm_readable_data": llm,
        "result_table": result_table_corr,
    }


def run_per_group_regression(
    df: pd.DataFrame,
    value_col: str,
    group_col: str,
    time_col: Optional[str] = None,
    ucl: Optional[float] = None,
    lcl: Optional[float] = None,
    title: str = "各分組線性回歸",
    cols: int = 4,
) -> Dict[str, Any]:
    """Per-group linear regression with a clean subplot grid.

    Each group (machine/tool/lot) gets its own subplot with scatter + regression line.
    Subplot titles show group name + slope + R² and are positioned above the chart area.
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    for c in (value_col, group_col):
        if c not in df.columns:
            raise ValueError(f"欄位 '{c}' 不存在，可用欄位：{list(df.columns)}")

    groups = sorted(df[group_col].dropna().unique())
    n = len(groups)
    cols = max(1, min(int(cols), n))
    rows = (n + cols - 1) // cols

    # Build subplot titles (group name only; slope/R² added via annotations after fitting)
    subplot_titles = [str(g) for g in groups] + [""] * (rows * cols - n)

    fig = make_subplots(
        rows=rows,
        cols=cols,
        subplot_titles=subplot_titles,
        vertical_spacing=max(0.08, 0.4 / rows),
        horizontal_spacing=0.06,
    )

    result_rows: List[Dict[str, Any]] = []
    stats_by_group: Dict[str, Any] = {}
    llm_parts: List[str] = []

    for idx, grp in enumerate(groups):
        row_i = idx // cols + 1
        col_i = idx % cols + 1
        gdf = df[df[group_col] == grp].copy()

        if time_col and time_col in gdf.columns:
            try:
                gdf[time_col] = pd.to_datetime(gdf[time_col])
                gdf = gdf.sort_values(time_col).reset_index(drop=True)
            except Exception:
                pass

        vals = pd.to_numeric(gdf[value_col], errors="coerce")
        x_num = np.arange(len(gdf))

        if time_col and time_col in gdf.columns:
            try:
                t_s = pd.to_datetime(gdf[time_col])
                t0 = t_s.iloc[0]
                x_disp = [(t_s.iloc[i] - t0).total_seconds() / 60.0 for i in range(len(gdf))]
            except Exception:
                x_disp = list(x_num)
        else:
            x_disp = list(x_num)

        mask = ~np.isnan(vals.values)
        if mask.sum() < 2:
            continue

        coeffs = np.polyfit(x_num[mask], vals.values[mask], 1)
        slope, intercept = float(coeffs[0]), float(coeffs[1])
        trend_y = intercept + slope * x_num
        y_mean = float(vals[mask].mean())
        ss_tot = float(np.sum((vals.values[mask] - y_mean) ** 2))
        ss_res = float(np.sum((vals.values[mask] - trend_y[mask]) ** 2))
        r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        x_list = [float(v) for v in x_disp]
        y_list = [float(v) if not np.isnan(v) else None for v in vals]
        trend_list = [float(v) for v in trend_y]

        fig.add_trace(go.Scatter(
            x=x_list, y=y_list,
            mode="markers", showlegend=False,
            marker=dict(color="#6366f1", size=4, opacity=0.6),
            name=str(grp),
        ), row=row_i, col=col_i)

        fig.add_trace(go.Scatter(
            x=x_list, y=trend_list,
            mode="lines", showlegend=False,
            line=dict(color="#ef4444", width=2, dash="dash"),
            name=f"{grp} trend",
        ), row=row_i, col=col_i)

        if ucl is not None:
            fig.add_trace(go.Scatter(
                x=[x_list[0], x_list[-1]], y=[ucl, ucl],
                mode="lines", showlegend=False,
                line=dict(color="#f97316", width=1, dash="dot"),
            ), row=row_i, col=col_i)
        if lcl is not None:
            fig.add_trace(go.Scatter(
                x=[x_list[0], x_list[-1]], y=[lcl, lcl],
                mode="lines", showlegend=False,
                line=dict(color="#3b82f6", width=1, dash="dot"),
            ), row=row_i, col=col_i)

        stats_by_group[str(grp)] = {
            "slope": round(slope, 6),
            "r_squared": round(r_squared, 4),
            "n": int(mask.sum()),
            "mean": round(y_mean, 4),
        }
        llm_parts.append(f"{grp}: slope={slope:.4f}, R²={r_squared:.4f}")

        # Add slope/R² as an inside-subplot annotation (top-left corner, data coordinates)
        y_top = float(vals[mask].max())
        if ucl is not None:
            y_top = max(y_top, ucl)
        fig.add_annotation(
            row=row_i, col=col_i,
            x=x_list[0],
            y=y_top,
            text=f"s={slope:.4f}  R²={r_squared:.3f}",
            xanchor="left",
            yanchor="top",
            showarrow=False,
            font=dict(size=8, color="#6366f1"),
            bgcolor="rgba(248,250,252,0.85)",
            borderpad=2,
        )

        for i, row_d in enumerate(gdf.itertuples()):
            result_rows.append({
                group_col: str(grp),
                "序號": i + 1,
                value_col: round(y_list[i], 4) if y_list[i] is not None else None,
                "趨勢線": round(trend_list[i], 4),
                "slope": round(slope, 6),
                "r_squared": round(r_squared, 4),
            })

    chart_height = max(320, rows * 280 + 80)
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        height=chart_height,
        template="plotly_white",
        margin=dict(l=40, r=20, t=60, b=40),
    )

    llm_readable = (
        f"{group_col} 各分組線性回歸（共 {n} 組）：\n" + "\n".join(llm_parts[:10])
    )
    if n > 10:
        llm_readable += f"\n…共 {n} 組"

    return {
        "stats": stats_by_group,
        "chart_data": fig.to_json(),
        "llm_readable_data": llm_readable,
        "result_table": result_rows[:500],
    }


# ── Dispatcher ────────────────────────────────────────────────────────────────

_RUNNERS = {
    "linear_regression":    run_linear_regression,
    "per_group_regression": run_per_group_regression,
    "spc_chart":            run_spc_chart,
    "boxplot":              run_boxplot,
    "stats_summary":        run_stats_summary,
    "correlation":          run_correlation,
}


def run_analysis(
    template: str,
    df: pd.DataFrame,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Dispatch to the correct analysis function."""
    if template not in _RUNNERS:
        available = ", ".join(_RUNNERS.keys())
        raise ValueError(f"未知分析模板 '{template}'，可用：{available}")
    return _RUNNERS[template](df, **params)
