"""MongoDB connection + one-time data seeding."""
import random
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from config import (
    MONGODB_URI, MONGODB_DB,
    TOTAL_LOTS, TOTAL_TOOLS, TOTAL_STEPS, TOTAL_RECIPES,
)

_client: AsyncIOMotorClient = None
_db: AsyncIOMotorDatabase = None


def get_db() -> AsyncIOMotorDatabase:
    return _db


async def connect_and_init() -> None:
    global _client, _db
    _client = AsyncIOMotorClient(MONGODB_URI)
    _db = _client[MONGODB_DB]

    await _create_indexes()
    await _seed_lots()
    await _seed_tools()
    await _seed_recipes()
    await _seed_apc_models()
    print(f"[DB] Connected to {MONGODB_DB}. Seed complete.")


async def disconnect() -> None:
    if _client:
        _client.close()


# ── Indexes ───────────────────────────────────────────────────

async def _create_indexes() -> None:
    db = _db
    await db.object_snapshots.create_index([("objectID", 1), ("objectName", 1), ("eventTime", -1)])
    await db.object_snapshots.create_index([("lotID", 1), ("objectName", 1), ("eventTime", -1)])
    await db.events.create_index([("lotID", 1), ("step", 1), ("eventTime", -1)])
    await db.events.create_index([("toolID", 1), ("step", 1), ("eventTime", -1)])
    await db.lots.create_index([("lot_id", 1)], unique=True)
    await db.tools.create_index([("tool_id", 1)], unique=True)
    await db.apc_state.create_index([("apc_id", 1)], unique=True)
    await db.recipe_data.create_index([("recipe_id", 1)], unique=True)


# ── Seeders (idempotent) ──────────────────────────────────────

async def _seed_lots() -> None:
    if await _db.lots.count_documents({}) > 0:
        return
    docs = [
        {"lot_id": f"LOT-{i:04d}", "current_step": 1, "status": "Waiting", "cycle": 0}
        for i in range(1, TOTAL_LOTS + 1)
    ]
    await _db.lots.insert_many(docs)
    print(f"[DB] Seeded {TOTAL_LOTS} lots.")


async def _seed_tools() -> None:
    if await _db.tools.count_documents({}) > 0:
        return
    docs = [
        {"tool_id": f"EQP-{i:02d}", "status": "Idle"}
        for i in range(1, TOTAL_TOOLS + 1)
    ]
    await _db.tools.insert_many(docs)
    print(f"[DB] Seeded {TOTAL_TOOLS} tools.")


# ── Physical parameter ranges for seeding ────────────────────
# Each tuple is (lo, hi) in engineering units matching RightInspector labels.

_RECIPE_PARAM_RANGES = [
    (25.0,   35.0),    # param_01  Etch Time         (s)
    (45.0,   55.0),    # param_02  Etch Depth        (nm)
    (1.3,    1.8),     # param_03  Etch Rate         (nm/s)
    (-5.0,   5.0),     # param_04  CD Bias           (nm)
    (10.0,   20.0),    # param_05  Over-Etch         (%)
    (13.0,   17.0),    # param_06  Process Press     (mTorr)
    (0.5,    2.0),     # param_07  Base Press        (mTorr)
    (40.0,   50.0),    # param_08  Chamber Temp      (°C)
    (40.0,   50.0),    # param_09  Wall Temp         (°C)
    (44.0,   56.0),    # param_10  CF4 Setpoint      (sccm)
    (7.5,    12.5),    # param_11  O2 Setpoint       (sccm)
    (88.0,   112.0),   # param_12  Ar Setpoint       (sccm)
    (8.5,    11.5),    # param_13  He Setpoint       (sccm)
    (1430.,  1570.),   # param_14  Source Power      (W)
    (330.,   470.),    # param_15  Bias Power        (W)
    (13.549, 13.571),  # param_16  Source Freq       (MHz)
    (395.,   405.),    # param_17  Bias Freq         (kHz)
    (0.30,   0.70),    # param_18  EPD Threshold     (AU)
    (20.0,   25.0),    # param_19  Min Etch Time     (s)
    (35.0,   45.0),    # param_20  Max Etch Time     (s)
]

_APC_PARAM_RANGES = [
    (0.0,    0.05),    # param_01  R2R Bias          (nm)
    (0.90,   1.10),    # param_02  R2R Gain          (—)
    (-2.0,   2.0),     # param_03  R2R Offset        (nm)
    (0.10,   0.40),    # param_04  Model Intercept   (—)
    (48.0,   52.0),    # param_05  Target CD         (nm)
    (8.0,    12.0),    # param_06  Target EPD        (s)
    (90.0,   110.0),   # param_07  Etch Rate         (nm/min)
    (1.0,    3.0),     # param_08  Uniformity        (%)
    (0.92,   1.08),    # param_09  FF Correction     (—)
    (0.20,   0.80),    # param_10  FF Weight         (—)
    (0.05,   0.25),    # param_11  FF Alpha          (—)
    (0.10,   0.50),    # param_12  Lot Weight        (—)
    (0.92,   1.08),    # param_13  FB Correction     (—)
    (0.05,   0.20),    # param_14  FB Alpha          (—)
    (0.85,   0.99),    # param_15  Model R²          (—)
    (0.90,   0.99),    # param_16  Stability Index   (—)
    (0.001,  0.010),   # param_17  Prediction Error  (nm)
    (0.90,   0.99),    # param_18  Convergence Idx   (—)
    (0.001,  0.010),   # param_19  Reg λ             (—)
    (0.88,   1.12),    # param_20  Response Factor   (—)
]


async def _seed_recipes() -> None:
    if await _db.recipe_data.count_documents({}) > 0:
        return
    docs = [
        {
            "recipe_id": f"RCP-{i:03d}",
            "parameters": {
                f"param_{j:02d}": round(random.uniform(*_RECIPE_PARAM_RANGES[j - 1]), 4)
                for j in range(1, 21)
            },
        }
        for i in range(1, TOTAL_RECIPES + 1)
    ]
    await _db.recipe_data.insert_many(docs)
    print(f"[DB] Seeded {TOTAL_RECIPES} recipes.")


def _make_apc_params() -> dict:
    """APC model parameters with physical engineering initial values."""
    return {
        f"param_{j:02d}": round(random.uniform(*_APC_PARAM_RANGES[j - 1]), 4)
        for j in range(1, 21)
    }


async def _seed_apc_models() -> None:
    if await _db.apc_state.count_documents({}) > 0:
        return
    docs = [
        {
            "apc_id": f"APC-{i:03d}",
            "bound_step": f"STEP_{i:03d}",
            "parameters": _make_apc_params(),
        }
        for i in range(1, TOTAL_STEPS + 1)
    ]
    await _db.apc_state.insert_many(docs)
    print(f"[DB] Seeded {TOTAL_STEPS} APC models.")
