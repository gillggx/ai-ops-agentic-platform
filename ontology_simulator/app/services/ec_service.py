"""EC Service — Equipment Constants with slow drift + PM recalibration.

Phase 12 expansion: 8 → 50 constants in 6 functional groups (RF / Vacuum /
Thermal / Gas / Mechanical / Maintenance counters) and per-(tool, chamber)
state — different chambers on the same tool drift independently so cross-
chamber match skills have something to compare.

Each constant slowly drifts per process step. After PM, values reset to
nominal ± small noise.

Status per constant:
  NORMAL → within tolerance
  DRIFT  → exceeds 50% of tolerance (early warning)
  ALERT  → exceeds tolerance (needs attention)
"""
import random
from typing import Dict
from app.database import get_db

# ── Equipment constant specs ──────────────────────────────────────────────────
# Phase 12: 8 → 50. Counters (etch_hours, wafer_count) start at 0 and only
# grow upward, so they get nominal=0 + a special handler below — they trip
# ALERT when they exceed an absolute threshold rather than a % of nominal.

EC_SPECS: Dict[str, dict] = {
    # ── RF subsystem (12) ──────────────────────────────────────
    "rf_power_offset":         {"nominal":   0.0, "tolerance_pct":  5.0, "unit": "W"},
    "rf_match_c1":             {"nominal": 180.0, "tolerance_pct":  5.0, "unit": "pF"},
    "rf_match_c2":             {"nominal": 220.0, "tolerance_pct":  5.0, "unit": "pF"},
    "rf_match_load":           {"nominal":  50.0, "tolerance_pct":  4.0, "unit": "Ω"},
    "rf_match_tune":           {"nominal":  50.0, "tolerance_pct":  4.0, "unit": "%"},
    "bias_power_offset":       {"nominal":   0.0, "tolerance_pct":  5.0, "unit": "W"},
    "bias_match_c1":           {"nominal": 200.0, "tolerance_pct":  5.0, "unit": "pF"},
    "bias_match_c2":           {"nominal": 240.0, "tolerance_pct":  5.0, "unit": "pF"},
    "rf_freq_calibration":     {"nominal": 13.560,"tolerance_pct":  0.1, "unit": "MHz"},
    "rf_cable_loss_db":        {"nominal":   0.5, "tolerance_pct": 10.0, "unit": "dB"},
    "rf_directional_coupler":  {"nominal":  30.0, "tolerance_pct":  3.0, "unit": "dB"},
    "ground_strap_resistance": {"nominal":   0.05,"tolerance_pct": 20.0, "unit": "Ω"},

    # ── Vacuum / pressure (10) ─────────────────────────────────
    "throttle_setpoint":       {"nominal":  50.0, "tolerance_pct":  3.0, "unit": "%"},
    "throttle_zero_offset":    {"nominal":   0.0, "tolerance_pct":  2.0, "unit": "%"},
    "turbo_pump_drive_offset": {"nominal":   0.0, "tolerance_pct":  3.0, "unit": "%"},
    "turbo_pump_speed_set":    {"nominal":30000.0,"tolerance_pct":  1.0, "unit": "rpm"},
    "fore_pump_baseline_a":    {"nominal":   4.0, "tolerance_pct":  8.0, "unit": "A"},
    "base_pressure_target":    {"nominal":   0.5, "tolerance_pct": 10.0, "unit": "mTorr"},
    "leak_rate_baseline":      {"nominal":   1e-7,"tolerance_pct": 50.0, "unit": "Torr·L/s"},
    "vent_pressure_set":       {"nominal": 760.0, "tolerance_pct":  1.0, "unit": "Torr"},
    "loadlock_pump_time_s":    {"nominal":  45.0, "tolerance_pct":  5.0, "unit": "s"},
    "iso_valve_seat_offset":   {"nominal":   0.0, "tolerance_pct":  3.0, "unit": "—"},

    # ── Thermal (8) ────────────────────────────────────────────
    "chamber_wall_temp":       {"nominal":  45.0, "tolerance_pct":  3.0, "unit": "°C"},
    "esc_zone1_setpoint":      {"nominal":  60.0, "tolerance_pct":  2.0, "unit": "°C"},
    "esc_zone2_setpoint":      {"nominal":  60.0, "tolerance_pct":  2.0, "unit": "°C"},
    "esc_zone3_setpoint":      {"nominal":  60.0, "tolerance_pct":  2.0, "unit": "°C"},
    "esc_zone4_setpoint":      {"nominal":  60.0, "tolerance_pct":  2.0, "unit": "°C"},
    "showerhead_temp_set":     {"nominal":  60.0, "tolerance_pct":  3.0, "unit": "°C"},
    "chuck_temp_set":          {"nominal":  20.0, "tolerance_pct":  2.0, "unit": "°C"},
    "thermo_couple_offset":    {"nominal":   0.0, "tolerance_pct":  5.0, "unit": "°C"},

    # ── Gas / MFC (8) ──────────────────────────────────────────
    "cf4_mfc_zero":            {"nominal":   0.0, "tolerance_pct":  2.0, "unit": "sccm"},
    "cf4_mfc_span":            {"nominal":   1.0, "tolerance_pct":  3.0, "unit": "—"},
    "o2_mfc_zero":             {"nominal":   0.0, "tolerance_pct":  2.0, "unit": "sccm"},
    "o2_mfc_span":             {"nominal":   1.0, "tolerance_pct":  3.0, "unit": "—"},
    "ar_mfc_zero":             {"nominal":   0.0, "tolerance_pct":  2.0, "unit": "sccm"},
    "ar_mfc_span":             {"nominal":   1.0, "tolerance_pct":  3.0, "unit": "—"},
    "he_backside_pressure":    {"nominal":  10.0, "tolerance_pct":  5.0, "unit": "Torr"},
    "purge_flow_set":          {"nominal":  20.0, "tolerance_pct":  5.0, "unit": "sccm"},

    # ── Mechanical (5) ────────────────────────────────────────
    "focus_ring_thickness":    {"nominal":   8.0, "tolerance_pct":  2.0, "unit": "mm"},
    "edge_ring_thickness":     {"nominal":   3.5, "tolerance_pct":  3.0, "unit": "mm"},
    "electrode_gap":           {"nominal":  13.5, "tolerance_pct":  1.0, "unit": "mm"},
    "lift_pin_height":         {"nominal":   2.0, "tolerance_pct":  5.0, "unit": "mm"},
    "slit_valve_open_pos":     {"nominal":  90.0, "tolerance_pct":  2.0, "unit": "mm"},

    # ── Maintenance counters (7) — grow until PM resets ────────
    # Counters: nominal=0, tolerance_pct unused; we evaluate using `alert_at`
    # absolute thresholds. Status semantics: NORMAL <50% of alert, DRIFT
    # 50–100%, ALERT >alert_at.
    "etch_hours_since_pm":     {"nominal":   0.0, "tolerance_pct":  0.0, "unit": "h",   "alert_at":   500.0},
    "wafer_count_since_pm":    {"nominal":   0.0, "tolerance_pct":  0.0, "unit": "—",   "alert_at": 25000.0},
    "rf_hours_since_pm":       {"nominal":   0.0, "tolerance_pct":  0.0, "unit": "h",   "alert_at":   400.0},
    "chamber_open_count":      {"nominal":   0.0, "tolerance_pct":  0.0, "unit": "—",   "alert_at":    50.0},
    "wet_clean_count":         {"nominal":   0.0, "tolerance_pct":  0.0, "unit": "—",   "alert_at":    10.0},
    "season_wafer_count":      {"nominal":  25.0, "tolerance_pct": 20.0, "unit": "—"},
    "calibration_age_days":    {"nominal":   0.0, "tolerance_pct":  0.0, "unit": "d",   "alert_at":    90.0},
}

