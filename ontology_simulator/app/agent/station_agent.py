"""Station Agent – orchestrates 4 object services, writes events, broadcasts WS.

Each (lot, tool, step) now generates TWO events that are merged at query time:
  ProcessStart (t0): Recipe + APC snapshots captured before processing begins
  ProcessEnd   (t1): DC + SPC snapshots captured after processing completes
"""
import asyncio
import random
from datetime import datetime
from app.database import get_db
from app.services import recipe_service, apc_service, dc_service, spc_service
from app.ws.manager import manager as ws_manager
from config import PROCESSING_MIN_SEC, PROCESSING_MAX_SEC, HOLD_PROBABILITY

_RECIPE_IDS = [f"RCP-{i:03d}" for i in range(1, 21)]
_BIAS_ALERT_THRESHOLD = 0.05

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
    Full processing cycle for one (Lot, Tool, Step) dispatch:
      ProcessStart phase (t0):
        1. Upload Recipe + APC snapshots (pre-process state)
        2. Write ProcessStart TOOL_EVENT + LOT_EVENT
        3. Broadcast ENTITY_LINK + TOOL_LINK
      [Process runs: PROCESSING_MIN_SEC ~ PROCESSING_MAX_SEC, with possible HOLD]
      ProcessEnd phase (t1):
        4. Generate DC readings + upload DC + SPC snapshots (post-process measurements)
        5. Write ProcessEnd TOOL_EVENT + LOT_EVENT
        6. Broadcast METRIC_UPDATE
    """
    db = get_db()
    start_time = datetime.utcnow()
    step_id    = f"STEP_{step_num:03d}"
    apc_id     = f"APC-{step_num:03d}"
    recipe_id  = random.choice(_RECIPE_IDS)

    # ── ProcessStart context ───────────────────────────────────
    ctx_start = {
        "eventTime": start_time,
        "lotID":     lot_id,
        "toolID":    tool_id,
        "step":      step_id,
        "status":    "ProcessStart",
    }

    # ── Stage 1: Upload Recipe + APC at ProcessStart ───────────
    recipe_snap_id, apc_result = await asyncio.gather(
        recipe_service.upload_snapshot(recipe_id, ctx_start),
        apc_service.drift_and_upload(apc_id, ctx_start),
    )
    apc_snap_id = apc_result["snapshot_id"]
    new_bias    = apc_result["new_bias"]
    prev_bias   = apc_result["prev_bias"]

    # ── Stage 2: Write ProcessStart events ────────────────────
    start_event_base = {
        "eventTime": start_time,
        "status":    "ProcessStart",
        "lotID":     lot_id,
        "toolID":    tool_id,
        "step":      step_id,
        "recipeID":  recipe_id,
        "apcID":     apc_id,
    }
    await asyncio.gather(
        db.events.insert_one({**start_event_base, "eventType": "TOOL_EVENT"}),
        db.events.insert_one({**start_event_base, "eventType": "LOT_EVENT"}),
    )

    ts_start = start_time.isoformat() + "Z"

    # ── Stage 3: Broadcast ENTITY_LINK (wafer load) ───────────
    await ws_manager.broadcast({
        "type":       "ENTITY_LINK",
        "machine_id": tool_id,
        "data": {
            "lot_id":    lot_id,
            "recipe":    recipe_id,
            "status":    "PROCESSING",
            "timestamp": ts_start,
        },
    })
    await asyncio.sleep(3)   # brief wafer-load setup

    await ws_manager.broadcast({
        "type":       "TOOL_LINK",
        "machine_id": tool_id,
        "data": {
            "apc": {"active": True,  "mode": "Run-to-Run"},
            "dc":  {"active": True,  "collection_plan": "HIGH_FREQ"},
            "spc": {"active": True},
        },
    })

    # ── Simulate real process time with possible HOLD ──────────
    process_time = random.uniform(PROCESSING_MIN_SEC, PROCESSING_MAX_SEC)

    if random.random() < HOLD_PROBABILITY:
        hold_after = random.uniform(process_time * 0.15, process_time * 0.70)
        await asyncio.sleep(hold_after)

        hold_ts = datetime.utcnow().isoformat() + "Z"
        hold_event = asyncio.Event()
        _hold_events[tool_id] = hold_event

        await ws_manager.broadcast({
            "type":       "MACHINE_HOLD",
            "machine_id": tool_id,
            "data": {
                "reason":    "Equipment fault detected — awaiting engineer acknowledge",
                "timestamp": hold_ts,
            },
        })
        print(f"[Agent] ⚠ HOLD – {tool_id} | {lot_id} | {step_id} | waiting for ACK")

        try:
            await asyncio.wait_for(hold_event.wait(), timeout=3600.0)
        except asyncio.TimeoutError:
            print(f"[Agent] HOLD timeout – {tool_id} auto-releasing")
        finally:
            _hold_events.pop(tool_id, None)

        print(f"[Agent] ✓ HOLD cleared – {tool_id} resuming processing")
        remaining = max(0.0, process_time - hold_after)
        await asyncio.sleep(remaining)
    else:
        await asyncio.sleep(process_time)

    # ── ProcessEnd phase ───────────────────────────────────────
    end_time = datetime.utcnow()
    ctx_end = {
        "eventTime": end_time,
        "lotID":     lot_id,
        "toolID":    tool_id,
        "step":      step_id,
        "status":    "ProcessEnd",
    }

    # ── Stage 4: Upload DC + SPC at ProcessEnd ─────────────────
    dc_readings = dc_service.generate_readings(tool_id)
    dc_snap_id, spc_result = await asyncio.gather(
        dc_service.upload_snapshot(dc_readings, ctx_end),
        spc_service.evaluate_and_upload(dc_readings, ctx_end),
    )
    spc_snap_id, spc_status = spc_result

    # ── Stage 5: Write ProcessEnd events ──────────────────────
    end_event_base = {
        "eventTime":     end_time,
        "status":        "ProcessEnd",
        "lotID":         lot_id,
        "toolID":        tool_id,
        "step":          step_id,
        "recipeID":      recipe_id,   # cross-ref back to start
        "apcID":         apc_id,      # cross-ref back to start
        "dcSnapshotId":  dc_snap_id,
        "spcSnapshotId": spc_snap_id,
        "spc_status":    spc_status,
    }
    await asyncio.gather(
        db.events.insert_one({**end_event_base, "eventType": "TOOL_EVENT"}),
        db.events.insert_one({**end_event_base, "eventType": "LOT_EVENT"}),
    )

    # ── Stage 6: Broadcast METRIC_UPDATE ──────────────────────
    trend      = "UP" if new_bias > prev_bias else "DOWN"
    bias_alert = new_bias > _BIAS_ALERT_THRESHOLD

    if spc_status == "OOC" and bias_alert:
        await db.tool_events.insert_one({
            "toolID":    tool_id,
            "lotID":     lot_id,
            "step":      step_id,
            "eventType": "ALARM",
            "eventTime": end_time,
            "metadata": {
                "alarm_code": "SPC_OOC_BIAS_ALERT",
                "spc_status": spc_status,
                "bias":       round(new_bias, 6),
                "recipe_id":  recipe_id,
            },
        })

    reflection = None
    if spc_status == "OOC":
        dc_service.reset_drift(tool_id)
        reflection = (
            f"[Agent Reflection] 偵測到 {tool_id} 在 {step_id} 的參數 param_01 偏移"
            f"（bias={new_bias:.4f}），建議執行線性回歸診斷。"
        )

    ts_end = end_time.isoformat() + "Z"
    await ws_manager.broadcast({
        "type":       "METRIC_UPDATE",
        "machine_id": tool_id,
        "target":     "APC",
        "data": {
            "bias":       round(new_bias, 6),
            "unit":       "nm",
            "trend":      trend,
            "bias_alert": bias_alert,
            "spc_status": spc_status,
            "reflection": reflection,
            "step":       step_id,
            "lot_id":     lot_id,
            "timestamp":  ts_end,
        },
    })

    print(
        f"[Agent] {lot_id} | {step_id} | {tool_id} | "
        f"Recipe={recipe_id} bias={new_bias:.4f}({trend}) SPC={spc_status}"
        + (" ⚠" if spc_status == "OOC" or bias_alert else "")
    )
    return {"start_time": start_time, "end_time": end_time, "spc_status": spc_status}
