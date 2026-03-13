"""REST API – Time-Machine query + monitoring endpoints."""
from datetime import datetime, timezone
from bson import ObjectId
from fastapi import APIRouter, Query, HTTPException
from app.database import get_db
from app.agent.station_agent import acknowledge_hold

router = APIRouter(prefix="/api/v1")

# ── Helpers ───────────────────────────────────────────────────

def _to_naive_utc(dt: datetime) -> datetime:
    """Normalise any timezone-aware datetime to a naive UTC datetime
    so comparisons with MongoDB (which stores naive UTC) are consistent."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _clean(doc: dict) -> dict:
    """Remove _id and convert ObjectId values to strings."""
    if doc is None:
        return {}
    return {
        k: str(v) if isinstance(v, ObjectId) else v
        for k, v in doc.items()
        if k != "_id"
    }


# ── Time-Machine Query ────────────────────────────────────────

@router.get("/context/query")
async def query_context(
    eventTime:  datetime = Query(..., description="ISO8601 reference time"),
    step:       str      = Query(..., description="e.g. STEP_001"),
    targetID:   str      = Query(..., description="Lot ID or Tool ID"),
    objectName: str      = Query(..., description="APC | RECIPE | DC | SPC | LOT | TOOL"),
):
    """
    Time-Machine API:
      1. Find the most recent event for (targetID, step) at or before eventTime.
      2. Use the event's object references to fetch the correct snapshot.
    """
    db = get_db()
    obj = objectName.upper()
    et  = _to_naive_utc(eventTime)

    # ── Step 1: locate anchor event ───────────────────────────
    event = await db.events.find_one(
        {
            "$or": [{"lotID": targetID}, {"toolID": targetID}],
            "step": step,
            "eventTime": {"$lte": et},
        },
        sort=[("eventTime", -1)],
    )

    if not event:
        raise HTTPException(
            status_code=404,
            detail=f"No event found for targetID='{targetID}' step='{step}' before {eventTime.isoformat()}",
        )

    # ── Step 2: return object data ────────────────────────────

    # LOT / TOOL → return current state from master collections
    if obj == "LOT":
        doc = await db.lots.find_one({"lot_id": targetID})
        if not doc:
            raise HTTPException(404, f"Lot '{targetID}' not found")
        return _clean(doc)

    if obj == "TOOL":
        doc = await db.tools.find_one({"tool_id": targetID})
        if not doc:
            raise HTTPException(404, f"Tool '{targetID}' not found")
        return _clean(doc)

    # DC / SPC → direct snapshot lookup by snapshot _id stored in event
    if obj in ("DC", "SPC"):
        snap_id_key = "dcSnapshotId" if obj == "DC" else "spcSnapshotId"
        snap_id_str = event.get(snap_id_key)
        if not snap_id_str:
            raise HTTPException(404, f"No {obj} snapshot reference in event")
        snap = await db.object_snapshots.find_one({"_id": ObjectId(snap_id_str)})
        if not snap:
            raise HTTPException(404, f"{obj} snapshot '{snap_id_str}' not found")
        return _clean(snap)

    # APC / RECIPE → time-machine lookup (effective_time <= eventTime, closest)
    object_id_map = {
        "APC":    event.get("apcID"),
        "RECIPE": event.get("recipeID"),
    }
    object_id = object_id_map.get(obj)
    if not object_id:
        raise HTTPException(400, f"Unsupported objectName: '{objectName}'")

    snap = await db.object_snapshots.find_one(
        {
            "objectID":   object_id,
            "objectName": obj,
            "eventTime":  {"$lte": et},
        },
        sort=[("eventTime", -1)],
    )
    if not snap:
        raise HTTPException(
            404,
            f"No {obj} snapshot for objectID='{object_id}' before {eventTime.isoformat()}",
        )
    return _clean(snap)


# ── Analytics / History ───────────────────────────────────────

@router.get("/analytics/history")
async def get_history(
    targetID:   str = Query(..., description="LOT-xxxx | EQP-xx | APC-xxx | etc."),
    objectName: str = Query(..., description="APC | RECIPE | DC | SPC"),
    limit:      int = Query(50, ge=1, le=500),
    step:       str = Query(None, description="Optional step filter, e.g. STEP_007"),
):
    """Return the most recent `limit` snapshots for a given object, oldest-first.

    - If targetID looks like a Lot (LOT-) or Tool (EQP-), filter by lotID / toolID.
    - Otherwise treat targetID as the objectID itself (e.g. APC-042).
    - Optional step filter narrows results to a specific process step.
    """
    db  = get_db()
    obj = objectName.upper()

    query: dict = {"objectName": obj}
    if targetID.startswith("LOT-"):
        query["lotID"] = targetID
    elif targetID.startswith("EQP-"):
        query["toolID"] = targetID
    else:
        query["objectID"] = targetID

    if step:
        query["step"] = step

    cursor = db.object_snapshots.find(query, {"_id": 0}).sort("eventTime", -1).limit(limit)
    docs   = await cursor.to_list(length=limit)
    # Return chronological order (oldest first) for chart rendering
    docs.reverse()
    return docs


# ── Monitoring ────────────────────────────────────────────────

@router.get("/status")
async def get_status():
    """Quick summary of current simulation state."""
    db = get_db()

    lot_pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    tool_pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]

    lot_counts  = {d["_id"]: d["count"] async for d in db.lots.aggregate(lot_pipeline)}
    tool_counts = {d["_id"]: d["count"] async for d in db.tools.aggregate(tool_pipeline)}
    total_events = await db.events.count_documents({})
    total_snaps  = await db.object_snapshots.count_documents({})

    return {
        "lots":             lot_counts,
        "tools":            tool_counts,
        "total_events":     total_events,
        "total_snapshots":  total_snaps,
    }


@router.get("/lots")
async def list_lots(status: str = Query(None, description="Filter by status")):
    filt = {"status": status} if status else {}
    docs = await get_db().lots.find(filt, {"_id": 0}).to_list(length=None)
    return docs


@router.get("/tools")
async def list_tools():
    docs = await get_db().tools.find({}, {"_id": 0}).to_list(length=None)
    return docs


# ── Event Timeline (TRACE mode) ───────────────────────────────

@router.get("/events")
async def list_events(
    toolID: str = Query(None, description="Filter by tool ID"),
    lotID:  str = Query(None, description="Filter by lot ID"),
    limit:  int = Query(50, ge=1, le=500),
):
    """Return the most recent `limit` events, newest-first.
    Used by the TRACE mode timeline panel."""
    filt: dict = {}
    if toolID:
        filt["toolID"] = toolID
    if lotID:
        filt["lotID"] = lotID
    cursor = get_db().events.find(filt, {"_id": 0}).sort("eventTime", -1).limit(limit)
    docs   = await cursor.to_list(length=limit)
    return docs


# ── Equipment HOLD Acknowledge ─────────────────────────────────

@router.post("/tools/{tool_id}/acknowledge")
async def acknowledge_tool_hold(tool_id: str):
    """Unblock a machine that is in equipment HOLD state.
    Called by the frontend when the engineer clicks ACKNOWLEDGE."""
    released = acknowledge_hold(tool_id)
    return {"tool_id": tool_id, "released": released}


# ── Audit: Index Count vs Actual Data Objects ──────────────────

@router.get("/audit")
async def get_audit():
    """
    Module 3 – Object & Index Tracker (Spec §4 last paragraph).

    For each subsystem (APC / DC / SPC / RECIPE), returns:
      - index_entries  : total snapshot rows (= how many times the sub-system was called)
      - distinct_objects: number of unique data objects actually stored
      - compression_ratio: index_entries / distinct_objects

    Example: RECIPE might have 8,000 index entries but only 20 distinct recipe versions.
    """
    db = get_db()

    subsystems = ["APC", "DC", "SPC", "RECIPE"]
    result = {}

    for obj in subsystems:
        # Total index entries
        index_entries = await db.object_snapshots.count_documents({"objectName": obj})

        # Distinct object IDs (unique data objects stored)
        pipeline = [
            {"$match":  {"objectName": obj}},
            {"$group":  {"_id": "$objectID"}},
            {"$count":  "n"},
        ]
        distinct_res    = await db.object_snapshots.aggregate(pipeline).to_list(length=1)
        distinct_objects = distinct_res[0]["n"] if distinct_res else 0

        # Newest & oldest snapshot timestamp
        newest_doc = await db.object_snapshots.find_one(
            {"objectName": obj}, sort=[("eventTime", -1)]
        )
        oldest_doc = await db.object_snapshots.find_one(
            {"objectName": obj}, sort=[("eventTime", 1)]
        )

        compression = round(index_entries / distinct_objects, 1) if distinct_objects else None

        result[obj] = {
            "index_entries":     index_entries,
            "distinct_objects":  distinct_objects,
            "compression_ratio": compression,
            "newest_event_time": newest_doc["eventTime"].isoformat() + "Z" if newest_doc else None,
            "oldest_event_time": oldest_doc["eventTime"].isoformat() + "Z" if oldest_doc else None,
        }

    # Events fan-out summary
    tool_events = await db.events.count_documents({"eventType": "TOOL_EVENT"})
    lot_events  = await db.events.count_documents({"eventType": "LOT_EVENT"})

    # Master data counts (actual stored versions, not snapshots)
    master = {
        "recipe_versions": await db.recipe_data.count_documents({}),
        "apc_models":      await db.apc_state.count_documents({}),
        "lots":            await db.lots.count_documents({}),
        "tools":           await db.tools.count_documents({}),
    }

    return {
        "subsystems":    result,
        "event_fanout":  {"TOOL_EVENT": tool_events, "LOT_EVENT": lot_events},
        "master_data":   master,
    }
