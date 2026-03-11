"""Statistical processing tools (v15.3).

Tools: calc_statistics, find_outliers, normalization,
       frequency_analysis, distribution_test
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _jsonify, _safe_float


def calc_statistics(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Return Mean, Std, Median, Variance, Skewness, Kurtosis for a numeric column."""
    try:
        import numpy as np
        col = params.get("column")
        if not col:
            # Auto-detect first numeric column
            sample = data[0] if data else {}
            col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not col:
            return ToolResult.err("No numeric column found. Specify 'column' param.")

        vals = [_safe_float(row.get(col)) for row in data]
        vals = [v for v in vals if not math.isnan(v)]
        if not vals:
            return ToolResult.err(f"Column '{col}' has no numeric values.")

        arr = np.array(vals)
        n = len(arr)
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1)) if n > 1 else 0.0
        median = float(np.median(arr))
        variance = float(np.var(arr, ddof=1)) if n > 1 else 0.0
        # Skewness (Fisher)
        if std > 0 and n > 2:
            skewness = float(np.mean(((arr - mean) / std) ** 3))
        else:
            skewness = 0.0
        # Excess kurtosis (Fisher)
        if std > 0 and n > 3:
            kurtosis = float(np.mean(((arr - mean) / std) ** 4) - 3)
        else:
            kurtosis = 0.0

        payload = {
            "column": col,
            "count": n,
            "mean": round(mean, 6),
            "std": round(std, 6),
            "median": round(median, 6),
            "variance": round(variance, 6),
            "min": round(float(arr.min()), 6),
            "max": round(float(arr.max()), 6),
            "skewness": round(skewness, 6),
            "kurtosis": round(kurtosis, 6),
            "percentiles": {
                "25": round(float(np.percentile(arr, 25)), 6),
                "75": round(float(np.percentile(arr, 75)), 6),
                "90": round(float(np.percentile(arr, 90)), 6),
            },
        }
        summary = (
            f"Column '{col}': N={n}, Mean={mean:.4f}, Std={std:.4f}, "
            f"Skewness={skewness:.3f} ({'right-skewed' if skewness > 0.5 else 'left-skewed' if skewness < -0.5 else 'symmetric'})"
        )
        return ToolResult.ok(summary, payload)
    except Exception as exc:
        return ToolResult.err(f"calc_statistics failed: {exc}")


