"""APC Service — active/passive parameters with 50% self-correction feedback loop.

Active params (5): APC will attempt to correct these toward target after each process.
  - 50% chance of correction: drift_next = current + (target - current) * 0.5
  - 50% chance of continued drift (same as before)

Passive params (15): drift freely, no correction. model_r2_score / stability_index
  degrade proportionally to how far active params have drifted from target.
"""
import random
from app.database import get_db
from config import APC_DRIFT_RATIO

# ── Active vs Passive classification ──────────────────────────────────────────

ACTIVE_PARAMS = frozenset({
    "etch_time_offset",   # R2R 蝕刻時間補償
    "rf_power_bias",      # RF 功率偏差修正
    "gas_flow_comp",      # 氣體流量補償
    "ff_correction",      # Feedforward 修正量
    "fb_correction",      # Feedback 修正量
})

# Params whose value degrades based on how far active params drift
DERIVED_PASSIVE = {
    "model_r2_score":      {"baseline": 0.95, "sensitivity": 0.3},
    "stability_index":     {"baseline": 0.95, "sensitivity": 0.2},
    "prediction_error_nm": {"baseline": 0.005, "sensitivity": 0.05, "invert": True},
}

# Store initial (target) values per apc_id for correction reference
_initial_values: dict[str, dict[str, float]] = {}

SELF_CORRECTION_PROBABILITY = 0.5
CORRECTION_STRENGTH = 0.5  # How much of the gap to close (0=none, 1=full snap-back)


async def _ensure_initial_values(apc_id: str, current_params: dict) -> dict:
    """Cache the initial parameter values as correction targets."""
    if apc_id not in _initial_values:
        _initial_values[apc_id] = dict(current_params)
    return _initial_values[apc_id]


async def drift_and_prepare(apc_id: str, prev_spc_status: str = "PASS") -> dict:
    """Apply drift to APC params with active/passive differentiation.

    Args:
        apc_id: APC model ID (e.g. APC-001)
        prev_spc_status: SPC status from previous process ("PASS" or "OOC").
            When OOC, active params have higher correction probability (80%).

    Returns dict with parameters, new_bias, prev_bias.
    """
    db = get_db()
    apc = await db.apc_state.find_one({"apc_id": apc_id})
    if not apc:
        return {"parameters": {}, "new_bias": 0, "prev_bias": 0}

    prev_bias = apc["parameters"].get("etch_time_offset", 0.0)
    targets = await _ensure_initial_values(apc_id, apc["parameters"])

    drifted = {}
    for k, v in apc["parameters"].items():
        # Apply random drift (same for all params)
        new_val = v * (1 + random.uniform(-APC_DRIFT_RATIO, APC_DRIFT_RATIO))

        if k in ACTIVE_PARAMS:
            # Active params: chance of self-correction toward target
            correction_prob = 0.8 if prev_spc_status == "OOC" else SELF_CORRECTION_PROBABILITY
            if random.random() < correction_prob:
                target = targets.get(k, v)
                correction = (target - new_val) * CORRECTION_STRENGTH
                new_val = new_val + correction

        drifted[k] = round(new_val, 6)

    # Derived passive params: degrade based on active param total drift
    total_active_drift = 0.0
    for k in ACTIVE_PARAMS:
        if k in targets and targets[k] != 0:
            total_active_drift += abs(drifted[k] - targets[k]) / abs(targets[k])
    avg_drift = total_active_drift / max(len(ACTIVE_PARAMS), 1)

    for k, spec in DERIVED_PASSIVE.items():
        baseline = spec["baseline"]
        sensitivity = spec["sensitivity"]
        if spec.get("invert"):
            # prediction_error_nm: goes UP when drift is large
            drifted[k] = round(baseline + avg_drift * sensitivity + random.gauss(0, 0.001), 6)
        else:
            # model_r2_score, stability_index: goes DOWN when drift is large
            degraded = baseline - avg_drift * sensitivity + random.gauss(0, 0.01)
            drifted[k] = round(max(0.5, min(1.0, degraded)), 6)

    # Persist updated state
    await db.apc_state.update_one(
        {"apc_id": apc_id},
        {"$set": {"parameters": drifted}},
    )

    return {
        "parameters": drifted,
        "new_bias":   drifted.get("etch_time_offset", 0.0),
        "prev_bias":  prev_bias,
    }


async def upload_snapshot(apc_id: str, parameters: dict, context: dict) -> str:
    """Write APC snapshot with unified eventTime. Returns inserted _id."""
    db = get_db()
    snapshot = {
        "eventTime":        context["eventTime"],
        "lotID":            context["lotID"],
        "toolID":           context["toolID"],
        "step":             context["step"],
        "objectName":       "APC",
        "objectID":         apc_id,
        "mode":             "Run-to-Run",
        "parameters":       parameters,
        "last_updated_time": context["eventTime"],
        "updated_by":       "apc_service",
    }
    result = await db.object_snapshots.insert_one(snapshot)
    return str(result.inserted_id)