# Per-process drift rate (fraction of nominal per step)
_DRIFT_RATE = 0.001  # 0.1% per process

# Counters that grow per-process (instead of drifting around nominal)
_COUNTER_INCREMENTS: Dict[str, float] = {
    "etch_hours_since_pm":  0.15,    # ~9 minutes per process
    "wafer_count_since_pm": 1.0,     # 1 wafer per process
    "rf_hours_since_pm":    0.15,
    "chamber_open_count":   0.0,     # bumped only on real chamber-open events (none yet)
    "wet_clean_count":      0.0,     # bumped only by PM endpoint
    "season_wafer_count":   0.5,     # half a wafer of season per process (decays after PM)
    "calibration_age_days": 0.005,   # ~7min real time per process; rough
}

# State key: (tool_id, chamber_id) → {constant_name: current_value}
# Chamber-aware: different chambers on same tool drift independently.
_tool_ec_state: Dict[tuple[str, str], Dict[str, float]] = {}


def _key(tool_id: str, chamber_id: str = "") -> tuple[str, str]:
    return (tool_id, chamber_id or "CH-DEFAULT")


def _init_tool_ec(tool_id: str, chamber_id: str = "") -> Dict[str, float]:
    """Initialize EC values near nominal for a (tool, chamber)."""
    state = {}
    for name, spec in EC_SPECS.items():
        if name in _COUNTER_INCREMENTS:
            # Counters start at 0 (or seasoning at random startup count)
            if name == "season_wafer_count":
                state[name] = round(random.uniform(0, 25), 4)
            else:
                state[name] = 0.0
        else:
            noise = spec["nominal"] * random.gauss(0, 0.001)
            state[name] = round(spec["nominal"] + noise, 4)
    _tool_ec_state[_key(tool_id, chamber_id)] = state
    return state


