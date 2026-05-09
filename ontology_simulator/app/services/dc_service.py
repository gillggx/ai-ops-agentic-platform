"""DC Service – ~120 sensor readings with real semiconductor domain names.

Phase 12 expansion (was 28 sensors):
  Vacuum/pressure  : 6 → 12  (added: turbo, cryo, fore_pump, gate_valve_temp, ...)
  Thermal          : 8 → 16  (added: pre_cooler, post_bake, sidewall, lid_temp, ...)
  RF Power         : 8 → 18  (added: harmonics, dual-freq, match-tuning, VPP/VDC, ...)
  Gas Flow         : 8 → 16  (added: HBr / SF6 / NF3 / Cl2 / BCl3 species, mixers)
  + OES bands      :     8   (Optical Emission Spectroscopy: F, CO, OH, etc.)
  + End-point      :     5   (EPD detector signals, slope, threshold trips)
  + RGA            :     6   (Residual Gas Analyzer: H2O, N2, O2, CO2, He, ...)
  + DC bias / sheath:    4   (chamber wall potential, sheath thickness proxies)
  + Process timing :     4   (recipe-time / step-time / stab-time / endpoint-time)

Total: ~120 sensors. SPC-monitored sensors have a small excursion probability
(~2% each) to drive ~10% overall OOC rate.

Phase 12 also adds chamber dimension: each tool has 4 chambers; readings are
generated per chamber (chamber_id passed through context). Per-chamber drift
phase makes the 4 chambers look like real-world unsynchronized aging.
"""
import math
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
    "turbo_pump_speed_rpm":   (27000., 33000.),  # Turbo speed        (rpm)
    "turbo_pump_temp_c":      (38.0,   45.0),    # Turbo temp         (°C)
    "cryo_pump_temp_k":       (12.0,   18.0),    # Cryo pump          (K)
    "fore_pump_current_a":    (3.0,    5.5),     # Fore-pump current  (A)
    "gate_valve_temp_c":      (40.0,   55.0),    # Gate valve temp    (°C)
    "vacuum_leak_rate":       (1e-9,   1e-8),    # He leak            (sccs)
    # ── Thermal ──────────────────────────────────────────────
    "esc_zone1_temp":         (58.0,   62.0),    # ESC Zone1 Temp     (°C)
    "esc_zone2_temp":         (58.0,   62.0),    # ESC Zone2 Temp     (°C)
    "esc_zone3_temp":         (58.0,   62.0),    # ESC Zone3 Temp     (°C)
    "esc_zone4_temp":         (58.0,   62.0),    # ESC Zone4 Temp     (°C)
    "chuck_temp_c":           (19.0,   21.0),    # Chuck Temp         (°C)
    "wall_temp_c":            (43.0,   47.0),    # Wall Temp          (°C)
    "ceiling_temp_c":         (58.0,   64.0),    # Ceiling Temp       (°C)
    "gas_inlet_temp_c":       (21.0,   24.0),    # Gas Inlet Temp     (°C)
    "exhaust_temp_c":         (65.0,   78.0),    # Exhaust Temp       (°C)
    "lid_temp_c":             (40.0,   48.0),    # Lid Temp           (°C)
    "sidewall_temp_c":        (50.0,   60.0),    # Sidewall Temp      (°C)
    "showerhead_temp_c":      (55.0,   65.0),    # Showerhead Temp    (°C)
    "pre_cooler_temp_c":      (15.0,   18.0),    # Pre-cooler         (°C)
    "post_bake_temp_c":       (90.0,  110.0),    # Post-bake          (°C)
    "chiller_supply_c":       (15.0,   18.0),    # Chiller supply     (°C)
    "chiller_return_c":       (18.0,   23.0),    # Chiller return     (°C)
    # ── RF Power ─────────────────────────────────────────────
    "rf_forward_power":      (1440.0, 1560.0),   # Source Power HF    (W)
    "reflected_power":          (8.0,   25.0),   # Source Refl HF     (W)
    "rf_2nd_harmonic_w":        (5.0,   18.0),   # RF 2nd harmonic    (W)
    "rf_3rd_harmonic_w":        (2.0,    8.0),   # RF 3rd harmonic    (W)
    "bias_power_lf_w":        (330.0,  470.0),   # Bias Power LF      (W)
    "bias_refl_lf_w":           (4.0,   12.0),   # Bias Refl LF       (W)
    "bias_voltage_v":         (830.0,  870.0),   # Bias Voltage       (V)
    "bias_current_a":           (0.36,   0.54),  # Bias Current       (A)
    "source_freq_mhz":        (13.549, 13.571),  # Source Freq        (MHz)
    "bias_freq_mhz":            (1.95,   2.05),  # Bias Freq          (MHz)
    "match_cap_c1_pf":        (158.0,  192.0),   # Match Cap C1       (pF)
    "match_cap_c2_pf":         (60.0,   90.0),   # Match Cap C2       (pF)
    "match_load_position":     (45.0,   55.0),   # Match Load Pos     (%)
    "match_tune_position":     (40.0,   60.0),   # Match Tune Pos     (%)
    "vpp_v":                  (180.0,  220.0),   # VPP                (V)
    "vdc_v":                  (-450.0, -380.0),  # VDC                (V)
    "rf_phase_deg":           (-15.0,   15.0),   # RF Phase           (°)
    "rf_impedance_ohm":        (45.0,   55.0),   # RF Impedance       (Ω)
    # ── Gas Flow ─────────────────────────────────────────────
    "cf4_flow_sccm":           (46.0,   54.0),   # CF4 Flow           (sccm)
    "o2_flow_sccm":             (7.5,   12.5),   # O2 Flow            (sccm)
    "ar_flow_sccm":            (88.0,  112.0),   # Ar Flow            (sccm)
    "n2_flow_sccm":             (0.0,    3.5),   # N2 Flow            (sccm)
    "helium_coolant_press":     (9.0,   11.0),   # He Backside Press  (Torr)
    "chf3_flow_sccm":          (13.0,   17.0),   # CHF3 Flow          (sccm)
    "c4f8_flow_sccm":           (7.5,   12.5),   # C4F8 Flow          (sccm)
    "total_flow_sccm":        (178.0,  212.0),   # Total Flow         (sccm)
    "hbr_flow_sccm":            (0.0,   60.0),   # HBr Flow           (sccm)
    "sf6_flow_sccm":            (0.0,   45.0),   # SF6 Flow           (sccm)
    "nf3_flow_sccm":            (0.0,   30.0),   # NF3 Flow           (sccm)
    "cl2_flow_sccm":            (0.0,   80.0),   # Cl2 Flow           (sccm)
    "bcl3_flow_sccm":           (0.0,   50.0),   # BCl3 Flow          (sccm)
    "h2_flow_sccm":             (0.0,   25.0),   # H2 Flow            (sccm)
    "purge_n2_sccm":          (180.0,  220.0),   # Purge N2           (sccm)
    "vent_flow_sccm":           (0.0,    3.0),   # Vent flow          (sccm)
    # ── OES (Optical Emission Spectroscopy) ───────────────────
    "oes_band_f_703nm":         (0.20,   0.45),  # F atomic line       (au)
    "oes_band_co_482nm":        (0.10,   0.30),  # CO band             (au)
    "oes_band_oh_309nm":        (0.05,   0.20),  # OH band             (au)
    "oes_band_cn_388nm":        (0.05,   0.18),  # CN band             (au)
    "oes_band_n2_337nm":        (0.10,   0.25),  # N2 band             (au)
    "oes_band_h_alpha":         (0.08,   0.22),  # Hα                  (au)
    "oes_band_o_777nm":         (0.15,   0.35),  # O atomic line       (au)
    "oes_endpoint_signal":      (0.20,   0.80),  # Composite EPD       (au)
    # ── End-Point Detection ───────────────────────────────────
    "epd_intensity":            (0.30,   0.70),  # EPD intensity       (au)
    "epd_slope_per_s":         (-0.05,   0.05),  # EPD slope           (au/s)
    "epd_trip_count":           (0,       3),    # EPD threshold trips (#)
    "epd_main_etch_time_s":    (24.0,   32.0),   # main-etch detected  (s)
    "epd_overetch_time_s":      (3.0,    8.0),   # overetch time       (s)
    # ── RGA (Residual Gas Analyzer) ───────────────────────────
    "rga_h2o_partial":          (1e-9,   5e-9),  # H2O partial         (Torr)
    "rga_n2_partial":            (5e-10, 3e-9),  # N2 partial          (Torr)
    "rga_o2_partial":            (1e-10, 1e-9),  # O2 partial          (Torr)
    "rga_co2_partial":           (5e-11, 5e-10), # CO2 partial         (Torr)
    "rga_he_partial":            (1e-9,  1e-8),  # He partial          (Torr)
    "rga_total_pressure":        (3e-9,  2e-8),  # RGA total           (Torr)
    # ── DC bias / sheath ──────────────────────────────────────
    "wall_potential_v":         (-50.0,   0.0),  # wall potential      (V)
    "sheath_voltage_v":         (-450.0, -380.), # sheath voltage      (V)
    "ion_density_estimate":     (1e10,   5e10),  # ion density         (cm⁻³)
    "plasma_density_estimate":  (1e10,   3e11),  # plasma density      (cm⁻³)
    # ── Process timing ────────────────────────────────────────
    "step_elapsed_s":           (0.0,   600.0),  # step time           (s)
    "stab_time_s":              (3.0,    8.0),   # stabilization       (s)
    "main_etch_time_s":        (24.0,   32.0),   # main etch elapsed   (s)
    "post_purge_s":             (4.0,    8.0),   # post purge          (s)
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

