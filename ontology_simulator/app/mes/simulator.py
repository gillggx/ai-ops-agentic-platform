"""MES Simulator – paced lot lifecycle across 10 Tools.

Architecture (2026-05-06 redesign):
  - Stuck "Processing" lots from previous runs are reset to "Waiting" on startup.
  - One-time cleanup: if a legacy DB has thousands of pre-seeded Waiting lots,
    trim down to ACTIVE_LOT_TARGET so the pacer model isn't drowned.
  - 10 machine coroutines run concurrently; each atomically claims any
    Waiting lot from MongoDB ($sample) and runs one step, then either
    advances current_step or marks the lot Finished at STEP_020.
  - A lot pacer coroutine wakes every PACER_INTERVAL_SEC, counts active
    lots (Waiting + Processing). If active < ACTIVE_LOT_TARGET it batch-
    creates LOT_BATCH_SIZE new lots with sequential IDs. This keeps the
    in-flight population near the target without ever pre-creating
    99,999 lots up front.
"""
import asyncio
import random
from datetime import datetime
from pymongo import ReturnDocument
from app.database import get_db
from app.agent.station_agent import process_step
from config import (
    TOTAL_TOOLS, TOTAL_STEPS, RECYCLE_LOTS,
    ACTIVE_LOT_TARGET, LOT_BATCH_SIZE, PACER_INTERVAL_SEC,
)

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

    # ── One-time cleanup of legacy bulk-seeded Waiting lots ────
    await _cleanup_excess_waiting(db)

    print(f"[MES] Simulation start: pacer target={ACTIVE_LOT_TARGET}, "
          f"batch={LOT_BATCH_SIZE}, total_steps={TOTAL_STEPS}")
    sim_start = datetime.utcnow()

    # ── Pacer + all machines run concurrently, both pulling from DB ──
    tools = [f"EQP-{i:02d}" for i in range(1, TOTAL_TOOLS + 1)]
    queue: asyncio.Queue = asyncio.Queue()  # always-empty placeholder; machines fall through to DB
    coroutines = [_machine_loop(tid, queue) for tid in tools] + [_lot_pacer()]
    print(f"[MES] {len(tools)} machines + 1 pacer starting")
    await asyncio.gather(*coroutines)

    elapsed = (datetime.utcnow() - sim_start).total_seconds()
    print(f"[MES] Stopped after {elapsed/60:.1f} min.")
    _running = False


async def _cleanup_excess_waiting(db) -> None:
    """One-time trim of legacy 99,999-pre-seeded DBs. Keeps the lowest
    ACTIVE_LOT_TARGET Waiting lot_ids and deletes the rest. No-ops once
    the DB is already paced, since count never exceeds target by much."""
    waiting = await db.lots.count_documents({"status": "Waiting"})
    if waiting <= ACTIVE_LOT_TARGET * 3:
        return
    keep_cursor = db.lots.find(
        {"status": "Waiting"}, {"_id": 0, "lot_id": 1}
    ).sort("lot_id", 1).limit(ACTIVE_LOT_TARGET)
    keep_ids = {doc["lot_id"] async for doc in keep_cursor}
    res = await db.lots.delete_many({
        "status": "Waiting",
        "lot_id": {"$nin": list(keep_ids)},
    })
    print(f"[MES] Cleanup: removed {res.deleted_count} excess Waiting lots, "
          f"kept {len(keep_ids)}")


async def _create_lot_batch(db, n: int) -> str:
    """Insert n new Waiting lots with sequential IDs continuing from the
    highest existing lot_id. Returns the new max lot_id."""
    last = await db.lots.find_one(
        {}, sort=[("lot_id", -1)], projection={"_id": 0, "lot_id": 1},
    )
    last_num = 0
    if last and isinstance(last.get("lot_id"), str) and last["lot_id"].startswith("LOT-"):
        try:
            last_num = int(last["lot_id"][4:])
        except ValueError:
            pass
    docs = [
        {"lot_id": f"LOT-{last_num + i + 1:04d}", "current_step": 1,
         "status": "Waiting", "cycle": 0}
        for i in range(n)
    ]
    await db.lots.insert_many(docs)
    return f"LOT-{last_num + n:04d}"


async def _lot_pacer() -> None:
    """Periodically top up the Waiting pool when in-flight count drops
    below target. Definition of "active" = Waiting + Processing — the
    user's intent is "lots that haven't finished yet"."""
    db = get_db()
    while _running:
        try:
            active = await db.lots.count_documents(
                {"status": {"$in": ["Waiting", "Processing"]}}
            )
            if active < ACTIVE_LOT_TARGET:
                new_max = await _create_lot_batch(db, LOT_BATCH_SIZE)
                print(f"[MES] Pacer: active={active} < {ACTIVE_LOT_TARGET}, "
                      f"+{LOT_BATCH_SIZE} new → tail={new_max}")
        except Exception as exc:
            print(f"[MES] Pacer error (will retry): {exc}")
        await asyncio.sleep(PACER_INTERVAL_SEC)
    print("[MES] Pacer stopped.")


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
