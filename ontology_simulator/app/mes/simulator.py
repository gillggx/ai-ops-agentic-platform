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
    TOTAL_TOOLS, TOTAL_STEPS, CHAMBERS_PER_TOOL,
    ACTIVE_LOT_TARGET, LOT_BATCH_SIZE, PACER_INTERVAL_SEC,
    MONITOR_LOT_EVERY,
    MANUAL_OVERRIDE_PER_DAY_MIN, MANUAL_OVERRIDE_PER_DAY_MAX,
)

_running = False

# ── Phase 12 step lists ──────────────────────────────────────
# Production lots run all 20 steps. Monitor lots are check vehicles —
# they only run a sparse subset (every 5th step) so an entire monitor
# lot finishes in ~30min instead of ~3h. Skills that compare monitor vs
# production aggregate at the chart-step level.
_PRODUCTION_STEPS = list(range(1, TOTAL_STEPS + 1))
_MONITOR_STEPS    = [s for s in (5, 10, 15, 20) if s <= TOTAL_STEPS]


def _next_step(current: int, lot_type: str) -> int | None:
    """Return the next step number after `current` for this lot_type, or
    None if the lot has finished its step list."""
    seq = _MONITOR_STEPS if lot_type == "monitor" else _PRODUCTION_STEPS
    later = [s for s in seq if s > current]
    return later[0] if later else None


