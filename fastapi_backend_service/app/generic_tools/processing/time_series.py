"""Time series tools (v15.3).

Tools: time_series_decompose, detect_step_change,
       resample_time_series, moving_window_op
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _jsonify, _safe_float


def time_series_decompose(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Decompose time series into trend, seasonality, residual using moving average."""
    try:
        import numpy as np

        col = params.get("column")
        period = int(params.get("period", 7))

        if not col:
            sample = data[0] if data else {}
            col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not col:
            return ToolResult.err("No numeric column found.")

        vals = [_safe_float(row.get(col)) for row in data]
        arr = np.array(vals)
        n = len(arr)
        if n < period * 2:
            return ToolResult.err(f"Need at least {period * 2} data points for period={period}.")

        # Trend: centered moving average
        half = period // 2
        trend = np.full(n, np.nan)
        for i in range(half, n - half):
            trend[i] = np.nanmean(arr[i - half: i + half + 1])

        # Seasonality: average deviation per period position
        deseason = arr - trend
        seasonal = np.full(n, np.nan)
        for pos in range(period):
            indices = [i for i in range(pos, n, period) if not math.isnan(deseason[i])]
            if indices:
                avg = np.nanmean(deseason[indices])
                for i in indices:
                    seasonal[i] = avg

        # Residual
        residual = arr - trend - seasonal

        def _nanlist(a):
            return [None if math.isnan(v) else round(float(v), 6) for v in a]

        return ToolResult.ok(
            f"Decomposed '{col}' (n={n}, period={period}): trend extracted via {period}-point moving average",
            {
                "column": col, "period": period, "n": n,
                "trend": _nanlist(trend),
                "seasonal": _nanlist(seasonal),
                "residual": _nanlist(residual),
                "original": _nanlist(arr),
            },
        )
    except Exception as exc:
        return ToolResult.err(f"time_series_decompose failed: {exc}")


def detect_step_change(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Detect step changes (mean shifts) using CUSUM algorithm."""
    try:
        import numpy as np

        col = params.get("column")
        threshold = float(params.get("threshold", 1.0))  # in sigma units

        if not col:
            sample = data[0] if data else {}
            col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not col:
            return ToolResult.err("No numeric column found.")

        vals = [_safe_float(row.get(col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        if n < 4:
            return ToolResult.err("Need at least 4 data points.")

        mu = float(np.mean(arr))
        sigma = float(np.std(arr, ddof=1))
        if sigma == 0:
            return ToolResult.err("Zero variance — no step change possible.")

        k = threshold * sigma / 2  # slack parameter

        # Upper and lower CUSUM
        cu = np.zeros(n)
        cl = np.zeros(n)
        for i in range(1, n):
            cu[i] = max(0, cu[i - 1] + (arr[i] - mu) - k)
            cl[i] = max(0, cl[i - 1] - (arr[i] - mu) - k)

        alert_threshold = threshold * sigma * 5
        change_points = [
            {"index": i, "direction": "up" if cu[i] > alert_threshold else "down",
             "cusum": round(float(cu[i] if cu[i] > alert_threshold else cl[i]), 6),
             "value": round(float(arr[i]), 6)}
            for i in range(1, n)
            if cu[i] > alert_threshold or cl[i] > alert_threshold
        ]

        # Deduplicate close change points
        deduped = []
        last_idx = -10
        for cp in change_points:
            if cp["index"] - last_idx > 3:
                deduped.append(cp)
                last_idx = cp["index"]

        return ToolResult.ok(
            f"CUSUM on '{col}': detected {len(deduped)} step change(s)",
            {
                "column": col, "n": n, "mean": round(mu, 6), "sigma": round(sigma, 6),
                "threshold": threshold, "change_points": deduped,
                "cusum_upper": [round(float(v), 4) for v in cu],
                "cusum_lower": [round(float(v), 4) for v in cl],
            },
        )
    except Exception as exc:
        return ToolResult.err(f"detect_step_change failed: {exc}")


def resample_time_series(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Resample a time series to a different interval (e.g., seconds → minutes)."""
    try:
        import pandas as pd

        time_col = params.get("time_col") or params.get("time")
        value_col = params.get("value_col") or params.get("column")
        interval = params.get("interval", "1min")
        agg_func = params.get("agg_func", "mean")

        if not time_col:
            # Guess first datetime-like column
            sample = data[0] if data else {}
            time_col = next(
                (k for k in sample if "time" in k.lower() or "date" in k.lower()), None
            )
        if not time_col:
            return ToolResult.err("No time column found. Specify 'time_col'.")

        df = pd.DataFrame(data)
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        df = df.dropna(subset=[time_col]).set_index(time_col)

        cols = [value_col] if value_col else df.select_dtypes(include="number").columns.tolist()
        if not cols:
            return ToolResult.err("No numeric columns to resample.")

        resampled = df[cols].resample(interval).agg(agg_func).dropna()
        rows = resampled.reset_index().to_dict(orient="records")

        return ToolResult.ok(
            f"Resampled {len(data)} rows → {len(rows)} rows at interval='{interval}' using {agg_func}",
            {"interval": interval, "agg_func": agg_func, "original_count": len(data),
             "resampled_count": len(rows), "rows": rows[:500]},
        )
    except Exception as exc:
        return ToolResult.err(f"resample_time_series failed: {exc}")


def moving_window_op(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Rolling window operations: mean, std, min, max, sum."""
    try:
        import numpy as np

        col = params.get("column")
        window = int(params.get("window", 5))
        op = params.get("op", "mean").lower()

        if not col:
            sample = data[0] if data else {}
            col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not col:
            return ToolResult.err("No numeric column found.")

        vals = [_safe_float(row.get(col)) for row in data]
        arr = np.array(vals)
        n = len(arr)
        result = np.full(n, np.nan)

        ops = {
            "mean": np.nanmean, "std": np.nanstd,
            "min": np.nanmin,  "max": np.nanmax, "sum": np.nansum,
        }
        fn = ops.get(op, np.nanmean)

        for i in range(window - 1, n):
            window_vals = arr[i - window + 1: i + 1]
            result[i] = fn(window_vals)

        out_key = f"{col}_rolling_{op}_{window}"
        rows = [
            {**row, out_key: None if math.isnan(r) else round(float(r), 6)}
            for row, r in zip(data, result)
        ]
        return ToolResult.ok(
            f"Rolling {op} (window={window}) on '{col}' → '{out_key}'",
            {"column": col, "op": op, "window": window, "out_column": out_key,
             "rows": rows[:500]},
        )
    except Exception as exc:
        return ToolResult.err(f"moving_window_op failed: {exc}")
