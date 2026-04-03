"""Correlation and regression tools (v15.3).

Tools: correlation_analysis, linear_regression
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _safe_float


def correlation_analysis(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Pearson and Spearman correlation between two series."""
    try:
        import numpy as np

        col_a = params.get("col_a") or params.get("series_a")
        col_b = params.get("col_b") or params.get("series_b")

        # Auto-detect first two numeric columns if not specified
        if not (col_a and col_b):
            sample = data[0] if data else {}
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if len(num_cols) < 2:
                return ToolResult.err("Need at least 2 numeric columns. Specify 'col_a' and 'col_b'.")
            col_a, col_b = num_cols[0], num_cols[1]

        pairs = [
            (_safe_float(row.get(col_a)), _safe_float(row.get(col_b)))
            for row in data
        ]
        pairs = [(a, b) for a, b in pairs if not (math.isnan(a) or math.isnan(b))]
        if len(pairs) < 3:
            return ToolResult.err("Need at least 3 paired values.")

        x = np.array([p[0] for p in pairs])
        y = np.array([p[1] for p in pairs])

        # Pearson
        pearson = float(np.corrcoef(x, y)[0, 1])

        # Spearman (rank correlation)
        rx = np.argsort(np.argsort(x)).astype(float)
        ry = np.argsort(np.argsort(y)).astype(float)
        spearman = float(np.corrcoef(rx, ry)[0, 1])

        # P-value approximation (t-distribution, df=n-2)
        n = len(pairs)
        def _pval(r: float) -> float:
            if abs(r) >= 1.0:
                return 0.0
            t = r * math.sqrt(n - 2) / math.sqrt(1 - r ** 2)
            # rough two-tailed p-value using normal approx for large n
            return 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))

        pearson_p = _pval(pearson)
        spearman_p = _pval(spearman)

        def _strength(r: float) -> str:
            a = abs(r)
            if a > 0.7:  return "strong"
            if a > 0.4:  return "moderate"
            if a > 0.2:  return "weak"
            return "negligible"

        summary = (
            f"'{col_a}' ↔ '{col_b}': Pearson r={pearson:.4f} ({_strength(pearson)}), "
            f"Spearman ρ={spearman:.4f}, n={n}"
        )
        return ToolResult.ok(summary, {
            "col_a": col_a, "col_b": col_b, "n": n,
            "pearson_r": round(pearson, 6),
            "pearson_p": round(pearson_p, 6),
            "spearman_r": round(spearman, 6),
            "spearman_p": round(spearman_p, 6),
            "strength": _strength(pearson),
            "direction": "positive" if pearson > 0 else "negative",
        })
    except Exception as exc:
        return ToolResult.err(f"correlation_analysis failed: {exc}")


def linear_regression(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """OLS linear regression: slope, intercept, R², residuals."""
    try:
        import numpy as np

        x_col = params.get("x_col") or params.get("x")
        y_col = params.get("y_col") or params.get("y")

        if not (x_col and y_col):
            sample = data[0] if data else {}
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if len(num_cols) < 2:
                return ToolResult.err("Need 2 numeric columns. Specify 'x_col' and 'y_col'.")
            x_col, y_col = num_cols[0], num_cols[1]

        pairs = [
            (_safe_float(row.get(x_col)), _safe_float(row.get(y_col)))
            for row in data
        ]
        pairs = [(x, y) for x, y in pairs if not (math.isnan(x) or math.isnan(y))]
        if len(pairs) < 3:
            return ToolResult.err("Need at least 3 data points.")

        x = np.array([p[0] for p in pairs])
        y = np.array([p[1] for p in pairs])

        coeffs = np.polyfit(x, y, 1)
        slope, intercept = float(coeffs[0]), float(coeffs[1])

        y_pred = slope * x + intercept
        ss_res = float(np.sum((y - y_pred) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        # Residuals
        residuals = [round(float(r), 6) for r in (y - y_pred)]

        summary = (
            f"Linear regression '{y_col}' ~ '{x_col}': "
            f"y = {slope:.6f}x + {intercept:.6f}, R²={r_squared:.4f}"
        )
        return ToolResult.ok(summary, {
            "x_col": x_col, "y_col": y_col, "n": len(pairs),
            "slope": round(slope, 8),
            "intercept": round(intercept, 8),
            "r_squared": round(r_squared, 6),
            "rmse": round(math.sqrt(ss_res / len(pairs)), 6),
            "equation": f"y = {slope:.6f}x + {intercept:.6f}",
            "residuals": residuals[:50],  # cap for large datasets
        })
    except Exception as exc:
        return ToolResult.err(f"linear_regression failed: {exc}")