# ── Per-(tool,chamber) drift state ─────────────────────────────
# Slow accumulation simulates tool/chamber aging/wear; reset on OOC.
# Phase 12: keyed by (tool_id, chamber_id) so 4 chambers in the same tool
# drift independently — what makes "Chamber Match" skills detectable.
# Each chamber has a unique phase offset (radians) so its drift trace looks
# unsynchronized from siblings.
_tool_drifts: dict[tuple[str, str], dict[str, float]] = {}
_chamber_phase: dict[tuple[str, str], float] = {}

# Drift rates (engineering units per process step, max random increment)
# Accelerated 3x so OOC appears within ~10 steps for visible demo effect.
_DRIFT_RATES: dict[str, float] = {
    "chamber_pressure":  0.20,   # Chamber Press mTorr/step → OOC after ~12 steps
    "esc_zone1_temp":    0.15,   # ESC Zone1 Temp °C/step   → OOC after ~17 steps
    "rf_forward_power":  8.0,    # Source Power HF W/step   → OOC after ~9 steps
    "bias_voltage_v":    2.0,    # Bias Voltage V/step      → OOC after ~10 steps
    "cf4_flow_sccm":     0.35,   # CF4 Flow sccm/step       → OOC after ~17 steps
}


def reset_drift(tool_id: str, chamber_id: str = "") -> None:
    """Reset all drift offsets for a (tool, chamber) — called after OOC /
    maintenance. If chamber_id is empty, resets every chamber on the tool."""
    keys = [k for k in _tool_drifts if k[0] == tool_id and (not chamber_id or k[1] == chamber_id)]
    for k in keys:
        _tool_drifts[k] = {s: 0.0 for s in _DRIFT_RATES}


