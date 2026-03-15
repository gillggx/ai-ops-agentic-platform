"""v2 Ontology Data Services API.

Each (lot, tool, step) now generates TWO events:
  ProcessStart (t0): Recipe + APC snapshots — pre-process state
  ProcessEnd   (t1): DC + SPC snapshots    — post-process measurements

Query layer merges them transparently. Trajectory APIs deduplicate into one
entry per step (with start_time + end_time). Context API accepts
?process_status=ProcessStart|ProcessEnd to control topology display (Option B).

Endpoints
---------
GET /api/v2/ontology/fanout/{event_id}
GET /api/v2/ontology/orphans
GET /api/v2/ontology/context
GET /api/v2/ontology/trajectory/tool/{tool_id}
GET /api/v2/ontology/trajectory/lot/{lot_id}
GET /api/v2/ontology/trajectory/{lot_id}   [legacy alias]
GET /api/v2/ontology/history/{object_type}/{object_id}
GET /api/v2/ontology/indices/{object_type}
GET /api/v2/ontology/enumerate
"""
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query
from app.database import get_db

router = APIRouter(prefix="/api/v2/ontology")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid ObjectId: {s!r}")


def _clean(doc: dict) -> dict:
    """Strip _id and stringify any ObjectId values."""
    if doc is None:
        return None
    return {k: str(v) if isinstance(v, ObjectId) else v for k, v in doc.items() if k != "_id"}


# ── GET /fanout/{event_id} ────────────────────────────────────────────────────

@router.get("/fanout/{event_id}")
async def get_fanout(event_id: str):
    """
    Given an event ObjectId, trace all subsystem registrations spawned from it.

    ProcessStart events link to Recipe + APC snapshots (matched by objectID + eventTime).
    ProcessEnd events link to DC + SPC snapshots (matched by snapshot _id).
    """
    db = get_db()
    event = await db.events.find_one({"_id": _oid(event_id)})
    if not event:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found")

    ev_status = event.get("status", "ProcessEnd")

    result = {
        "event_id":      event_id,
        "eventTime":     event["eventTime"].isoformat() + "Z",
        "eventType":     event.get("eventType"),
        "process_status": ev_status,
        "lotID":         event.get("lotID"),
        "toolID":        event.get("toolID"),
        "step":          event.get("step"),
        "spc_status":    event.get("spc_status"),
        "subsystems":    {},
    }

    # ── APC (ProcessStart only) ───────────────────────────────────────────────
    apc_id = event.get("apcID")
    if apc_id:
        snap = await db.object_snapshots.find_one(
            {"objectID": apc_id, "objectName": "APC", "status": "ProcessStart",
             "eventTime": event["eventTime"]}
        )
        master = await db.apc_state.find_one({"apc_id": apc_id})
        result["subsystems"]["APC"] = {
            "object_id":       apc_id,
            "snapshot_id":     str(snap["_id"]) if snap else None,
            "snapshot_exists": snap is not None,
            "master_exists":   master is not None,
            "orphan":          snap is None,
            "parameters":      snap.get("parameters") if snap else None,
        }

    # ── RECIPE (ProcessStart only) ────────────────────────────────────────────
    recipe_id = event.get("recipeID")
    if recipe_id:
        snap = await db.object_snapshots.find_one(
            {"objectID": recipe_id, "objectName": "RECIPE", "status": "ProcessStart",
             "eventTime": event["eventTime"]}
        )
        master = await db.recipe_data.find_one({"recipe_id": recipe_id})
        result["subsystems"]["RECIPE"] = {
            "object_id":       recipe_id,
            "snapshot_id":     str(snap["_id"]) if snap else None,
            "snapshot_exists": snap is not None,
            "master_exists":   master is not None,
            "orphan":          snap is None,
            "parameters":      snap.get("parameters") if snap else None,
        }

    # ── DC (ProcessEnd only) ──────────────────────────────────────────────────
    dc_snap_id = event.get("dcSnapshotId")
    if dc_snap_id:
        snap = await db.object_snapshots.find_one({"_id": _oid(dc_snap_id)})
        result["subsystems"]["DC"] = {
            "object_id":       snap.get("objectID") if snap else None,
            "snapshot_id":     dc_snap_id,
            "snapshot_exists": snap is not None,
            "master_exists":   None,
            "orphan":          snap is None,
            "sensor_count":    len(snap.get("parameters", {})) if snap else 0,
        }

    # ── SPC (ProcessEnd only) ─────────────────────────────────────────────────
    spc_snap_id = event.get("spcSnapshotId")
    if spc_snap_id:
        snap = await db.object_snapshots.find_one({"_id": _oid(spc_snap_id)})
        result["subsystems"]["SPC"] = {
            "object_id":       snap.get("objectID") if snap else None,
            "snapshot_id":     spc_snap_id,
            "snapshot_exists": snap is not None,
            "master_exists":   None,
            "orphan":          snap is None,
            "spc_status":      event.get("spc_status"),
        }

    return result


