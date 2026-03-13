"""DC Service – 30 sensor readings with physical units; SPC-monitored sensors have
a small excursion probability (~2% each) to drive ~10% overall OOC rate.

Sensor layout:
  sensor_01–06  : Vacuum / pressure / valve
  sensor_07–14  : Thermal (ESC, wall, ceiling, gas)
  sensor_15–22  : RF Power (source/bias) + matching network
  sensor_23–30  : Gas flow (MFCs + total)
"""
import random
from app.database import get_db

# ── Physical operating ranges ─────────────────────────────────
# Format: sensor_id -> (lo, hi) in engineering units
_SENSOR_RANGES: dict[str, tuple[float, float]] = {
    # ── Vacuum ───────────────────────────────────────────────
    "sensor_01": (13.0, 17.0),     # Chamber Press    (mTorr)
    "sensor_02": (0.8,  1.8),      # Foreline Press   (mTorr)
    "sensor_03": (0.025, 0.075),   # Load Lock Press  (mTorr)
    "sensor_04": (0.003, 0.010),   # Transfer Press   (mTorr)
    "sensor_05": (30.0, 70.0),     # Throttle Pos     (%)
    "sensor_06": (35.0, 65.0),     # Gate Valve Pos   (%)
    # ── Thermal ──────────────────────────────────────────────
    "sensor_07": (58.0, 62.0),     # ESC Zone1 Temp   (°C)
    "sensor_08": (58.0, 62.0),     # ESC Zone2 Temp   (°C)
    "sensor_09": (58.0, 62.0),     # ESC Zone3 Temp   (°C)
    "sensor_10": (19.0, 21.0),     # Chuck Temp       (°C)
    "sensor_11": (43.0, 47.0),     # Wall Temp        (°C)
    "sensor_12": (58.0, 64.0),     # Ceiling Temp     (°C)
    "sensor_13": (21.0, 24.0),     # Gas Inlet Temp   (°C)
    "sensor_14": (65.0, 78.0),     # Exhaust Temp     (°C)
    # ── RF Power ─────────────────────────────────────────────
    "sensor_15": (1440., 1560.),   # Source Power HF  (W)
    "sensor_16": (8.0,  25.0),     # Source Refl HF   (W)
    "sensor_17": (330., 470.),     # Bias Power LF    (W)
    "sensor_18": (4.0,  12.0),     # Bias Refl LF     (W)
    "sensor_19": (830., 870.),     # Bias Voltage     (V)
    "sensor_20": (0.36, 0.54),     # Bias Current     (A)
    "sensor_21": (13.549, 13.571), # Source Freq      (MHz)
    "sensor_22": (158., 192.),     # Match Cap C1     (pF)
    # ── Gas Flow ─────────────────────────────────────────────
    "sensor_23": (46.,  54.),      # CF4 Flow         (sccm)
    "sensor_24": (7.5,  12.5),     # O2 Flow          (sccm)
    "sensor_25": (88.,  112.),     # Ar Flow          (sccm)
    "sensor_26": (0.0,  3.5),      # N2 Flow          (sccm)
    "sensor_27": (9.0,  11.0),     # He Flow          (sccm)
    "sensor_28": (13.0, 17.0),     # CHF3 Flow        (sccm)
    "sensor_29": (7.5,  12.5),     # C4F8 Flow        (sccm)
    "sensor_30": (178., 212.),     # Total Flow       (sccm)
}

# Excursion bounds for the 5 SPC-monitored sensors.
# These values DEFINITELY breach spc_service.py control limits.
_SPC_EXCURSION: dict[str, tuple[float, float]] = {
    "sensor_01": (9.5,  20.5),     # SPC limits 12.5 / 17.5
    "sensor_07": (53.0, 67.0),     # SPC limits 57.5 / 62.5
    "sensor_15": (1300., 1700.),   # SPC limits 1430 / 1570
    "sensor_19": (795.,  915.),    # SPC limits 820 / 880
    "sensor_23": (36.,   64.),     # SPC limits 44 / 56
}

# Per-sensor excursion probability → ~10% total OOC from 5 charts
# math: 1 - (1 - p)^5 ≈ 0.10  →  p ≈ 0.021
_EXCURSION_PROB = 0.021

# ── Per-tool drift state ───────────────────────────────────────
# Slow accumulation simulates tool aging/wear; reset on OOC (maintenance).
# Format: tool_id → {sensor_id: drift_offset}
_tool_drifts: dict[str, dict[str, float]] = {}

# Drift rates (engineering units per process step, max random increment)
_DRIFT_RATES: dict[str, float] = {
    "sensor_01": 0.06,    # Chamber Press mTorr/step → OOC after ~40 steps
    "sensor_07": 0.05,    # ESC Zone1 Temp °C/step   → OOC after ~50 steps
    "sensor_15": 2.5,     # Source Power HF W/step   → OOC after ~28 steps
    "sensor_19": 0.6,     # Bias Voltage V/step      → OOC after ~33 steps
    "sensor_23": 0.10,    # CF4 Flow sccm/step       → OOC after ~60 steps
}


def reset_drift(tool_id: str) -> None:
    """Reset all drift offsets for a tool (called after OOC / maintenance)."""
    _tool_drifts[tool_id] = {s: 0.0 for s in _DRIFT_RATES}


def _get_drift(tool_id: str) -> dict[str, float]:
    if tool_id not in _tool_drifts:
        _tool_drifts[tool_id] = {s: 0.0 for s in _DRIFT_RATES}
    return _tool_drifts[tool_id]


def generate_readings(tool_id: str = "") -> dict:
    """Return 30 simulated sensor readings with per-tool drift on SPC sensors."""
    drift = _get_drift(tool_id) if tool_id else {}
    readings: dict[str, float] = {}
    for sensor, (lo, hi) in _SENSOR_RANGES.items():
        if sensor in _SPC_EXCURSION and random.random() < _EXCURSION_PROB:
            # Sudden excursion — use out-of-range region (drift not applied)
            exc_lo, exc_hi = _SPC_EXCURSION[sensor]
            val = (random.uniform(exc_lo, lo) if random.random() < 0.5
                   else random.uniform(hi, exc_hi))
        else:
            # Normal reading shifted by accumulated drift
            val = random.uniform(lo, hi) + drift.get(sensor, 0.0)
        readings[sensor] = round(val, 4)

    # Accumulate drift for next step (tool ages a little more each run)
    if tool_id:
        for s, rate in _DRIFT_RATES.items():
            drift[s] += random.uniform(0.0, rate)

    return readings


async def upload_snapshot(dc_params: dict, context: dict) -> str:
    """Store a DC snapshot and return its inserted _id as string."""
    db = get_db()

    ts = context["eventTime"].strftime("%Y%m%d%H%M%S%f")
    snapshot = {
        "eventTime":         context["eventTime"],
        "lotID":             context["lotID"],
        "toolID":            context["toolID"],
        "step":              context["step"],
        "objectName":        "DC",
        "objectID":          f"DC-{context['lotID']}-{context['step']}-{ts}",
        "collection_plan":   "HIGH_FREQ",
        "parameters":        dc_params,
        "last_updated_time": context["eventTime"],
        "updated_by":        "dc_service",
    }
    result = await db.object_snapshots.insert_one(snapshot)
    return str(result.inserted_id)
