"""ML-style tools without scipy/sklearn (v15.3).

Tools: cluster_data, vector_similarity
"""
from __future__ import annotations

import math
import random
from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _jsonify, _safe_float


def cluster_data(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """K-means clustering (pure numpy, no sklearn)."""
    try:
        import numpy as np

        k = int(params.get("k", 3))
        max_iter = int(params.get("max_iter", 100))
        cols = params.get("columns")

        df_rows = []
        for row in data:
            if cols:
                vec = [_safe_float(row.get(c, 0)) for c in cols]
            else:
                vec = [_safe_float(v) for v in row.values() if isinstance(v, (int, float))]
            if any(math.isnan(v) for v in vec):
                continue
            df_rows.append(vec)

        if len(df_rows) < k:
            return ToolResult.err(f"Need at least {k} valid rows for k={k}.")

        X = np.array(df_rows, dtype=float)
        n, d = X.shape

        # Initialize centroids (k-means++ style: pick random then farthest)
        indices = list(range(n))
        random.shuffle(indices)
        centroids = X[indices[:k]].copy()

        labels = np.zeros(n, dtype=int)
        for _ in range(max_iter):
            # Assign
            dists = np.array([[np.linalg.norm(x - c) for c in centroids] for x in X])
            new_labels = np.argmin(dists, axis=1)
            if np.array_equal(new_labels, labels):
                break
            labels = new_labels
            # Update centroids
            for j in range(k):
                members = X[labels == j]
                if len(members):
                    centroids[j] = members.mean(axis=0)

        # Inertia (within-cluster sum of squares)
        inertia = float(sum(
            np.linalg.norm(X[i] - centroids[labels[i]]) ** 2
            for i in range(n)
        ))

        cluster_sizes = {int(j): int((labels == j).sum()) for j in range(k)}
        result_rows = [
            {**row, "cluster": int(labels[i])}
            for i, row in enumerate(data)
            if i < len(labels)
        ]

        return ToolResult.ok(
            f"K-means (k={k}): {n} points → clusters {cluster_sizes}, inertia={inertia:.2f}",
            {
                "k": k, "n": n, "inertia": round(inertia, 4),
                "cluster_sizes": cluster_sizes,
                "centroids": [
                    {f"dim_{j}": round(float(v), 6) for j, v in enumerate(c)}
                    for c in centroids
                ],
                "rows": result_rows[:500],
            },
        )
    except Exception as exc:
        return ToolResult.err(f"cluster_data failed: {exc}")


def vector_similarity(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Cosine similarity and Euclidean distance between two vectors."""
    try:
        import numpy as np

        vec_a = params.get("vec_a")
        vec_b = params.get("vec_b")
        col_a = params.get("col_a")
        col_b = params.get("col_b")

        # If vectors not directly provided, extract from data columns
        if not (vec_a and vec_b) and (col_a and col_b):
            vec_a = [_safe_float(row.get(col_a)) for row in data]
            vec_b = [_safe_float(row.get(col_b)) for row in data]
            vec_a = [v for v in vec_a if not math.isnan(v)]
            vec_b = [v for v in vec_b if not math.isnan(v)]

        if not (vec_a and vec_b):
            return ToolResult.err("Provide 'vec_a' + 'vec_b' (float arrays) or 'col_a' + 'col_b'.")

        a = np.array(vec_a, dtype=float)
        b = np.array(vec_b, dtype=float)

        if len(a) != len(b):
            min_len = min(len(a), len(b))
            a, b = a[:min_len], b[:min_len]

        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        cosine = float(np.dot(a, b) / (norm_a * norm_b)) if (norm_a and norm_b) else 0.0
        euclidean = float(np.linalg.norm(a - b))
        manhattan = float(np.sum(np.abs(a - b)))

        return ToolResult.ok(
            f"Vector similarity (n={len(a)}): cosine={cosine:.6f}, euclidean={euclidean:.6f}",
            {
                "n": len(a),
                "cosine_similarity": round(cosine, 8),
                "cosine_distance": round(1 - cosine, 8),
                "euclidean_distance": round(euclidean, 8),
                "manhattan_distance": round(manhattan, 8),
            },
        )
    except Exception as exc:
        return ToolResult.err(f"vector_similarity failed: {exc}")


# ── NEW ML TOOLS (v15.4) ──────────────────────────────────────────────────────

def pca_variance(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """PCA explained variance ratio for specified feature columns."""
    try:
        import numpy as np
        feature_cols = params.get("feature_cols", [])
        n_components = int(params.get("n_components", 3))
        if not feature_cols:
            sample = data[0] if data else {}
            feature_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
        if len(feature_cols) < 2:
            return ToolResult.err("Need at least 2 feature columns.")
        rows = []
        for row in data:
            vec = [_safe_float(row.get(c, 0)) for c in feature_cols]
            if not any(math.isnan(v) for v in vec):
                rows.append(vec)
        if len(rows) < 2:
            return ToolResult.err("Insufficient valid rows.")
        X = np.array(rows, dtype=float)
        X_centered = X - X.mean(axis=0)
        n_comp = min(n_components, X.shape[1], X.shape[0] - 1)
        try:
            from sklearn.decomposition import PCA
            pca = PCA(n_components=n_comp)
            pca.fit(X_centered)
            evr = [float(v) for v in pca.explained_variance_ratio_]
        except ImportError:
            cov = np.cov(X_centered.T)
            eigenvalues = np.linalg.eigvalsh(cov)[::-1]
            total_var = float(np.sum(eigenvalues))
            evr = [float(e) / total_var for e in eigenvalues[:n_comp]]
        cumulative = [sum(evr[:i + 1]) for i in range(len(evr))]
        components = [{"pc": i + 1, "explained_var_ratio": round(evr[i], 4),
                       "cumulative": round(cumulative[i], 4)} for i in range(len(evr))]
        return ToolResult.ok(
            f"PCA ({len(feature_cols)} features, {n_comp} components): "
            f"cumulative variance={cumulative[-1]:.3f}",
            {"feature_cols": feature_cols, "n_samples": len(rows),
             "n_components": n_comp, "components": components,
             "total_explained": round(cumulative[-1], 4)},
        )
    except Exception as exc:
        return ToolResult.err(f"pca_variance failed: {exc}")


def vif_analysis(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Variance Inflation Factor for detecting multicollinearity."""
    try:
        import numpy as np
        feature_cols = params.get("feature_cols", [])
        if not feature_cols:
            sample = data[0] if data else {}
            feature_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
        if len(feature_cols) < 2:
            return ToolResult.err("Need at least 2 feature columns.")
        rows = []
        for row in data:
            vec = [_safe_float(row.get(c, 0)) for c in feature_cols]
            if not any(math.isnan(v) for v in vec):
                rows.append(vec)
        X = np.array(rows, dtype=float)
        if len(X) < len(feature_cols) + 1:
            return ToolResult.err("Need more rows than features for VIF.")
        vifs = []
        for i, col in enumerate(feature_cols):
            y = X[:, i]
            x_other = np.delete(X, i, axis=1)
            x_with_const = np.column_stack([np.ones(len(x_other)), x_other])
            try:
                coeffs, _, _, _ = np.linalg.lstsq(x_with_const, y, rcond=None)
                y_hat = x_with_const @ coeffs
                ss_res = float(np.sum((y - y_hat) ** 2))
                ss_tot = float(np.sum((y - np.mean(y)) ** 2))
                r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
                vif = 1 / (1 - r2) if r2 < 1 else float("inf")
            except Exception:
                vif = float("inf")
            vifs.append({"feature": col, "vif": round(float(vif), 4),
                         "multicollinear": vif > 10})
        high_vif = [v for v in vifs if v["vif"] > 10]
        return ToolResult.ok(
            f"VIF analysis ({len(feature_cols)} features): "
            f"{len(high_vif)} features with VIF > 10",
            {"feature_cols": feature_cols, "n_samples": len(X),
             "vif_scores": vifs, "high_multicollinearity": high_vif},
        )
    except Exception as exc:
        return ToolResult.err(f"vif_analysis failed: {exc}")


def feature_variance(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Filter features by variance threshold."""
    try:
        import numpy as np
        feature_cols = params.get("feature_cols", [])
        threshold = float(params.get("threshold", 0.0))
        if not feature_cols:
            sample = data[0] if data else {}
            feature_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
        variances = {}
        for col in feature_cols:
            vals = np.array([_safe_float(row.get(col)) for row in data])
            variances[col] = float(np.nanvar(vals, ddof=1))
        kept = [c for c in feature_cols if variances[c] > threshold]
        removed = [c for c in feature_cols if variances[c] <= threshold]
        results = [{"feature": c, "variance": round(variances[c], 6),
                    "kept": variances[c] > threshold} for c in feature_cols]
        return ToolResult.ok(
            f"Feature variance filter (threshold={threshold}): "
            f"{len(kept)} kept, {len(removed)} removed",
            {"threshold": threshold, "kept_features": kept,
             "removed_features": removed, "variance_scores": results},
        )
    except Exception as exc:
        return ToolResult.err(f"feature_variance failed: {exc}")


def mutual_information(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Mutual information between features and a target column."""
    try:
        import numpy as np
        feature_cols = params.get("feature_cols", [])
        target_col = params.get("target_col")
        if not target_col:
            return ToolResult.err("'target_col' required.")
        if not feature_cols:
            sample = data[0] if data else {}
            feature_cols = [k for k, v in sample.items()
                            if isinstance(v, (int, float)) and k != target_col]
        rows = [(
            [_safe_float(row.get(c, 0)) for c in feature_cols],
            _safe_float(row.get(target_col))
        ) for row in data]
        rows = [(x, y) for x, y in rows if not (any(math.isnan(v) for v in x) or math.isnan(y))]
        if len(rows) < 4:
            return ToolResult.err("Insufficient valid rows.")
        X = np.array([r[0] for r in rows])
        y = np.array([r[1] for r in rows])
        try:
            from sklearn.feature_selection import mutual_info_regression
            mi_scores = mutual_info_regression(X, y, random_state=42)
        except ImportError:
            # Pearson correlation as proxy for MI
            mi_scores = [abs(float(np.corrcoef(X[:, i], y)[0, 1])) for i in range(X.shape[1])]
        results = sorted([{"feature": c, "mi_score": round(float(s), 6)}
                          for c, s in zip(feature_cols, mi_scores)],
                         key=lambda x: -x["mi_score"])
        return ToolResult.ok(
            f"Mutual information with '{target_col}': top feature='{results[0]['feature']}' "
            f"(score={results[0]['mi_score']})",
            {"target_col": target_col, "n_features": len(feature_cols),
             "n_samples": len(rows), "mi_scores": results},
        )
    except Exception as exc:
        return ToolResult.err(f"mutual_information failed: {exc}")


def binning_equal_width(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Equal-width discretization of a numeric column."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        n_bins = int(params.get("n_bins", 5))
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = np.array([_safe_float(row.get(value_col)) for row in data])
        lo, hi = float(np.nanmin(vals)), float(np.nanmax(vals))
        bin_width = (hi - lo) / n_bins
        edges = [lo + i * bin_width for i in range(n_bins + 1)]
        out_col = f"{value_col}_bin"
        rows_out = []
        bin_counts = [0] * n_bins
        for row, v in zip(data, vals):
            if math.isnan(v):
                rows_out.append({**row, out_col: None})
                continue
            b = min(int((v - lo) / bin_width), n_bins - 1) if bin_width > 0 else 0
            bin_counts[b] += 1
            label = f"[{round(edges[b], 3)}, {round(edges[b+1], 3)})"
            rows_out.append({**row, out_col: label})
        return ToolResult.ok(
            f"Equal-width binning '{value_col}' → {n_bins} bins (width={bin_width:.4f})",
            {"column": value_col, "out_column": out_col, "n_bins": n_bins,
             "bin_width": round(bin_width, 6), "edges": [round(e, 4) for e in edges],
             "bin_counts": bin_counts, "rows": _jsonify(rows_out[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"binning_equal_width failed: {exc}")


def binning_quantile(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Quantile-based discretization of a numeric column."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        n_bins = int(params.get("n_bins", 4))
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = np.array([_safe_float(row.get(value_col)) for row in data])
        clean = vals[~np.isnan(vals)]
        quantiles = [float(np.percentile(clean, 100 * i / n_bins)) for i in range(n_bins + 1)]
        out_col = f"{value_col}_qbin"
        rows_out = []
        bin_counts = [0] * n_bins
        for row, v in zip(data, vals):
            if math.isnan(v):
                rows_out.append({**row, out_col: None})
                continue
            b = n_bins - 1
            for i in range(n_bins):
                if v <= quantiles[i + 1]:
                    b = i
                    break
            bin_counts[b] += 1
            label = f"Q{b+1}[{round(quantiles[b], 3)}, {round(quantiles[b+1], 3)}]"
            rows_out.append({**row, out_col: label})
        return ToolResult.ok(
            f"Quantile binning '{value_col}' → {n_bins} quantile bins",
            {"column": value_col, "out_column": out_col, "n_bins": n_bins,
             "quantile_edges": [round(q, 4) for q in quantiles],
             "bin_counts": bin_counts, "rows": _jsonify(rows_out[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"binning_quantile failed: {exc}")


def target_encode(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Replace category with mean of target (target encoding)."""
    try:
        import numpy as np
        cat_col = params.get("cat_col")
        target_col = params.get("target_col")
        if not (cat_col and target_col):
            return ToolResult.err("'cat_col' and 'target_col' required.")
        group_means = {}
        groups = {}
        for row in data:
            c = str(row.get(cat_col, ""))
            v = _safe_float(row.get(target_col))
            if not math.isnan(v):
                groups.setdefault(c, []).append(v)
        global_mean = float(np.mean([v for vs in groups.values() for v in vs]))
        for c, vs in groups.items():
            group_means[c] = float(np.mean(vs))
        out_col = f"{cat_col}_target_enc"
        rows_out = [{**row, out_col: round(group_means.get(str(row.get(cat_col, "")), global_mean), 6)}
                    for row in data]
        return ToolResult.ok(
            f"Target encoding '{cat_col}' → '{out_col}' using mean of '{target_col}'",
            {"cat_col": cat_col, "target_col": target_col, "out_col": out_col,
             "global_mean": round(global_mean, 6),
             "encoding_map": {k: round(v, 4) for k, v in group_means.items()},
             "rows": _jsonify(rows_out[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"target_encode failed: {exc}")


def polynomial_interaction(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Generate polynomial and interaction features for two columns."""
    try:
        import numpy as np
        col_a = params.get("col_a")
        col_b = params.get("col_b")
        if not (col_a and col_b):
            sample = data[0] if data else {}
            num_cols = [k for k, v in sample.items() if isinstance(v, (int, float))]
            if len(num_cols) < 2:
                return ToolResult.err("Need 2 numeric columns.")
            col_a, col_b = num_cols[0], num_cols[1]
        rows_out = []
        for row in data:
            a = _safe_float(row.get(col_a))
            b = _safe_float(row.get(col_b))
            rows_out.append({
                **row,
                f"{col_a}_sq": round(a * a, 6) if not math.isnan(a) else None,
                f"{col_b}_sq": round(b * b, 6) if not math.isnan(b) else None,
                f"{col_a}_{col_b}_interact": round(a * b, 6) if not (math.isnan(a) or math.isnan(b)) else None,
                f"{col_a}_cb": round(a ** 3, 6) if not math.isnan(a) else None,
            })
        return ToolResult.ok(
            f"Polynomial/interaction features for '{col_a}' and '{col_b}': 4 new columns added",
            {"col_a": col_a, "col_b": col_b,
             "new_cols": [f"{col_a}_sq", f"{col_b}_sq",
                          f"{col_a}_{col_b}_interact", f"{col_a}_cb"],
             "rows": _jsonify(rows_out[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"polynomial_interaction failed: {exc}")


def robust_scale(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Median/IQR robust scaling (outlier-resistant)."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = np.array([_safe_float(row.get(value_col)) for row in data])
        clean = vals[~np.isnan(vals)]
        median = float(np.median(clean))
        q1, q3 = float(np.percentile(clean, 25)), float(np.percentile(clean, 75))
        iqr = q3 - q1 or 1.0
        out_col = f"{value_col}_robust_scaled"
        rows_out = [
            {**row, out_col: round((v - median) / iqr, 6) if not math.isnan(v) else None}
            for row, v in zip(data, vals)
        ]
        return ToolResult.ok(
            f"Robust scaling '{value_col}' (median={median:.4f}, IQR={iqr:.4f}) → '{out_col}'",
            {"column": value_col, "out_column": out_col,
             "median": round(median, 6), "iqr": round(iqr, 6),
             "q1": round(q1, 6), "q3": round(q3, 6),
             "rows": _jsonify(rows_out[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"robust_scale failed: {exc}")


def winsorize(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Clip values at percentile bounds (Winsorization)."""
    try:
        import numpy as np
        value_col = params.get("value_col") or params.get("column")
        lower_pct = float(params.get("lower_pct", 1.0))
        upper_pct = float(params.get("upper_pct", 99.0))
        if not value_col:
            sample = data[0] if data else {}
            value_col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not value_col:
            return ToolResult.err("No numeric column found.")
        vals = np.array([_safe_float(row.get(value_col)) for row in data])
        clean = vals[~np.isnan(vals)]
        lo_val = float(np.percentile(clean, lower_pct))
        hi_val = float(np.percentile(clean, upper_pct))
        clipped = np.clip(vals, lo_val, hi_val)
        n_clipped = int(np.sum((vals < lo_val) | (vals > hi_val)))
        out_col = f"{value_col}_winsorized"
        rows_out = [
            {**row, out_col: round(float(c), 6) if not math.isnan(v) else None}
            for row, v, c in zip(data, vals, clipped)
        ]
        return ToolResult.ok(
            f"Winsorize '{value_col}' [{lower_pct}%–{upper_pct}%]: "
            f"clipped {n_clipped}/{len(data)} values to [{lo_val:.4f}, {hi_val:.4f}]",
            {"column": value_col, "out_column": out_col,
             "lower_bound": round(lo_val, 6), "upper_bound": round(hi_val, 6),
             "n_clipped": n_clipped,
             "rows": _jsonify(rows_out[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"winsorize failed: {exc}")
