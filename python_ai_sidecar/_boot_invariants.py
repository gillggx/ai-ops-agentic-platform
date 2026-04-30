"""Boot-time consistency checks for the sidecar.

Catches "rubber-stamp drift": adding a new block / state key requires
touching N parallel registrations. Without these checks the only signal
of a missing registration is a runtime crash on the first user that
trips through the broken code path.

Each check logs at ERROR level and (where safe) raises so the service
fails-fast at startup instead of degrading silently.

Adopted in 2026-04-30 after a single 24-hour stretch produced four
identical-shape bugs (block whitelist drift, GraphState dropping run()
kwargs, Java proxy missing forward fields, Flyway disabled in prod).
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ── 1. Block-registration consistency ─────────────────────────────────
# Adding a new block requires four parallel updates:
#   1. pipeline_builder/blocks/<x>.py            executor implementation
#   2. BUILTIN_EXECUTORS dict                    runtime registry
#   3. SIDECAR_NATIVE_BLOCKS frozenset           native fast-path whitelist
#   4. pb_blocks DB row (Flyway / manual seed)   catalog visible to LLM
#
# Miss any one → silent degrade or runtime crash. The check below diffs
# the in-process registries (1+2 = BUILTIN_EXECUTORS keys, 3 = whitelist)
# and the DB list, and screams loud at boot.

async def check_block_consistency(java_client: Any) -> None:
    """Compare BUILTIN_EXECUTORS ↔ SIDECAR_NATIVE_BLOCKS ↔ DB pb_blocks.

    Logs each mismatch at ERROR level. Does NOT raise — sidecar should
    still boot so partial drift can be observed and fixed without
    bricking the service.
    """
    try:
        from python_ai_sidecar.pipeline_builder.blocks import BUILTIN_EXECUTORS
        from python_ai_sidecar.executor.real_executor import SIDECAR_NATIVE_BLOCKS
    except Exception as exc:  # noqa: BLE001
        logger.warning("block consistency check skipped — import failed: %s", exc)
        return

    builtin = set(BUILTIN_EXECUTORS.keys())
    native = set(SIDECAR_NATIVE_BLOCKS)

    db_names: set[str] = set()
    try:
        rows = await java_client.list_blocks()
        db_names = {r.get("name") for r in (rows or []) if r.get("name")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("block consistency check: java list_blocks failed (%s) — DB diff skipped", exc)

    builtin_not_native = builtin - native
    builtin_not_db = builtin - db_names if db_names else set()
    native_not_builtin = native - builtin
    db_not_builtin = (db_names - builtin) if db_names else set()

    if builtin_not_native:
        logger.error(
            "BLOCK DRIFT — in BUILTIN_EXECUTORS but not in SIDECAR_NATIVE_BLOCKS: %s "
            "(pipelines using these blocks will fall through to legacy walker → 500). "
            "Fix: add to executor/real_executor.py:SIDECAR_NATIVE_BLOCKS frozenset.",
            sorted(builtin_not_native),
        )
    if builtin_not_db:
        logger.error(
            "BLOCK DRIFT — in BUILTIN_EXECUTORS but missing from pb_blocks DB: %s "
            "(LLM cannot see these blocks in catalog). "
            "Fix: write a Flyway migration + run manually if prod has flyway.enabled=false.",
            sorted(builtin_not_db),
        )
    if native_not_builtin:
        logger.error(
            "BLOCK DRIFT — in SIDECAR_NATIVE_BLOCKS but no executor in BUILTIN_EXECUTORS: %s "
            "(executor module missing or import broken).",
            sorted(native_not_builtin),
        )
    if db_not_builtin:
        # This one is informational — DB may carry deprecated blocks intentionally.
        logger.warning(
            "BLOCK DRIFT (informational) — in pb_blocks DB but no executor: %s "
            "(deprecated rows still in catalog).",
            sorted(db_not_builtin),
        )
    if not (builtin_not_native or builtin_not_db or native_not_builtin):
        logger.info(
            "block consistency OK: %d builtin, %d native, %d in DB",
            len(builtin), len(native), len(db_names),
        )


# ── 2. GraphState ↔ orchestrator.run() kwargs ─────────────────────────
# When a new field is added to AgentOrchestratorV2.run(...) it must also
# appear in graph.py:GraphState (TypedDict), otherwise LangGraph drops
# the key from initial_state and downstream nodes silently see None.
# This is a synchronous module-level invariant — fail fast at import.

# Set by orchestrator.py at import time (one source of truth) and consumed
# by graph.py to assert all keys are declared.
ORCHESTRATOR_RUN_STATE_KEYS: frozenset[str] = frozenset({
    "user_id",
    "session_id",
    "user_message",
    "client_context",
    "canvas_overrides",
    "mode",
    "pipeline_snapshot",
})


def assert_graph_state_covers_run_kwargs(graph_state_keys: Iterable[str]) -> None:
    """Raise if any orchestrator.run() state key is missing from GraphState.

    Called from graph.py module-level so the sidecar fails to import if
    a new run() kwarg is added without GraphState being updated.
    """
    declared = set(graph_state_keys)
    missing = ORCHESTRATOR_RUN_STATE_KEYS - declared
    if missing:
        raise RuntimeError(
            f"GraphState (graph.py) is missing keys passed by orchestrator.run(): "
            f"{sorted(missing)}. LangGraph will silently drop these from "
            f"initial_state, causing nodes to read None. Add them to GraphState."
        )
