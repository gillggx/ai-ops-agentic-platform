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
from datetime import datetime
from app.database import get_db
from app.services import recipe_service, apc_service, dc_service, spc_service
from app.services import fdc_service, ec_service
from app.ws.manager import manager as ws_manager
from config import PROCESSING_MIN_SEC, PROCESSING_MAX_SEC, HOLD_PROBABILITY

_RECIPE_IDS = [f"RCP-{i:03d}" for i in range(1, 21)]
_BIAS_ALERT_THRESHOLD = 0.05

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


async def process_step(lot_id: str, tool_id: str, step_num: int) -> dict:
    """
    Full processing cycle for one (Lot, Tool, Step):
      1. Prepare APC drift + Recipe (pre-process)
      2. Simulate process time (with possible HOLD)
      3. Generate DC readings + SPC evaluation
      4. FDC classification
      5. EC drift
      6. Write everything at once with unified eventTime:
         - 1 event
         - 6 object_snapshots (DC, SPC, APC, RECIPE, FDC, EC)
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
            await asyncio.wait_for(hold_event.wait(), timeout=3600.0)
        except asyncio.TimeoutError:
            print(f"[Agent] HOLD timeout – {tool_id} auto-releasing")
        finally:
            _hold_events.pop(tool_id, None)

        remaining = max(0.0, process_time - hold_after)
        await asyncio.sleep(remaining)
    else:
        await asyncio.sleep(process_time)

    # ── Stage 3: Process complete — generate measurements ─────
    dc_readings = dc_service.generate_readings(tool_id)
    spc_status, spc_charts = spc_service.evaluate(dc_readings)

    # ── Stage 4: FDC classification ───────────────────────────
    fdc_result = fdc_service.classify(dc_readings, spc_status, apc_params)

    # ── Stage 5: EC drift ─────────────────────────────────────
    ec_data = ec_service.apply_process_drift(tool_id)

    # ── Stage 6: Write everything with unified eventTime ──────
    event_time = datetime.utcnow()
    ctx = {
        "eventTime": event_time,
        "lotID":     lot_id,
        "toolID":    tool_id,
        "step":      step_id,
    }

    # Write 6 object snapshots + 1 event in parallel
    await asyncio.gather(
        dc_service.upload_snapshot(dc_readings, ctx),
        spc_service.upload_snapshot(spc_status, spc_charts, ctx),
        apc_service.upload_snapshot(apc_id, apc_params, ctx),
        recipe_service.upload_snapshot_from_params(recipe_id, recipe_params, ctx, recipe_version),
        fdc_service.upload_snapshot(fdc_result, ctx),
        ec_service.upload_snapshot(ec_data, ctx),
        db.events.insert_one({
            "eventTime":          event_time,
            "lotID":              lot_id,
            "toolID":             tool_id,
            "step":               step_id,
            "recipeID":           recipe_id,
            "apcID":              apc_id,
            "spc_status":         spc_status,
            "fdc_classification": fdc_result.classification,
        }),
    )

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
    print(
        f"[Agent] {lot_id} | {step_id} | {tool_id} | "
        f"{log_recipe} bias={new_bias:.4f}({trend}) SPC={spc_status}{log_fdc}"
        + (" ⚠" if spc_status == "OOC" or bias_alert else "")
    )
    return {"event_time": event_time, "spc_status": spc_status, "fdc": fdc_result.classification}