# ── GET /orphans ──────────────────────────────────────────────────────────────

@router.get("/orphans")
async def get_orphans(limit: int = Query(50, ge=1, le=500)):
    """Scan recent events and detect broken snapshot references."""
    db = get_db()
    orphan_list = []

    cursor = db.events.find({}).sort("eventTime", -1).limit(limit * 4)
    async for event in cursor:
        broken = []
        ev_status = event.get("status", "ProcessEnd")

        if ev_status == "ProcessEnd":
            dc_id = event.get("dcSnapshotId")
            if dc_id:
                exists = await db.object_snapshots.find_one({"_id": _oid(dc_id)}, {"_id": 1})
                if not exists:
                    broken.append({"subsystem": "DC", "missing_id": dc_id})

            spc_id = event.get("spcSnapshotId")
            if spc_id:
                exists = await db.object_snapshots.find_one({"_id": _oid(spc_id)}, {"_id": 1})
                if not exists:
                    broken.append({"subsystem": "SPC", "missing_id": spc_id})

        if ev_status == "ProcessStart":
            apc_id = event.get("apcID")
            if apc_id:
                exists = await db.object_snapshots.find_one(
                    {"objectID": apc_id, "objectName": "APC",
                     "status": "ProcessStart", "eventTime": event["eventTime"]},
                    {"_id": 1},
                )
                if not exists:
                    broken.append({"subsystem": "APC", "missing_id": apc_id})

            recipe_id = event.get("recipeID")
            if recipe_id:
                exists = await db.object_snapshots.find_one(
                    {"objectID": recipe_id, "objectName": "RECIPE",
                     "status": "ProcessStart", "eventTime": event["eventTime"]},
                    {"_id": 1},
                )
                if not exists:
                    broken.append({"subsystem": "RECIPE", "missing_id": recipe_id})

        if broken:
            orphan_list.append({
                "event_id":      str(event["_id"]),
                "eventTime":     event["eventTime"].isoformat() + "Z",
                "process_status": ev_status,
                "lotID":         event.get("lotID"),
                "toolID":        event.get("toolID"),
                "step":          event.get("step"),
                "broken_links":  broken,
            })
            if len(orphan_list) >= limit:
                break

    return {
        "total_orphans": len(orphan_list),
        "orphans":       orphan_list,
    }


# ── GET /context — Graph Context Service ─────────────────────────────────────

