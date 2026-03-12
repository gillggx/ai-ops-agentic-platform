"""Base types and helpers for Generic Tools (v15.4)."""
from __future__ import annotations

import base64
import json
import math
import struct
from typing import Any, Dict


class ToolResult:
    """Standard output envelope for all generic tools."""

    @staticmethod
    def ok(summary: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "summary": summary, "payload": payload}

    @staticmethod
    def err(message: str) -> Dict[str, Any]:
        return {"status": "error", "summary": message, "payload": {}}


def _safe_float(v: Any) -> float:
    """Convert to float, return NaN on failure."""
    try:
        f = float(v)
        return f if math.isfinite(f) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _jsonify(obj: Any) -> Any:
    """Recursively convert numpy/pandas types to plain Python for JSON."""
    try:
        import numpy as np
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            f = float(obj)
            return None if math.isnan(f) else f
        if isinstance(obj, np.ndarray):
            return [_jsonify(x) for x in obj.tolist()]
    except ImportError:
        pass
    try:
        import pandas as pd
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
    except ImportError:
        pass
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(x) for x in obj]
    if isinstance(obj, float):
        return None if math.isnan(obj) else obj
    return obj


def _strip_bdata(obj: Any) -> Any:
    """Decode Plotly 6.x bdata binary encoding back to plain float lists."""
    if isinstance(obj, dict):
        if "bdata" in obj and "dtype" in obj:
            try:
                dtype = obj["dtype"]
                raw = base64.b64decode(obj["bdata"])
                fmt_map = {
                    "float64": "d", "float32": "f",
                    "int64": "q", "int32": "i", "int16": "h", "uint8": "B",
                }
                fmt = fmt_map.get(dtype, "d")
                size = struct.calcsize(fmt)
                n = len(raw) // size
                return list(struct.unpack(f"<{n}{fmt}", raw))
            except Exception:
                return []
        return {k: _strip_bdata(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_bdata(v) for v in obj]
    return obj


def _plotly_to_payload(fig) -> Dict[str, Any]:
    """Convert a Plotly Figure to a JSON-safe payload dict (bdata-free)."""
    raw = json.loads(fig.to_json())
    return {"plotly": _strip_bdata(raw)}


def _tight_xrange(x_vals, pad_pct: float = 0.05):
    """Compute [lo, hi] X-axis range with padding. Handles datetime strings and numeric values."""
    valid = [v for v in (x_vals or []) if v is not None]
    if not valid:
        return None
    try:
        import pandas as pd
        ts = pd.to_datetime(valid, errors="coerce")
        good = ts.dropna()
        if len(good) >= max(1, len(valid) * 0.5):
            t_min, t_max = good.min(), good.max()
            span_s = max((t_max - t_min).total_seconds(), 60)
            pad = pd.Timedelta(seconds=span_s * pad_pct)
            return [(t_min - pad).isoformat(), (t_max + pad).isoformat()]
    except Exception:
        pass
    try:
        nums = [float(v) for v in valid if v is not None]
        nums = [n for n in nums if not math.isnan(n)]
        if not nums:
            return None
        lo, hi = min(nums), max(nums)
        span = (hi - lo) if hi != lo else (abs(hi) * 0.1 or 1.0)
        pad = span * pad_pct
        return [lo - pad, hi + pad]
    except Exception:
        return None


def _tight_yrange(y_vals_list, pad_pct: float = 0.10):
    """Compute [lo, hi] Y-axis range from multiple lists of Y values."""
    all_y = []
    for ys in (y_vals_list or []):
        for v in (ys or []):
            try:
                f = float(v)
                if not math.isnan(f):
                    all_y.append(f)
            except (TypeError, ValueError):
                pass
    if not all_y:
        return None
    lo, hi = min(all_y), max(all_y)
    span = (hi - lo) if hi != lo else (abs(hi) * 0.1 or 1.0)
    pad = span * pad_pct
    return [lo - pad, hi + pad]


def _apply_tight_range(fig, x_vals=None, y_vals_list=None, pad_x: float = 0.05, pad_y: float = 0.10):
    """Apply tight axis ranges to a Plotly Figure to prevent data clustering."""
    updates: Dict[str, Any] = {}
    if x_vals:
        xr = _tight_xrange(x_vals, pad_pct=pad_x)
        if xr:
            updates["xaxis"] = {"range": xr}
    if y_vals_list:
        yr = _tight_yrange(y_vals_list, pad_pct=pad_y)
        if yr:
            updates["yaxis"] = {"range": yr}
    if updates:
        fig.update_layout(**updates)
    return fig
