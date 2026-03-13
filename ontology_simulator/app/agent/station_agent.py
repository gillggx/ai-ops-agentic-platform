"""Station Agent – orchestrates 4 object services, writes events, broadcasts WS."""
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
# tool_id → Event (set by acknowledge_hold when user clicks ACKNOWLEDGE)
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
      1. Concurrent DB uploads (Recipe / APC / DC / SPC)
      2. Write Tool + Lot events to MongoDB
      3. Broadcast ENTITY_LINK → (0.8s) → TOOL_LINK
      4. Simulate real process time (10–15 s dev / 10–20 min prod)
         with 5% chance of mid-process HOLD that waits for API acknowledge
      5. Broadcast METRIC_UPDATE
    """
    db = get_db()
    event_time = datetime.utcnow()
    step_id    = f"STEP_{step_num:03d}"
    apc_id     = f"APC-{step_num:03d}"
    recipe_id  = random.choice(_RECIPE_IDS)

    context = {
        "eventTime": event_time,
        "lotID":     lot_id,
        "toolID":    tool_id,
        "step":      step_id,
    }

    dc_readings = dc_service.generate_readings(tool_id)

    # ── Concurrent DB uploads ──────────────────────────────────
    recipe_snap_id, apc_result, dc_snap_id, spc_result = await asyncio.gather(
        recipe_service.upload_snapshot(recipe_id, context),
        apc_service.drift_and_upload(apc_id, context),
        dc_service.upload_snapshot(dc_readings, context),
        spc_service.evaluate_and_upload(dc_readings, context),
    )
    apc_snap_id = apc_result["snapshot_id"]
    new_bias    = apc_result["new_bias"]
    prev_bias   = apc_result["prev_bias"]
    spc_snap_id, spc_status = spc_result

    # ── Write lightweight events ───────────────────────────────
    event_base = {
        "eventTime":     event_time,
        "lotID":         lot_id,
        "toolID":        tool_id,
        "step":          step_id,
        "recipeID":      recipe_id,
        "apcID":         apc_id,
        "dcSnapshotId":  dc_snap_id,
        "spcSnapshotId": spc_snap_id,
        "spc_status":    spc_status,
    }
    await asyncio.gather(
        db.events.insert_one({**event_base, "eventType": "TOOL_EVENT"}),
        db.events.insert_one({**event_base, "eventType": "LOT_EVENT"}),
    )

    ts = event_time.isoformat() + "Z"

    # ── Stage 1: ENTITY_LINK → STAGE_LOAD ─────────────────────
    await ws_manager.broadcast({
        "type":       "ENTITY_LINK",
        "machine_id": tool_id,
        "data": {
            "lot_id":    lot_id,
            "recipe":    recipe_id,
            "status":    "PROCESSING",
            "timestamp": ts,
        },
    })
    await asyncio.sleep(3)   # brief wafer-load setup (3 s is realistic, not fake)

    # ── Stage 2: TOOL_LINK → STAGE_PROCESS (RUNNING) ──────────
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
        # HOLD fires at a random point within the first 70% of process time
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
            # Wait up to 1 hour; in practice engineer clicks ACKNOWLEDGE
            await asyncio.wait_for(hold_event.wait(), timeout=3600.0)
        except asyncio.TimeoutError:
            print(f"[Agent] HOLD timeout – {tool_id} auto-releasing")
        finally:
            _hold_events.pop(tool_id, None)

        print(f"[Agent] ✓ HOLD cleared – {tool_id} resuming processing")
        # Continue with remaining process time
        remaining = max(0.0, process_time - hold_after)
        await asyncio.sleep(remaining)
    else:
        await asyncio.sleep(process_time)

    # ── Stage 3: METRIC_UPDATE → STAGE_ANALYSIS → DONE ────────
    trend      = "UP" if new_bias > prev_bias else "DOWN"
    bias_alert = new_bias > _BIAS_ALERT_THRESHOLD

    reflection = None
    if spc_status == "OOC":
        dc_service.reset_drift(tool_id)   # maintenance reset — drift starts fresh
        reflection = (
            f"[Agent Reflection] 偵測到 {tool_id} 在 {step_id} 的參數 param_01 偏移"
            f"（bias={new_bias:.4f}），建議執行線性回歸診斷。"
        )

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
            "timestamp":  ts,
        },
    })

    print(
        f"[Agent] {lot_id} | {step_id} | {tool_id} | "
        f"Recipe={recipe_id} bias={new_bias:.4f}({trend}) SPC={spc_status}"
        + (" ⚠" if spc_status == "OOC" or bias_alert else "")
    )
    return {"event_time": event_time, "spc_status": spc_status}
