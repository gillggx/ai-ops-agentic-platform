"""EC Service — Equipment Constants with slow drift + PM recalibration.

8 equipment constants per tool that slowly drift from nominal values.
After each PM cycle, constants are recalibrated (reset to nominal ± small noise).

Status per constant:
  NORMAL → within tolerance
  DRIFT  → exceeds 50% of tolerance (early warning)
  ALERT  → exceeds tolerance (needs attention)
"""
import random
from dataclasses import dataclass
from typing import Dict
from app.database import get_db

# ── Equipment constant specs ──────────────────────────────────────────────────

EC_SPECS: Dict[str, dict] = {
    "rf_power_offset":      {"nominal": 0.0,   "tolerance_pct": 5.0,  "unit": "W"},
    "throttle_setpoint":    {"nominal": 50.0,  "tolerance_pct": 3.0,  "unit": "%"},
    "he_backside_pressure": {"nominal": 10.0,  "tolerance_pct": 5.0,  "unit": "Torr"},
    "focus_ring_thickness": {"nominal": 8.0,   "tolerance_pct": 2.0,  "unit": "mm"},
    "chamber_wall_temp":    {"nominal": 45.0,  "tolerance_pct": 3.0,  "unit": "°C"},
    "electrode_gap":        {"nominal": 13.5,  "tolerance_pct": 1.0,  "unit": "mm"},
    "rf_match_c1":          {"nominal": 180.0, "tolerance_pct": 5.0,  "unit": "pF"},
    "rf_match_c2":          {"nominal": 220.0, "tolerance_pct": 5.0,  "unit": "pF"},
}

# Per-process drift rate (fraction of nominal per step)
_DRIFT_RATE = 0.001  # 0.1% per process

# In-memory state per tool (tool_id → {constant_name: current_value})
_tool_ec_state: Dict[str, Dict[str, float]] = {}


def _init_tool_ec(tool_id: str) -> Dict[str, float]:
    """Initialize EC values near nominal for a tool."""
    state = {}
    for name, spec in EC_SPECS.items():
        noise = spec["nominal"] * random.gauss(0, 0.001)
        state[name] = round(spec["nominal"] + noise, 4)
    _tool_ec_state[tool_id] = state
    return state


def get_ec_state(tool_id: str) -> Dict[str, float]:
    """Get current EC values for a tool (init if first time)."""
    if tool_id not in _tool_ec_state:
        return _init_tool_ec(tool_id)
    return _tool_ec_state[tool_id]


def apply_process_drift(tool_id: str) -> Dict[str, dict]:
    """Apply tiny drift to each EC constant for one process step.

    Returns dict of {constant_name: {value, nominal, tolerance_pct, status, unit}}.
    """
    state = get_ec_state(tool_id)

    result = {}
    for name, spec in EC_SPECS.items():
        nominal = spec["nominal"]
        tol_pct = spec["tolerance_pct"]

        # Apply micro-drift
        drift = nominal * random.gauss(0, _DRIFT_RATE)
        state[name] = round(state[name] + drift, 4)
        current = state[name]

        # Calculate status
        if nominal != 0:
            pct_from_nominal = abs(current - nominal) / abs(nominal) * 100
        else:
            pct_from_nominal = abs(current) * 100

        if pct_from_nominal > tol_pct:
            status = "ALERT"
        elif pct_from_nominal > tol_pct * 0.5:
            status = "DRIFT"
        else:
            status = "NORMAL"

        result[name] = {
            "value": current,
            "nominal": nominal,
            "tolerance_pct": tol_pct,
            "deviation_pct": round(pct_from_nominal, 2),
            "status": status,
            "unit": spec["unit"],
        }

    _tool_ec_state[tool_id] = state
    return result


def pm_recalibrate(tool_id: str) -> None:
    """Reset EC constants to near-nominal after PM cycle."""
    _init_tool_ec(tool_id)


async def upload_snapshot(ec_data: Dict[str, dict], context: dict) -> str:
    """Write EC snapshot with unified eventTime."""
    db = get_db()
    snapshot = {
        "eventTime":        context["eventTime"],
        "lotID":            context["lotID"],
        "toolID":           context["toolID"],
        "step":             context["step"],
        "objectName":       "EC",
        "objectID":         context["toolID"],
        "constants":        ec_data,
        "last_updated_time": context["eventTime"],
        "updated_by":       "ec_service",
    }
    result = await db.object_snapshots.insert_one(snapshot)
    return str(result.inserted_id)
