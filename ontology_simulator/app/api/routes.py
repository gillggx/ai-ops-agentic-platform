"""REST API – Time-Machine query + monitoring endpoints."""
import math
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

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

    # ── LOT / TOOL: live master state — no anchor event needed ────
    # These always reflect current state; safe to query even when a step is in-progress.
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

    # ── DC / SPC: captured at ProcessEnd — find event that has the snapshot ref ──
    # (ProcessStart events never have dcSnapshotId/spcSnapshotId; don't time-filter)
    if obj in ("DC", "SPC"):
        snap_id_key = "dcSnapshotId" if obj == "DC" else "spcSnapshotId"
        event = await db.events.find_one(
            {
                "$or": [{"lotID": targetID}, {"toolID": targetID}],
                "step": step,
                snap_id_key: {"$exists": True, "$ne": None},
            },
            sort=[("eventTime", -1)],
        )
        if not event:
            raise HTTPException(404, f"No {obj} snapshot reference found for step='{step}' — step may still be in progress")
        snap_id_str = event.get(snap_id_key)
        snap = await db.object_snapshots.find_one({"_id": ObjectId(snap_id_str)})
        if not snap:
            raise HTTPException(404, f"{obj} snapshot '{snap_id_str}' not found")
        return _clean(snap)

    # ── Step 1: locate anchor event for APC / RECIPE (at or before requested time) ──
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
            detail=f"No completed event for targetID='{targetID}' step='{step}' — step may still be in progress",
        )

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


# ── SPC/DC Analytics helpers ──────────────────────────────────

_VALID_CHARTS = {"xbar_chart", "r_chart", "s_chart", "p_chart", "c_chart"}


def _compute_stats(values: list[float]) -> dict:
    if not values:
        return {"mean": 0.0, "ucl": 0.0, "lcl": 0.0, "std_dev": 0.0}
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    std = math.sqrt(var) if var > 0 else 0.0
    return {
        "mean": round(mean, 4),
        "ucl": round(mean + 3 * std, 4),
        "lcl": round(mean - 3 * std, 4),
        "std_dev": round(std, 4),
    }


def _trend(points: list[dict]) -> str:
    recent = [p["value"] for p in points[-10:] if p.get("value") is not None]
    if len(recent) < 4:
        return "STABLE"
    n = len(recent)
    xi = list(range(n))
    mi = (n - 1) / 2
    mv = sum(recent) / n
    cov = sum((xi[i] - mi) * (recent[i] - mv) for i in range(n))
    var = sum((xi[i] - mi) ** 2 for i in range(n))
    slope = cov / var if var > 0 else 0.0
    span = max(recent) - min(recent) or 1.0
    rel = slope / span * n
    if rel > 0.15:
        return "DRIFTING_UP"
    if rel < -0.15:
        return "DRIFTING_DOWN"
    ooc_recent = sum(1 for p in points[-10:] if p.get("is_ooc"))
    if ooc_recent >= 3:
        return "OSCILLATING"
    return "STABLE"