@router.get("/context")
async def get_graph_context(
    lot_id:         str  = Query(..., description="Lot ID, e.g. LOT-0001"),
    step:           str  = Query(..., description="Step ID, e.g. STEP_005"),
    process_status: str  = Query(
        "ProcessEnd",
        description="ProcessStart → show Recipe+APC only; ProcessEnd → show all 4 objects",
    ),
    ooc_only: bool = Query(False, description="If true, only return OOC events"),
):
    """
    Graph Context Service (Option B topology model).

    Given (lot_id, step, process_status), returns a nested JSON with all related
    entities. Two phases are supported:

      process_status=ProcessStart (t0):
        root.event_time = start_time
        recipe + apc populated; dc + spc = null (not yet measured)

      process_status=ProcessEnd (t1, default):
        root.event_time = end_time
        All 4 objects populated. root.start_time shows when processing began.

    This enables topology to accurately reflect what information was available
    at each phase of the process lifecycle.
    """
    db = get_db()

    req_status = process_status if process_status in ("ProcessStart", "ProcessEnd") else "ProcessEnd"

    filt: dict = {"lotID": lot_id, "step": step, "status": req_status, "eventType": "LOT_EVENT"}
    if ooc_only and req_status == "ProcessEnd":
        filt["spc_status"] = "OOC"

    event = await db.events.find_one(filt, sort=[("eventTime", -1)])
    if not event:
        # Fallback: try without status filter (backward compat with old data)
        filt_fb = {"lotID": lot_id, "step": step, "eventType": "LOT_EVENT"}
        if ooc_only:
            filt_fb["spc_status"] = "OOC"
        event = await db.events.find_one(filt_fb, sort=[("eventTime", -1)])
    if not event:
        detail = f"No event found for lot_id='{lot_id}' step='{step}' status='{req_status}'"
        raise HTTPException(status_code=404, detail=detail)

    event_id   = str(event["_id"])
    event_time = event["eventTime"]
    ev_status  = event.get("status", req_status)

    # ── If ProcessEnd, also fetch the paired ProcessStart event ───────────────
    start_event = None
    if ev_status == "ProcessEnd":
        start_event = await db.events.find_one(
            {"lotID": lot_id, "step": step, "status": "ProcessStart", "eventType": "LOT_EVENT"},
            sort=[("eventTime", -1)],
        )

    start_time = start_event["eventTime"] if start_event else None

    # ── Root node ──────────────────────────────────────────────────────────────
    root = {
        "lot_id":         lot_id,
        "step":           step,
        "event_id":       event_id,
        "process_status": ev_status,
        "event_time":     event_time.isoformat() + "Z",
        "start_time":     start_time.isoformat() + "Z" if start_time else None,
        "spc_status":     event.get("spc_status"),
        "recipe_id":      event.get("recipeID"),
        "apc_id":         event.get("apcID"),
        "tool_id":        event.get("toolID"),
    }

    # ── Tool node ──────────────────────────────────────────────────────────────
    tool_doc = await db.tools.find_one({"tool_id": event.get("toolID")})
    tool = _clean(tool_doc) if tool_doc else {"tool_id": event.get("toolID"), "status": "unknown"}

    # ── Recipe + APC: from ProcessStart event time ────────────────────────────
    # Use start_event time if available; else use current event time (old data)
    recipe_time = start_time if start_time else event_time
    apc_time    = start_time if start_time else event_time

    recipe_snap = await db.object_snapshots.find_one(
        {"objectID": event.get("recipeID"), "objectName": "RECIPE", "eventTime": recipe_time}
    )
    recipe = _clean(recipe_snap) if recipe_snap else {
        "recipe_id": event.get("recipeID"), "orphan": True
    }

    apc_snap = await db.object_snapshots.find_one(
        {"objectID": event.get("apcID"), "objectName": "APC", "eventTime": apc_time}
    )
    apc = _clean(apc_snap) if apc_snap else {
        "apc_id": event.get("apcID"), "orphan": True
    }

    # ── DC + SPC: only available at ProcessEnd ────────────────────────────────
    dc = None
    spc = None
    if ev_status == "ProcessEnd":
        dc_snap_id = event.get("dcSnapshotId")
        if dc_snap_id:
            dc_snap = await db.object_snapshots.find_one({"_id": _oid(dc_snap_id)})
            dc = _clean(dc_snap) if dc_snap else {"snapshot_id": dc_snap_id, "orphan": True}

        spc_snap_id = event.get("spcSnapshotId")
        if spc_snap_id:
            spc_snap = await db.object_snapshots.find_one({"_id": _oid(spc_snap_id)})
            spc = _clean(spc_snap) if spc_snap else {"snapshot_id": spc_snap_id, "orphan": True}

    return {
        "root":   root,
        "tool":   tool,
        "recipe": recipe,
        "apc":    apc,
        "dc":     dc,
        "spc":    spc,
    }


