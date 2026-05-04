import os

# ── Simulation Scale ──────────────────────────────────────────
TOTAL_LOTS    = int(os.getenv("TOTAL_LOTS", "99999"))
TOTAL_TOOLS   = 10
TOTAL_STEPS   = 10
TOTAL_RECIPES = 20

# ── Timing (seconds; canonical contract: 8-10 min process, see SPEC §2.1) ──
HEARTBEAT_MIN_SEC  = float(os.getenv("HEARTBEAT_MIN",   "5"))
HEARTBEAT_MAX_SEC  = float(os.getenv("HEARTBEAT_MAX",   "10"))
PROCESSING_MIN_SEC = float(os.getenv("PROCESSING_MIN",  "480"))   # 8 min
PROCESSING_MAX_SEC = float(os.getenv("PROCESSING_MAX",  "600"))   # 10 min
HOLD_PROBABILITY   = float(os.getenv("HOLD_PROBABILITY", "0.02"))   # 2% equipment hold (was 5%)
# HOLD timeout: tool sits idle this long before auto-release if engineer
# never acknowledges. Was 3600s (1h) — caused tools to look "stuck" for an
# hour in mongo while real activity continued elsewhere. 300s (5min) keeps
# the demo of HOLD visible without burning per-tool time budget.
HOLD_TIMEOUT_SEC   = float(os.getenv("HOLD_TIMEOUT_SEC", "300"))

# ── Lot Recycling ─────────────────────────────────────────────
# True  → finished lots reset to step 1 (run forever)
# False → finished lots stay Finished (finite run)
RECYCLE_LOTS = os.getenv("RECYCLE_LOTS", "true").lower() == "true"

# ── MongoDB ───────────────────────────────────────────────────
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB  = os.getenv("MONGODB_DB",  "semiconductor_sim")

# ── Physics ───────────────────────────────────────────────────
APC_DRIFT_RATIO  = float(os.getenv("APC_DRIFT_RATIO",  "0.05"))   # ±5% per process
OOC_PROBABILITY  = float(os.getenv("OOC_PROBABILITY",  "0.07"))   # 7% baseline OOC rate
# Lowered from 0.30 (saturated dashboard with 9/10 crit). Drift-driven OOC
# (chamber/heater wear) still kicks in via dc_service._DRIFT_RATES so the
# tail of the distribution still trips alarms — just less often per step.
