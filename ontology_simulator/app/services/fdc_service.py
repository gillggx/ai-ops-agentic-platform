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

# DC sensor thresholds for WARNING (tighter than SPC limits)
_DC_WARNING_THRESHOLDS = {
    "chamber_pressure":  (13.5, 16.5),   # SPC limits are 12.5/17.5
    "rf_forward_power": (1450, 1550),     # SPC limits are 1430/1570
    "bias_voltage_v":    (830, 870),      # SPC limits are 820/880
    "esc_zone1_temp":    (58.5, 61.5),    # SPC limits are 57.5/62.5
    "cf4_flow_sccm":     (46, 54),        # SPC limits are 44/56
}

_FAULT_CODES = {
    "chamber_pressure": "VACUUM_LEAK_001",
    "rf_forward_power": "RF_DRIFT_001",
    "bias_voltage_v":   "BIAS_SHIFT_001",
    "esc_zone1_temp":   "THERMAL_DRIFT_001",
    "cf4_flow_sccm":    "GAS_FLOW_001",
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