@router.get("/analytics/step-spc")
async def get_step_spc(
    step:       str                  = Query(..., description="e.g. STEP_007"),
    chart_name: str                  = Query(..., description="xbar_chart | r_chart | s_chart | p_chart | c_chart"),
    limit:      int                  = Query(100, ge=1, le=500),
    start:      Optional[datetime]   = Query(None),
    end:        Optional[datetime]   = Query(None),
):
    """Step-centric SPC chart timeseries: all lots at `step`, for one control chart."""
    if chart_name not in _VALID_CHARTS:
        raise HTTPException(400, f"Invalid chart_name '{chart_name}'. Must be one of: {', '.join(sorted(_VALID_CHARTS))}")

    db = get_db()
    query: dict = {"objectName": "SPC", "step": step.upper()}
    time_filter: dict = {}
    if start:
        time_filter["$gte"] = _to_naive_utc(start)
    if end:
        time_filter["$lte"] = _to_naive_utc(end)
    if time_filter:
        query["eventTime"] = time_filter

    cursor = db.object_snapshots.find(query, {"_id": 0}).sort("eventTime", 1).limit(limit)
    docs = await cursor.to_list(length=limit)

    data: list[dict] = []
    ooc_count = 0
    max_consec = 0
    cur_consec = 0

    for doc in docs:
        charts = doc.get("charts") or {}
        chart = charts.get(chart_name)
        if not chart:
            continue
        val = chart.get("value")
        ucl = chart.get("ucl")
        lcl = chart.get("lcl")
        is_ooc = (val is not None and ucl is not None and lcl is not None and (val > ucl or val < lcl))
        if is_ooc:
            ooc_count += 1
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0
        data.append({
            "eventTime": doc.get("eventTime"),
            "lotID": doc.get("lotID"),
            "toolID": doc.get("toolID"),
            "value": round(val, 4) if val is not None else None,
            "ucl": ucl,
            "lcl": lcl,
            "is_ooc": is_ooc,
        })

    total = len(data)
    pass_rate = round((total - ooc_count) / total * 100, 1) if total else 0.0
    trend_label = _trend(data)
    ooc_ts = [pt["eventTime"] for pt in data if pt["is_ooc"]][:20]

    return {
        "step": step.upper(),
        "chart_name": chart_name,
        "total": total,
        "ooc_count": ooc_count,
        "pass_rate": pass_rate,
        "consecutive_ooc": max_consec,
        "trend": trend_label,
        "ooc_timestamps": ooc_ts,
        "data": data,
    }


@router.get("/analytics/step-dc")
async def get_step_dc(
    step:      str                  = Query(..., description="e.g. STEP_007"),
    parameter: str                  = Query(..., description="DC sensor key, e.g. sensor_01"),
    limit:     int                  = Query(100, ge=1, le=500),
    start:     Optional[datetime]   = Query(None),
    end:       Optional[datetime]   = Query(None),
):
    """Step-centric DC timeseries: all lots that passed through `step`, for one sensor."""
    db = get_db()
    query: dict = {"objectName": "DC", "step": step.upper()}
    time_filter: dict = {}
    if start:
        time_filter["$gte"] = _to_naive_utc(start)
    if end:
        time_filter["$lte"] = _to_naive_utc(end)
    if time_filter:
        query["eventTime"] = time_filter

    cursor = db.object_snapshots.find(query, {"_id": 0}).sort("eventTime", 1).limit(limit)
    docs = await cursor.to_list(length=limit)

    data: list[float] = []
    values: list[float] = []
    rows: list[dict] = []

    for doc in docs:
        params = doc.get("parameters") or {}
        val = params.get(parameter)
        if not isinstance(val, (int, float)):
            continue
        values.append(float(val))
        rows.append({
            "eventTime": doc.get("eventTime"),
            "lotID": doc.get("lotID"),
            "toolID": doc.get("toolID"),
            "value": round(float(val), 4),
            "is_ooc": False,
        })

    stats = _compute_stats(values)
    ucl, lcl = stats["ucl"], stats["lcl"]
    for pt in rows:
        pt["is_ooc"] = pt["value"] > ucl or pt["value"] < lcl

    ooc_count = sum(1 for pt in rows if pt["is_ooc"])
    return {
        "step": step.upper(),
        "parameter": parameter,
        "total": len(rows),
        "ooc_count": ooc_count,
        **stats,
        "data": rows,
    }


# ── Process Events + Process Info ─────────────────────────────