# ── GET /trajectory/tool/{tool_id} — Pillar 2: Tool-Centric Trajectory ───────

@router.get("/trajectory/tool/{tool_id}")
async def get_tool_trajectory(
    tool_id: str,
    limit: int = Query(200, ge=1, le=1000),
    include_state_events: bool = Query(False),
):
    """
    Pillar 2 — Tool-Centric Trajectory.

    Returns deduplicated batch history for ``tool_id`` — one entry per (lot, step)
    combining ProcessStart (start_time, recipe, apc) with ProcessEnd (end_time,
    dc, spc, spc_status). In-progress batches (ProcessEnd not yet written) appear
    with end_time=null.
    """
    db = get_db()

    tool_doc = await db.tools.find_one({"tool_id": tool_id})
    if not tool_doc:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found")

    cursor = (
        db.events
        .find({"toolID": tool_id, "eventType": "TOOL_EVENT"})
        .sort("eventTime", 1)
        .limit(limit * 2)   # ×2 because each batch = 2 events
    )
    events = await cursor.to_list(length=limit * 2)

    # Group by (lot_id, step) → merge ProcessStart + ProcessEnd
    batch_map: dict = {}
    for ev in events:
        key = (ev.get("lotID"), ev.get("step"))
        if key not in batch_map:
            batch_map[key] = {"lot_id": ev.get("lotID"), "step": ev.get("step")}
        ev_status = ev.get("status", "ProcessEnd")
        if ev_status == "ProcessStart":
            batch_map[key]["start_time"]  = ev["eventTime"].isoformat() + "Z"
            batch_map[key]["recipe_id"]   = ev.get("recipeID")
            batch_map[key]["apc_id"]      = ev.get("apcID")
        else:
            batch_map[key]["end_time"]        = ev["eventTime"].isoformat() + "Z"
            batch_map[key]["spc_status"]      = ev.get("spc_status")
            batch_map[key]["dc_snapshot_id"]  = ev.get("dcSnapshotId")
            batch_map[key]["spc_snapshot_id"] = ev.get("spcSnapshotId")

    # Sort by start_time descending; limit to requested count
    batches = sorted(
        batch_map.values(),
        key=lambda b: b.get("start_time") or b.get("end_time") or "",
        reverse=True,
    )[:limit]

    state_events = []
    if include_state_events:
        se_cursor = (
            db.tool_events
            .find({"toolID": tool_id})
            .sort("eventTime", -1)
            .limit(limit)
        )
        se_docs = await se_cursor.to_list(length=limit)
        for se in se_docs:
            state_events.append({
                "event_id":   str(se["_id"]),
                "event_time": se["eventTime"].isoformat() + "Z",
                "event_type": se.get("eventType"),
                "lot_id":     se.get("lotID"),
                "step":       se.get("step"),
                "metadata":   se.get("metadata", {}),
            })

    return {
        "tool_id":       tool_id,
        "tool_info":     _clean(tool_doc),
        "total_batches": len(batches),
        "batches":       batches,
        "state_events":  state_events,
    }


# ── GET /trajectory/lot/{lot_id} — Pillar 3 canonical URL ────────────────────

@router.get("/trajectory/lot/{lot_id}")
async def get_lot_trajectory_canonical(lot_id: str):
    """Pillar 3 — Lot-Centric Trajectory (canonical URL)."""
    return await _lot_trajectory_impl(lot_id)


@router.get("/trajectory/{lot_id}")
async def get_trajectory(lot_id: str):
    """Legacy alias for Pillar 3 — kept for backward compatibility."""
    return await _lot_trajectory_impl(lot_id)


