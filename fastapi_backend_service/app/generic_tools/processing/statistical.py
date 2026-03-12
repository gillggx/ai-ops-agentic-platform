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


# ── NEW STATISTICAL TOOLS (v15.4) ─────────────────────────────────────────────

def ttest_one_sample(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """One-sample t-test: test if column mean equals target_mean."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        target_mean = float(params.get("target_mean", 0.0))
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found. Specify 'value_col'.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        if n < 2:
            return ToolResult.err("Need at least 2 data points.")
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1))
        se = std / math.sqrt(n)
        t_stat = (mean - target_mean) / se if se > 0 else 0.0
        # Approximate two-tailed p-value using t-distribution approximation
        try:
            from scipy import stats
            p_value = float(stats.ttest_1samp(arr, target_mean).pvalue)
        except ImportError:
            # Normal approximation for large n
            import math as _m
            p_value = float(2 * (1 - 0.5 * (1 + _m.erf(abs(t_stat) / _m.sqrt(2)))))
        reject = p_value < 0.05
        return ToolResult.ok(
            f"One-sample t-test '{value_col}': t={t_stat:.4f}, p={p_value:.4f} "
            f"→ {'REJECT H0' if reject else 'fail to reject H0'} (μ₀={target_mean})",
            {"column": value_col, "n": n, "sample_mean": round(mean, 6),
             "target_mean": target_mean, "t_statistic": round(t_stat, 6),
             "p_value": round(p_value, 6), "reject_h0": reject, "alpha": 0.05},
        )
    except Exception as exc:
        return ToolResult.err(f"ttest_one_sample failed: {exc}")


def ttest_two_sample(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Two independent-sample t-test comparing group means."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        group_col = params.get("group_col")
        if not (value_col and group_col):
            return ToolResult.err("'value_col' and 'group_col' required.")
        groups = {}
        for row in data:
            g = str(row.get(group_col, ""))
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                groups.setdefault(g, []).append(v)
        if len(groups) < 2:
            return ToolResult.err("Need at least 2 groups.")
        keys = list(groups.keys())[:2]
        a, b = np.array(groups[keys[0]]), np.array(groups[keys[1]])
        mean_a, mean_b = float(np.mean(a)), float(np.mean(b))
        try:
            from scipy import stats
            t_stat, p_value = stats.ttest_ind(a, b)
            t_stat, p_value = float(t_stat), float(p_value)
        except ImportError:
            na, nb = len(a), len(b)
            sa, sb = float(np.std(a, ddof=1)), float(np.std(b, ddof=1))
            se = math.sqrt(sa**2/na + sb**2/nb) if (na > 1 and nb > 1) else 1e-9
            t_stat = (mean_a - mean_b) / se if se > 0 else 0.0
            p_value = float(2 * (1 - 0.5 * (1 + math.erf(abs(t_stat) / math.sqrt(2)))))
        reject = p_value < 0.05
        return ToolResult.ok(
            f"Two-sample t-test '{value_col}': {keys[0]} (n={len(a)}) vs {keys[1]} (n={len(b)}), "
            f"t={t_stat:.4f}, p={p_value:.4f} → {'REJECT H0' if reject else 'fail to reject H0'}",
            {"value_col": value_col, "group_col": group_col,
             "group_a": keys[0], "mean_a": round(mean_a, 6), "n_a": len(a),
             "group_b": keys[1], "mean_b": round(mean_b, 6), "n_b": len(b),
             "t_statistic": round(t_stat, 6), "p_value": round(p_value, 6),
             "reject_h0": reject, "alpha": 0.05},
        )
    except Exception as exc:
        return ToolResult.err(f"ttest_two_sample failed: {exc}")


def chi_square_test(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Chi-square test of independence (two columns) or goodness-of-fit (one column)."""
    try:
        import numpy as np
        col_a = params.get("col_a")
        col_b = params.get("col_b")
        if not col_a:
            sample = data[0] if data else {}
            str_cols = [k for k, v in sample.items() if isinstance(v, str)]
            col_a = str_cols[0] if str_cols else None
        if not col_a:
            return ToolResult.err("'col_a' required.")
        if col_b:
            # Independence test
            try:
                import pandas as pd
                from scipy.stats import chi2_contingency
                df = pd.DataFrame(data)
                ct = pd.crosstab(df[col_a], df[col_b])
                chi2, p, dof, _ = chi2_contingency(ct.values)
                return ToolResult.ok(
                    f"Chi-square independence test '{col_a}' vs '{col_b}': "
                    f"χ²={chi2:.4f}, dof={dof}, p={p:.4f} → "
                    f"{'DEPENDENT' if p < 0.05 else 'independent'}",
                    {"col_a": col_a, "col_b": col_b, "chi2": round(float(chi2), 6),
                     "dof": dof, "p_value": round(float(p), 6), "reject_h0": p < 0.05},
                )
            except ImportError:
                return ToolResult.err("scipy required for chi-square independence test.")
        else:
            # Goodness-of-fit
            from collections import Counter
            counts = Counter(str(row.get(col_a, "")) for row in data)
            observed = np.array(list(counts.values()), dtype=float)
            expected = np.full(len(observed), observed.mean())
            chi2 = float(np.sum((observed - expected) ** 2 / expected))
            dof = len(observed) - 1
            p_approx = math.exp(-chi2 / 2) if chi2 < 100 else 0.0
            return ToolResult.ok(
                f"Chi-square goodness-of-fit '{col_a}': χ²={chi2:.4f}, dof={dof}, p≈{p_approx:.4f}",
                {"col": col_a, "chi2": round(chi2, 6), "dof": dof,
                 "p_value_approx": round(p_approx, 6), "reject_h0": p_approx < 0.05,
                 "counts": dict(counts)},
            )
    except Exception as exc:
        return ToolResult.err(f"chi_square_test failed: {exc}")


def anova_oneway(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """One-way ANOVA across groups."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        group_col = params.get("group_col")
        if not (value_col and group_col):
            return ToolResult.err("'value_col' and 'group_col' required.")
        groups = {}
        for row in data:
            g = str(row.get(group_col, ""))
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                groups.setdefault(g, []).append(v)
        if len(groups) < 2:
            return ToolResult.err("Need at least 2 groups.")
        arrays = [np.array(v) for v in groups.values()]
        try:
            from scipy.stats import f_oneway
            f_stat, p_value = f_oneway(*arrays)
            f_stat, p_value = float(f_stat), float(p_value)
        except ImportError:
            grand_mean = float(np.mean(np.concatenate(arrays)))
            ss_between = sum(len(a) * (float(np.mean(a)) - grand_mean) ** 2 for a in arrays)
            ss_within = sum(float(np.sum((a - np.mean(a)) ** 2)) for a in arrays)
            df_between = len(arrays) - 1
            df_within = sum(len(a) - 1 for a in arrays)
            f_stat = (ss_between / df_between) / (ss_within / df_within) if df_within > 0 and ss_within > 0 else 0.0
            p_value = math.exp(-f_stat / 2) if f_stat < 50 else 0.0
        group_stats = {g: {"mean": round(float(np.mean(a)), 4), "n": len(a)} for g, a in groups.items()}
        return ToolResult.ok(
            f"One-way ANOVA '{value_col}' by '{group_col}': F={f_stat:.4f}, p={p_value:.4f} "
            f"→ {'SIGNIFICANT' if p_value < 0.05 else 'not significant'}",
            {"value_col": value_col, "group_col": group_col, "f_statistic": round(f_stat, 6),
             "p_value": round(p_value, 6), "reject_h0": p_value < 0.05,
             "n_groups": len(groups), "group_stats": group_stats},
        )
    except Exception as exc:
        return ToolResult.err(f"anova_oneway failed: {exc}")


def mann_whitney_u(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Mann-Whitney U non-parametric rank test for two groups."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        group_col = params.get("group_col")
        if not (value_col and group_col):
            return ToolResult.err("'value_col' and 'group_col' required.")
        groups = {}
        for row in data:
            g = str(row.get(group_col, ""))
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                groups.setdefault(g, []).append(v)
        if len(groups) < 2:
            return ToolResult.err("Need at least 2 groups.")
        keys = list(groups.keys())[:2]
        a, b = np.array(groups[keys[0]]), np.array(groups[keys[1]])
        try:
            from scipy.stats import mannwhitneyu
            stat, p_value = mannwhitneyu(a, b, alternative="two-sided")
            stat, p_value = float(stat), float(p_value)
        except ImportError:
            na, nb = len(a), len(b)
            u_stat = 0.0
            for ai in a:
                for bi in b:
                    if ai > bi:
                        u_stat += 1
                    elif ai == bi:
                        u_stat += 0.5
            stat = u_stat
            mu = na * nb / 2
            sigma = math.sqrt(na * nb * (na + nb + 1) / 12) + 1e-9
            z = (stat - mu) / sigma
            p_value = float(2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2)))))
        return ToolResult.ok(
            f"Mann-Whitney U '{value_col}': {keys[0]} vs {keys[1]}, U={stat:.2f}, p={p_value:.4f} "
            f"→ {'SIGNIFICANT' if p_value < 0.05 else 'not significant'}",
            {"value_col": value_col, "group_col": group_col,
             "group_a": keys[0], "n_a": len(a), "group_b": keys[1], "n_b": len(b),
             "u_statistic": round(stat, 4), "p_value": round(p_value, 6),
             "reject_h0": p_value < 0.05},
        )
    except Exception as exc:
        return ToolResult.err(f"mann_whitney_u failed: {exc}")


def kruskal_wallis(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Kruskal-Wallis non-parametric multi-group test."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        group_col = params.get("group_col")
        if not (value_col and group_col):
            return ToolResult.err("'value_col' and 'group_col' required.")
        groups = {}
        for row in data:
            g = str(row.get(group_col, ""))
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                groups.setdefault(g, []).append(v)
        if len(groups) < 2:
            return ToolResult.err("Need at least 2 groups.")
        arrays = [np.array(v) for v in groups.values()]
        try:
            from scipy.stats import kruskal
            h_stat, p_value = kruskal(*arrays)
            h_stat, p_value = float(h_stat), float(p_value)
        except ImportError:
            all_vals = np.concatenate(arrays)
            n = len(all_vals)
            ranks = np.argsort(np.argsort(all_vals)) + 1
            offset = 0
            h_stat = 0.0
            for a in arrays:
                ni = len(a)
                ri = ranks[offset:offset + ni]
                h_stat += ni * (float(np.mean(ri)) - (n + 1) / 2) ** 2
                offset += ni
            h_stat = 12 / (n * (n + 1)) * h_stat
            p_value = math.exp(-h_stat / 2) if h_stat < 50 else 0.0
        return ToolResult.ok(
            f"Kruskal-Wallis '{value_col}' by '{group_col}': H={h_stat:.4f}, p={p_value:.4f} "
            f"→ {'SIGNIFICANT' if p_value < 0.05 else 'not significant'}",
            {"value_col": value_col, "group_col": group_col,
             "h_statistic": round(h_stat, 6), "p_value": round(p_value, 6),
             "reject_h0": p_value < 0.05, "n_groups": len(groups),
             "group_sizes": {g: len(a) for g, a in groups.items()}},
        )
    except Exception as exc:
        return ToolResult.err(f"kruskal_wallis failed: {exc}")


def shapiro_wilk(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Shapiro-Wilk normality test (n <= 5000)."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        if n < 3:
            return ToolResult.err("Need at least 3 data points.")
        if n > 5000:
            arr = arr[:5000]
            n = 5000
        try:
            from scipy.stats import shapiro
            w_stat, p_value = shapiro(arr)
            w_stat, p_value = float(w_stat), float(p_value)
        except ImportError:
            # Jarque-Bera as fallback
            mean, std = float(np.mean(arr)), float(np.std(arr, ddof=1))
            s = float(np.mean(((arr - mean) / std) ** 3))
            k = float(np.mean(((arr - mean) / std) ** 4))
            jb = n / 6 * (s ** 2 + (k - 3) ** 2 / 4)
            w_stat = max(0.0, 1.0 - jb / n)
            p_value = math.exp(-jb / 2) * (1 + jb / 2) if jb < 50 else 0.0
        is_normal = p_value > 0.05
        return ToolResult.ok(
            f"Shapiro-Wilk '{value_col}' (n={n}): W={w_stat:.4f}, p={p_value:.4f} "
            f"→ {'likely normal' if is_normal else 'NOT normal'} (α=0.05)",
            {"column": value_col, "n": n, "w_statistic": round(w_stat, 6),
             "p_value": round(p_value, 6), "is_normal": is_normal},
        )
    except Exception as exc:
        return ToolResult.err(f"shapiro_wilk failed: {exc}")


def levene_variance(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Levene's test for equality of variances across groups."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        group_col = params.get("group_col")
        if not (value_col and group_col):
            return ToolResult.err("'value_col' and 'group_col' required.")
        groups = {}
        for row in data:
            g = str(row.get(group_col, ""))
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                groups.setdefault(g, []).append(v)
        if len(groups) < 2:
            return ToolResult.err("Need at least 2 groups.")
        arrays = [np.array(v) for v in groups.values()]
        try:
            from scipy.stats import levene
            w_stat, p_value = levene(*arrays)
            w_stat, p_value = float(w_stat), float(p_value)
        except ImportError:
            # Brown-Forsythe approximation using medians
            z_groups = [np.abs(a - np.median(a)) for a in arrays]
            all_z = np.concatenate(z_groups)
            grand_mean = float(np.mean(all_z))
            n_total = len(all_z)
            k = len(arrays)
            ss_between = sum(len(z) * (float(np.mean(z)) - grand_mean) ** 2 for z in z_groups)
            ss_within = sum(float(np.sum((z - np.mean(z)) ** 2)) for z in z_groups)
            df1, df2 = k - 1, n_total - k
            w_stat = (ss_between / df1) / (ss_within / df2) if df2 > 0 and ss_within > 0 else 0.0
            p_value = math.exp(-w_stat / 2) if w_stat < 50 else 0.0
        equal_var = p_value > 0.05
        return ToolResult.ok(
            f"Levene test '{value_col}' by '{group_col}': W={w_stat:.4f}, p={p_value:.4f} "
            f"→ {'equal variance' if equal_var else 'UNEQUAL variance'} (α=0.05)",
            {"value_col": value_col, "group_col": group_col,
             "w_statistic": round(w_stat, 6), "p_value": round(p_value, 6),
             "equal_variance": equal_var,
             "group_stds": {g: round(float(np.std(np.array(v), ddof=1)), 4)
                            for g, v in groups.items()}},
        )
    except Exception as exc:
        return ToolResult.err(f"levene_variance failed: {exc}")


def spearman_correlation(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Spearman rank correlation between two columns."""
    try:
        import numpy as np
        col_x = params.get("col_x")
        col_y = params.get("col_y")
        if not (col_x and col_y):
            sample = data[0] if data else {}
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if len(num_cols) < 2:
                return ToolResult.err("Need 2 numeric columns.")
            col_x, col_y = num_cols[0], num_cols[1]
        pairs = [(row.get(col_x), row.get(col_y)) for row in data]
        pairs = [(x, y) for x, y in pairs
                 if not (math.isnan(_safe_float(x)) or math.isnan(_safe_float(y)))]
        if len(pairs) < 3:
            return ToolResult.err("Need at least 3 valid pairs.")
        x_arr = np.array([_safe_float(p[0]) for p in pairs])
        y_arr = np.array([_safe_float(p[1]) for p in pairs])
        try:
            from scipy.stats import spearmanr
            rho, p_value = spearmanr(x_arr, y_arr)
            rho, p_value = float(rho), float(p_value)
        except ImportError:
            rank_x = np.argsort(np.argsort(x_arr)).astype(float)
            rank_y = np.argsort(np.argsort(y_arr)).astype(float)
            n = len(rank_x)
            d2 = np.sum((rank_x - rank_y) ** 2)
            rho = 1 - 6 * float(d2) / (n * (n * n - 1)) if n > 2 else 0.0
            t_stat = rho * math.sqrt((n - 2) / (1 - rho ** 2 + 1e-9))
            p_value = float(2 * (1 - 0.5 * (1 + math.erf(abs(t_stat) / math.sqrt(2)))))
        return ToolResult.ok(
            f"Spearman correlation '{col_x}' vs '{col_y}' (n={len(pairs)}): "
            f"ρ={rho:.4f}, p={p_value:.4f}",
            {"col_x": col_x, "col_y": col_y, "n": len(pairs),
             "spearman_rho": round(rho, 6), "p_value": round(p_value, 6),
             "significant": p_value < 0.05},
        )
    except Exception as exc:
        return ToolResult.err(f"spearman_correlation failed: {exc}")


def partial_correlation(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Partial correlation between col_x and col_y controlling for control_col."""
    try:
        import numpy as np
        col_x = params.get("col_x")
        col_y = params.get("col_y")
        control_col = params.get("control_col")
        if not (col_x and col_y and control_col):
            return ToolResult.err("'col_x', 'col_y', and 'control_col' required.")
        rows = [(row.get(col_x), row.get(col_y), row.get(control_col)) for row in data]
        rows = [(x, y, c) for x, y, c in rows
                if not any(math.isnan(_safe_float(v)) for v in (x, y, c))]
        if len(rows) < 4:
            return ToolResult.err("Need at least 4 valid rows.")
        x = np.array([_safe_float(r[0]) for r in rows])
        y = np.array([_safe_float(r[1]) for r in rows])
        c = np.array([_safe_float(r[2]) for r in rows])

        def _residuals(a, b):
            slope = np.cov(a, b)[0, 1] / (np.var(b, ddof=1) + 1e-12)
            return a - slope * b

        rx = _residuals(x, c)
        ry = _residuals(y, c)
        r = float(np.corrcoef(rx, ry)[0, 1])
        n = len(rows)
        t_stat = r * math.sqrt((n - 3) / (1 - r ** 2 + 1e-12))
        p_value = float(2 * (1 - 0.5 * (1 + math.erf(abs(t_stat) / math.sqrt(2)))))
        return ToolResult.ok(
            f"Partial correlation '{col_x}'↔'{col_y}' controlling '{control_col}': "
            f"r={r:.4f}, p={p_value:.4f}",
            {"col_x": col_x, "col_y": col_y, "control_col": control_col,
             "n": n, "partial_r": round(r, 6), "p_value": round(p_value, 6),
             "significant": p_value < 0.05},
        )
    except Exception as exc:
        return ToolResult.err(f"partial_correlation failed: {exc}")


def bootstrap_ci(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Bootstrap 95% confidence interval for the mean."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        n_boot = int(params.get("n_boot", 1000))
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array([v for v in vals if not math.isnan(v)])
        n = len(arr)
        if n < 2:
            return ToolResult.err("Need at least 2 data points.")
        rng = np.random.default_rng(42)
        boot_means = [float(np.mean(rng.choice(arr, size=n, replace=True))) for _ in range(n_boot)]
        boot_means = sorted(boot_means)
        ci_lower = boot_means[int(0.025 * n_boot)]
        ci_upper = boot_means[int(0.975 * n_boot)]
        observed_mean = float(np.mean(arr))
        return ToolResult.ok(
            f"Bootstrap CI '{value_col}' (n={n}, B={n_boot}): "
            f"mean={observed_mean:.4f}, 95% CI=[{ci_lower:.4f}, {ci_upper:.4f}]",
            {"column": value_col, "n": n, "n_bootstrap": n_boot,
             "mean": round(observed_mean, 6),
             "ci_lower_95": round(ci_lower, 6), "ci_upper_95": round(ci_upper, 6),
             "ci_width": round(ci_upper - ci_lower, 6)},
        )
    except Exception as exc:
        return ToolResult.err(f"bootstrap_ci failed: {exc}")


def cohens_d(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Cohen's d effect size between two groups."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        group_col = params.get("group_col")
        if not (value_col and group_col):
            return ToolResult.err("'value_col' and 'group_col' required.")
        groups = {}
        for row in data:
            g = str(row.get(group_col, ""))
            v = _safe_float(row.get(value_col))
            if not math.isnan(v):
                groups.setdefault(g, []).append(v)
        if len(groups) < 2:
            return ToolResult.err("Need at least 2 groups.")
        keys = list(groups.keys())[:2]
        a, b = np.array(groups[keys[0]]), np.array(groups[keys[1]])
        mean_diff = float(np.mean(a)) - float(np.mean(b))
        pooled_std = math.sqrt(((len(a) - 1) * float(np.var(a, ddof=1)) +
                                (len(b) - 1) * float(np.var(b, ddof=1))) /
                               (len(a) + len(b) - 2 + 1e-12))
        d = mean_diff / pooled_std if pooled_std > 0 else 0.0
        magnitude = "small" if abs(d) < 0.5 else "medium" if abs(d) < 0.8 else "large"
        return ToolResult.ok(
            f"Cohen's d '{value_col}': {keys[0]} vs {keys[1]}: d={d:.4f} ({magnitude} effect)",
            {"value_col": value_col, "group_col": group_col,
             "group_a": keys[0], "mean_a": round(float(np.mean(a)), 4), "n_a": len(a),
             "group_b": keys[1], "mean_b": round(float(np.mean(b)), 4), "n_b": len(b),
             "cohens_d": round(d, 6), "pooled_std": round(pooled_std, 6),
             "magnitude": magnitude},
        )
    except Exception as exc:
        return ToolResult.err(f"cohens_d failed: {exc}")


def percentile_analysis(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Compute configurable percentiles (P5, P25, P50, P75, P95, P99)."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        group_col = params.get("group_col")
        pcts = params.get("percentiles", [5, 25, 50, 75, 95, 99])
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")

        def _compute(arr):
            return {f"P{p}": round(float(np.percentile(arr, p)), 6) for p in pcts}

        if group_col:
            groups = {}
            for row in data:
                g = str(row.get(group_col, ""))
                v = _safe_float(row.get(value_col))
                if not math.isnan(v):
                    groups.setdefault(g, []).append(v)
            result = {g: _compute(np.array(v)) for g, v in groups.items()}
            return ToolResult.ok(
                f"Percentile analysis '{value_col}' by '{group_col}': {len(groups)} groups",
                {"value_col": value_col, "group_col": group_col,
                 "percentiles": list(pcts), "groups": result},
            )
        else:
            vals = [_safe_float(row.get(value_col)) for row in data]
            arr = np.array([v for v in vals if not math.isnan(v)])
            result = _compute(arr)
            return ToolResult.ok(
                f"Percentile analysis '{value_col}' (n={len(arr)}): "
                f"P50={result.get('P50')}, P95={result.get('P95')}",
                {"value_col": value_col, "n": len(arr), **result},
            )
    except Exception as exc:
        return ToolResult.err(f"percentile_analysis failed: {exc}")


def outlier_score_zscore(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Z-score per row with outlier flag."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        threshold = float(params.get("threshold", 3.0))
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = [_safe_float(row.get(value_col)) for row in data]
        arr = np.array(vals)
        mean = float(np.nanmean(arr))
        std = float(np.nanstd(arr, ddof=1)) or 1.0
        z_scores = (arr - mean) / std
        rows_out = []
        outlier_count = 0
        for i, (row, z) in enumerate(zip(data, z_scores)):
            is_outlier = bool(abs(z) > threshold)
            if is_outlier:
                outlier_count += 1
            rows_out.append({**row, f"{value_col}_zscore": round(float(z), 4),
                             f"{value_col}_outlier": is_outlier})
        return ToolResult.ok(
            f"Z-score outlier scoring '{value_col}': {outlier_count}/{len(data)} outliers "
            f"(threshold={threshold}σ)",
            {"column": value_col, "threshold": threshold, "mean": round(mean, 6),
             "std": round(std, 6), "outlier_count": outlier_count,
             "outlier_pct": round(outlier_count / len(data) * 100, 2),
             "rows": _jsonify(rows_out[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"outlier_score_zscore failed: {exc}")


def rank_transform(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Rank-transform values for non-parametric pre-processing."""
    try:
        import numpy as np
        value_col = params.get("value_col")
        method = params.get("method", "average")
        group_col = params.get("group_col")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")

        def _rank(arr):
            try:
                from scipy.stats import rankdata
                return rankdata(arr, method=method).tolist()
            except ImportError:
                return (np.argsort(np.argsort(arr)) + 1).tolist()

        rows_out = [dict(r) for r in data]
        out_col = f"{value_col}_rank"
        if group_col:
            groups = {}
            for i, row in enumerate(rows_out):
                g = str(row.get(group_col, ""))
                groups.setdefault(g, []).append(i)
            for g, idxs in groups.items():
                vals = np.array([_safe_float(rows_out[i].get(value_col)) for i in idxs])
                ranks = _rank(vals)
                for idx, rank in zip(idxs, ranks):
                    rows_out[idx][out_col] = round(float(rank), 4)
        else:
            vals = np.array([_safe_float(row.get(value_col)) for row in rows_out])
            ranks = _rank(vals)
            for row, rank in zip(rows_out, ranks):
                row[out_col] = round(float(rank), 4)

        return ToolResult.ok(
            f"Rank transform '{value_col}' → '{out_col}' (method={method})",
            {"column": value_col, "out_column": out_col, "method": method,
             "rows": _jsonify(rows_out[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"rank_transform failed: {exc}")
