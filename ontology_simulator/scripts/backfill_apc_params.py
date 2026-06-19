"""One-time migration (2026-06-18): back-fill empty APC object_snapshots.

Companion to the `_seed_apc_models` back-fill fix (database.py). After
TOTAL_STEPS grew 10→20, APC-011..020 were never seeded, so every STEP_011..020
APC `object_snapshots` doc had empty `parameters` (no etch_time_offset) — which
made APC-case agent builds thrash. The seed fix only repairs apc_state (master)
going forward; this script repairs the EXISTING history in place (no reset, no
data loss).

For each `object_snapshots` doc with objectName=APC and empty parameters, copy
the matching apc_state model's parameters with a small per-snapshot jitter so a
per-recipe box-plot distribution isn't flat.

Run once after the seed fix is deployed and the simulator has restarted (so
apc_state already covers all TOTAL_STEPS models):

    python ontology_simulator/scripts/backfill_apc_params.py
"""
import asyncio
import random

from motor.motor_asyncio import AsyncIOMotorClient

from config import MONGODB_URI, MONGODB_DB


def _jitter(base_params: dict) -> dict:
    out = {}
    for k, v in base_params.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            out[k] = v
        else:
            out[k] = round(
                (v if v else 0.0) * (1 + random.uniform(-0.12, 0.12))
                + (0 if v else random.uniform(-0.15, 0.15)),
                4,
            )
    return out


async def main() -> None:
    from pymongo import UpdateOne

    db = AsyncIOMotorClient(MONGODB_URI)[MONGODB_DB]
    base = {}
    async for d in db.apc_state.find({}):
        base[d["apc_id"]] = d.get("parameters") or {}

    ops, filled, skipped = [], 0, 0
    async for snap in db.object_snapshots.find({"objectName": "APC", "parameters": {}}):
        bp = base.get(snap.get("objectID"))
        if not bp:
            skipped += 1
            continue
        ops.append(UpdateOne({"_id": snap["_id"]}, {"$set": {"parameters": _jitter(bp)}}))
        if len(ops) >= 1000:
            await db.object_snapshots.bulk_write(ops)
            filled += len(ops)
            ops = []
    if ops:
        await db.object_snapshots.bulk_write(ops)
        filled += len(ops)

    remaining = await db.object_snapshots.count_documents({"objectName": "APC", "parameters": {}})
    print(f"filled {filled} APC snapshots, skipped {skipped} (no apc_state base); "
          f"remaining empty: {remaining}")


if __name__ == "__main__":
    asyncio.run(main())
