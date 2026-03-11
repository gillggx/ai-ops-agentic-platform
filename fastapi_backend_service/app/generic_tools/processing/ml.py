"""ML-style tools without scipy/sklearn (v15.3).

Tools: cluster_data, vector_similarity
"""
from __future__ import annotations

import math
import random
from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _safe_float


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