async def _lot_trajectory_impl(lot_id: str) -> dict:
    """
    Lot-Centric Trace — ordered sequence of steps for this lot.

    Each entry is deduplicated from ProcessStart + ProcessEnd events, yielding
    one record per step with both start_time and end_time plus all object refs.
    In-progress steps have end_time=null.
    """
    db = get_db()

    lot_doc = await db.lots.find_one({"lot_id": lot_id})
    if not lot_doc:
        raise HTTPException(status_code=404, detail=f"Lot '{lot_id}' not found")

    cursor = db.events.find({"lotID": lot_id, "eventType": "LOT_EVENT"}).sort("eventTime", 1)
    events = await cursor.to_list(length=None)

    # Group by step → merge ProcessStart + ProcessEnd
    step_map: dict = {}
    for ev in events:
        key = ev.get("step")
        if key not in step_map:
            step_map[key] = {"step": key, "tool_id": ev.get("toolID")}
        ev_status = ev.get("status", "ProcessEnd")
        if ev_status == "ProcessStart":
            step_map[key]["start_time"] = ev["eventTime"].isoformat() + "Z"
            step_map[key]["recipe_id"]  = ev.get("recipeID")
            step_map[key]["apc_id"]     = ev.get("apcID")
        else:
            step_map[key]["end_time"]        = ev["eventTime"].isoformat() + "Z"
            step_map[key]["spc_status"]      = ev.get("spc_status")
            step_map[key]["dc_snapshot_id"]  = ev.get("dcSnapshotId")
            step_map[key]["spc_snapshot_id"] = ev.get("spcSnapshotId")

    steps = sorted(
        step_map.values(),
        key=lambda s: s.get("start_time") or s.get("end_time") or "",
    )

    return {
        "lot_id":      lot_id,
        "total_steps": len(steps),
        "steps":       steps,
    }


# ── GET /history/{object_type}/{object_id} — Pillar 4: Object-Centric ────────

_VALID_HISTORY_TYPES = {"APC", "RECIPE", "DC", "SPC"}


@router.get("/history/{object_type}/{object_id}")
async def get_object_history(
    object_type: str,
    object_id: str,
    limit: int = Query(200, ge=1, le=1000),
):
    """
    Pillar 4 — Object-Centric Performance History.

    Returns snapshot history for a specific object, with each record joined
    against the events collection to surface spc_status. The ``process_status``
    field indicates which phase the snapshot was captured in (ProcessStart or
    ProcessEnd), matching the semantics introduced in the two-event model.
    """
    obj_type = object_type.upper()
    if obj_type not in _VALID_HISTORY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid object_type '{object_type}'. Must be one of: {sorted(_VALID_HISTORY_TYPES)}",
        )

    db = get_db()

    cursor = (
        db.object_snapshots
        .find({"objectID": object_id, "objectName": obj_type})
        .sort("eventTime", -1)
        .limit(limit)
    )
    snapshots = await cursor.to_list(length=limit)

    if not snapshots:
        raise HTTPException(
            status_code=404,
            detail=f"No history found for {obj_type}/{object_id}",
        )

    history = []
    for snap in snapshots:
        event_time   = snap.get("eventTime")
        snap_id      = str(snap["_id"])
        snap_status  = snap.get("status")  # ProcessStart or ProcessEnd

        # ── Join: locate the production event that generated this snapshot ──
        if obj_type == "APC":
            ev = await db.events.find_one(
                {"apcID": object_id, "eventTime": event_time, "status": "ProcessStart"},
                {"spc_status": 1, "lotID": 1, "toolID": 1, "step": 1},
            )
        elif obj_type == "RECIPE":
            ev = await db.events.find_one(
                {"recipeID": object_id, "eventTime": event_time, "status": "ProcessStart"},
                {"spc_status": 1, "lotID": 1, "toolID": 1, "step": 1},
            )
        elif obj_type == "DC":
            ev = await db.events.find_one(
                {"dcSnapshotId": snap_id},
                {"spc_status": 1, "lotID": 1, "toolID": 1, "step": 1},
            )
        else:  # SPC
            ev = await db.events.find_one(
                {"spcSnapshotId": snap_id},
                {"spc_status": 1, "lotID": 1, "toolID": 1, "step": 1},
            )

        # For Recipe/APC: spc_status lives on the ProcessEnd event for the same (lot, step)
        spc_status = None
        if ev:
            spc_status = ev.get("spc_status")
            if spc_status is None and obj_type in ("APC", "RECIPE"):
                lot_id = snap.get("lotID") or ev.get("lotID")
                step   = snap.get("step")  or ev.get("step")
                end_ev = await db.events.find_one(
                    {"lotID": lot_id, "step": step, "status": "ProcessEnd",
                     "eventType": "LOT_EVENT"},
                    {"spc_status": 1},
                )
                if end_ev:
                    spc_status = end_ev.get("spc_status")

        lot_id  = snap.get("lotID")  or (ev.get("lotID")  if ev else None)
        tool_id = snap.get("toolID") or (ev.get("toolID") if ev else None)
        step    = snap.get("step")   or (ev.get("step")   if ev else None)

        history.append({
            "snapshot_id":    snap_id,
            "process_status": snap_status,
            "event_time":     event_time.isoformat() + "Z" if event_time else None,
            "lot_id":         lot_id,
            "tool_id":        tool_id,
            "step":           step,
            "spc_status":     spc_status,
            "parameters":     snap.get("parameters"),
        })

    return {
        "object_type":   obj_type,
        "object_id":     object_id,
        "total_records": len(history),
        "history":       history,
    }