@router.get("/process/events")
async def get_process_events(
    toolID:    Optional[str]      = Query(None),
    lotID:     Optional[str]      = Query(None),
    step:      Optional[str]      = Query(None),
    eventTime: Optional[str]      = Query(None),
    start_time: Optional[str]     = Query(None),
    limit:     int                = Query(100, ge=1, le=500),
):
    """Query process events. Input determines single or multi:
    - lotID + step → single event (or few if multiple cycles)
    - toolID or lotID alone → multiple events across steps
    """
    if not toolID and not lotID:
        raise HTTPException(400, "Must provide toolID or lotID (or both)")

    db = get_db()
    filt: dict = {}
    if toolID:
        filt["toolID"] = toolID
    if lotID:
        filt["lotID"] = lotID
    if step:
        filt["step"] = step.upper()
    if eventTime:
        try:
            et = datetime.fromisoformat(eventTime.replace("Z", "+00:00").split("+")[0])
            filt["eventTime"] = et
        except ValueError:
            pass
    if start_time:
        try:
            cutoff = datetime.fromisoformat(start_time.replace("Z", "+00:00").split("+")[0])
            filt.setdefault("eventTime", {})
            if isinstance(filt["eventTime"], dict):
                filt["eventTime"]["$gte"] = cutoff
        except ValueError:
            pass

    cursor = db.events.find(filt, {"_id": 0}).sort("eventTime", -1).limit(limit)
    docs = await cursor.to_list(length=limit)
    return docs


@router.get("/process/info")
async def get_process_info(
    toolID:    Optional[str]      = Query(None),
    lotID:     Optional[str]      = Query(None),
    step:      Optional[str]      = Query(None),
    eventTime: Optional[str]      = Query(None),
    start_time: Optional[str]     = Query(None),
    limit:     int                = Query(50, ge=1, le=100),
):
    """Query process events + join complete object data (DC/SPC/APC/RECIPE).

    Same input as /process/events but returns enriched results with full
    object snapshots joined by lotID + step + eventTime.
    """
    if not toolID and not lotID:
        raise HTTPException(400, "Must provide toolID or lotID (or both)")

    db = get_db()
    filt: dict = {}
    if toolID:
        filt["toolID"] = toolID
    if lotID:
        filt["lotID"] = lotID
    if step:
        filt["step"] = step.upper()
    if eventTime:
        try:
            et = datetime.fromisoformat(eventTime.replace("Z", "+00:00").split("+")[0])
            filt["eventTime"] = et
        except ValueError:
            pass
    if start_time:
        try:
            cutoff = datetime.fromisoformat(start_time.replace("Z", "+00:00").split("+")[0])
            filt.setdefault("eventTime", {})
            if isinstance(filt["eventTime"], dict):
                filt["eventTime"]["$gte"] = cutoff
        except ValueError:
            pass

    cursor = db.events.find(filt, {"_id": 0}).sort("eventTime", -1).limit(limit)
    events = await cursor.to_list(length=limit)

    results = []
    for ev in events:
        # Join object_snapshots by lotID + step + eventTime
        snap_filt = {
            "lotID": ev.get("lotID"),
            "step":  ev.get("step"),
            "eventTime": ev.get("eventTime"),
        }
        snaps = await db.object_snapshots.find(snap_filt, {"_id": 0}).to_list(length=10)

        objects = {}
        for snap in snaps:
            obj_name = snap.get("objectName", "")
            # Remove internal fields, keep the useful data
            clean = {k: v for k, v in snap.items()
                     if k not in ("eventTime", "lotID", "toolID", "step",
                                  "objectName", "last_updated_time", "updated_by")}
            objects[obj_name] = clean

        results.append({
            "event": ev,
            "objects": objects,
        })

    return results


# ── Unified Object Timeseries Query ──────────────────────────

class ObjectQueryRequest(BaseModel):
    object_name: str       # SPC / APC / DC / RECIPE
    object_id: str         # step code (SPC), APC model ID, equipment ID (DC)
    parameter: str         # e.g. charts.xbar_chart.value, rf_power_bias, sensor_01
    since: Optional[str] = None   # 24h / 7d / 30d
    limit: int = 200


