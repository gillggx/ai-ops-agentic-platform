"""Data transformation tools (v15.3).

Tools: data_filter, data_aggregation, pivot_table,
       flatten_json, sort_by_multiple, cumulative_op,
       set_operation
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from app.generic_tools._base import ToolResult, _jsonify, _safe_float


def data_filter(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Filter rows using a pandas-style query string or simple condition."""
    try:
        import pandas as pd

        condition = params.get("condition", "")
        if not condition:
            return ToolResult.err("'condition' param required (e.g., 'value > 45').")

        df = pd.DataFrame(data)
        filtered = df.query(condition)
        rows = filtered.to_dict(orient="records")

        return ToolResult.ok(
            f"Filter '{condition}': {len(data)} → {len(rows)} rows ({round(len(rows)/len(data)*100, 1)}% kept)",
            {"condition": condition, "original_count": len(data),
             "filtered_count": len(rows), "rows": _jsonify(rows[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"data_filter failed: {exc}")


def data_aggregation(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Group-by aggregation (sum/mean/count/min/max/std)."""
    try:
        import pandas as pd

        group_by = params.get("group_by")
        agg_func = params.get("agg_func", "mean")
        value_col = params.get("column") or params.get("value_col")

        if not group_by:
            return ToolResult.err("'group_by' param required (column name or list).")

        df = pd.DataFrame(data)
        if isinstance(group_by, str):
            group_by = [group_by]

        agg_cols = [value_col] if value_col else df.select_dtypes(include="number").columns.tolist()
        if not agg_cols:
            return ToolResult.err("No numeric columns to aggregate.")

        grouped = df.groupby(group_by)[agg_cols].agg(agg_func).reset_index()
        rows = grouped.to_dict(orient="records")

        return ToolResult.ok(
            f"Group by {group_by}, {agg_func}: {len(data)} → {len(rows)} groups",
            {"group_by": group_by, "agg_func": agg_func,
             "group_count": len(rows), "rows": _jsonify(rows)},
        )
    except Exception as exc:
        return ToolResult.err(f"data_aggregation failed: {exc}")


def pivot_table(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Pivot long table to wide format."""
    try:
        import pandas as pd

        index = params.get("index")
        col = params.get("col") or params.get("columns")
        val = params.get("val") or params.get("values")
        agg_func = params.get("agg_func", "mean")

        if not (index and col and val):
            return ToolResult.err("'index', 'col', and 'val' params required.")

        df = pd.DataFrame(data)
        pivot = df.pivot_table(values=val, index=index, columns=col,
                               aggfunc=agg_func, fill_value=0)
        rows = pivot.reset_index().to_dict(orient="records")

        return ToolResult.ok(
            f"Pivot: index='{index}', columns='{col}', values='{val}', agg={agg_func} → {len(rows)} rows × {len(pivot.columns)} cols",
            {"index": index, "columns": col, "values": val,
             "shape": [len(rows), len(pivot.columns)], "rows": _jsonify(rows)},
        )
    except Exception as exc:
        return ToolResult.err(f"pivot_table failed: {exc}")


def flatten_json(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Flatten nested JSON/dict structures to single-level key-value pairs."""
    try:
        import pandas as pd

        sep = params.get("sep", "_")
        flat = pd.json_normalize(data, sep=sep)
        rows = flat.to_dict(orient="records")
        original_cols = set(data[0].keys()) if data else set()
        new_cols = set(rows[0].keys()) if rows else set()
        added = new_cols - original_cols

        return ToolResult.ok(
            f"Flattened {len(data)} records: {len(original_cols)} → {len(new_cols)} columns (+{len(added)} from nesting)",
            {"original_cols": len(original_cols), "flat_cols": len(new_cols),
             "new_cols": list(added), "rows": _jsonify(rows[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"flatten_json failed: {exc}")


def sort_by_multiple(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Sort by multiple columns with configurable ascending/descending per column."""
    try:
        import pandas as pd

        criteria = params.get("criteria", [])
        if not criteria:
            return ToolResult.err("'criteria' param required: list of {col, order: 'asc'|'desc'}.")

        df = pd.DataFrame(data)
        cols = [c["col"] for c in criteria]
        asc = [c.get("order", "asc") == "asc" for c in criteria]
        sorted_df = df.sort_values(by=cols, ascending=asc)
        rows = sorted_df.to_dict(orient="records")

        return ToolResult.ok(
            f"Sorted {len(data)} rows by {[c['col'] for c in criteria]}",
            {"criteria": criteria, "rows": _jsonify(rows[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"sort_by_multiple failed: {exc}")


def cumulative_op(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Cumulative sum, product, min, or max on a numeric column."""
    try:
        import numpy as np

        col = params.get("column")
        op = params.get("op", "sum").lower()

        if not col:
            sample = data[0] if data else {}
            col = next((k for k, v in sample.items() if isinstance(v, (int, float))), None)
        if not col:
            return ToolResult.err("No numeric column found.")

        vals = [_safe_float(row.get(col)) for row in data]
        arr = np.array(vals)
        ops = {"sum": np.cumsum, "prod": np.cumprod,
               "min": np.minimum.accumulate, "max": np.maximum.accumulate}
        fn = ops.get(op, np.cumsum)
        result = fn(arr)

        out_key = f"{col}_cum_{op}"
        rows = [
            {**row, out_key: None if math.isnan(r) else round(float(r), 6)}
            for row, r in zip(data, result)
        ]
        return ToolResult.ok(
            f"Cumulative {op} on '{col}' → '{out_key}', final={round(float(result[-1]), 6) if len(result) else 'N/A'}",
            {"column": col, "op": op, "out_column": out_key, "rows": _jsonify(rows[:500])},
        )
    except Exception as exc:
        return ToolResult.err(f"cumulative_op failed: {exc}")


def set_operation(data: List[Dict[str, Any]], **params) -> Dict[str, Any]:
    """Perform set operations between two lists (intersection, union, difference)."""
    try:
        list_a = params.get("list_a", [])
        list_b = params.get("list_b", [])
        op = params.get("op", "intersection").lower()

        if not list_a and data:
            # Use data as list_a if not provided
            col = params.get("column")
            if col:
                list_a = [row.get(col) for row in data]

        set_a, set_b = set(map(str, list_a)), set(map(str, list_b))
        if op == "intersection":
            result = sorted(set_a & set_b)
        elif op == "union":
            result = sorted(set_a | set_b)
        elif op in ("difference", "diff"):
            result = sorted(set_a - set_b)
        elif op == "symmetric_difference":
            result = sorted(set_a ^ set_b)
        else:
            return ToolResult.err(f"Unknown op '{op}'. Use: intersection, union, difference, symmetric_difference.")

        return ToolResult.ok(
            f"Set {op}: |A|={len(set_a)}, |B|={len(set_b)} → result has {len(result)} elements",
            {"op": op, "size_a": len(set_a), "size_b": len(set_b),
             "result_size": len(result), "result": result[:200]},
        )
    except Exception as exc:
        return ToolResult.err(f"set_operation failed: {exc}")
