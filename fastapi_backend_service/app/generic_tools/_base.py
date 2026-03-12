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
