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
    # object_snapshots: queries by (objectID, objectName, status, eventTime)
    await db.object_snapshots.create_index([("objectID", 1), ("objectName", 1), ("status", 1), ("eventTime", -1)])
    await db.object_snapshots.create_index([("lotID", 1), ("objectName", 1), ("status", 1), ("eventTime", -1)])
    # SPC domain index: tool-centric OOC search (search_ooc_events, get_baseline_stats)
    await db.object_snapshots.create_index([("toolID", 1), ("objectName", 1), ("status", 1), ("eventTime", -1)])
    # events: queries by (lotID/toolID, step, status, eventType)
    await db.events.create_index([("lotID", 1), ("step", 1), ("status", 1), ("eventType", 1), ("eventTime", -1)])
    await db.events.create_index([("toolID", 1), ("step", 1), ("status", 1), ("eventType", 1), ("eventTime", -1)])
    await db.lots.create_index([("lot_id", 1)], unique=True)
    await db.tools.create_index([("tool_id", 1)], unique=True)
    await db.apc_state.create_index([("apc_id", 1)], unique=True)
    await db.recipe_data.create_index([("recipe_id", 1)], unique=True)


# ── Seeders (idempotent) ──────────────────────────────────────

async def _seed_lots() -> None:
    # 2026-05-06: stop pre-seeding all 99999 lots up front — the lot pacer
    # in app/mes/simulator.py creates new lots in batches once active count
    # drops below ACTIVE_LOT_TARGET. Seed just the initial batch (20) so
    # machines have something to claim on first boot.
    from config import ACTIVE_LOT_TARGET
    if await _db.lots.count_documents({}) > 0:
        return
    docs = [
        {"lot_id": f"LOT-{i:04d}", "current_step": 1, "status": "Waiting", "cycle": 0}
        for i in range(1, ACTIVE_LOT_TARGET + 1)
    ]
    await _db.lots.insert_many(docs)
    print(f"[DB] Seeded {ACTIVE_LOT_TARGET} initial lots (pacer takes over from here).")


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
# Each tuple is (lo, hi) in engineering units.
# Keys use real semiconductor domain names (no param_N / sensor_N).

_RECIPE_PARAMS: list[tuple[str, float, float]] = [
    ("etch_time_s",           25.0,   35.0),    # Etch Time         (s)
    ("target_thickness_nm",   45.0,   55.0),    # Target Thickness  (nm)
    ("etch_rate_nm_per_s",     1.3,    1.8),    # Etch Rate         (nm/s)
    ("cd_bias_nm",            -5.0,    5.0),    # CD Bias           (nm)
    ("over_etch_pct",         10.0,   20.0),    # Over-Etch         (%)
    ("process_pressure_mtorr",13.0,   17.0),    # Process Press     (mTorr)
    ("base_pressure_mtorr",    0.5,    2.0),    # Base Press        (mTorr)
    ("chamber_temp_c",        40.0,   50.0),    # Chamber Temp      (°C)
    ("wall_temp_c",           40.0,   50.0),    # Wall Temp         (°C)
    ("cf4_setpoint_sccm",     44.0,   56.0),    # CF4 Setpoint      (sccm)
    ("o2_setpoint_sccm",       7.5,   12.5),    # O2 Setpoint       (sccm)
    ("ar_setpoint_sccm",      88.0,  112.0),    # Ar Setpoint       (sccm)
    ("he_setpoint_sccm",       8.5,   11.5),    # He Setpoint       (sccm)
    ("source_power_w",      1430.0, 1570.0),    # Source Power      (W)
    ("bias_power_w",          330.0,  470.0),   # Bias Power        (W)
    ("source_freq_mhz",    13.549,  13.571),    # Source Freq       (MHz)
    ("bias_freq_khz",         395.0,  405.0),   # Bias Freq         (kHz)
    ("epd_threshold_au",       0.30,   0.70),   # EPD Threshold     (AU)
    ("min_etch_time_s",       20.0,   25.0),    # Min Etch Time     (s)
    ("max_etch_time_s",       35.0,   45.0),    # Max Etch Time     (s)
]