def _get_drift(tool_id: str, chamber_id: str) -> dict[str, float]:
    key = (tool_id, chamber_id)
    if key not in _tool_drifts:
        _tool_drifts[key] = {s: 0.0 for s in _DRIFT_RATES}
        # Each chamber gets a unique phase so its drift trace doesn't move
        # in lockstep with siblings.
        _chamber_phase[key] = random.uniform(0.0, 2.0 * math.pi)
    return _tool_drifts[key]


def generate_readings(tool_id: str = "", chamber_id: str = "") -> dict:
    """Return ~120 simulated sensor readings, drift-shifted per-(tool,chamber).

    Phase 12: chamber_id is now a first-class arg. When empty (legacy call
    sites), readings still work but drift is shared across the "default"
    chamber slot — kept for back-compat with code paths not yet chamber-aware.
    """
    chamber_id = chamber_id or "CH-DEFAULT"
    drift = _get_drift(tool_id, chamber_id) if tool_id else {}
    phase = _chamber_phase.get((tool_id, chamber_id), 0.0) if tool_id else 0.0
    readings: dict[str, float] = {}
    for sensor, (lo, hi) in _SENSOR_RANGES.items():
        if sensor in _SPC_EXCURSION and random.random() < _EXCURSION_PROB:
            exc_lo, exc_hi = _SPC_EXCURSION[sensor]
            val = (random.uniform(exc_lo, lo) if random.random() < 0.5
                   else random.uniform(hi, exc_hi))
        else:
            # Normal reading shifted by accumulated drift + small chamber-phase
            # bias so chambers visibly differ even at same drift magnitude.
            chamber_bias = 0.0
            if sensor in _DRIFT_RATES:
                chamber_bias = math.sin(phase) * (hi - lo) * 0.05
            val = random.uniform(lo, hi) + drift.get(sensor, 0.0) + chamber_bias
        # Phase 12: 4-decimal round nukes precision for sub-µ scale sensors
        # (rga_h2o_partial ~1e-9 → 0). Use 12 decimals so RGA / leak-rate /
        # other small-scale sensors round-trip safely while regular
        # engineering units still display cleanly via downstream `toFixed`.
        readings[sensor] = round(val, 12)

    if tool_id:
        for s, rate in _DRIFT_RATES.items():
            drift[s] = drift[s] * 0.98 + random.gauss(0, rate * 0.3)

    return readings


async def upload_snapshot(dc_params: dict, context: dict) -> str:
    """Store a DC snapshot and return its inserted _id as string."""
    db = get_db()

    snapshot = {
        "eventTime":         context["eventTime"],
        "lotID":             context["lotID"],
        "toolID":            context["toolID"],
        "chamberID":         context.get("chamberID"),    # Phase 12
        "step":              context["step"],
        "objectName":        "DC",
        "objectID":          context["toolID"],
        "parameters":        dc_params,
        "last_updated_time": context["eventTime"],
        "updated_by":        "dc_service",
    }
    result = await db.object_snapshots.insert_one(snapshot)
    return str(result.inserted_id)