@router.post("/objects/query")
async def query_object_timeseries(body: ObjectQueryRequest):
    """Unified object parameter timeseries query.

    Routes to the correct MongoDB query based on object_name:
    - SPC: queries object_snapshots where objectName=SPC, extracts chart value/ucl/lcl
    - APC: queries object_snapshots where objectName=APC, extracts parameter value
    - DC:  queries object_snapshots where objectName=DC, extracts sensor value
    - RECIPE: queries object_snapshots where objectName=RECIPE, extracts parameter value

    object_id semantics:
    - SPC → step code (e.g. STEP_007)
    - APC → APC model ID (e.g. APC-007) or step code
    - DC  → equipment ID (e.g. EQP-01) or step code
    """
    db = get_db()
    obj = body.object_name.upper()
    param = body.parameter
    limit = min(body.limit, 500)

    # Build base query
    query: dict = {"objectName": obj}

    # object_id → filter field depends on object_name
    if obj == "SPC":
        query["step"] = body.object_id.upper()
    elif obj == "APC":
        if body.object_id.upper().startswith("APC"):
            query["objectID"] = body.object_id
        else:
            query["step"] = body.object_id.upper()
    elif obj == "DC":
        if body.object_id.upper().startswith("EQP"):
            query["toolID"] = body.object_id
        else:
            query["step"] = body.object_id.upper()
    else:
        query["step"] = body.object_id.upper()

    # Time filter from since
    if body.since:
        from datetime import timedelta
        import re as _re
        m = _re.match(r"(\d+)([hdw])", body.since.strip().lower())
        if m:
            num, unit = int(m.group(1)), m.group(2)
            delta = timedelta(hours=num) if unit == "h" else timedelta(days=num) if unit == "d" else timedelta(weeks=num)
            # Get latest event time from simulator
            latest_doc = await db.object_snapshots.find_one(
                {"objectName": obj}, sort=[("eventTime", -1)]
            )
            if latest_doc and latest_doc.get("eventTime"):
                cutoff = latest_doc["eventTime"] - delta
                query["eventTime"] = {"$gte": cutoff}

    cursor = db.object_snapshots.find(query, {"_id": 0}).sort("eventTime", 1).limit(limit)
    docs = await cursor.to_list(length=limit)

    # Extract values based on object_name + parameter
    data = []
    values_for_stats = []

    for doc in docs:
        event_time = doc.get("eventTime")
        lot_id = doc.get("lotID", "")
        tool_id = doc.get("toolID", "")

        # Navigate to the parameter value using dot-notation
        val = doc
        ucl_val = None
        lcl_val = None

        if obj == "SPC" and param.startswith("charts."):
            # e.g. charts.xbar_chart.value → doc["charts"]["xbar_chart"]["value"]
            parts = param.split(".")
            charts = doc.get("charts") or {}
            chart = charts.get(parts[1]) if len(parts) >= 2 else {}
            if isinstance(chart, dict):
                val = chart.get(parts[2]) if len(parts) >= 3 else chart.get("value")
                ucl_val = chart.get("ucl")
                lcl_val = chart.get("lcl")
            else:
                val = None
        elif obj in ("APC", "RECIPE"):
            params_dict = doc.get("parameters") or {}
            val = params_dict.get(param)
        elif obj == "DC":
            params_dict = doc.get("parameters") or {}
            # DC sensors might be {sensor_01: {value: X, display_name: Y}} or plain float
            sensor = params_dict.get(param)
            if isinstance(sensor, dict):
                val = sensor.get("value")
            else:
                val = sensor
        else:
            val = None

        if val is None or not isinstance(val, (int, float)):
            continue

        val = float(val)
        values_for_stats.append(val)

        is_ooc = False
        if ucl_val is not None and lcl_val is not None:
            is_ooc = val > ucl_val or val < lcl_val

        point = {
            "eventTime": event_time,
            "lotID": lot_id,
            "toolID": tool_id,
            "value": round(val, 6),
            "is_ooc": is_ooc,
        }
        if ucl_val is not None:
            point["ucl"] = ucl_val
        if lcl_val is not None:
            point["lcl"] = lcl_val
        data.append(point)

    # Compute stats
    stats = _compute_stats(values_for_stats) if values_for_stats else {
        "mean": 0, "std_dev": 0, "ucl": 0, "lcl": 0
    }
    ooc_count = sum(1 for d in data if d.get("is_ooc"))
    total = len(data)

    return {
        "object_name": obj,
        "object_id": body.object_id,
        "parameter": param,
        "total_points": total,
        "stats": {
            **stats,
            "ooc_count": ooc_count,
            "pass_rate": round((total - ooc_count) / total * 100, 1) if total else 0,
        },
        "data": data,
    }


