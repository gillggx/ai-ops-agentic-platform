import os

# ── Simulation Scale ──────────────────────────────────────────
# 2026-05-06: switch from "pre-create 99999 lots, $sample randomly" to
# "keep ~20 lots in-flight, top up batches of 10 when active count drops".
# This raises the avg events-per-lot from 2.62 → ~20 (full STEP_001 →
# STEP_020 lifecycle) so trace lanes and lot-level trends have enough
# signal to be useful.
TOTAL_TOOLS   = 10
TOTAL_STEPS   = 20                                        # was 10
TOTAL_RECIPES = 20

# Phase 12 — chamber dimension. Each tool has N chambers; per-process
# chamber routing is random (per user decision: chambers each process
# random, not per-lot fixed). Chamber-level data lets cross-chamber match
# / drift / utilization skills work.
CHAMBERS_PER_TOOL = int(os.getenv("CHAMBERS_PER_TOOL", "4"))

# Phase 12 — monitor lot generator. Every Nth production lot, a monitor
# lot is interleaved (special step subset, looser SPC limits).
MONITOR_LOT_EVERY     = int(os.getenv("MONITOR_LOT_EVERY",     "20"))
# SPC limits: production = mean ± 1.5σ; monitor = mean ± 2.0σ (looser).
SPC_SD_PRODUCTION     = float(os.getenv("SPC_SD_PRODUCTION",   "1.5"))
SPC_SD_MONITOR        = float(os.getenv("SPC_SD_MONITOR",      "2.0"))

# Phase 12 — daily manual override cron. 1-2 random APC/recipe edits per
# 24h to populate parameter_audit_log with "engineer:<name>" rows.
MANUAL_OVERRIDE_PER_DAY_MIN = int(os.getenv("MANUAL_OVERRIDE_MIN", "1"))
MANUAL_OVERRIDE_PER_DAY_MAX = int(os.getenv("MANUAL_OVERRIDE_MAX", "2"))

# Lot pacer — keep concurrent in-flight lots near a target. New batches
# are created lazily only when active count falls below the target.
# Finished lots stay Finished (no recycle); pacer creates fresh sequential
# IDs. The legacy `TOTAL_LOTS` and `RECYCLE_LOTS` envs were removed
# 2026-05-08 — they pre-dated the pacer model and pinning lots to a fixed
# pool conflicted with the "lots flow through" semantics the topology
# trace view depends on.
ACTIVE_LOT_TARGET = int(os.getenv("ACTIVE_LOT_TARGET", "20"))
LOT_BATCH_SIZE    = int(os.getenv("LOT_BATCH_SIZE",    "10"))
PACER_INTERVAL_SEC = float(os.getenv("PACER_INTERVAL_SEC", "10"))

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

# ── MongoDB ───────────────────────────────────────────────────
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB  = os.getenv("MONGODB_DB",  "semiconductor_sim")

# ── Physics ───────────────────────────────────────────────────
APC_DRIFT_RATIO  = float(os.getenv("APC_DRIFT_RATIO",  "0.05"))   # ±5% per process
OOC_PROBABILITY  = float(os.getenv("OOC_PROBABILITY",  "0.07"))   # 7% baseline OOC rate
# Lowered from 0.30 (saturated dashboard with 9/10 crit). Drift-driven OOC
# (chamber/heater wear) still kicks in via dc_service._DRIFT_RATES so the
# tail of the distribution still trips alarms — just less often per step.
