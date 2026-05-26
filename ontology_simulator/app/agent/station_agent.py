"""Station Agent – orchestrates 6 object services, writes ONE event per process.

Each (lot, tool, step) generates:
  - 1 event (with spc_status, fdc_classification)
  - 6 object_snapshots (DC, SPC, APC, RECIPE, FDC, EC) — all with same eventTime

Enhanced data model:
  - APC: active/passive params with 50% self-correction feedback loop
  - Recipe: 10% version bump with parameter offset adjustment
  - DC: exponential drift (slow wandering baseline) + PM reset
  - FDC: rule-based fault classification (NORMAL/WARNING/FAULT)
  - EC: equipment constants with slow drift + PM recalibration
"""
import asyncio
import random
import uuid
from datetime import datetime
from app.database import get_db
from app.services import recipe_service, apc_service, dc_service, spc_service
from app.services import fdc_service, ec_service
from app.ws.manager import manager as ws_manager
from config import (
    PROCESSING_MIN_SEC, PROCESSING_MAX_SEC, HOLD_PROBABILITY, HOLD_TIMEOUT_SEC,
    PHOTO_OOC_PROBABILITY,
)

_RECIPE_IDS = [f"RCP-{i:03d}" for i in range(1, 21)]
_BIAS_ALERT_THRESHOLD = 0.05


def _is_photo_step(step_num: int) -> bool:
    """Photo lithography stations live at every 5th step (STEP_005, _010,
    _015, _020). Re-used by the rework trigger logic below."""
    return step_num > 0 and step_num % 5 == 0


# ── Rework field-name mapping ──────────────────────────────────────────
# ReworkInfo intentionally uses different field names than MESInfo so the
# system MCP description has to teach the LLM the correspondence (the
# canonical example for "MCP description is the only documentation source"
# per CLAUDE.md). Keep this dict in sync with the MCP output_schema.
_REWORK_FIELD_RENAME = {
    "flowID":            "mainPD_ID",
    "stageID":           "PDID",
    "processJobID":      "rwJobID",
    "slotList":          "slotMap",
    "productID":         "prodCode",
    "photoLayerID":      "layerName",
    "technology":        "techNode",
    "mainPD":            "rootPD",
    "subPDID":           "subPDCode",
    "routeID":           "routeName",
    "recipeGroup":       "recipeFamily",
    "foupID":            "carrierID",
    "waferCount":        "slotCount",
    "lotType":           "lotKind",
    "lotPriority":       "priorityClass",
    "customer":          "customerCode",
    "mfgRegion":         "region",
    "processOrder":      "stepSeq",
    "eqpRecipeRevision": "toolRecipeRev",
    "holdState":         "holdStatus",
}


def _build_mes_info(
    *, lot_doc: dict, step_num: int, step_id: str, lot_type: str,
) -> dict:
    """Combine the lot's static mes_profile with this step's dynamic fields
    into the MESInfo sub-object that goes onto every event row."""
    profile = lot_doc.get("mes_profile", {}) if lot_doc else {}
    flow_id = profile.get("flowID", "")
    is_photo = _is_photo_step(step_num)
    return {
        "flowID":            flow_id,
        "step":              step_id,
        "stageID":           f"STG-{'PHOTO' if is_photo else 'GEN'}-{step_id}",
        "processJobID":      f"PJ-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
        "slotList":          list(range(1, int(profile.get("waferCount", 25)) + 1)),
        "productID":         profile.get("productID", ""),
        "photoLayerID":      f"M{step_num // 5}" if is_photo else None,
        "technology":        profile.get("technology", ""),
        "mainPD":             profile.get("mainPD", ""),
        "subPDID":           f"SPD-{step_id}-V1",
        "routeID":            profile.get("routeID", ""),
        "recipeGroup":        profile.get("recipeGroup", ""),
        "foupID":             profile.get("foupID", ""),
        "waferCount":         profile.get("waferCount", 25),
        "lotType":            lot_type,
        "lotPriority":        profile.get("lotPriority", "NORMAL"),
        "customer":           profile.get("customer", ""),
        "mfgRegion":          profile.get("mfgRegion", ""),
        "processOrder":       step_num,
        "eqpRecipeRevision":  profile.get("eqpRecipeRevision", ""),
        "dispatchPriority":   profile.get("dispatchPriority", 5),
        "holdState":          profile.get("holdState", "RELEASED"),
    }


def _to_rework_info(mes_info: dict) -> dict:
    """Apply the field-name rename so rework records have the deliberately
    different schema the MCP description documents."""
    return {_REWORK_FIELD_RENAME.get(k, k): v for k, v in mes_info.items()}

# Track previous SPC status per (tool, step) for APC feedback
_prev_spc_status: dict[str, str] = {}

# Per-machine asyncio Events for equipment HOLD acknowledgment
_hold_events: dict[str, asyncio.Event] = {}


