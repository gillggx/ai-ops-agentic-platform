"""Utility processing tools (v15.3).

Tools: missing_value_impute, regex_extractor,
       diff_engine, cross_reference, logic_evaluator
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _jsonify, _safe_float


def missing_value_impute(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Fill missing values using mean, median, forward-fill, or a constant."""
    try:
        import numpy as np

        col = params.get("column")
        strategy = params.get("strategy", "mean").lower()
        fill_value = params.get("fill_value")

        cols_to_fill = [col] if col else None

        rows = [dict(r) for r in data]
        fill_log = []

        def _fill_col(c: str):
            vals = [row.get(c) for row in rows]
            nulls = [i for i, v in enumerate(vals) if v is None or (isinstance(v, float) and np.isnan(v))]
            if not nulls:
                return

            num_vals = [_safe_float(v) for v in vals if v is not None]
            num_vals = [v for v in num_vals if not np.isnan(v)]

            if strategy == "mean" and num_vals:
                replacement = float(np.mean(num_vals))
            elif strategy == "median" and num_vals:
                replacement = float(np.median(num_vals))
            elif strategy == "prev":
                replacement = None  # handled per-index
            elif fill_value is not None:
                replacement = fill_value
            else:
                replacement = 0

            for i in nulls:
                if strategy == "prev":
                    prev = next((rows[j].get(c) for j in range(i - 1, -1, -1)
                                 if rows[j].get(c) is not None), 0)
                    rows[i][c] = prev
                else:
                    rows[i][c] = replacement
            fill_log.append({"column": c, "filled": len(nulls), "strategy": strategy})

        if cols_to_fill:
            for c in cols_to_fill:
                _fill_col(c)
        else:
            for c in (rows[0].keys() if rows else []):
                _fill_col(c)

        total_filled = sum(f["filled"] for f in fill_log)
        return ToolResult.ok(
            f"Imputed {total_filled} missing values using strategy='{strategy}'",
            {"strategy": strategy, "fill_log": fill_log,
             "rows": _jsonify(rows[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"missing_value_impute failed: {exc}")


def regex_extractor(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Extract text using regex from a string column."""
    try:
        col = params.get("column")
        pattern = params.get("pattern")
        out_col = params.get("out_col", "extracted")

        if not (col and pattern):
            return ToolResult.err("'column' and 'pattern' params required.")

        compiled = re.compile(pattern)
        rows = []
        match_count = 0
        for row in data:
            val = str(row.get(col, ""))
            m = compiled.search(val)
            extracted = m.group(0) if m else None
            if extracted:
                match_count += 1
            rows.append({**row, out_col: extracted})

        return ToolResult.ok(
            f"Regex '{pattern}' on '{col}': matched {match_count}/{len(data)} rows",
            {"column": col, "pattern": pattern, "out_col": out_col,
             "match_count": match_count, "rows": _jsonify(rows[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"regex_extractor failed: {exc}")


def diff_engine(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Compare two JSON objects and return a diff of changed paths/values."""
    try:
        obj_a = params.get("obj_a", {})
        obj_b = params.get("obj_b", {})

        # If data is provided as two rows
        if not (obj_a and obj_b) and len(data) >= 2:
            obj_a, obj_b = data[0], data[1]

        def _flatten(d: Any, prefix: str = "") -> Dict[str, Any]:
            result = {}
            if isinstance(d, dict):
                for k, v in d.items():
                    result.update(_flatten(v, f"{prefix}.{k}" if prefix else k))
            elif isinstance(d, list):
                for i, v in enumerate(d):
                    result.update(_flatten(v, f"{prefix}[{i}]"))
            else:
                result[prefix] = d
            return result

        flat_a = _flatten(obj_a)
        flat_b = _flatten(obj_b)
        all_keys = set(flat_a) | set(flat_b)

        diffs = []
        for key in sorted(all_keys):
            va = flat_a.get(key, "__missing__")
            vb = flat_b.get(key, "__missing__")
            if va != vb:
                diffs.append({"path": key, "before": va, "after": vb,
                              "change_type": "added" if va == "__missing__"
                              else "removed" if vb == "__missing__" else "modified"})

        return ToolResult.ok(
            f"Diff: {len(diffs)} change(s) found across {len(all_keys)} keys",
            {"total_keys": len(all_keys), "diff_count": len(diffs), "diffs": diffs},
        )
    except Exception as exc:
        return ToolResult.err(f"diff_engine failed: {exc}")


def cross_reference(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Join two datasets on a common key (inner/left join)."""
    try:
        import pandas as pd

        list_b = params.get("list_b", [])
        key = params.get("key")
        join_type = params.get("join_type", "inner")

        if not key:
            return ToolResult.err("'key' param required (common column name).")
        if not list_b:
            return ToolResult.err("'list_b' param required (second dataset as list-of-dicts).")

        df_a = pd.DataFrame(data)
        df_b = pd.DataFrame(list_b)

        merged = pd.merge(df_a, df_b, on=key, how=join_type, suffixes=("_a", "_b"))
        rows = merged.to_dict(orient="records")

        return ToolResult.ok(
            f"Cross-reference on '{key}' ({join_type} join): {len(data)} × {len(list_b)} → {len(rows)} rows",
            {"key": key, "join_type": join_type, "count_a": len(data),
             "count_b": len(list_b), "result_count": len(rows),
             "rows": _jsonify(rows[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"cross_reference failed: {exc}")


def logic_evaluator(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Evaluate a boolean expression with a safe whitelist context."""
    try:
        expression = params.get("expression", "")
        context = params.get("context", {})

        if not expression:
            return ToolResult.err("'expression' param required.")

        # Whitelist: only math/comparison operators, no builtins
        _FORBIDDEN = re.compile(r'\b(import|exec|eval|open|os|sys|subprocess|__)\b')
        if _FORBIDDEN.search(expression):
            return ToolResult.err("Expression contains forbidden keywords.")

        import math as _math
        safe_ns = {
            "math": _math, "abs": abs, "min": min, "max": max,
            "round": round, "len": len, "sum": sum,
            **context,
        }

        result = eval(expression, {"__builtins__": {}}, safe_ns)  # noqa: S307

        return ToolResult.ok(
            f"Expression '{expression}' → {result}",
            {"expression": expression, "result": result,
             "result_type": type(result).__name__},
        )
    except Exception as exc:
        return ToolResult.err(f"logic_evaluator failed: {exc}")