_APC_PARAMS: list[tuple[str, float, float]] = [
    ("etch_time_offset",       0.0,   0.05),    # Etch Time Offset  (s)
    ("rf_power_bias",          0.90,   1.10),   # RF Power Bias     (—)
    ("gas_flow_comp",         -2.0,    2.0),    # Gas Flow Comp     (sccm)
    ("model_intercept",        0.10,   0.40),   # Model Intercept   (—)
    ("target_cd_nm",          48.0,   52.0),    # Target CD         (nm)
    ("target_epd_s",           8.0,   12.0),    # Target EPD        (s)
    ("etch_rate_pred",        90.0,  110.0),    # Etch Rate Pred    (nm/min)
    ("uniformity_pct",         1.0,    3.0),    # Uniformity        (%)
    ("ff_correction",          0.92,   1.08),   # FF Correction     (—)
    ("ff_weight",              0.20,   0.80),   # FF Weight         (—)
    ("ff_alpha",               0.05,   0.25),   # FF Alpha          (—)
    ("lot_weight",             0.10,   0.50),   # Lot Weight        (—)
    ("fb_correction",          0.92,   1.08),   # FB Correction     (—)
    ("fb_alpha",               0.05,   0.20),   # FB Alpha          (—)
    ("model_r2_score",         0.85,   0.99),   # Model R²          (—)
    ("stability_index",        0.90,   0.99),   # Stability Index   (—)
    ("prediction_error_nm",    0.001,  0.010),  # Prediction Error  (nm)
    ("convergence_idx",        0.90,   0.99),   # Convergence Idx   (—)
    ("reg_lambda",             0.001,  0.010),  # Reg λ             (—)
    ("response_factor",        0.88,   1.12),   # Response Factor   (—)
]


async def _seed_recipes() -> None:
    # Force re-seed if existing data still uses legacy param_N naming
    first = await _db.recipe_data.find_one({})
    if first:
        keys = list((first.get("parameters") or {}).keys())
        if keys and not keys[0].startswith("param_"):
            # Check if version field exists; if not, add it
            if "version" not in first:
                await _db.recipe_data.update_many({}, {"$set": {"version": 1}})
                print("[DB] Added version=1 to existing recipes.")
            return
        print("[DB] Detected legacy param_N keys in recipe_data — dropping for re-seed.")
        await _db.recipe_data.drop()

    docs = [
        {
            "recipe_id": f"RCP-{i:03d}",
            "version": 1,
            "parameters": {
                name: round(random.uniform(lo, hi), 4)
                for name, lo, hi in _RECIPE_PARAMS
            },
        }
        for i in range(1, TOTAL_RECIPES + 1)
    ]
    await _db.recipe_data.insert_many(docs)
    print(f"[DB] Seeded {TOTAL_RECIPES} recipes (semantic params, version=1).")


def _make_apc_params() -> dict:
    """APC model parameters with real semiconductor domain names."""
    return {
        name: round(random.uniform(lo, hi), 6)
        for name, lo, hi in _APC_PARAMS
    }


async def _seed_apc_models() -> None:
    # Force re-seed if existing data still uses legacy param_N naming
    first = await _db.apc_state.find_one({})
    if first:
        keys = list((first.get("parameters") or {}).keys())
        if keys and not keys[0].startswith("param_"):
            return  # Already semantic — skip
        print("[DB] Detected legacy param_N keys in apc_state — dropping for re-seed.")
        await _db.apc_state.drop()

    docs = [
        {
            "apc_id": f"APC-{i:03d}",
            "bound_step": f"STEP_{i:03d}",
            "parameters": _make_apc_params(),
        }
        for i in range(1, TOTAL_STEPS + 1)
    ]
    await _db.apc_state.insert_many(docs)
    print(f"[DB] Seeded {TOTAL_STEPS} APC models (semantic params).")
