"""DC Service – 30 sensor readings with real semiconductor domain names; SPC-monitored
sensors have a small excursion probability (~2% each) to drive ~10% overall OOC rate.

Sensor layout:
  Vacuum/pressure  : chamber_pressure, foreline_pressure, loadlock_pressure, ...
  Thermal (ESC)    : esc_zone1_temp, esc_zone2_temp, esc_zone3_temp, chuck_temp_c, ...
  RF Power         : rf_forward_power, reflected_power, bias_power_lf_w, ...
  Gas Flow (MFCs)  : cf4_flow_sccm, o2_flow_sccm, ar_flow_sccm, helium_coolant_press, ...
"""
import random
from app.database import get_db
from config import OOC_PROBABILITY

# ── Physical operating ranges ─────────────────────────────────
# Format: sensor_name -> (lo, hi) in engineering units
_SENSOR_RANGES: dict[str, tuple[float, float]] = {
    # ── Vacuum ───────────────────────────────────────────────
    "chamber_pressure":       (13.0,   17.0),    # Chamber Press      (mTorr)
    "foreline_pressure":       (0.8,    1.8),    # Foreline Press     (mTorr)
    "loadlock_pressure":      (0.025,  0.075),   # Load Lock Press    (mTorr)
    "transfer_pressure":      (0.003,  0.010),   # Transfer Press     (mTorr)
    "throttle_position_pct":  (30.0,   70.0),    # Throttle Pos       (%)
    "gate_valve_position_pct":(35.0,   65.0),    # Gate Valve Pos     (%)
    # ── Thermal ──────────────────────────────────────────────
    "esc_zone1_temp":         (58.0,   62.0),    # ESC Zone1 Temp     (°C)
    "esc_zone2_temp":         (58.0,   62.0),    # ESC Zone2 Temp     (°C)
    "esc_zone3_temp":         (58.0,   62.0),    # ESC Zone3 Temp     (°C)
    "chuck_temp_c":           (19.0,   21.0),    # Chuck Temp         (°C)
    "wall_temp_c":            (43.0,   47.0),    # Wall Temp          (°C)
    "ceiling_temp_c":         (58.0,   64.0),    # Ceiling Temp       (°C)
    "gas_inlet_temp_c":       (21.0,   24.0),    # Gas Inlet Temp     (°C)
    "exhaust_temp_c":         (65.0,   78.0),    # Exhaust Temp       (°C)
    # ── RF Power ─────────────────────────────────────────────
    "rf_forward_power":      (1440.0, 1560.0),   # Source Power HF    (W)
    "reflected_power":          (8.0,   25.0),   # Source Refl HF     (W)
    "bias_power_lf_w":        (330.0,  470.0),   # Bias Power LF      (W)
    "bias_refl_lf_w":           (4.0,   12.0),   # Bias Refl LF       (W)
    "bias_voltage_v":         (830.0,  870.0),   # Bias Voltage       (V)
    "bias_current_a":           (0.36,   0.54),  # Bias Current       (A)
    "source_freq_mhz":        (13.549, 13.571),  # Source Freq        (MHz)
    "match_cap_c1_pf":        (158.0,  192.0),   # Match Cap C1       (pF)
    # ── Gas Flow ─────────────────────────────────────────────
    "cf4_flow_sccm":           (46.0,   54.0),   # CF4 Flow           (sccm)
    "o2_flow_sccm":             (7.5,   12.5),   # O2 Flow            (sccm)
    "ar_flow_sccm":            (88.0,  112.0),   # Ar Flow            (sccm)
    "n2_flow_sccm":             (0.0,    3.5),   # N2 Flow            (sccm)
    "helium_coolant_press":     (9.0,   11.0),   # He Backside Press  (Torr)
    "chf3_flow_sccm":          (13.0,   17.0),   # CHF3 Flow          (sccm)
    "c4f8_flow_sccm":           (7.5,   12.5),   # C4F8 Flow          (sccm)
    "total_flow_sccm":        (178.0,  212.0),   # Total Flow         (sccm)
}

# Excursion bounds for the 5 SPC-monitored sensors.
# These values DEFINITELY breach spc_service.py control limits.
_SPC_EXCURSION: dict[str, tuple[float, float]] = {
    "chamber_pressure":   (9.5,    20.5),    # SPC limits 12.5 / 17.5
    "esc_zone1_temp":    (53.0,   67.0),     # SPC limits 57.5 / 62.5
    "rf_forward_power":  (1300.0, 1700.0),   # SPC limits 1430 / 1570
    "bias_voltage_v":    (795.0,  915.0),    # SPC limits 820 / 880
    "cf4_flow_sccm":     (36.0,   64.0),     # SPC limits 44 / 56
}

# Per-sensor excursion probability derived from target total OOC rate (config.OOC_PROBABILITY).
# math: P(total OOC) = 1 - (1 - p)^5  →  p = 1 - (1 - OOC_PROBABILITY)^(1/5)
_EXCURSION_PROB = 1.0 - (1.0 - OOC_PROBABILITY) ** (1.0 / 5.0)

# ── Per-tool drift state ───────────────────────────────────────
# Slow accumulation simulates tool aging/wear; reset on OOC (maintenance).
# Format: tool_id → {sensor_name: drift_offset}
_tool_drifts: dict[str, dict[str, float]] = {}

# Drift rates (engineering units per process step, max random increment)
# Accelerated 3x so OOC appears within ~10 steps for visible demo effect.
_DRIFT_RATES: dict[str, float] = {
    "chamber_pressure":  0.20,   # Chamber Press mTorr/step → OOC after ~12 steps
    "esc_zone1_temp":    0.15,   # ESC Zone1 Temp °C/step   → OOC after ~17 steps
    "rf_forward_power":  8.0,    # Source Power HF W/step   → OOC after ~9 steps
    "bias_voltage_v":    2.0,    # Bias Voltage V/step      → OOC after ~10 steps
    "cf4_flow_sccm":     0.35,   # CF4 Flow sccm/step       → OOC after ~17 steps
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
        "status":            context.get("status", "ProcessEnd"),
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