def get_ec_state(tool_id: str, chamber_id: str = "") -> Dict[str, float]:
    """Get current EC values for a (tool, chamber). Init on first access."""
    k = _key(tool_id, chamber_id)
    if k not in _tool_ec_state:
        return _init_tool_ec(tool_id, chamber_id)
    return _tool_ec_state[k]


def _evaluate_status(name: str, current: float, spec: dict) -> tuple[str, float]:
    """Return (status, deviation_pct) for one constant.

    Counter-style consts use `alert_at` absolute threshold; everything else
    uses % deviation from nominal vs. tolerance_pct.
    """
    if name in _COUNTER_INCREMENTS and "alert_at" in spec:
        alert_at = spec["alert_at"]
        pct_used = (current / alert_at) * 100 if alert_at else 0.0
        if current >= alert_at:
            return "ALERT", round(pct_used, 2)
        if current >= alert_at * 0.5:
            return "DRIFT", round(pct_used, 2)
        return "NORMAL", round(pct_used, 2)

    nominal = spec["nominal"]
    tol_pct = spec["tolerance_pct"]
    if nominal != 0:
        pct = abs(current - nominal) / abs(nominal) * 100
    else:
        pct = abs(current) * 100  # for nominal==0 with tolerance_pct as absolute

    if pct > tol_pct:
        return "ALERT", round(pct, 2)
    if pct > tol_pct * 0.5:
        return "DRIFT", round(pct, 2)
    return "NORMAL", round(pct, 2)


def apply_process_drift(tool_id: str, chamber_id: str = "") -> Dict[str, dict]:
    """Apply tiny drift (or counter increment) per process step.

    Phase 12: chamber-aware. Same tool, different chambers → different state.
    """
    state = get_ec_state(tool_id, chamber_id)

    result = {}
    for name, spec in EC_SPECS.items():
        if name in _COUNTER_INCREMENTS:
            # Counter grows monotonically per process
            inc = _COUNTER_INCREMENTS[name]
            # Add tiny variance so values aren't perfectly identical across tools
            jitter = random.uniform(0.9, 1.1) if inc > 0 else 0
            state[name] = round(state[name] + inc * jitter, 4)
        else:
            # Normal drift around nominal
            drift = spec["nominal"] * random.gauss(0, _DRIFT_RATE)
            state[name] = round(state[name] + drift, 4)

        current = state[name]
        status, deviation_pct = _evaluate_status(name, current, spec)

        result[name] = {
            "value":         current,
            "nominal":       spec["nominal"],
            "tolerance_pct": spec["tolerance_pct"],
            "deviation_pct": deviation_pct,
            "status":        status,
            "unit":          spec["unit"],
        }
        if "alert_at" in spec:
            result[name]["alert_at"] = spec["alert_at"]

    _tool_ec_state[_key(tool_id, chamber_id)] = state
    return result


def pm_recalibrate(tool_id: str, chamber_id: str = "") -> None:
    """Reset EC constants near-nominal after PM cycle. Counters → 0."""
    _init_tool_ec(tool_id, chamber_id)


async def upload_snapshot(ec_data: Dict[str, dict], context: dict) -> str:
    """Write EC snapshot with unified eventTime. Phase 12: includes chamberID."""
    db = get_db()
    snapshot = {
        "eventTime":        context["eventTime"],
        "lotID":            context["lotID"],
        "toolID":           context["toolID"],
        "chamberID":        context.get("chamberID"),    # Phase 12
        "step":             context["step"],
        "objectName":       "EC",
        "objectID":         f"{context['toolID']}-{context.get('chamberID', 'CH')}",
        "constants":        ec_data,
        "last_updated_time": context["eventTime"],
        "updated_by":       "ec_service",
    }
    result = await db.object_snapshots.insert_one(snapshot)
    return str(result.inserted_id)