def acknowledge_hold(tool_id: str) -> bool:
    """Called by the API endpoint when user acknowledges an equipment HOLD."""
    event = _hold_events.get(tool_id)
    if event and not event.is_set():
        event.set()
        return True
    return False


async def process_step(
    lot_id: str,
    tool_id: str,
    step_num: int,
    chamber_id: str = "CH-1",
    lot_type: str = "production",
) -> dict:
    """
    Full processing cycle for one (Lot, Tool, Chamber, Step):
      1. Prepare APC drift + Recipe (pre-process)
      2. Simulate process time (with possible HOLD)
      3. Generate DC readings + SPC evaluation
      4. FDC classification
      5. EC drift
      6. Write everything at once with unified eventTime:
         - 1 event
         - 6 object_snapshots (DC, SPC, APC, RECIPE, FDC, EC)

    Phase 12: chamber_id is the actual chamber (CH-1..CH-4) that processed
    this wafer. lot_type ('production' | 'monitor') feeds SPC limits and
    flows through onto every snapshot row.
    """
    db = get_db()
    step_id   = f"STEP_{step_num:03d}"
    apc_id    = f"APC-{step_num:03d}"
    recipe_id = random.choice(_RECIPE_IDS)

    # ── Stage 1: Pre-process preparation (no DB writes) ───────
    # APC drift with feedback from previous SPC status
    prev_status_key = f"{tool_id}:{step_id}"
    prev_spc = _prev_spc_status.get(prev_status_key, "PASS")
    apc_result = await apc_service.drift_and_prepare(apc_id, prev_spc_status=prev_spc)
    new_bias   = apc_result["new_bias"]
    prev_bias  = apc_result["prev_bias"]
    apc_params = apc_result["parameters"]

    # Recipe lookup (with possible version bump)
    recipe_result = await recipe_service.get_and_maybe_bump_params(recipe_id)
    recipe_params = recipe_result["parameters"]
    recipe_version = recipe_result["recipe_version"]

    # ── Stage 2: Broadcast processing start + simulate time ───
    await ws_manager.broadcast({
        "type":       "ENTITY_LINK",
        "machine_id": tool_id,
        "data": {
            "lot_id":    lot_id,
            "recipe":    recipe_id,
            "status":    "PROCESSING",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    })

    # Simulate real process time with possible HOLD
    process_time = random.uniform(PROCESSING_MIN_SEC, PROCESSING_MAX_SEC)

    if random.random() < HOLD_PROBABILITY:
        hold_after = random.uniform(process_time * 0.15, process_time * 0.70)
        await asyncio.sleep(hold_after)

        hold_event = asyncio.Event()
        _hold_events[tool_id] = hold_event

        await ws_manager.broadcast({
            "type":       "MACHINE_HOLD",
            "machine_id": tool_id,
            "data": {
                "reason":    "Equipment fault detected — awaiting engineer acknowledge",
                "timestamp": datetime.utcnow().isoformat() + "Z",
            },
        })
        print(f"[Agent] ⚠ HOLD – {tool_id} | {lot_id} | {step_id}")

        try:
            await asyncio.wait_for(hold_event.wait(), timeout=HOLD_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            print(f"[Agent] HOLD timeout ({HOLD_TIMEOUT_SEC}s) – {tool_id} auto-releasing")
        finally:
            _hold_events.pop(tool_id, None)

        remaining = max(0.0, process_time - hold_after)
        await asyncio.sleep(remaining)
    else:
        await asyncio.sleep(process_time)

    # ── Stage 3: Process complete — generate measurements ─────
    dc_readings = dc_service.generate_readings(tool_id, chamber_id)
    spc_status, spc_charts = spc_service.evaluate(dc_readings, lot_type=lot_type)

    # Photo stations have a tightened OOC rate (PHOTO_OOC_PROBABILITY,
    # default 0.30) because every photo-station OOC triggers a rework
    # record below. We override here rather than threading the prob into
    # spc_service so the chart math stays unchanged for non-photo steps.
    if _is_photo_step(step_num) and spc_status != "OOC":
        if random.random() < PHOTO_OOC_PROBABILITY:
            spc_status = "OOC"

    # ── Stage 4: FDC classification ───────────────────────────
    fdc_result = fdc_service.classify(dc_readings, spc_status, apc_params)

    # ── Stage 5: EC drift ─────────────────────────────────────
    ec_data = ec_service.apply_process_drift(tool_id, chamber_id)

    # ── Stage 6: Write everything with unified eventTime ──────
    event_time = datetime.utcnow()
    ctx = {
        "eventTime": event_time,
        "lotID":     lot_id,
        "toolID":    tool_id,
        "chamberID": chamber_id,           # Phase 12
        "lot_type":  lot_type,             # Phase 12
        "step":      step_id,
    }

    # MESInfo enrichment — fetch the lot's static mes_profile once.
    lot_doc = await db.lots.find_one({"lot_id": lot_id}, projection={"_id": 0, "mes_profile": 1})
    mes_info = _build_mes_info(
        lot_doc=lot_doc or {}, step_num=step_num, step_id=step_id, lot_type=lot_type,
    )

    # Write 6 object snapshots + 1 event in parallel
    await asyncio.gather(
        dc_service.upload_snapshot(dc_readings, ctx),
        spc_service.upload_snapshot(spc_status, spc_charts, ctx),
        apc_service.upload_snapshot(apc_id, apc_params, ctx),
        recipe_service.upload_snapshot_from_params(recipe_id, recipe_params, ctx, recipe_version),
        fdc_service.upload_snapshot(fdc_result, ctx),
        ec_service.upload_snapshot(ec_data, ctx),
        # Phase Y: explicit eventType lets consumers tell PROCESS_END events
        # apart from future PROCESS_START / HEARTBEAT emissions (currently we
        # only write the END so the row count == lot-step count). Existing
        # queries that don't filter on eventType continue to work because we
        # default-write PROCESS_END.
        db.events.insert_one({
            "eventTime":          event_time,
            "eventType":          "PROCESS_END",
            "lotID":              lot_id,
            "toolID":             tool_id,
            "chamberID":          chamber_id,        # Phase 12
            "lot_type":           lot_type,          # Phase 12
            "step":               step_id,
            "recipeID":           recipe_id,
            "apcID":              apc_id,
            "spc_status":         spc_status,
            "fdc_classification": fdc_result.classification,
            "MESInfo":            mes_info,          # Phase Rework — 20 MES fields
        }),
    )

    # Rework trigger — photo station OOC. 1:1 mapping with OOC events at
    # photo steps. reworkCount is the running per-lot count; race-safe
    # because each step runs serially per lot.
    if _is_photo_step(step_num) and spc_status == "OOC":
        prior = await db.rework_records.count_documents({"lotID": lot_id})
        await db.rework_records.insert_one({
            "reworkTime":  event_time,
            "reworkCount": prior + 1,
            "lotID":       lot_id,
            "step":        step_id,
            "reworkInfo":  _to_rework_info(mes_info),
        })

    # Remember SPC status for APC feedback next time
    _prev_spc_status[prev_status_key] = spc_status

    # ── Stage 7: Post-process broadcasts + alerts ─────────────
    trend     = "UP" if new_bias > prev_bias else "DOWN"
    bias_alert = new_bias > _BIAS_ALERT_THRESHOLD

    if spc_status == "OOC" and bias_alert:
        await db.tool_events.insert_one({
            "toolID":    tool_id,
            "lotID":     lot_id,
            "step":      step_id,
            "eventType": "ALARM",
            "eventTime": event_time,
            "metadata": {
                "alarm_code": "SPC_OOC_BIAS_ALERT",
                "spc_status": spc_status,
                "fdc":        fdc_result.classification,
                "bias":       round(new_bias, 6),
                "recipe_id":  recipe_id,
            },
        })

    if spc_status == "OOC":
        dc_service.reset_drift(tool_id)
        # Publish OOC to NATS
        try:
            from app.services.ooc_event_publisher import publish_ooc_event, OOCEventPayload
            await publish_ooc_event(OOCEventPayload(
                equipment_id=tool_id, lot_id=lot_id, step_id=step_id,
                parameter="xbar_chart", ooc_details={
                    "rule": "Limit Violation", "value": 0, "ucl": 0, "lcl": 0,
                },
                severity="warning",
            ))
        except Exception:
            pass

    ts_end = event_time.isoformat() + "Z"
    await ws_manager.broadcast({
        "type":       "METRIC_UPDATE",
        "machine_id": tool_id,
        "target":     "APC",
        "data": {
            "bias":       round(new_bias, 6),
            "trend":      trend,
            "spc_status": spc_status,
            "fdc":        fdc_result.classification,
            "step":       step_id,
            "lot_id":     lot_id,
            "timestamp":  ts_end,
        },
    })

    log_fdc = f" FDC={fdc_result.classification}" if fdc_result.classification != "NORMAL" else ""
    log_recipe = f" Recipe={recipe_id}v{recipe_version}" + (" ↑BUMP" if recipe_result.get("version_bumped") else "")
    log_kind = f"[{lot_type[:3].upper()}]" if lot_type != "production" else ""
    print(
        f"[Agent] {lot_id}{log_kind} | {step_id} | {tool_id}/{chamber_id} | "
        f"{log_recipe} bias={new_bias:.4f}({trend}) SPC={spc_status}{log_fdc}"
        + (" ⚠" if spc_status == "OOC" or bias_alert else "")
    )
    return {"event_time": event_time, "spc_status": spc_status, "fdc": fdc_result.classification}
