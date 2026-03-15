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
import hashlib
import math
import random
from datetime import datetime, timezone, timedelta
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
    lot_id:     str           = Query(..., description="Lot ID, e.g. LOT-0001"),
    step:       str           = Query(..., description="Step ID, e.g. STEP_005"),
    event_time: datetime|None = Query(None,  description="ISO8601 anchor time — locks context to the specific run that started at/near this time"),
    ooc_only:   bool          = Query(False, description="If true, only return OOC events"),
):
    """
    Graph Context Service.

    Anchors to the process run whose ProcessStart is at/before event_time.
    Only returns DC+SPC if the ProcessEnd for THAT run has been written.
    This prevents showing stale DC/SPC from a previous cycle when a lot is
    currently in-progress on the same step.

      in_progress=False: full context (Recipe+APC+DC+SPC)
      in_progress=True : partial context (Recipe+APC only; DC+SPC=null)
    """
    db = get_db()

    # ── 1. Find the anchored ProcessStart ─────────────────────────────────────
    start_filt: dict = {"lotID": lot_id, "step": step, "status": "ProcessStart", "eventType": "LOT_EVENT"}
    if event_time:
        # Normalise to naive UTC for MongoDB comparison
        et = event_time.astimezone(timezone.utc).replace(tzinfo=None) if event_time.tzinfo else event_time
        # ProcessStart at or before the anchor (within 5s tolerance for clock skew)
        start_filt["eventTime"] = {"$lte": et + timedelta(seconds=5)}
    start_event = await db.events.find_one(start_filt, sort=[("eventTime", -1)])

    # ── 2. Find the paired ProcessEnd (must come AFTER this ProcessStart) ──────
    end_filt: dict = {"lotID": lot_id, "step": step, "status": "ProcessEnd", "eventType": "LOT_EVENT"}
    if start_event:
        end_filt["eventTime"] = {"$gt": start_event["eventTime"]}
    if ooc_only:
        end_filt["spc_status"] = "OOC"
    end_event = await db.events.find_one(end_filt, sort=[("eventTime", 1)])  # earliest end after start

    # ── Determine authoritative event & phase ─────────────────────────────────
    # Priority: ProcessEnd (complete) > ProcessStart (in-progress) > 404
    if end_event:
        event     = end_event
        ev_status = "ProcessEnd"
        in_progress = False
    elif start_event:
        # Step is currently in-progress; return partial context (Recipe+APC only)
        event     = start_event
        ev_status = "ProcessStart"
        in_progress = True
    else:
        raise HTTPException(
            status_code=404,
            detail=f"No event found for lot_id='{lot_id}' step='{step}'",
        )

    if ooc_only and ev_status != "ProcessEnd":
        raise HTTPException(status_code=404, detail="No OOC ProcessEnd event found")

    event_id   = str(event["_id"])
    event_time = event["eventTime"]
    start_time = start_event["eventTime"] if start_event else None

    # ── Root node ──────────────────────────────────────────────────────────────
    root = {
        "lot_id":         lot_id,
        "step":           step,
        "event_id":       event_id,
        "process_status": ev_status,
        "in_progress":    in_progress,
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

    # ── Recipe + APC: from ProcessStart event ────────────────────────────────
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
    spc_snap_raw = None
    if ev_status == "ProcessEnd":
        dc_snap_id = event.get("dcSnapshotId")
        if dc_snap_id:
            dc_snap = await db.object_snapshots.find_one({"_id": _oid(dc_snap_id)})
            dc = _clean(dc_snap) if dc_snap else {"snapshot_id": dc_snap_id, "orphan": True}

        spc_snap_id = event.get("spcSnapshotId")
        if spc_snap_id:
            spc_snap_raw = await db.object_snapshots.find_one({"_id": _oid(spc_snap_id)})
            spc = _clean(spc_snap_raw) if spc_snap_raw else {"snapshot_id": spc_snap_id, "orphan": True}

    tool_id = event.get("toolID")

    # ── EC: ProcessStart only — machine state before process ─────────────────
    ec = _compute_ec(tool_id) if tool_id else None

    # ── FDC + OCAP: ProcessEnd only ───────────────────────────────────────────
    fdc = None
    ocap = None
    if ev_status == "ProcessEnd":
        if tool_id:
            fdc = await _compute_fdc_for_context(db, tool_id, step)
        if root.get("spc_status") == "OOC":
            ocap = _compute_ocap_inline(lot_id, step, "OOC", spc_snap_raw)

    # ── Summary (LLM-readable, concise) ──────────────────────────────────────
    summary = _build_summary(root, recipe, apc, dc, spc, ec=ec, ocap=ocap)

    return {
        "root":    root,
        "tool":    tool,
        "recipe":  recipe,   # ProcessStart
        "apc":     apc,      # ProcessStart
        "ec":      ec,       # ProcessStart — machine constants vs golden baseline
        "dc":      dc,       # ProcessEnd
        "spc":     spc,      # ProcessEnd
        "fdc":     fdc,      # ProcessEnd — U-chart defect rate trend
        "ocap":    ocap,     # ProcessEnd, OOC only — action plan
        "summary": summary,
    }


def _compute_ec(tool_id: str) -> dict:
    """Compute deterministic Equipment Constants for a tool (no DB needed)."""
    seed = int(hashlib.md5(tool_id.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    ec_params = {
        "rf_power_offset":       {"setpoint": 0.0,    "unit": "W",    "tolerance_pct": 2.0},
        "throttle_setpoint":     {"setpoint": 65.0,   "unit": "%",    "tolerance_pct": 3.0},
        "he_backside_pressure":  {"setpoint": 10.0,   "unit": "Torr", "tolerance_pct": 5.0},
        "focus_ring_thickness":  {"setpoint": 8.5,    "unit": "mm",   "tolerance_pct": 8.0},
        "chamber_wall_temp":     {"setpoint": 60.0,   "unit": "°C",   "tolerance_pct": 4.0},
        "electrode_gap":         {"setpoint": 27.0,   "unit": "mm",   "tolerance_pct": 1.5},
        "rf_match_c1":           {"setpoint": 142.0,  "unit": "pF",   "tolerance_pct": 3.0},
        "rf_match_c2":           {"setpoint": 88.0,   "unit": "pF",   "tolerance_pct": 3.0},
    }

    constants = {}
    drift_count = 0
    for param, spec in ec_params.items():
        drift_factor = rng.gauss(0, spec["tolerance_pct"] * 0.4)
        value = round(spec["setpoint"] + spec["setpoint"] * drift_factor / 100, 3) if spec["setpoint"] != 0 else round(drift_factor * 0.01, 4)
        deviation_pct = abs((value - spec["setpoint"]) / spec["setpoint"] * 100) if spec["setpoint"] != 0 else abs(value) * 10
        if deviation_pct > spec["tolerance_pct"]:
            status = "ALERT" if deviation_pct > spec["tolerance_pct"] * 2 else "DRIFT"
            drift_count += 1
        else:
            status = "NORMAL"
        constants[param] = {"value": value, "setpoint": spec["setpoint"], "unit": spec["unit"],
                            "tolerance_pct": spec["tolerance_pct"], "deviation_pct": round(deviation_pct, 2), "status": status}

    drift_params = [p for p, v in constants.items() if v["status"] != "NORMAL"]
    if drift_params:
        most_critical = max(drift_params, key=lambda p: constants[p]["deviation_pct"])
        summary = f"{drift_count} parameter(s) drifting on {tool_id}. Most critical: {most_critical} ({constants[most_critical]['deviation_pct']:.1f}% deviation)."
    else:
        summary = f"All EC parameters within tolerance on {tool_id}."

    return {"tool_id": tool_id, "constants": constants, "drift_count": drift_count, "summary": summary}


async def _compute_fdc_for_context(db, tool_id: str, step: str, limit: int = 20) -> dict:
    """Compute FDC U-chart condensed summary for a tool/step (ProcessEnd context)."""
    query = {"toolID": tool_id, "status": "ProcessEnd", "eventType": "LOT_EVENT", "step": step}
    cursor = (
        db.events
        .find(query, {"lotID": 1, "step": 1, "eventTime": 1, "spc_status": 1, "_id": 0})
        .sort("eventTime", -1)
        .limit(limit)
    )
    records = await cursor.to_list(length=limit)

    if not records:
        return {"tool_id": tool_id, "step": step, "uchart": [], "ooc_count": 0,
                "baseline": {"u_bar": 0, "ucl": 0, "lcl": 0}, "summary": f"No FDC data for {tool_id} {step}"}

    seed_base = int(hashlib.md5(tool_id.encode()).hexdigest()[:8], 16)
    uchart_data = []
    for i, rec in enumerate(records):
        rng = random.Random(seed_base + i)
        is_ooc = rec.get("spc_status") == "OOC"
        base_u = rng.gauss(0.05, 0.015)
        u_value = round(max(0.0, base_u * (1.8 if is_ooc else 1.0)), 4)
        uchart_data.append({"lot_id": rec.get("lotID"), "step": rec.get("step"),
                             "event_time": rec["eventTime"].isoformat() + "Z" if rec.get("eventTime") else None,
                             "u_value": u_value, "sample_size": rng.randint(45, 55),
                             "spc_status": rec.get("spc_status", "PASS")})

    u_bar = sum(r["u_value"] for r in uchart_data) / len(uchart_data)
    n_avg = sum(r["sample_size"] for r in uchart_data) / len(uchart_data)
    ucl = round(u_bar + 3 * math.sqrt(u_bar / n_avg), 4) if u_bar > 0 else 0.0
    lcl = round(max(0, u_bar - 3 * math.sqrt(u_bar / n_avg)), 4) if u_bar > 0 else 0.0
    ooc_count = sum(1 for r in uchart_data if r["u_value"] > ucl or (lcl > 0 and r["u_value"] < lcl))
    uchart_data.sort(key=lambda x: x["event_time"] or "")

    return {"tool_id": tool_id, "step": step, "uchart": uchart_data,
            "baseline": {"u_bar": round(u_bar, 4), "ucl": ucl, "lcl": lcl, "n_average": round(n_avg, 1)},
            "ooc_count": ooc_count,
            "summary": f"{tool_id} {step}: {len(uchart_data)} lots, u_bar={u_bar:.4f}, UCL={ucl:.4f}, OOC={ooc_count}/{len(uchart_data)}"}


def _compute_ocap_inline(lot_id: str, step: str, spc_status: str, spc_snap: dict | None) -> dict | None:
    """Build OCAP from already-fetched SPC snapshot. Returns None if SPC PASS."""
    if spc_status != "OOC":
        return None

    triggered_by = []
    if spc_snap:
        charts = spc_snap.get("charts", {}) or spc_snap.get("parameters", {})
        for chart_name, chart_data in charts.items():
            if isinstance(chart_data, dict) and chart_data.get("status") == "OOC":
                triggered_by.append({
                    "chart": chart_name,
                    "parameter": chart_data.get("parameter", chart_name),
                    "violation_type": "beyond_control_limit",
                    "value": chart_data.get("latest_value"),
                    "ucl": chart_data.get("ucl"),
                    "lcl": chart_data.get("lcl"),
                })

    if not triggered_by:
        seed = int(hashlib.md5(f"{lot_id}{step}".encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        candidates = ["xbar_chart (CD mean shift)", "r_chart (within-wafer range)", "s_chart (std dev spike)"]
        triggered_by = [{
            "chart": rng.choice(candidates),
            "parameter": "cd_mean",
            "violation_type": "beyond_3sigma",
            "value": None, "ucl": None, "lcl": None,
        }]

    n = len(triggered_by)
    severity = "CRITICAL" if n >= 3 else "HIGH" if n == 2 else "MEDIUM"
    actions = [
        {"priority": 1, "category": "HOLD",    "action": f"Hold lot {lot_id} — do not proceed to next step until root cause confirmed", "owner": "Process Engineer", "deadline_hours": 1},
        {"priority": 2, "category": "VERIFY",  "action": "Re-measure critical dimension on 5 monitor wafers from same cassette", "owner": "Metrology", "deadline_hours": 2},
        {"priority": 3, "category": "INSPECT", "action": f"Check equipment constants on {step} tool — focus on rf_power_offset and throttle_setpoint", "owner": "Equipment Engineer", "deadline_hours": 4},
        {"priority": 4, "category": "REVIEW",  "action": "Compare APC model parameters with last 10 PASS lots — check for model drift", "owner": "APC Engineer", "deadline_hours": 8},
    ]
    if severity in ("HIGH", "CRITICAL"):
        actions.append({"priority": 5, "category": "ESCALATE",
                        "action": "Notify shift supervisor and fab manager — potential systematic issue",
                        "owner": "Shift Engineer", "deadline_hours": 1})

    chart_names = [t["chart"] for t in triggered_by]
    summary = (f"OOC on {lot_id} {step}: {n} chart(s) triggered ({', '.join(chart_names)}). "
               f"Severity={severity}. {len(actions)} action(s) required.")
    return {"lot_id": lot_id, "step": step, "spc_status": spc_status,
            "triggered_by": triggered_by, "actions": actions, "severity": severity, "summary": summary}


def _build_summary(root: dict, recipe: dict | None, apc: dict | None,
                   dc: dict | None, spc: dict | None,
                   ec: dict | None = None, ocap: dict | None = None) -> str:
    """One-paragraph text summary for LLM consumption.
    Surfaces only the diagnostically relevant values — no raw parameter dumps.
    """
    parts: list[str] = []

    phase = "⏳ In Progress" if root.get("in_progress") else "Complete"
    ts    = (root.get("event_time") or "")[:19].replace("T", " ")
    parts.append(f"[{root['lot_id']} @ {root.get('tool_id','?')} {root['step']} | {ts} | {phase}]")

    # Recipe
    if recipe and not recipe.get("orphan"):
        rid = recipe.get("objectID") or recipe.get("recipe_id", "?")
        parts.append(f"Recipe: {rid}")

    # APC
    if apc and not apc.get("orphan"):
        aid   = apc.get("objectID") or apc.get("apc_id", "?")
        params = apc.get("parameters") or {}
        bias  = params.get("rf_power_bias") or params.get("model_intercept")
        bias_str = f" bias={bias:.4f}" if isinstance(bias, (int, float)) else ""
        parts.append(f"APC: {aid}{bias_str}")

    # DC
    if dc and not dc.get("orphan"):
        dc_status = dc.get("status", "?")
        params    = dc.get("parameters") or {}
        # Surface any OOC parameters (value outside control limits)
        ooc_fields: list[str] = []
        for k, v in params.items():
            if k.endswith("_ucl") or k.endswith("_lcl"):
                continue
            ucl = params.get(f"{k}_ucl")
            lcl = params.get(f"{k}_lcl")
            if isinstance(v, (int, float)) and isinstance(ucl, (int, float)) and v > ucl:
                ooc_fields.append(f"{k}={v:.3f}>UCL{ucl:.3f}")
            elif isinstance(v, (int, float)) and isinstance(lcl, (int, float)) and v < lcl:
                ooc_fields.append(f"{k}={v:.3f}<LCL{lcl:.3f}")
        ooc_str = " VIOLATIONS: " + ", ".join(ooc_fields[:3]) if ooc_fields else ""
        parts.append(f"DC: {dc_status}{ooc_str}")

    # SPC
    if spc and not spc.get("orphan"):
        spc_status = root.get("spc_status") or spc.get("status", "?")
        charts     = spc.get("charts") or {}
        ooc_charts = [name for name, c in charts.items()
                      if isinstance(c, dict) and c.get("status") == "OOC"]
        ooc_str = f" OOC charts: {', '.join(ooc_charts[:3])}" if ooc_charts else ""
        parts.append(f"SPC: {spc_status}{ooc_str}")

    # EC (ProcessStart)
    if ec:
        drift_count = ec.get("drift_count", 0)
        if drift_count > 0:
            alerts = [p for p, v in ec.get("constants", {}).items() if v.get("status") == "ALERT"]
            drifts = [p for p, v in ec.get("constants", {}).items() if v.get("status") == "DRIFT"]
            ec_str = ""
            if alerts:
                ec_str += f" ALERT: {', '.join(alerts[:2])}"
            if drifts:
                ec_str += f" DRIFT: {', '.join(drifts[:2])}"
            parts.append(f"EC:{ec_str}")
        else:
            parts.append("EC: all OK")

    # OCAP (ProcessEnd, OOC only)
    if ocap:
        parts.append(f"OCAP: severity={ocap.get('severity')} {len(ocap.get('actions', []))} actions")

    if root.get("in_progress"):
        parts.append("DC/SPC not yet available (step in progress).")

    return " | ".join(parts)


# ── GET /trajectory/tool/{tool_id} — Pillar 2: Tool-Centric Trajectory ───────

@router.get("/trajectory/tool/{tool_id}/step/{step}")
async def get_tool_step_trajectory(
    tool_id: str,
    step: str,
    start_time: datetime | None = Query(None, description="Window start (ISO8601)"),
    end_time:   datetime | None = Query(None, description="Window end (ISO8601)"),
    limit: int = Query(200, ge=1, le=1000),
):
    """
    Tool + Step query — all lots that ran a specific step on this tool.

    Returns one entry per lot, ordered newest-first. Optionally filtered by
    start_time / end_time window (applied to ProcessEnd eventTime).
    """
    db = get_db()
    filt: dict = {"toolID": tool_id, "step": step, "eventType": "TOOL_EVENT"}
    if start_time or end_time:
        time_filt: dict = {}
        if start_time:
            st = start_time.astimezone(timezone.utc).replace(tzinfo=None) if start_time.tzinfo else start_time
            time_filt["$gte"] = st
        if end_time:
            et = end_time.astimezone(timezone.utc).replace(tzinfo=None) if end_time.tzinfo else end_time
            time_filt["$lte"] = et
        filt["eventTime"] = time_filt

    raw = await db.events.find(filt, {"_id": 0}).sort("eventTime", -1).limit(limit * 2).to_list(length=limit * 2)

    # Merge ProcessStart + ProcessEnd per lot
    lot_map: dict = {}
    for ev in raw:
        lot = ev.get("lotID")
        if lot not in lot_map:
            lot_map[lot] = {"lot_id": lot, "tool_id": tool_id, "step": step}
        ev_status = ev.get("status", "ProcessEnd")
        if ev_status == "ProcessStart":
            lot_map[lot]["start_time"] = ev["eventTime"].isoformat() + "Z"
            lot_map[lot]["recipe_id"]  = ev.get("recipeID")
            lot_map[lot]["apc_id"]     = ev.get("apcID")
        else:
            lot_map[lot]["end_time"]        = ev["eventTime"].isoformat() + "Z"
            lot_map[lot]["spc_status"]      = ev.get("spc_status")
            lot_map[lot]["dc_snapshot_id"]  = ev.get("dcSnapshotId")
            lot_map[lot]["spc_snapshot_id"] = ev.get("spcSnapshotId")

    batches = sorted(
        lot_map.values(),
        key=lambda b: b.get("end_time") or b.get("start_time") or "",
        reverse=True,
    )[:limit]

    summary = (
        f"Tool {tool_id}, Step {step}: {len(batches)} lot(s) found"
        + (f" in window [{start_time.isoformat()[:16] if start_time else ''} → {end_time.isoformat()[:16] if end_time else ''}]" if start_time or end_time else "")
        + f". OOC: {sum(1 for b in batches if b.get('spc_status') == 'OOC')} / {len(batches)}."
    )
    return {
        "tool_id": tool_id,
        "step":    step,
        "total_batches": len(batches),
        "batches": batches,
        "summary": summary,
    }


@router.get("/trajectory/tool/{tool_id}")
async def get_tool_trajectory(
    tool_id: str,
    start_time: datetime | None = Query(None, description="Window start (ISO8601) — filter by ProcessEnd eventTime"),
    end_time:   datetime | None = Query(None, description="Window end (ISO8601)"),
    limit: int = Query(200, ge=1, le=1000),
    include_state_events: bool = Query(False),
):
    """
    Pillar 2 — Tool-Centric Trajectory.

    Returns deduplicated batch history for ``tool_id`` — one entry per (lot, step)
    combining ProcessStart (start_time, recipe, apc) with ProcessEnd (end_time,
    dc, spc, spc_status). In-progress batches (ProcessEnd not yet written) appear
    with end_time=null.

    Optional start_time / end_time filter the window by ProcessEnd eventTime.
    """
    db = get_db()

    tool_doc = await db.tools.find_one({"tool_id": tool_id})
    if not tool_doc:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found")

    filt: dict = {"toolID": tool_id, "eventType": "TOOL_EVENT"}
    if start_time or end_time:
        time_filt: dict = {}
        if start_time:
            st = start_time.astimezone(timezone.utc).replace(tzinfo=None) if start_time.tzinfo else start_time
            time_filt["$gte"] = st
        if end_time:
            et = end_time.astimezone(timezone.utc).replace(tzinfo=None) if end_time.tzinfo else end_time
            time_filt["$lte"] = et
        filt["eventTime"] = time_filt

    cursor = (
        db.events
        .find(filt)
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
async def get_lot_trajectory_canonical(
    lot_id: str,
    start_time: datetime | None = Query(None, description="Window start (ISO8601)"),
    end_time:   datetime | None = Query(None, description="Window end (ISO8601)"),
    limit:      int            = Query(500, ge=1, le=2000),
):
    """Pillar 3 — Lot-Centric Trajectory (canonical URL).

    Optional start_time / end_time narrow results to a specific period.
    limit caps the number of returned steps (default 500 = full lot history).
    """
    return await _lot_trajectory_impl(lot_id, start_time=start_time, end_time=end_time, limit=limit)


@router.get("/trajectory/{lot_id}")
async def get_trajectory(lot_id: str):
    """Legacy alias for Pillar 3 — kept for backward compatibility."""
    return await _lot_trajectory_impl(lot_id)


async def _lot_trajectory_impl(
    lot_id: str,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 500,
) -> dict:
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

    filt: dict = {"lotID": lot_id, "eventType": "LOT_EVENT"}
    if start_time or end_time:
        time_filt: dict = {}
        if start_time:
            st = start_time.astimezone(timezone.utc).replace(tzinfo=None) if start_time.tzinfo else start_time
            time_filt["$gte"] = st
        if end_time:
            et = end_time.astimezone(timezone.utc).replace(tzinfo=None) if end_time.tzinfo else end_time
            time_filt["$lte"] = et
        filt["eventTime"] = time_filt

    cursor = db.events.find(filt).sort("eventTime", 1).limit(limit * 2)
    events = await cursor.to_list(length=limit * 2)

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
    )[:limit]

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
    object_id:   str,
    start_time:  datetime | None = Query(None, description="Window start (ISO8601)"),
    end_time:    datetime | None = Query(None, description="Window end (ISO8601)"),
    limit:       int             = Query(200, ge=1, le=1000),
):
    """
    Pillar 4 — Object-Centric Performance History.

    Returns snapshot history for a specific object, with each record joined
    against the events collection to surface spc_status. The ``process_status``
    field indicates which phase the snapshot was captured in (ProcessStart or
    ProcessEnd), matching the semantics introduced in the two-event model.

    Optional start_time / end_time filter snapshots to a time window.
    """
    obj_type = object_type.upper()
    if obj_type not in _VALID_HISTORY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid object_type '{object_type}'. Must be one of: {sorted(_VALID_HISTORY_TYPES)}",
        )

    db = get_db()

    snap_filt: dict = {"objectID": object_id, "objectName": obj_type}
    if start_time or end_time:
        time_filt: dict = {}
        if start_time:
            st = start_time.astimezone(timezone.utc).replace(tzinfo=None) if start_time.tzinfo else start_time
            time_filt["$gte"] = st
        if end_time:
            et = end_time.astimezone(timezone.utc).replace(tzinfo=None) if end_time.tzinfo else end_time
            time_filt["$lte"] = et
        snap_filt["eventTime"] = time_filt

    cursor = (
        db.object_snapshots
        .find(snap_filt)
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


# ── GET /stats/baseline — DC Parameter Baseline Statistics ───────────────────

@router.get("/stats/baseline")
async def get_baseline_stats(
    tool_id:    str            = Query(..., description="Tool ID, e.g. EQP-01"),
    recipe_id:  str | None     = Query(None, description="Optional recipe filter, e.g. RCP-003"),
    start_time: datetime | None = Query(None, description="Window start (ISO8601)"),
    end_time:   datetime | None = Query(None, description="Window end (ISO8601)"),
    limit:      int            = Query(200, ge=10, le=2000),
):
    """
    DC Parameter Baseline Statistics.

    Returns mean and std_dev for every DC parameter across all ProcessEnd
    snapshots matching the filter window. Agent uses this to compute
    3-sigma bounds and judge whether a current reading is anomalous.

    Response includes per-parameter: mean, std_dev, min, max, sample_count.
    Also returns a 'summary' string for direct LLM consumption.
    """
    db = get_db()

    filt: dict = {"toolID": tool_id, "objectName": "DC"}
    if start_time:
        st = start_time.astimezone(timezone.utc).replace(tzinfo=None) if start_time.tzinfo else start_time
        filt.setdefault("eventTime", {})["$gte"] = st
    if end_time:
        et = end_time.astimezone(timezone.utc).replace(tzinfo=None) if end_time.tzinfo else end_time
        filt.setdefault("eventTime", {})["$lte"] = et

    # If recipe_id specified, only include snapshots from events using that recipe
    event_tool_ids: set | None = None
    if recipe_id:
        ev_cursor = db.events.find(
            {"toolID": tool_id, "recipeID": recipe_id, "status": "ProcessEnd"},
            {"dcSnapshotId": 1}
        ).limit(limit)
        evs = await ev_cursor.to_list(length=limit)
        snap_ids = [_oid(e["dcSnapshotId"]) for e in evs if e.get("dcSnapshotId")]
        if not snap_ids:
            raise HTTPException(404, f"No DC snapshots found for tool={tool_id} recipe={recipe_id}")
        filt["_id"] = {"$in": snap_ids}

    cursor = db.object_snapshots.find(filt).sort("eventTime", -1).limit(limit)
    snaps  = await cursor.to_list(length=limit)

    if not snaps:
        raise HTTPException(404, f"No DC snapshots found for tool_id='{tool_id}'")

    # Accumulate per-parameter statistics
    import math
    param_values: dict[str, list[float]] = {}
    for snap in snaps:
        for k, v in (snap.get("parameters") or {}).items():
            if isinstance(v, (int, float)) and not math.isnan(v):
                param_values.setdefault(k, []).append(float(v))

    stats: dict[str, dict] = {}
    for param, vals in param_values.items():
        n    = len(vals)
        mean = sum(vals) / n
        std  = math.sqrt(sum((x - mean) ** 2 for x in vals) / n) if n > 1 else 0.0
        stats[param] = {
            "mean":         round(mean, 6),
            "std_dev":      round(std, 6),
            "min":          round(min(vals), 6),
            "max":          round(max(vals), 6),
            "sample_count": n,
            "ucl_3sigma":   round(mean + 3 * std, 6),
            "lcl_3sigma":   round(mean - 3 * std, 6),
        }

    # LLM summary
    window_str = ""
    if start_time or end_time:
        window_str = f" [{(start_time or '').isoformat()[:10]} → {(end_time or '').isoformat()[:10]}]"
    recipe_str = f" recipe={recipe_id}" if recipe_id else ""
    summary = (
        f"Baseline stats for {tool_id}{recipe_str}{window_str}: "
        f"{len(snaps)} samples, {len(stats)} DC parameters. "
        f"Use ucl_3sigma/lcl_3sigma to judge if current readings are anomalous."
    )

    return {
        "tool_id":      tool_id,
        "recipe_id":    recipe_id,
        "sample_count": len(snaps),
        "param_count":  len(stats),
        "stats":        stats,
        "summary":      summary,
    }


# ── GET /timeseries/tool/{tool_id}/step/{step} — DC Parameter Time Series ────

@router.get("/timeseries/tool/{tool_id}/step/{step}")
async def get_dc_timeseries(
    tool_id: str,
    step: str,
    params: str | None = Query(None, description="Comma-separated DC parameter names to include, e.g. 'chamber_pressure,cf4_flow_sccm'. Omit to return all."),
    limit: int = Query(50, ge=5, le=500, description="Number of most recent process runs to return"),
):
    """
    DC Parameter Time Series — returns the last N measured values for each DC parameter
    on a specific (tool_id, step) combination, ordered oldest→newest.

    Designed for SPC charting: each point = one completed process run (ProcessEnd).
    Include baseline UCL/LCL computed from the same window so the frontend can
    draw control limits without a separate API call.

    Response:
    - tool_id, step, sample_count
    - param_names: list of parameter names in the dataset
    - series: { param_name: [{ t, lot_id, value }, ...] }  (oldest → newest)
    - baseline: { param_name: { mean, std_dev, ucl_3sigma, lcl_3sigma } }
    - spc_status_series: [{ t, lot_id, spc_status }]  (to overlay OOC markers)
    """
    import math
    db = get_db()

    # Fetch DC snapshots for this tool+step, newest first
    cursor = (
        db.object_snapshots
        .find({"toolID": tool_id, "step": step, "objectName": "DC"})
        .sort("eventTime", -1)
        .limit(limit)
    )
    snaps = await cursor.to_list(length=limit)

    if not snaps:
        raise HTTPException(404, f"No DC snapshots found for tool_id='{tool_id}' step='{step}'")

    # Reverse to chronological order
    snaps = list(reversed(snaps))

    # Determine which params to include
    param_filter = set(p.strip() for p in params.split(",")) if params else None

    # Build series data
    all_param_names: set[str] = set()
    for snap in snaps:
        for k in (snap.get("parameters") or {}).keys():
            if param_filter is None or k in param_filter:
                all_param_names.add(k)

    param_names = sorted(all_param_names)
    series: dict[str, list] = {p: [] for p in param_names}

    for snap in snaps:
        t = snap["eventTime"].isoformat() + "Z" if snap.get("eventTime") else None
        lot_id = snap.get("lotID")
        parameters = snap.get("parameters") or {}
        for p in param_names:
            val = parameters.get(p)
            if val is not None:
                series[p].append({"t": t, "lot_id": lot_id, "value": round(float(val), 6)})

    # Compute baseline from same window
    baseline: dict[str, dict] = {}
    for p in param_names:
        vals = [pt["value"] for pt in series[p] if pt["value"] is not None]
        if not vals:
            continue
        n    = len(vals)
        mean = sum(vals) / n
        std  = math.sqrt(sum((x - mean) ** 2 for x in vals) / n) if n > 1 else 0.0
        baseline[p] = {
            "mean":       round(mean, 4),
            "std_dev":    round(std, 4),
            "ucl_3sigma": round(mean + 3 * std, 4),
            "lcl_3sigma": round(mean - 3 * std, 4),
            "sample_count": n,
        }

    # Fetch SPC status for same runs (to overlay OOC markers)
    spc_cursor = (
        db.object_snapshots
        .find({"toolID": tool_id, "step": step, "objectName": "SPC"})
        .sort("eventTime", -1)
        .limit(limit)
    )
    spc_snaps = await spc_cursor.to_list(length=limit)
    spc_snaps = list(reversed(spc_snaps))
    spc_status_series = [
        {
            "t": s["eventTime"].isoformat() + "Z" if s.get("eventTime") else None,
            "lot_id": s.get("lotID"),
            "spc_status": s.get("spc_status") or s.get("parameters", {}).get("spc_status"),
        }
        for s in spc_snaps
    ]

    return {
        "tool_id":           tool_id,
        "step":              step,
        "sample_count":      len(snaps),
        "param_names":       param_names,
        "series":            series,
        "baseline":          baseline,
        "spc_status_series": spc_status_series,
    }


# ── POST /search — Semantic Event Search ─────────────────────────────────────

@router.post("/search")
async def search_events(body: dict):
    """
    Semantic Event Search.

    Cross-lot / cross-tool OOC correlation query. Agent uses this to ask:
    'Find all lots that had SPC OOC on EQP-01 in the past 24 hours.'

    Request body:
      tool_id     (str, optional)
      lot_id      (str, optional)
      step        (str, optional)
      status      (str, optional) — 'OOC' | 'PASS'
      start_time  (str, ISO8601, optional)
      end_time    (str, ISO8601, optional)
      limit       (int, default 50)

    Returns matching ProcessEnd events with lot_id, tool_id, step,
    spc_status, event_time, and snapshot IDs.
    """
    db    = get_db()
    limit = min(int(body.get("limit", 50)), 200)

    filt: dict = {"eventType": "LOT_EVENT", "status": "ProcessEnd"}

    if body.get("tool_id"):
        filt["toolID"] = body["tool_id"]
    if body.get("lot_id"):
        filt["lotID"] = body["lot_id"]
    if body.get("step"):
        filt["step"] = body["step"]
    if body.get("status"):
        filt["spc_status"] = body["status"].upper()

    time_filt: dict = {}
    for key, op in [("start_time", "$gte"), ("end_time", "$lte")]:
        val = body.get(key)
        if val:
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                time_filt[op] = dt
            except ValueError:
                pass
    if time_filt:
        filt["eventTime"] = time_filt

    cursor = db.events.find(filt).sort("eventTime", -1).limit(limit)
    events = await cursor.to_list(length=limit)

    results = []
    for ev in events:
        results.append({
            "event_id":         str(ev["_id"]),
            "lot_id":           ev.get("lotID"),
            "tool_id":          ev.get("toolID"),
            "step":             ev.get("step"),
            "spc_status":       ev.get("spc_status"),
            "event_time":       ev["eventTime"].isoformat() + "Z",
            "dc_snapshot_id":   ev.get("dcSnapshotId"),
            "spc_snapshot_id":  ev.get("spcSnapshotId"),
        })

    ooc_count  = sum(1 for r in results if r["spc_status"] == "OOC")
    pass_count = len(results) - ooc_count
    summary = (
        f"Found {len(results)} events matching query "
        f"({ooc_count} OOC, {pass_count} PASS). "
        + (f"Filtered to tool={body.get('tool_id')}" if body.get("tool_id") else "")
        + (f", step={body.get('step')}" if body.get("step") else "")
        + "."
    )

    return {
        "total":   len(results),
        "ooc_count":  ooc_count,
        "pass_count": pass_count,
        "summary": summary,
        "events":  results,
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


# ── GET /tools/status — All Tools Status Overview ────────────────────────────

@router.get("/tools/status")
async def get_tools_status_overview(
    recent_batches: int = Query(5, ge=1, le=20, description="Number of recent batches to summarize per tool"),
):
    """
    All-tools status overview — returns Idle/Busy status + recent SPC health for every tool.

    For each tool:
    - current_status: Idle | Busy (from tools collection)
    - current_lot: lot currently being processed (if Busy)
    - recent_ooc_count: number of OOC batches in last N batches
    - last_spc_status: PASS | OOC | N/A of most recent completed batch
    - last_activity: timestamp of last ProcessEnd event
    - total_batches_processed: lifetime batch count
    """
    db = get_db()
    tool_ids = sorted(await db.tools.distinct("tool_id"))

    tools_status = []
    for tool_id in tool_ids:
        tool_doc = await db.tools.find_one({"tool_id": tool_id})
        tool_info = _clean(tool_doc) if tool_doc else {}

        # Get recent TOOL_EVENTs (ProcessEnd) for this tool, newest first
        cursor = (
            db.events
            .find({"toolID": tool_id, "eventType": "TOOL_EVENT", "status": "ProcessEnd"})
            .sort("eventTime", -1)
            .limit(recent_batches)
        )
        recent_ends = await cursor.to_list(length=recent_batches)

        ooc_count = sum(1 for e in recent_ends if e.get("spc_status") == "OOC")
        last_spc  = recent_ends[0].get("spc_status", "N/A") if recent_ends else "N/A"
        last_time = (
            recent_ends[0]["eventTime"].isoformat() + "Z"
            if recent_ends and recent_ends[0].get("eventTime") else None
        )

        # Find in-progress lot (ProcessStart without matching ProcessEnd)
        current_lot = None
        if tool_info.get("status") == "Busy":
            in_prog = await db.events.find_one(
                {"toolID": tool_id, "eventType": "TOOL_EVENT", "status": "ProcessStart"},
                sort=[("eventTime", -1)],
            )
            if in_prog:
                current_lot = in_prog.get("lotID")

        total = await db.events.count_documents(
            {"toolID": tool_id, "eventType": "TOOL_EVENT", "status": "ProcessEnd"}
        )

        tools_status.append({
            "tool_id":               tool_id,
            "current_status":        tool_info.get("status", "Unknown"),
            "current_lot":           current_lot,
            "last_spc_status":       last_spc,
            "recent_ooc_count":      ooc_count,
            "recent_batches_checked": len(recent_ends),
            "last_activity":         last_time,
            "total_batches_processed": total,
        })

    return {
        "tool_count":   len(tools_status),
        "recent_window": recent_batches,
        "tools":        tools_status,
    }


# ── GET /equipment/{tool_id}/constants — Equipment Constants ─────────────────

@router.get("/equipment/{tool_id}/constants")
async def get_equipment_constants(tool_id: str):
    """Equipment Constants for a tool — compare current values against golden baseline."""
    return _compute_ec(tool_id)


# ── GET /fdc/{tool_id}/uchart — FDC U-Chart ──────────────────────────────────

@router.get("/fdc/{tool_id}/uchart")
async def get_fdc_uchart(tool_id: str, step: str = None, limit: int = 50):
    """FDC U-chart: defect count per unit time series for a tool/step."""
    db = get_db()

    # Fetch recent ProcessEnd events for this tool (and optionally step)
    query: dict = {"toolID": tool_id, "status": "ProcessEnd", "eventType": "LOT_EVENT"}
    if step:
        query["step"] = step

    cursor = (
        db.events
        .find(query, {"lotID": 1, "step": 1, "eventTime": 1, "spc_status": 1, "_id": 0})
        .sort("eventTime", -1)
        .limit(limit)
    )
    records = await cursor.to_list(length=limit)

    if not records:
        return {
            "tool_id": tool_id,
            "step": step,
            "uchart": [],
            "baseline": {"u_bar": 0, "ucl": 0, "lcl": 0, "n_average": 50},
            "ooc_count": 0,
            "summary": f"No FDC data found for {tool_id}" + (f" step {step}" if step else ""),
        }

    # Generate U-chart values — correlated with SPC status
    seed_base = int(hashlib.md5(tool_id.encode()).hexdigest()[:8], 16)
    uchart_data = []

    for i, rec in enumerate(records):
        rng = random.Random(seed_base + i)
        sample_size = rng.randint(45, 55)
        # OOC batches tend to have higher defect counts
        base_rate = 0.08 if rec.get("spc_status") == "OOC" else 0.04
        defect_count = int(rng.gauss(base_rate * sample_size, 1.5))
        defect_count = max(0, defect_count)
        u_value = round(defect_count / sample_size, 4)

        event_time = rec.get("eventTime")
        uchart_data.append({
            "event_time": event_time.isoformat() + "Z" if event_time else None,
            "lot_id": rec["lotID"],
            "step": rec.get("step", step or ""),
            "defect_count": defect_count,
            "sample_size": sample_size,
            "u_value": u_value,
            "spc_status": rec.get("spc_status", "PASS"),
        })

    # Calculate U-chart baseline (u-bar and control limits)
    u_bar = sum(r["u_value"] for r in uchart_data) / len(uchart_data)
    n_avg = sum(r["sample_size"] for r in uchart_data) / len(uchart_data)
    ucl = round(u_bar + 3 * math.sqrt(u_bar / n_avg), 4) if u_bar > 0 else 0.0
    lcl = round(max(0, u_bar - 3 * math.sqrt(u_bar / n_avg)), 4) if u_bar > 0 else 0.0

    # Mark OOC based on U-chart limits
    ooc_count = 0
    for r in uchart_data:
        if r["u_value"] > ucl or (lcl > 0 and r["u_value"] < lcl):
            r["spc_status"] = "OOC"
            ooc_count += 1

    uchart_data.sort(key=lambda x: x["event_time"] or "")

    summary = f"{tool_id}" + (f" {step}" if step else "") + f": {len(uchart_data)} lots, u_bar={u_bar:.4f}, UCL={ucl:.4f}, OOC={ooc_count}/{len(uchart_data)}"

    return {
        "tool_id": tool_id,
        "step": step,
        "uchart": uchart_data,
        "baseline": {"u_bar": round(u_bar, 4), "ucl": ucl, "lcl": lcl, "n_average": round(n_avg, 1)},
        "ooc_count": ooc_count,
        "summary": summary,
    }


# ── GET /ocap/{lot_id}/{step} — OCAP Action Plan ──────────────────────────────

@router.get("/ocap/{lot_id}/{step}")
async def get_ocap(lot_id: str, step: str):
    """OCAP: Out-of-Control Action Plan for a lot/step."""
    db = get_db()

    record = await db.events.find_one(
        {"lotID": lot_id, "step": step, "status": "ProcessEnd"},
        {"spc_status": 1, "spcSnapshotId": 1, "_id": 0}
    )
    spc_status = record.get("spc_status", "PASS") if record else "PASS"

    spc_snap = None
    if record and record.get("spcSnapshotId") and spc_status == "OOC":
        snap_id = record["spcSnapshotId"]
        spc_snap = await db.object_snapshots.find_one(
            {"_id": snap_id} if isinstance(snap_id, ObjectId) else {"_id": _oid(snap_id)}
        )

    result = _compute_ocap_inline(lot_id, step, spc_status, spc_snap)
    if result is None:
        return {"lot_id": lot_id, "step": step, "spc_status": spc_status,
                "triggered_by": [], "actions": [], "severity": "LOW",
                "summary": f"{lot_id} {step}: SPC PASS — no OCAP required."}
    return result
