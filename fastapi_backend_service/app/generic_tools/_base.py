"""Base types and helpers for Generic Tools (v15.3)."""
from __future__ import annotations

import json
import math
from typing import Any, Dict


class ToolResult:
    """Standard output envelope for all 50 generic tools."""

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
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            f = float(obj)
            return None if math.isnan(f) else f
        if isinstance(obj, np.ndarray):
            return [_jsonify(x) for x in obj.tolist()]
    except ImportError:
        pass
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(x) for x in obj]
    if isinstance(obj, float):
        return None if math.isnan(obj) else obj
    return obj


def _plotly_to_payload(fig) -> Dict[str, Any]:
    """Convert a Plotly Figure to a JSON-safe payload dict."""
    raw = json.loads(fig.to_json())
    return {"plotly": raw}
