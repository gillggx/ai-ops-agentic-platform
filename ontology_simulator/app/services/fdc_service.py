"""FDC Service — Fault Detection & Classification per process event.

Rule-based classification using DC readings + SPC status + APC model health:
  NORMAL  → all within spec
  WARNING → early drift detected (APC model degrading OR DC slow drift)
  FAULT   → SPC OOC + DC sensor significantly out of range

Each classification generates an FDC snapshot (objectName='FDC') alongside
the SPC/APC/DC/RECIPE snapshots for the same eventTime.
"""
import random
from dataclasses import dataclass, field, asdict
from typing import List
from app.database import get_db


@dataclass
class FDCResult:
    classification: str = "NORMAL"       # NORMAL | WARNING | FAULT
    fault_code: str = ""                 # e.g. "RF_DRIFT_001"
    confidence: float = 1.0              # 0.0 ~ 1.0
    contributing_sensors: List[str] = field(default_factory=list)
    description: str = ""


# ── Fault rules ───────────────────────────────────────────────────────────────

# DC sensor thresholds for WARNING (tighter than SPC limits) — Phase 12
# expanded to ~30 sensors. Each maps to a domain-specific fault code so
# downstream skills can group by fault family (FDC_VACUUM_*, FDC_RF_*, etc.).
_DC_WARNING_THRESHOLDS = {
    # ── Vacuum / pressure ───────────────────────────────────────
    "chamber_pressure":     (13.5,  16.5),
    "foreline_pressure":     (0.9,   1.7),
    "loadlock_pressure":    (0.030, 0.070),
    "throttle_position_pct":(32.0,  68.0),
    "turbo_pump_speed_rpm": (28000, 32000),
    "turbo_pump_temp_c":    (39.0,  44.0),
    "fore_pump_current_a":   (3.2,   5.3),
    # ── RF Power ────────────────────────────────────────────────
    "rf_forward_power":    (1450,  1550),
    "reflected_power":       (8,    22),
    "rf_2nd_harmonic_w":     (5.0,  16.0),
    "bias_power_lf_w":      (340,   460),
    "bias_voltage_v":       (832,   868),
    "vpp_v":                (185,   215),
    "match_tune_position":  (42.0,  58.0),
    # ── Thermal ─────────────────────────────────────────────────
    "esc_zone1_temp":       (58.5,  61.5),
    "esc_zone2_temp":       (58.5,  61.5),
    "esc_zone3_temp":       (58.5,  61.5),
    "esc_zone4_temp":       (58.5,  61.5),
    "chuck_temp_c":         (19.3,  20.7),
    "wall_temp_c":          (43.5,  46.5),
    "showerhead_temp_c":    (56.0,  64.0),
    # ── Gas Flow ────────────────────────────────────────────────
    "cf4_flow_sccm":        (46,    54),
    "o2_flow_sccm":          (8.0,  12.0),
    "ar_flow_sccm":         (90,   110),
    "helium_coolant_press":  (9.3,  10.7),
    "total_flow_sccm":     (180,   210),
    # ── OES / EPD ───────────────────────────────────────────────
    "oes_endpoint_signal":   (0.25, 0.75),
    "oes_band_f_703nm":      (0.22, 0.43),
    "epd_intensity":         (0.32, 0.68),
    # ── Contamination (RGA) ─────────────────────────────────────
    "rga_h2o_partial":       (1.5e-9, 4.5e-9),
}

