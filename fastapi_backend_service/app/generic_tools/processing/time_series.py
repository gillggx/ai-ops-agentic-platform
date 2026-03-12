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


# ── NEW TIME SERIES TOOLS (v15.4) ─────────────────────────────────────────────

def stationarity_test(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Augmented Dickey-Fuller test for unit root (non-stationarity)."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        if n < 20:
            return ToolResult.err("Need at least 20 data points for ADF test.")
        try:
            from statsmodels.tsa.stattools import adfuller
            result = adfuller(arr)
            adf_stat, p_value = float(result[0]), float(result[1])
            critical = {k: round(float(v), 4) for k, v in result[4].items()}
        except ImportError:
            # Manual ADF approximation: regress diff on lagged level
            y_diff = np.diff(arr)
            y_lag = arr[:-1]
            n2 = len(y_diff)
            cov = float(np.cov(y_diff, y_lag)[0, 1])
            var_lag = float(np.var(y_lag, ddof=1))
            beta = cov / var_lag if var_lag > 0 else 0.0
            resid = y_diff - beta * y_lag
            se = math.sqrt(float(np.var(resid, ddof=2)) / (var_lag * n2 + 1e-12))
            adf_stat = beta / se if se > 0 else 0.0
            p_value = 0.01 if adf_stat < -3.5 else 0.05 if adf_stat < -2.9 else 0.1 if adf_stat < -2.58 else 0.5
            critical = {"1%": -3.5, "5%": -2.9, "10%": -2.58}
        is_stationary = p_value < 0.05
        return ToolResult.ok(
            f"ADF test '{value_col}' (n={n}): ADF={adf_stat:.4f}, p={p_value:.4f} "
            f"→ {'STATIONARY' if is_stationary else 'NON-STATIONARY'} (α=0.05)",
            {"column": value_col, "n": n, "adf_statistic": round(adf_stat, 6),
             "p_value": round(p_value, 6), "is_stationary": is_stationary,
             "critical_values": critical},
        )
    except Exception as exc:
        return ToolResult.err(f"stationarity_test failed: {exc}")


def autocorrelation_analysis(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """ACF and PACF values up to max_lags."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        max_lags = int(params.get("max_lags", 20))
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        if n < 10:
            return ToolResult.err("Need at least 10 data points.")
        max_lags = min(max_lags, n // 2 - 1)
        arr_centered = arr - np.mean(arr)
        var = float(np.var(arr_centered, ddof=0)) + 1e-12
        acf = [1.0] + [float(np.sum(arr_centered[k:] * arr_centered[:-k])) / (var * n)
                       for k in range(1, max_lags + 1)]
        # Yule-Walker PACF approximation
        pacf = [1.0]
        for k in range(1, max_lags + 1):
            R = np.array([[acf[abs(i - j)] for j in range(k)] for i in range(k)])
            r = np.array([acf[i + 1] for i in range(k)])
            try:
                coeffs = np.linalg.solve(R, r)
                pacf.append(float(coeffs[-1]))
            except np.linalg.LinAlgError:
                pacf.append(0.0)
        conf_interval = 1.96 / math.sqrt(n)
        acf_records = [{"lag": i, "acf": round(v, 4), "significant": abs(v) > conf_interval}
                       for i, v in enumerate(acf)]
        pacf_records = [{"lag": i, "pacf": round(v, 4), "significant": abs(v) > conf_interval}
                        for i, v in enumerate(pacf)]
        return ToolResult.ok(
            f"ACF/PACF '{value_col}' (n={n}, max_lags={max_lags}): "
            f"conf_interval=±{conf_interval:.4f}",
            {"column": value_col, "n": n, "max_lags": max_lags,
             "conf_interval": round(conf_interval, 4),
             "acf": acf_records, "pacf": pacf_records},
        )
    except Exception as exc:
        return ToolResult.err(f"autocorrelation_analysis failed: {exc}")


def ewma_smoothing(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Exponential weighted moving average smoothing."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        span = float(params.get("span", 10))
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        alpha = 2.0 / (span + 1)
        ewma = []
        prev = None
        for v in vals:
            if math.isnan(v):
                ewma.append(None)
                continue
            if prev is None:
                prev = v
            else:
                prev = alpha * v + (1 - alpha) * prev
            ewma.append(round(prev, 6))
        out_col = f"{value_col}_ewma_{int(span)}"
        rows_out = [{**row, out_col: e} for row, e in zip(data, ewma)]
        return ToolResult.ok(
            f"EWMA smoothing '{value_col}' (span={span}, α={alpha:.4f}) → '{out_col}'",
            {"column": value_col, "out_column": out_col, "span": span, "alpha": round(alpha, 6),
             "rows": _jsonify(rows_out[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"ewma_smoothing failed: {exc}")


def cusum_detection(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """CUSUM cumulative sum for mean shift detection."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        k = float(params.get("k", 0.5))
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        target = float(params.get("target", np.mean(arr)))
        sigma = float(np.std(arr, ddof=1)) or 1.0
        k_abs = k * sigma
        h = 5 * sigma  # decision interval
        cu, cl = np.zeros(n), np.zeros(n)
        for i in range(1, n):
            cu[i] = max(0, cu[i-1] + arr[i] - target - k_abs)
            cl[i] = max(0, cl[i-1] - (arr[i] - target) - k_abs)
        signals_up = [{"index": i, "cusum": round(float(cu[i]), 4)} for i in range(n) if cu[i] > h]
        signals_dn = [{"index": i, "cusum": round(float(cl[i]), 4)} for i in range(n) if cl[i] > h]
        return ToolResult.ok(
            f"CUSUM detection '{value_col}': {len(signals_up)} upward + {len(signals_dn)} downward signals",
            {"column": value_col, "target": round(target, 4), "k": k,
             "decision_interval": round(h, 4), "n": n,
             "signals_up": signals_up[:50], "signals_down": signals_dn[:50],
             "cusum_upper": [round(float(v), 4) for v in cu],
             "cusum_lower": [round(float(v), 4) for v in cl]},
        )
    except Exception as exc:
        return ToolResult.err(f"cusum_detection failed: {exc}")


def seasonal_strength(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Measure seasonal strength vs trend using STL-like variance decomposition."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        period = int(params.get("period", 7))
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        if n < period * 2:
            return ToolResult.err(f"Need at least {period * 2} data points.")
        half = period // 2
        trend = np.full(n, np.nan)
        for i in range(half, n - half):
            trend[i] = np.nanmean(arr[i - half: i + half + 1])
        detrended = arr - trend
        seasonal = np.full(n, np.nan)
        for pos in range(period):
            idxs = [i for i in range(pos, n, period) if not math.isnan(detrended[i])]
            if idxs:
                avg = float(np.nanmean(detrended[idxs]))
                for i in idxs:
                    seasonal[i] = avg
        residual = arr - trend - seasonal
        var_residual = float(np.nanvar(residual))
        var_deseasoned = float(np.nanvar(arr - seasonal))
        var_detrended = float(np.nanvar(detrended))
        seasonal_str = max(0.0, 1 - var_residual / (var_detrended + 1e-12))
        trend_str = max(0.0, 1 - var_residual / (var_deseasoned + 1e-12))
        return ToolResult.ok(
            f"Seasonal strength '{value_col}' (period={period}): "
            f"seasonal={seasonal_str:.3f}, trend={trend_str:.3f}",
            {"column": value_col, "period": period, "n": n,
             "seasonal_strength": round(seasonal_str, 4),
             "trend_strength": round(trend_str, 4),
             "var_residual": round(var_residual, 6)},
        )
    except Exception as exc:
        return ToolResult.err(f"seasonal_strength failed: {exc}")


def rolling_statistics(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Rolling mean/std/min/max statistics."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        window = int(params.get("window", 10))
        stats_list = params.get("stats", ["mean", "std"])
        if isinstance(stats_list, str):
            stats_list = [stats_list]
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = np.array([_safe_float(row.get(value_col)) for row in data])
        n = len(vals)
        ops_map = {"mean": np.nanmean, "std": np.nanstd, "min": np.nanmin, "max": np.nanmax}
        result_cols = {}
        for stat in stats_list:
            fn = ops_map.get(stat, np.nanmean)
            out = np.full(n, np.nan)
            for i in range(window - 1, n):
                out[i] = fn(vals[i - window + 1: i + 1])
            result_cols[f"{value_col}_rolling_{stat}_{window}"] = out
        rows_out = []
        for i, row in enumerate(data):
            r = dict(row)
            for col, arr in result_cols.items():
                r[col] = None if math.isnan(arr[i]) else round(float(arr[i]), 6)
            rows_out.append(r)
        return ToolResult.ok(
            f"Rolling stats '{value_col}' (window={window}): {stats_list}",
            {"column": value_col, "window": window, "stats": stats_list,
             "rows": _jsonify(rows_out[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"rolling_statistics failed: {exc}")


def change_point_pettitt(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Pettitt test for detecting a single change point in a series."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        if n < 5:
            return ToolResult.err("Need at least 5 data points.")
        # Compute U statistics
        U = np.zeros(n)
        for t in range(1, n):
            for i in range(t):
                U[t] += np.sign(arr[t] - arr[i])
        K = np.abs(U)
        cp_idx = int(np.argmax(K))
        K_max = float(K[cp_idx])
        # Approximate p-value
        p_value = float(2 * math.exp(-6 * K_max ** 2 / (n ** 3 + n ** 2)))
        mean_before = float(np.mean(arr[:cp_idx + 1]))
        mean_after = float(np.mean(arr[cp_idx + 1:])) if cp_idx < n - 1 else 0.0
        return ToolResult.ok(
            f"Pettitt test '{value_col}': change point at index {cp_idx}, "
            f"K={K_max:.2f}, p≈{p_value:.4f}",
            {"column": value_col, "n": n, "change_point_index": cp_idx,
             "K_statistic": round(K_max, 4), "p_value": round(p_value, 6),
             "significant": p_value < 0.05,
             "mean_before": round(mean_before, 4), "mean_after": round(mean_after, 4)},
        )
    except Exception as exc:
        return ToolResult.err(f"change_point_pettitt failed: {exc}")


def fft_dominant_freq(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """FFT top-N dominant frequencies."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        top_n = int(params.get("top_n", 5))
        sampling_rate = float(params.get("sampling_rate", 1.0))
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        if n < 8:
            return ToolResult.err("Need at least 8 data points for FFT.")
        fft_vals = np.fft.rfft(arr - np.mean(arr))
        freqs = np.fft.rfftfreq(n, d=1.0 / sampling_rate)
        amplitudes = np.abs(fft_vals)
        sorted_idx = np.argsort(amplitudes)[::-1]
        top_freqs = [
            {"rank": i + 1, "frequency": round(float(freqs[idx]), 6),
             "amplitude": round(float(amplitudes[idx]), 4),
             "period": round(1.0 / float(freqs[idx]), 4) if freqs[idx] > 0 else None}
            for i, idx in enumerate(sorted_idx[1:top_n + 1])
        ]
        dominant = top_freqs[0] if top_freqs else {}
        return ToolResult.ok(
            f"FFT '{value_col}' (n={n}): dominant freq={dominant.get('frequency')}, "
            f"amplitude={dominant.get('amplitude')}",
            {"column": value_col, "n": n, "sampling_rate": sampling_rate,
             "top_frequencies": top_freqs},
        )
    except Exception as exc:
        return ToolResult.err(f"fft_dominant_freq failed: {exc}")


def lag_correlation(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Cross-correlation between two columns at multiple lags."""
    try:
        import numpy as np
        col_x = params.get("col_x")
        col_y = params.get("col_y")
        max_lags = int(params.get("max_lags", 10))
        if not (col_x and col_y):
            sample = data[0] if data else {}
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if len(num_cols) < 2:
                return ToolResult.err("Need 2 numeric columns.")
            col_x, col_y = num_cols[0], num_cols[1]
        x = np.array([_safe_float(row.get(col_x)) for row in data])
        y = np.array([_safe_float(row.get(col_y)) for row in data])
        n = len(x)
        xc = x - np.nanmean(x)
        yc = y - np.nanmean(y)
        sx = float(np.nanstd(xc, ddof=1)) or 1.0
        sy = float(np.nanstd(yc, ddof=1)) or 1.0
        lags_result = []
        for lag in range(-max_lags, max_lags + 1):
            if lag >= 0:
                a, b = xc[:n - lag] if lag > 0 else xc, yc[lag:] if lag > 0 else yc
            else:
                a, b = xc[-lag:], yc[:n + lag]
            if len(a) > 2:
                r = float(np.nanmean(a * b)) / (sx * sy)
                lags_result.append({"lag": lag, "correlation": round(r, 4)})
        best = max(lags_result, key=lambda x: abs(x["correlation"]))
        return ToolResult.ok(
            f"Lag correlation '{col_x}' vs '{col_y}': best lag={best['lag']}, r={best['correlation']}",
            {"col_x": col_x, "col_y": col_y, "max_lags": max_lags,
             "best_lag": best["lag"], "best_correlation": best["correlation"],
             "lag_correlations": lags_result},
        )
    except Exception as exc:
        return ToolResult.err(f"lag_correlation failed: {exc}")


def trend_strength(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Ratio of trend variance to total variance."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        time_col = params.get("time_col")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        if n < 4:
            return ToolResult.err("Need at least 4 data points.")
        t = np.arange(n, dtype=float)
        slope = float(np.polyfit(t, arr, 1)[0])
        trend = slope * t + (float(np.mean(arr)) - slope * float(np.mean(t)))
        var_trend = float(np.var(trend, ddof=1))
        var_total = float(np.var(arr, ddof=1))
        strength = var_trend / var_total if var_total > 0 else 0.0
        return ToolResult.ok(
            f"Trend strength '{value_col}' (n={n}): {strength:.4f} "
            f"({'strong' if strength > 0.6 else 'moderate' if strength > 0.3 else 'weak'} trend)",
            {"column": value_col, "n": n, "slope": round(slope, 6),
             "trend_strength": round(strength, 4),
             "var_trend": round(var_trend, 6), "var_total": round(var_total, 6)},
        )
    except Exception as exc:
        return ToolResult.err(f"trend_strength failed: {exc}")


def run_length_encoding(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Detect consecutive run lengths above/below threshold."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        threshold = params.get("threshold")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        if threshold is None:
            threshold = float(np.mean(arr))
        above = arr >= float(threshold)
        runs = []
        i = 0
        while i < n:
            j = i
            while j < n and above[j] == above[i]:
                j += 1
            runs.append({"start": i, "end": j - 1, "length": j - i,
                         "above_threshold": bool(above[i]),
                         "mean_val": round(float(np.mean(arr[i:j])), 4)})
            i = j
        max_run = max(runs, key=lambda r: r["length"])
        return ToolResult.ok(
            f"Run-length encoding '{value_col}' (threshold={threshold:.3f}): "
            f"{len(runs)} runs, max run={max_run['length']}",
            {"column": value_col, "threshold": round(float(threshold), 4),
             "n_runs": len(runs), "max_run_length": max_run["length"],
             "runs": runs[:100]},
        )
    except Exception as exc:
        return ToolResult.err(f"run_length_encoding failed: {exc}")


def time_between_events(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Mean/std/max time between threshold crossings (upward)."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        threshold = float(params.get("threshold", 0.0))
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        above = arr >= threshold
        crossings = [i for i in range(1, len(above)) if above[i] and not above[i - 1]]
        if len(crossings) < 2:
            return ToolResult.ok(
                f"Time between events '{value_col}': fewer than 2 crossings of threshold={threshold}",
                {"column": value_col, "threshold": threshold, "n_crossings": len(crossings),
                 "intervals": []},
            )
        intervals = [crossings[i + 1] - crossings[i] for i in range(len(crossings) - 1)]
        return ToolResult.ok(
            f"Time between events '{value_col}' (threshold={threshold}): "
            f"{len(crossings)} events, mean interval={np.mean(intervals):.2f}",
            {"column": value_col, "threshold": threshold,
             "n_crossings": len(crossings), "crossing_indices": crossings,
             "mean_interval": round(float(np.mean(intervals)), 4),
             "std_interval": round(float(np.std(intervals)), 4),
             "max_interval": int(max(intervals)), "min_interval": int(min(intervals))},
        )
    except Exception as exc:
        return ToolResult.err(f"time_between_events failed: {exc}")


def velocity_acceleration(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """First and second derivative (velocity and acceleration) of a column."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array(vals)
        velocity = np.gradient(arr)
        acceleration = np.gradient(velocity)
        vel_col = f"{value_col}_velocity"
        acc_col = f"{value_col}_acceleration"
        rows_out = [
            {**row, vel_col: round(float(v), 6), acc_col: round(float(a), 6)}
            for row, v, a in zip(data, velocity, acceleration)
        ]
        max_vel_idx = int(np.argmax(np.abs(velocity)))
        return ToolResult.ok(
            f"Velocity/acceleration '{value_col}': max |velocity|={abs(velocity[max_vel_idx]):.4f} at idx {max_vel_idx}",
            {"column": value_col, "velocity_col": vel_col, "acceleration_col": acc_col,
             "max_velocity": round(float(np.max(np.abs(velocity))), 4),
             "max_acceleration": round(float(np.max(np.abs(acceleration))), 4),
             "rows": _jsonify(rows_out[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"velocity_acceleration failed: {exc}")


def seasonality_index(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Seasonality index: ratio of each period's mean to overall mean."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        period_col = params.get("period_col")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        if not period_col:
            return ToolResult.err("'period_col' required (e.g. month, day_of_week).")
        groups = {}
        for row in data:
            p = str(row.get(period_col, ""))
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                groups.setdefault(p, []).append(v)
        if not groups:
            return ToolResult.err("No valid data found.")
        overall_mean = float(np.mean([v for vals in groups.values() for v in vals]))
        si = {p: round(float(np.mean(vals)) / overall_mean, 4) if overall_mean != 0 else 1.0
              for p, vals in sorted(groups.items())}
        return ToolResult.ok(
            f"Seasonality index '{value_col}' by '{period_col}': "
            f"max={max(si.values()):.3f}, min={min(si.values()):.3f}",
            {"value_col": value_col, "period_col": period_col,
             "overall_mean": round(overall_mean, 4),
             "seasonality_index": si},
        )
    except Exception as exc:
        return ToolResult.err(f"seasonality_index failed: {exc}")


def time_weighted_average(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Time-weighted average (area under curve / time span)."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        time_col = params.get("time_col")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = np.array([_safe_float(row.get(value_col)) for row in data])
        if time_col:
            import pandas as pd
            times = pd.to_datetime([row.get(time_col) for row in data], errors="coerce")
            dt = np.array([(t - times[0]).total_seconds() for t in times])
        else:
            dt = np.arange(len(vals), dtype=float)
        mask = ~np.isnan(vals)
        v, t = vals[mask], dt[mask]
        if len(v) < 2:
            return ToolResult.err("Need at least 2 valid data points.")
        # Trapezoidal integration
        twa = float(np.trapz(v, t)) / (float(t[-1]) - float(t[0])) if t[-1] != t[0] else float(v[0])
        simple_mean = float(np.mean(v))
        return ToolResult.ok(
            f"Time-weighted average '{value_col}': TWA={twa:.4f}, simple mean={simple_mean:.4f}",
            {"column": value_col, "time_col": time_col, "n": len(v),
             "time_weighted_average": round(twa, 6),
             "simple_mean": round(simple_mean, 6),
             "time_span": round(float(t[-1] - t[0]), 4)},
        )
    except Exception as exc:
        return ToolResult.err(f"time_weighted_average failed: {exc}")
