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

    # ── Staggered start: 4–6 machines at T=0, rest deferred ────
    tools = [f"EQP-{i:02d}" for i in range(1, TOTAL_TOOLS + 1)]
    random.shuffle(tools)
    immediate_count = random.randint(4, 6)
    immediate_tools = tools[:immediate_count]
    deferred_tools  = tools[immediate_count:]

    async def _deferred_loop(tid: str) -> None:
        delay = random.uniform(10, 60)
        print(f"[MES] {tid} deferred start in {delay:.0f}s")
        await asyncio.sleep(delay)
        await _machine_loop(tid, queue)

    coroutines = [_machine_loop(tid, queue) for tid in immediate_tools]
    coroutines += [_deferred_loop(tid) for tid in deferred_tools]
    await asyncio.gather(*coroutines)

    elapsed = (datetime.utcnow() - sim_start).total_seconds()
    print(f"[MES] All lots processed in {elapsed/60:.1f} min. Simulator idle.")
    _running = False


def stop() -> None:
    global _running
    _running = False


async def _claim_lot_from_db(db) -> dict | None:
    """Atomically claim one waiting lot from MongoDB (for recycled lots)."""
    return await db.lots.find_one_and_update(
        {"status": "Waiting"},
        {"$set": {"status": "Processing"}},
        sort=[("lot_id", 1)],
        return_document=ReturnDocument.AFTER,
    )


async def _machine_loop(tool_id: str, queue: asyncio.Queue) -> None:
    """Single machine loop: pull lots from queue, then DB, indefinitely."""
    db = get_db()
    processed = 0

    while _running:
        # ── Fast path: shared startup queue ──────────────────────
        lot = None
        try:
            lot = queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        # ── Fallback: claim a recycled/waiting lot from DB ────────
        if lot is None:
            lot = await _claim_lot_from_db(db)

        if lot is None:
            # Genuinely nothing to do — wait and retry
            await asyncio.sleep(5)
            continue

        lot_id   = lot["lot_id"]
        step_num = lot.get("current_step", 1)

        # Mark tool busy (lot is already "Processing" via atomic claim or explicit set)
        await db.tools.update_one({"tool_id": tool_id}, {"$set": {"status": "Busy"}})
        await db.lots.update_one({"lot_id": lot_id},    {"$set": {"status": "Processing"}})

        try:
            await process_step(lot_id, tool_id, step_num)
            processed += 1
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

    print(f"[MES] {tool_id} stopped — processed {processed} lots.")