_FAULT_CODES = {
    # Vacuum
    "chamber_pressure":     "FDC_VAC_PRESSURE_DRIFT",
    "foreline_pressure":    "FDC_VAC_FORELINE_DRIFT",
    "loadlock_pressure":    "FDC_VAC_LOADLOCK_LEAK",
    "throttle_position_pct":"FDC_VAC_THROTTLE_STUCK",
    "turbo_pump_speed_rpm": "FDC_VAC_TURBO_DEGRADE",
    "turbo_pump_temp_c":    "FDC_VAC_TURBO_HOT",
    "fore_pump_current_a":  "FDC_VAC_FORE_PUMP_LOAD",
    # RF
    "rf_forward_power":     "FDC_RF_SOURCE_DRIFT",
    "reflected_power":      "FDC_RF_REFL_HIGH",
    "rf_2nd_harmonic_w":    "FDC_RF_HARMONIC_HIGH",
    "bias_power_lf_w":      "FDC_RF_BIAS_DRIFT",
    "bias_voltage_v":       "FDC_RF_BIAS_VOLT_DRIFT",
    "vpp_v":                "FDC_RF_VPP_DRIFT",
    "match_tune_position":  "FDC_RF_MATCH_OFF",
    # Thermal
    "esc_zone1_temp":       "FDC_THERMAL_ESC1_DRIFT",
    "esc_zone2_temp":       "FDC_THERMAL_ESC2_DRIFT",
    "esc_zone3_temp":       "FDC_THERMAL_ESC3_DRIFT",
    "esc_zone4_temp":       "FDC_THERMAL_ESC4_DRIFT",
    "chuck_temp_c":         "FDC_THERMAL_CHUCK_DRIFT",
    "wall_temp_c":          "FDC_THERMAL_WALL_DRIFT",
    "showerhead_temp_c":    "FDC_THERMAL_SHOWER_DRIFT",
    # Gas
    "cf4_flow_sccm":        "FDC_GAS_CF4_DEVIATION",
    "o2_flow_sccm":         "FDC_GAS_O2_DEVIATION",
    "ar_flow_sccm":         "FDC_GAS_AR_DEVIATION",
    "helium_coolant_press": "FDC_GAS_HE_BACKSIDE",
    "total_flow_sccm":      "FDC_GAS_TOTAL_DEVIATION",
    # OES / EPD
    "oes_endpoint_signal":  "FDC_OES_ENDPOINT_OFF",
    "oes_band_f_703nm":     "FDC_OES_F_BAND_DRIFT",
    "epd_intensity":        "FDC_EPD_SIGNAL_LOW",
    # Contamination
    "rga_h2o_partial":      "FDC_RGA_H2O_HIGH",
}


def classify(
    dc_readings: dict,
    spc_status: str,
    apc_params: dict,
) -> FDCResult:
    """Classify the process event based on sensor readings + SPC + APC health.

    Priority: FAULT > WARNING > NORMAL
    """
    contributing = []
    fault_code = ""
    description_parts = []

    # Check 1: SPC OOC + DC sensor significantly out of range → FAULT
    if spc_status == "OOC":
        for sensor, (lo, hi) in _DC_WARNING_THRESHOLDS.items():
            val = dc_readings.get(sensor, 0)
            if val < lo or val > hi:
                contributing.append(sensor)
                fault_code = _FAULT_CODES.get(sensor, "UNKNOWN_FAULT")
        if contributing:
            return FDCResult(
                classification="FAULT",
                fault_code=fault_code,
                confidence=round(0.85 + random.uniform(0, 0.14), 2),
                contributing_sensors=contributing,
                description=f"SPC OOC + {', '.join(contributing)} out of warning range",
            )

    # Check 2: APC model degrading → WARNING
    r2 = apc_params.get("model_r2_score", 1.0)
    stability = apc_params.get("stability_index", 1.0)
    if r2 < 0.75 or stability < 0.80:
        return FDCResult(
            classification="WARNING",
            fault_code="APC_MODEL_DEGRADE",
            confidence=round(0.7 + random.uniform(0, 0.2), 2),
            contributing_sensors=[],
            description=f"APC model degrading: R²={r2:.3f}, stability={stability:.3f}",
        )

    # Check 3: DC sensors in WARNING zone (not OOC, but drifting)
    for sensor, (lo, hi) in _DC_WARNING_THRESHOLDS.items():
        val = dc_readings.get(sensor, 0)
        if val < lo or val > hi:
            contributing.append(sensor)
    if len(contributing) >= 2:
        return FDCResult(
            classification="WARNING",
            fault_code="MULTI_SENSOR_DRIFT",
            confidence=round(0.6 + random.uniform(0, 0.2), 2),
            contributing_sensors=contributing,
            description=f"Multiple sensors drifting: {', '.join(contributing)}",
        )

    return FDCResult(
        classification="NORMAL",
        confidence=round(0.95 + random.uniform(0, 0.05), 2),
    )


async def upload_snapshot(fdc_result: FDCResult, context: dict) -> str:
    """Write FDC snapshot with unified eventTime."""
    db = get_db()
    snapshot = {
        "eventTime":        context["eventTime"],
        "lotID":            context["lotID"],
        "toolID":           context["toolID"],
        "step":             context["step"],
        "objectName":       "FDC",
        "objectID":         f"FDC-{context['toolID']}",
        "classification":   fdc_result.classification,
        "fault_code":       fdc_result.fault_code,
        "confidence":       fdc_result.confidence,
        "contributing_sensors": fdc_result.contributing_sensors,
        "description":      fdc_result.description,
        "last_updated_time": context["eventTime"],
        "updated_by":       "fdc_service",
    }
    result = await db.object_snapshots.insert_one(snapshot)
    return str(result.inserted_id)
