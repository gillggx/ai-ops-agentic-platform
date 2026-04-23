"""MES Simulator – queue-driven dispatch of 100 Lots across 10 Tools.

Architecture:
  - Stuck "Processing" lots from previous runs are reset to "Waiting" on startup.
  - All waiting lots are loaded into an asyncio.Queue at startup.
  - 10 machine coroutines run concurrently; each pops a lot, processes it,
    then immediately grabs the next one.
  - When the initial queue empties (recycled lots are in MongoDB, not the queue),
    each machine falls back to an atomic DB claim so work never stops.
  - Staggered start: 4–6 machines at T=0, rest deferred 300–720 s.
"""
import asyncio
import random
from datetime import datetime
from pymongo import ReturnDocument
from app.database import get_db
from app.agent.station_agent import process_step
from config import TOTAL_TOOLS, TOTAL_STEPS, RECYCLE_LOTS

_running = False


async def run() -> None:
    global _running
    _running = True

    db = get_db()

    # ── Reset lots stuck in "Processing" from a previous run ───
    stuck = await db.lots.count_documents({"status": "Processing"})
    if stuck:
        await db.lots.update_many(
            {"status": "Processing"},
            {"$set": {"status": "Waiting"}},
        )
        print(f"[MES] Reset {stuck} stuck lots → Waiting")

    # ── Load all waiting lots into the shared queue ─────────────
    lots = await db.lots.find({"status": "Waiting"}).sort("lot_id", 1).to_list(length=None)
    if not lots:
        print("[MES] No waiting lots — nothing to do.")
        _running = False
        return

    queue: asyncio.Queue = asyncio.Queue()
    for lot in lots:
        queue.put_nowait(lot)

    total = queue.qsize()
    print(f"[MES] Simulation start: {total} lots queued across {TOTAL_TOOLS} tools")
    sim_start = datetime.utcnow()

    # ── All machines start immediately ──────────────────────────
    tools = [f"EQP-{i:02d}" for i in range(1, TOTAL_TOOLS + 1)]
    coroutines = [_machine_loop(tid, queue) for tid in tools]
    print(f"[MES] All {len(tools)} machines starting immediately")
    await asyncio.gather(*coroutines)

    elapsed = (datetime.utcnow() - sim_start).total_seconds()
    print(f"[MES] All lots processed in {elapsed/60:.1f} min. Simulator idle.")
    _running = False


def stop() -> None:
    global _running
    _running = False


async def _claim_lot_from_db(db) -> dict | None:
    """Atomically claim one waiting lot from MongoDB (for recycled lots).

    Uses random sampling (MongoDB $sample) so all 10 tools don't pile on
    the lowest lot_id in lockstep — that caused every Processing lot to be
    stuck at the same current_step (e.g. every heatmap row was STEP_002).
    """
    # $sample picks one random Waiting lot; then atomically claim it.
    cursor = db.lots.aggregate([
        {"$match": {"status": "Waiting"}},
        {"$sample": {"size": 1}},
        {"$project": {"_id": 0, "lot_id": 1}},
    ])
    async for picked in cursor:
        claimed = await db.lots.find_one_and_update(
            {"lot_id": picked["lot_id"], "status": "Waiting"},
            {"$set": {"status": "Processing"}},
            return_document=ReturnDocument.AFTER,
        )
        if claimed is not None:
            return claimed
    return None


async def _machine_loop(tool_id: str, queue: asyncio.Queue) -> None:
    """Single machine loop: pull lots from queue, then DB, indefinitely."""
    db = get_db()
    processed = 0
    pm_counter   = 0
    pm_threshold = random.randint(8, 12)   # PM every 8-12 lots

    while _running:
        # ── Claim a lot atomically (queue hint → DB atomic lock) ──
        lot = None

        # Try queue first as a hint for which lot to claim
        queue_hint = None
        try:
            queue_hint = queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        if queue_hint:
            # Atomic claim: only succeeds if lot is still Waiting
            lot = await db.lots.find_one_and_update(
                {"lot_id": queue_hint["lot_id"], "status": "Waiting"},
                {"$set": {"status": "Processing"}},
                return_document=ReturnDocument.AFTER,
            )

        # Fallback: claim any waiting lot from DB
        if lot is None:
            lot = await _claim_lot_from_db(db)

        if lot is None:
            await asyncio.sleep(5)
            continue

        lot_id   = lot["lot_id"]
        step_num = lot.get("current_step", 1)

        await db.tools.update_one({"tool_id": tool_id}, {"$set": {"status": "Busy"}})

        try:
            await process_step(lot_id, tool_id, step_num)
            processed  += 1
            pm_counter += 1
        except Exception as exc:
            print(f"[MES] ERROR – {lot_id} on {tool_id} step {step_num}: {exc}")
        finally:
            await db.tools.update_one({"tool_id": tool_id}, {"$set": {"status": "Idle"}})

            next_step = step_num + 1
            if next_step > TOTAL_STEPS:
                if RECYCLE_LOTS:
                    await db.lots.update_one(
                        {"lot_id": lot_id},
                        {"$set": {"status": "Waiting", "current_step": 1},
                         "$inc": {"cycle": 1}},
                    )
                    print(f"[MES] {lot_id} recycled (cycle done).")
                else:
                    await db.lots.update_one(
                        {"lot_id": lot_id}, {"$set": {"status": "Finished"}}
                    )
                    print(f"[MES] {lot_id} FINISHED.")
            else:
                await db.lots.update_one(
                    {"lot_id": lot_id},
                    {"$set": {"status": "Waiting", "current_step": next_step}},
                )

        # ── PM cycle: every pm_threshold lots ────────────────────
        if pm_counter >= pm_threshold and _running:
            pm_start_time = datetime.utcnow()
            await db.tool_events.insert_one({
                "toolID":    tool_id,
                "eventType": "PM_START",
                "eventTime": pm_start_time,
                "metadata":  {
                    "reason":              "Scheduled chamber maintenance",
                    "lots_since_last_pm":  pm_counter,
                },
            })
            print(f"[MES] {tool_id} PM_START (after {pm_counter} lots)")
            await db.tools.update_one({"tool_id": tool_id}, {"$set": {"status": "Maintenance"}})

            pm_duration = random.uniform(15, 25)   # 15-25s in dev
            await asyncio.sleep(pm_duration)

            pm_done_time = datetime.utcnow()
            await db.tool_events.insert_one({
                "toolID":    tool_id,
                "eventType": "PM_DONE",
                "eventTime": pm_done_time,
                "metadata":  {
                    "duration_sec":       round(pm_duration, 1),
                    "lots_since_last_pm": pm_counter,
                },
            })
            print(f"[MES] {tool_id} PM_DONE (took {pm_duration:.1f}s)")
            await db.tools.update_one({"tool_id": tool_id}, {"$set": {"status": "Idle"}})

            # PM recalibration: reset DC drift + EC constants
            from app.services import dc_service, ec_service
            dc_service.reset_drift(tool_id)
            ec_service.pm_recalibrate(tool_id)
            print(f"[MES] {tool_id} DC drift + EC constants recalibrated after PM")

            pm_counter   = 0
            pm_threshold = random.randint(8, 12)   # reset for next cycle

    print(f"[MES] {tool_id} stopped — processed {processed} lots.")