# ── Object Info (metadata query) ─────────────────────────────

# Maps objectName → which key in the snapshot holds the enumerable fields
_FIELD_SOURCES = {
    "SPC":    ("charts",     "charts"),
    "APC":    ("parameters", "parameters"),
    "DC":     ("parameters", "parameters"),
    "RECIPE": ("parameters", "parameters"),
}


@router.get("/object-info")
async def get_object_info(
    step:       str = Query(..., description="e.g. STEP_013"),
    objectName: str = Query(..., description="SPC | APC | DC | RECIPE"),
):
    """Return metadata about what fields/charts are available for a given
    step + objectName combination.

    Looks up one snapshot from object_snapshots to extract field names,
    then counts total snapshots matching the query.

    Response:
      {step, objectName, field_type, available_fields, sample_count}
    """
    db = get_db()
    obj = objectName.upper()

    if obj not in _FIELD_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"objectName must be one of: {', '.join(_FIELD_SOURCES.keys())}. Got: {objectName}",
        )

    field_key, field_type = _FIELD_SOURCES[obj]

    # Find one snapshot to extract field names
    sample = await db.object_snapshots.find_one(
        {"objectName": obj, "step": step},
        {"_id": 0, field_key: 1},
        sort=[("eventTime", -1)],
    )

    if sample is None:
        return {
            "step": step,
            "objectName": obj,
            "field_type": field_type,
            "available_fields": [],
            "sample_count": 0,
        }

    fields_data = sample.get(field_key, {})
    available_fields = sorted(fields_data.keys()) if isinstance(fields_data, dict) else []

    # Count total snapshots for this step + objectName
    sample_count = await db.object_snapshots.count_documents(
        {"objectName": obj, "step": step},
    )

    return {
        "step": step,
        "objectName": obj,
        "field_type": field_type,
        "available_fields": available_fields,
        "sample_count": sample_count,
    }


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
    toolID:     Optional[str] = Query(None, description="Filter by tool ID"),
    lotID:      Optional[str] = Query(None, description="Filter by lot ID"),
    start_time: Optional[str] = Query(None, description="ISO8601 cutoff"),
    limit:      int           = Query(50, ge=1, le=500),
):
    """Return the most recent `limit` events, newest-first.

    Each event is one completed process step. Every event has spc_status.
    No dedup needed — one event per (lot, step, cycle).
    """
    filt: dict = {}
    if toolID:
        filt["toolID"] = toolID
    if lotID:
        filt["lotID"] = lotID
    if start_time:
        try:
            cutoff = datetime.fromisoformat(start_time.replace("Z", "+00:00").split("+")[0])
            filt["eventTime"] = {"$gte": cutoff}
        except ValueError:
            pass

    cursor = get_db().events.find(filt, {"_id": 0}).sort("eventTime", -1).limit(limit)
    return await cursor.to_list(length=limit)


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


# ── Admin: Reset Simulation Data ──────────────────────────────
# Drops only simulation collections (object_snapshots, events).
# Seed/master data (lots, tools, recipe_data, apc_state) is preserved.

@router.post("/admin/reset-simulation")
async def reset_simulation():
    """Drop simulation collections so the simulator regenerates fresh MES data from scratch.

    Preserved: lots, tools, recipe_data, apc_state (seed/master data).
    Dropped:   object_snapshots, events (simulation output).
    """
    db = get_db()
    dropped = []
    for col_name in ("object_snapshots", "events"):
        await db[col_name].drop()
        dropped.append(col_name)
    return {
        "status":  "ok",
        "dropped": dropped,
        "message": "Simulation data reset. Simulator will regenerate MES data on next cycle.",
    }
