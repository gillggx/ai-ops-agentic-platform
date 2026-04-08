"""APC Service – parameters drift ±APC_DRIFT_RATIO after each process."""
import random
from app.database import get_db
from config import APC_DRIFT_RATIO


async def drift_and_prepare(apc_id: str) -> dict:
    """Apply drift to APC params and return new values (NO snapshot write).

    Returns dict with parameters, new_bias, prev_bias.
    """
    db = get_db()
    apc = await db.apc_state.find_one({"apc_id": apc_id})

    prev_bias = apc["parameters"].get("etch_time_offset", 0.0)

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


# Keep backward compat for any code still calling old API
async def drift_and_upload(apc_id: str, context: dict) -> dict:
    """Legacy: drift + immediate write. Used by old station_agent."""
    result = await drift_and_prepare(apc_id)
    snap_id = await upload_snapshot(apc_id, result["parameters"], context)
    return {**result, "snapshot_id": snap_id}
