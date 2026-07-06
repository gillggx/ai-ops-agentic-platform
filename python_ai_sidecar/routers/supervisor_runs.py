"""Manual-trigger endpoints for the Supervisor offline runs.

POST /internal/supervisor/runs        — start a forensics / curation pass as a
                                        DETACHED asyncio task; returns the
                                        run_id immediately. Single-flight: a
                                        second POST while one is active → 409.
GET  /internal/supervisor/runs/status — running flag + the last finished run's
                                        outcome (ok + the CLI counters line).

The run functions are the exact same code paths the CLIs use
(`tools/supervisor_forensics/run.py`, `tools/supervisor_curate/...`):
`run_forensics(...)` and `run_curation(...)`. java_base / internal token come
from CONFIG (same source every sidecar → Java call uses) — never from the
request body.

Single-flight note: state transitions happen with NO await between check and
set, inside async handlers on the single-threaded event loop — that makes the
check-and-set atomic without a Lock (a module-level asyncio.Lock would bind to
the first event loop it touches, which breaks TestClient re-use).

A run must NEVER crash the sidecar: `_execute_run` wraps everything and
records failures into the status `last` entry (ok=false, summary=error).

Auth: `require_service_token`, same as every /internal/* route.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..auth import CallerContext, ServiceAuth
from ..config import CONFIG
from ..supervisor_curation.proposer import run_curation
from ..supervisor_forensics.forensics import (
    DEFAULT_DAYS,
    DEFAULT_TRACE_DIR,
    MAX_DEEP_DIVES,
    run_forensics,
)

log = logging.getLogger("python_ai_sidecar.supervisor_runs")
router = APIRouter(prefix="/internal/supervisor", tags=["supervisor"])

#: Request-level ceiling on max_deep_dives. run_forensics additionally clamps
#: to its own MAX_DEEP_DIVES hard cap — this just bounds the accepted input.
REQUEST_MAX_DEEP_DIVES = 10


class StartRunRequest(BaseModel):
    kind: Literal["forensics", "curation"]
    days: int = Field(default=DEFAULT_DAYS, ge=1, le=90)
    max_deep_dives: int = Field(default=MAX_DEEP_DIVES, ge=0)


# ── single-flight state (module-level; mutated only on the event loop) ────

_run_state: dict[str, Any] = {
    "running": False,
    "run_id": None,
    "kind": None,
    "started_at": None,
    "progress": None,   # live {stage, scanned, checked, ...} — mutated by the run
    "last": None,
}
#: Strong reference to the detached task — asyncio only keeps weak refs, so
#: without this the run could be garbage-collected mid-flight.
_current_task: Optional[asyncio.Task] = None


def _reset_state_for_tests() -> None:
    """Test hook — restore pristine module state between test cases."""
    global _current_task
    _run_state.update(running=False, run_id=None, kind=None,
                      started_at=None, progress=None, last=None)
    _current_task = None


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ── summary formatting — mirrors the counters line the CLIs print ─────────

def _format_forensics_summary(res: Any) -> str:
    return (
        f"traces={res.traces_scanned} failed={res.failed_traces} "
        f"hotspots={res.hotspots} dropped_single_case={res.dropped_single_case} "
        f"deep_dives={res.deep_dives} proposed={res.proposed} "
        f"deduped={res.deduped} skipped_invalid={res.skipped_invalid} "
        f"skipped_gated={res.skipped_gated} cfg={res.cfg_proposed} "
        f"cfg_deduped={res.cfg_deduped} verified={res.verified} "
        f"model={res.llm_model} tokens={res.input_tokens}/{res.output_tokens}"
    )


def _format_curation_summary(res: Any) -> str:
    return (
        f"proposed={res.proposed} skipped_invalid={res.skipped_invalid} "
        f"deduped={res.deduped} errors={len(res.errors)} "
        f"model={res.llm_model} tokens={res.input_tokens}/{res.output_tokens}"
    )


# ── the detached run task ─────────────────────────────────────────────────

async def _execute_run(run_id: str, kind: str, days: int,
                       max_deep_dives: int) -> None:
    """One supervisor pass. NEVER raises — any failure lands in the status
    `last` entry so a manual run can't take the sidecar down."""
    ok = False
    summary = ""
    try:
        def _on_progress(p: dict) -> None:
            # Detached-task callback runs on the same loop as status reads —
            # a plain dict swap is atomic enough for telemetry.
            _run_state["progress"] = p
        if kind == "forensics":
            res = await run_forensics(
                CONFIG.java_api_url,
                CONFIG.java_internal_token,
                trace_dir=os.environ.get("BUILDER_TRACE_DIR", DEFAULT_TRACE_DIR),
                days=days,
                max_deep_dives=max_deep_dives,
                progress=_on_progress,
            )
            summary = _format_forensics_summary(res)
        else:
            res = await run_curation(
                CONFIG.java_api_url, CONFIG.java_internal_token)
            summary = _format_curation_summary(res)
        ok = not res.errors
        if res.errors:
            summary += " | errors: " + "; ".join(str(e) for e in res.errors[:5])
        log.info("supervisor %s run %s finished ok=%s: %s",
                 kind, run_id, ok, summary)
    except Exception as ex:  # noqa: BLE001 — outermost barrier for the detached task
        ok = False
        summary = f"{type(ex).__name__}: {ex}"
        log.exception("supervisor %s run %s failed", kind, run_id)
    finally:
        _run_state["last"] = {
            "run_id": run_id,
            "kind": kind,
            "started_at": _run_state["started_at"],
            "finished_at": _utcnow_iso(),
            "ok": ok,
            "summary": summary,
        }
        _run_state.update(running=False, run_id=None, kind=None,
                          started_at=None, progress=None)


# ── endpoints ─────────────────────────────────────────────────────────────

@router.post("/runs")
async def start_supervisor_run(
    req: StartRunRequest,
    caller: CallerContext = ServiceAuth,  # noqa: ARG001 — auth gate only
) -> Any:
    """Start one supervisor pass in the background. 409 while one is active."""
    global _current_task
    # No await between this check and the state set — atomic on the loop.
    if _run_state["running"]:
        return JSONResponse(
            status_code=409,
            content={
                "running": True,
                "kind": _run_state["kind"],
                "started_at": _run_state["started_at"],
            },
        )
    run_id = str(uuid.uuid4())
    _run_state.update(running=True, run_id=run_id, kind=req.kind,
                      started_at=_utcnow_iso(), progress=None)
    capped_dives = min(req.max_deep_dives, REQUEST_MAX_DEEP_DIVES)
    _current_task = asyncio.ensure_future(
        _execute_run(run_id, req.kind, req.days, capped_dives))
    log.info("supervisor %s run %s started (days=%d max_deep_dives=%d)",
             req.kind, run_id, req.days, capped_dives)
    return {"run_id": run_id, "started": True}


@router.get("/runs/status")
async def supervisor_run_status(
    caller: CallerContext = ServiceAuth,  # noqa: ARG001 — auth gate only
) -> dict[str, Any]:
    return {
        "running": _run_state["running"],
        "kind": _run_state["kind"],
        "started_at": _run_state["started_at"],
        "progress": _run_state["progress"],
        "last": _run_state["last"],
    }
