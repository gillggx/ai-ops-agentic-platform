import os

# ── Simulation Scale ──────────────────────────────────────────
TOTAL_LOTS    = int(os.getenv("TOTAL_LOTS", "9999"))
TOTAL_TOOLS   = 10
TOTAL_STEPS   = 100
TOTAL_RECIPES = 20

# ── Timing (seconds; dev defaults — prod: set PROCESSING_MIN/MAX to 480/600) ─
HEARTBEAT_MIN_SEC  = float(os.getenv("HEARTBEAT_MIN",   "5"))
HEARTBEAT_MAX_SEC  = float(os.getenv("HEARTBEAT_MAX",   "10"))
PROCESSING_MIN_SEC = float(os.getenv("PROCESSING_MIN",  "300"))   # 5 min
PROCESSING_MAX_SEC = float(os.getenv("PROCESSING_MAX",  "360"))   # 6 min
HOLD_PROBABILITY   = float(os.getenv("HOLD_PROBABILITY", "0.05"))   # 5% equipment hold

# ── Lot Recycling ─────────────────────────────────────────────
# True  → finished lots reset to step 1 (run forever)
# False → finished lots stay Finished (finite run)
RECYCLE_LOTS = os.getenv("RECYCLE_LOTS", "true").lower() == "true"

# ── MongoDB ───────────────────────────────────────────────────
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB  = os.getenv("MONGODB_DB",  "semiconductor_sim")

# ── Physics ───────────────────────────────────────────────────
APC_DRIFT_RATIO  = float(os.getenv("APC_DRIFT_RATIO",  "0.05"))   # ±5% per process
OOC_PROBABILITY  = float(os.getenv("OOC_PROBABILITY",  "0.20"))   # 20% OOC rate