def _initial_step(lot_type: str) -> int:
    seq = _MONITOR_STEPS if lot_type == "monitor" else _PRODUCTION_STEPS
    return seq[0]


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

    # ── Pacer + all machines + manual-override cron run concurrently ──
    tools = [f"EQP-{i:02d}" for i in range(1, TOTAL_TOOLS + 1)]
    queue: asyncio.Queue = asyncio.Queue()  # always-empty placeholder; machines fall through to DB
    coroutines = (
        [_machine_loop(tid, queue) for tid in tools]
        + [_lot_pacer(), _manual_override_cron()]
    )
    print(f"[MES] {len(tools)} machines + pacer + override-cron starting")
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
    highest existing lot_id. Phase 12: every Nth lot is a monitor lot
    (lot_type='monitor', initial_step from MONITOR_STEPS). Returns the
    new max lot_id."""
    last = await db.lots.find_one(
        {}, sort=[("lot_id", -1)], projection={"_id": 0, "lot_id": 1},
    )
    last_num = 0
    if last and isinstance(last.get("lot_id"), str) and last["lot_id"].startswith("LOT-"):
        try:
            last_num = int(last["lot_id"][4:])
        except ValueError:
            pass

    docs = []
    for i in range(n):
        lot_num = last_num + i + 1
        # Every Nth lot becomes a monitor — uses sequential lot_num so the
        # interleave is deterministic and observable in the data.
        is_monitor = (lot_num % MONITOR_LOT_EVERY == 0)
        lot_type   = "monitor" if is_monitor else "production"
        docs.append({
            "lot_id":       f"LOT-{lot_num:04d}",
            "current_step": _initial_step(lot_type),
            "status":       "Waiting",
            "cycle":        0,
            "lot_type":     lot_type,
        })
    await db.lots.insert_many(docs)
    n_monitor = sum(1 for d in docs if d["lot_type"] == "monitor")
    if n_monitor:
        print(f"[MES] Pacer batch: {n_monitor} monitor + {n - n_monitor} production")
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
        lot_type = lot.get("lot_type", "production")

        # Phase 12: pick a chamber for this process. User decision: random
        # per process (NOT pinned per lot) — lets cross-chamber match /
        # drift / utilization skills detect chamber-level signal.
        chamber_id = f"CH-{random.randint(1, CHAMBERS_PER_TOOL)}"

        await db.tools.update_one({"tool_id": tool_id}, {"$set": {"status": "Busy"}})

        # Step advancement is INSIDE the try, only after process_step succeeds.
        # On Exception OR asyncio.CancelledError (graceful shutdown), the lot
        # stays in Processing/current_step=N — startup's "Reset stuck lots" puts
        # it back to Waiting at the same step, and a machine retries it.
        # finally only releases the tool's Busy flag.
        try:
            await process_step(lot_id, tool_id, step_num, chamber_id, lot_type)
            processed  += 1
            pm_counter += 1

            # Phase 12: monitor lots run only [5, 10, 15, 20]; production
            # runs all 20. _next_step encapsulates that branch.
            next_step = _next_step(step_num, lot_type)
            if next_step is None:
                # Lot completed its step list → mark Finished. The pacer's
                # active-count threshold drops below target → fresh lots
                # get created with sequential IDs. (Removed 2026-05-08:
                # RECYCLE_LOTS=true branch that reset step=1 + cycle++
                # forever — incompatible with the pacer's new-lot
                # contract; see config.py history note.)
                await db.lots.update_one(
                    {"lot_id": lot_id}, {"$set": {"status": "Finished"}}
                )
                print(f"[MES] {lot_id} ({lot_type}) FINISHED.")
            else:
                await db.lots.update_one(
                    {"lot_id": lot_id},
                    {"$set": {"status": "Waiting", "current_step": next_step}},
                )
        except Exception as exc:
            print(f"[MES] ERROR – {lot_id} on {tool_id} step {step_num}: {exc}")
        finally:
            await db.tools.update_one({"tool_id": tool_id}, {"$set": {"status": "Idle"}})

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

            # PM recalibration: reset DC drift + EC constants on every chamber.
            # Phase 12 — PM is whole-tool maintenance, so all 4 chambers reset
            # together. (per-chamber PM events would need new event types.)
            from app.services import dc_service, ec_service
            dc_service.reset_drift(tool_id)  # passes chamber_id="" → resets all
            for ch in range(1, CHAMBERS_PER_TOOL + 1):
                ec_service.pm_recalibrate(tool_id, f"CH-{ch}")
            print(f"[MES] {tool_id} DC drift + EC constants recalibrated after PM "
                  f"({CHAMBERS_PER_TOOL} chambers)")

            pm_counter   = 0
            pm_threshold = random.randint(8, 12)   # reset for next cycle

    print(f"[MES] {tool_id} stopped — processed {processed} lots.")


# ── Phase 12 manual-override cron ──────────────────────────────
# Once per simulated 24h, fire 1-2 random "engineer override" rows on
# either an APC or a recipe parameter. These rows populate
# parameter_audit_log with `source='engineer:<name>'` so RECIPE_TRACE /
# APC_AUDIT skills have realistic human-in-the-loop data to surface.
#
# Implementation: instead of waiting an actual 24h (boring in a demo run),
# treat 24h sim-time as ~30min wall-clock — fire the daily quota across
# that interval. Easy override via env if a slower cadence is desired.

_ENGINEER_NAMES = ["alice.chen", "bob.lin", "carol.wu", "dave.huang", "eve.kao"]
_OVERRIDE_REASONS = [
    "Process tuning per yield review",
    "Manual offset following golden-wafer match",
    "Recipe correction after CDx slip",
    "Adjustment per Eng Bulletin EB-2026-04",
    "Realignment with reference tool",
    "Drift compensation override",
]
_SIM_DAY_SEC = float(__import__("os").environ.get("SIM_DAY_SEC", "1800"))  # 30min default


async def _manual_override_cron() -> None:
    db = get_db()
    while _running:
        n = random.randint(MANUAL_OVERRIDE_PER_DAY_MIN, MANUAL_OVERRIDE_PER_DAY_MAX)
        # Spread the n overrides across the simulated day window.
        slots = sorted(random.uniform(0, _SIM_DAY_SEC) for _ in range(n))
        last = 0.0
        for slot in slots:
            wait = max(0.0, slot - last)
            try:
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                return
            if not _running:
                return
            try:
                await _emit_random_override(db)
            except Exception as exc:
                print(f"[MES] override-cron error (will retry): {exc}")
            last = slot
        # Sleep the rest of the day
        await asyncio.sleep(max(0.0, _SIM_DAY_SEC - last))
    print("[MES] override-cron stopped.")


async def _emit_random_override(db) -> None:
    """Pick APC or RECIPE at random, mutate one param, write audit row."""
    from app.services import audit_service

    engineer = random.choice(_ENGINEER_NAMES)
    reason   = random.choice(_OVERRIDE_REASONS)

    if random.random() < 0.5:
        # APC override
        apc = await db.apc_state.aggregate([{"$sample": {"size": 1}}]).to_list(1)
        if not apc:
            return
        doc = apc[0]
        params = doc.get("parameters", {})
        if not params:
            return
        param = random.choice(list(params.keys()))
        old = params[param]
        try:
            new = round(float(old) * random.uniform(0.95, 1.05), 6)
        except (TypeError, ValueError):
            return
        await db.apc_state.update_one(
            {"apc_id": doc["apc_id"]},
            {"$set": {f"parameters.{param}": new}},
        )
        await audit_service.record_engineer_override(
            object_name="APC", object_id=doc["apc_id"],
            parameter=param, old_value=old, new_value=new,
            engineer=engineer, reason=reason,
        )
        print(f"[MES] override → APC/{doc['apc_id']}.{param}: {old}→{new} ({engineer})")
    else:
        # Recipe override
        recipe = await db.recipe_data.aggregate([{"$sample": {"size": 1}}]).to_list(1)
        if not recipe:
            return
        doc = recipe[0]
        params = doc.get("parameters", {})
        if not params:
            return
        param = random.choice(list(params.keys()))
        old = params[param]
        try:
            new = round(float(old) * random.uniform(0.97, 1.03), 4)
        except (TypeError, ValueError):
            return
        new_version = doc.get("version", 1) + 1
        await db.recipe_data.update_one(
            {"recipe_id": doc["recipe_id"]},
            {"$set": {f"parameters.{param}": new, "version": new_version}},
        )
        await audit_service.record_engineer_override(
            object_name="RECIPE", object_id=doc["recipe_id"],
            parameter=param, old_value=old, new_value=new,
            engineer=engineer, reason=reason,
        )
        print(f"[MES] override → RECIPE/{doc['recipe_id']}.{param}: "
              f"{old}→{new} v{new_version} ({engineer})")
