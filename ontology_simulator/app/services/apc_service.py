"""APC Service – parameters drift ±APC_DRIFT_RATIO after each process."""
import random
from app.database import get_db
from config import APC_DRIFT_RATIO


async def drift_and_upload(apc_id: str, context: dict) -> dict:
    """Apply drift, persist new state, upload snapshot.

    Returns dict with snapshot_id, new_bias (param_01), prev_bias for trend calc.
    """
    db = get_db()
    apc = await db.apc_state.find_one({"apc_id": apc_id})

    prev_bias = apc["parameters"]["param_01"]

    # Drift every parameter by ±APC_DRIFT_RATIO
    drifted = {
        k: round(v * (1 + random.uniform(-APC_DRIFT_RATIO, APC_DRIFT_RATIO)), 6)
        for k, v in apc["parameters"].items()
    }

    # Persist updated state
    await db.apc_state.update_one(
        {"apc_id": apc_id},
        {"$set": {"parameters": drifted}},
    )

    # Upload snapshot (with mode metadata per v1.1 spec)
    snapshot = {
        "eventTime":        context["eventTime"],
        "lotID":            context["lotID"],
        "toolID":           context["toolID"],
        "step":             context["step"],
        "objectName":       "APC",
        "objectID":         apc_id,
        "mode":             "Run-to-Run",
        "parameters":       drifted,
        "last_updated_time": context["eventTime"],
        "updated_by":       "apc_service",
    }
    result = await db.object_snapshots.insert_one(snapshot)
    return {
        "snapshot_id": str(result.inserted_id),
        "new_bias":    drifted["param_01"],
        "prev_bias":   prev_bias,
    }