# ── GET /indices/{object_type} — Object-Centric Index Explorer ───────────────

_VALID_OBJECT_TYPES = {"APC", "RECIPE", "DC", "SPC"}

@router.get("/indices/{object_type}")
async def get_object_indices(
    object_type: str,
    limit: int = Query(50, ge=1, le=200),
    status: str = Query(None, description="Filter by spc_status, e.g. 'OOC'"),
    process_status: str = Query(None, description="Filter by process phase: ProcessStart | ProcessEnd"),
):
    """
    Object-Centric Index Explorer — list the most recent N snapshot index records,
    newest first.

    Each record now includes ``process_status`` indicating which phase the snapshot
    was captured in (ProcessStart for RECIPE/APC; ProcessEnd for DC/SPC).
    """
    obj = object_type.upper()
    if obj not in _VALID_OBJECT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid object_type '{object_type}'. Must be one of: {sorted(_VALID_OBJECT_TYPES)}",
        )

    db = get_db()
    filt: dict = {"objectName": obj}
    if status:
        filt["spc_status"] = status.upper()
    if process_status and process_status in ("ProcessStart", "ProcessEnd"):
        filt["status"] = process_status

    cursor = (
        db.object_snapshots
        .find(filt)
        .sort("eventTime", -1)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)

    records = []
    for doc in docs:
        records.append({
            "index_id":       str(doc["_id"]),
            "object_id":      doc.get("objectID"),
            "process_status": doc.get("status"),
            "event_time":     doc["eventTime"].isoformat() + "Z" if doc.get("eventTime") else None,
            "lot_id":         doc.get("lotID"),
            "tool_id":        doc.get("toolID"),
            "step":           doc.get("step"),
            "payload":        {k: (str(v) if isinstance(v, ObjectId) else v)
                               for k, v in doc.items() if k not in ("_id",)},
        })

    return {
        "object_type": obj,
        "count":       len(records),
        "records":     records,
    }


# ── GET /enumerate — list available lot_ids, tool_ids, steps ─────────────────

@router.get("/enumerate")
async def enumerate_ids():
    """Return sorted lists of all lot_ids, tool_ids, and step names for UI dropdowns."""
    db = get_db()
    lot_docs  = await db.lots.distinct("lot_id")
    tool_docs = await db.tools.distinct("tool_id")
    from config import TOTAL_STEPS
    steps = [f"STEP_{str(i).zfill(3)}" for i in range(1, TOTAL_STEPS + 1)]
    return {
        "lot_ids":  sorted(lot_docs),
        "tool_ids": sorted(tool_docs),
        "steps":    steps,
    }