def find_outliers(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Identify outliers by sigma (z-score) or IQR method."""
    try:
        import numpy as np
        col = params.get("column")
        method = params.get("method", "sigma")
        if not col:
            sample = data[0] if data else {}
            col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not col:
            return ToolResult.err("No numeric column found.")

        vals = [(i, _safe_float(row.get(col))) for i, row in enumerate(data)]
        clean = [(i, v) for i, v in vals if not math.isnan(v)]
        arr = np.array([v for _, v in clean])

        if method == "iqr":
            q1, q3 = np.percentile(arr, 25), np.percentile(arr, 75)
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        else:
            mean, std = np.mean(arr), np.std(arr, ddof=1)
            lo, hi = mean - 3 * std, mean + 3 * std

        outliers = [
            {"index": i, "value": round(v, 6)}
            for i, v in clean
            if v < lo or v > hi
        ]
        rate = round(len(outliers) / len(clean) * 100, 2) if clean else 0
        summary = (
            f"Found {len(outliers)} outliers ({rate}%) in '{col}' using {method.upper()} "
            f"[bounds: {lo:.4f} ~ {hi:.4f}]"
        )
        return ToolResult.ok(summary, {
            "column": col, "method": method,
            "lower_bound": round(float(lo), 6),
            "upper_bound": round(float(hi), 6),
            "outlier_count": len(outliers),
            "outlier_rate_pct": rate,
            "outliers": outliers,
        })
    except Exception as exc:
        return ToolResult.err(f"find_outliers failed: {exc}")


def normalization(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Normalize a numeric column to [0,1] (min-max) or z-score."""
    try:
        import numpy as np
        col = params.get("column")
        method = params.get("method", "minmax")  # "minmax" | "zscore"
        if not col:
            sample = data[0] if data else {}
            col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not col:
            return ToolResult.err("No numeric column found.")

        vals = [_safe_float(row.get(col)) for row in data]
        arr = np.array(vals)
        mask = ~np.isnan(arr)

        if method == "zscore":
            mu, sigma = np.nanmean(arr), np.nanstd(arr, ddof=1)
            normalized = np.where(mask, (arr - mu) / (sigma if sigma else 1), np.nan)
        else:
            lo = params.get("min", float(np.nanmin(arr)))
            hi = params.get("max", float(np.nanmax(arr)))
            span = hi - lo or 1
            normalized = np.where(mask, (arr - lo) / span, np.nan)

        result_rows = [
            {**row, f"{col}_normalized": round(float(n), 6) if not math.isnan(n) else None}
            for row, n in zip(data, normalized)
        ]
        return ToolResult.ok(
            f"Normalized '{col}' using {method} → appended as '{col}_normalized'",
            {"method": method, "column": col, "rows": _jsonify(result_rows)},
        )
    except Exception as exc:
        return ToolResult.err(f"normalization failed: {exc}")


def frequency_analysis(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """FFT frequency analysis on a numeric column (if sample_rate given)
    OR value frequency count (categorical column)."""
    try:
        import numpy as np
        col = params.get("column")
        sample_rate = params.get("sample_rate")

        if not col:
            sample = data[0] if data else {}
            col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not col:
            return ToolResult.err("No numeric column found.")

        vals = [_safe_float(row.get(col)) for row in data]

        if sample_rate is not None:
            # FFT mode
            arr = np.array([v for v in vals if not math.isnan(v)])
            n = len(arr)
            if n < 4:
                return ToolResult.err("Need at least 4 data points for FFT.")
            fft_vals = np.fft.rfft(arr - np.mean(arr))
            freqs = np.fft.rfftfreq(n, d=1.0 / float(sample_rate))
            amplitudes = np.abs(fft_vals)
            top_idx = int(np.argmax(amplitudes[1:]) + 1)  # skip DC
            dominant_freq = float(freqs[top_idx])
            freq_list = [
                {"freq": round(float(f), 6), "amplitude": round(float(a), 6)}
                for f, a in zip(freqs[:20], amplitudes[:20])
            ]
            return ToolResult.ok(
                f"FFT on '{col}': dominant frequency = {dominant_freq:.4f} Hz",
                {"mode": "fft", "dominant_freq": dominant_freq,
                 "sample_rate": sample_rate, "frequencies": freq_list},
            )
        else:
            # Value count mode
            from collections import Counter
            str_vals = [str(row.get(col, "")) for row in data]
            counts = Counter(str_vals)
            total = len(data)
            freq_list = [
                {"value": v, "count": c, "pct": round(c / total * 100, 2)}
                for v, c in counts.most_common(50)
            ]
            return ToolResult.ok(
                f"Value frequency for '{col}': {len(counts)} unique values, top='{freq_list[0]['value']}' ({freq_list[0]['pct']}%)",
                {"mode": "count", "column": col, "unique_count": len(counts), "frequencies": freq_list},
            )
    except Exception as exc:
        return ToolResult.err(f"frequency_analysis failed: {exc}")


def distribution_test(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Test if data follows a distribution using Jarque-Bera normality test (pure numpy)."""
    try:
        import numpy as np
        col = params.get("column")
        dist = params.get("dist", "normal")
        if not col:
            sample = data[0] if data else {}
            col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not col:
            return ToolResult.err("No numeric column found.")

        vals = [_safe_float(row.get(col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        if n < 8:
            return ToolResult.err("Need at least 8 samples for distribution test.")

        mean, std = np.mean(arr), np.std(arr, ddof=1)
        if std == 0:
            return ToolResult.err("Zero variance — cannot test distribution.")

        # Jarque-Bera statistic
        s = float(np.mean(((arr - mean) / std) ** 3))   # skewness
        k = float(np.mean(((arr - mean) / std) ** 4))   # raw kurtosis
        jb = n / 6 * (s ** 2 + (k - 3) ** 2 / 4)

        # Approximate p-value from chi-squared(2) via Wilson-Hilferty
        # chi-sq CDF approx: 1 - exp(-jb/2) * (1 + jb/2) for df=2
        p_approx = math.exp(-jb / 2) * (1 + jb / 2) if jb < 50 else 0.0
        is_normal = p_approx > 0.05

        return ToolResult.ok(
            f"Jarque-Bera test on '{col}': JB={jb:.4f}, p≈{p_approx:.4f} "
            f"→ {'likely normal' if is_normal else 'NOT normal'} (α=0.05)",
            {
                "column": col, "dist": dist, "n": n,
                "jb_statistic": round(jb, 6),
                "p_value_approx": round(p_approx, 6),
                "skewness": round(s, 6),
                "excess_kurtosis": round(k - 3, 6),
                "is_normal": is_normal,
            },
        )
    except Exception as exc:
        return ToolResult.err(f"distribution_test failed: {exc}")
