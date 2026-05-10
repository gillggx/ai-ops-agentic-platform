"""BuildTracer — opt-in observability for graph_build runs.

Why: previously when a build went wrong (LLM mis-shapes a param, repair
fails to converge, validate misses a wiring bug) we had to read sidecar
journalctl + DB to reconstruct what happened. trace.py captures the
actual LLM exchanges + per-graph-node deltas to a single JSON file per
build, plus optional SSE debug events for live UI inspection.

Enable by setting `BUILDER_TRACE_DIR=/tmp/builder-traces` (or any
writable dir) on the sidecar process. When unset, all tracer methods
are cheap no-ops — zero perf impact in prod.

Per CLAUDE.md「flow 由 graph 決定」this is purely observational —
nothing the tracer records affects the graph's routing or LLM output.

File schema (one .json per build):
{
  "build_id":      "hex8",
  "session_id":    "...",
  "started_at":    "iso",
  "instruction":   "user 講的話",
  "skip_confirm":  bool,
  "skill_step_mode": bool,
  "declared_inputs": [...],         # base_pipeline.inputs at build start
  "graph_steps":   [{node, status, duration_ms, **fields}, ...],
  "llm_calls":     [{node, system_chars, user_msg, raw_response, parsed?}, ...],
  "final_pipeline":{...},           # the final state.final_pipeline
  "status":        "success | failed | interrupted",
  "duration_ms":   int,
  "finished_at":   "iso"
}
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger(__name__)


_TRACE_DIR_ENV = "BUILDER_TRACE_DIR"
_DEBUG_SSE_ENV = "BUILDER_TRACE_SSE"   # set to "1" to also emit debug_trace SSE events

# Ambient tracer for the current build (set by stream_graph_build wrapper,
# read by node helpers). Avoids passing tracer through every node signature.
_current_tracer: contextvars.ContextVar[Optional["BuildTracer"]] = contextvars.ContextVar(
    "_current_build_tracer", default=None,
)


def _trace_dir() -> Optional[Path]:
    raw = os.environ.get(_TRACE_DIR_ENV)
    if not raw:
        return None
    p = Path(raw)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as ex:  # noqa: BLE001
        logger.warning("BuildTracer: cannot create trace dir %s: %s", p, ex)
        return None
    return p


def _sse_debug_enabled() -> bool:
    return os.environ.get(_DEBUG_SSE_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def get_current_tracer() -> Optional["BuildTracer"]:
    """Return the tracer for the in-flight build, or None when tracing
    is disabled or no build is currently active."""
    return _current_tracer.get()


class BuildTracer:
    """Per-build trace recorder. Use as an async context manager.

    Methods are tolerant of None values and never raise — broken tracing
    must not break the graph.
    """

    def __init__(
        self,
        *,
        instruction: str,
        session_id: str,
        skip_confirm: bool,
        skill_step_mode: bool,
        declared_inputs: list[Any],
        trace_dir: Path,
    ):
        self.build_id = uuid.uuid4().hex[:12]
        self.session_id = session_id
        self.started_at = datetime.now(tz=timezone.utc)
        self._t0 = time.perf_counter()
        self._dir = trace_dir
        self._path = trace_dir / f"{self.started_at.strftime('%Y%m%d-%H%M%S')}-{self.build_id}.json"
        self._payload: dict[str, Any] = {
            "build_id": self.build_id,
            "session_id": session_id,
            "started_at": self.started_at.isoformat(),
            "instruction": instruction,
            "skip_confirm": skip_confirm,
            "skill_step_mode": skill_step_mode,
            "declared_inputs": _safe_jsonable(declared_inputs),
            "graph_steps": [],
            "llm_calls": [],
            "final_pipeline": None,
            "status": None,
            "duration_ms": None,
            "finished_at": None,
        }
        # Step-timer for record_step's auto-duration (when caller doesn't pass one)
        self._step_starts: dict[str, float] = {}
        self._token = None

    @property
    def path(self) -> Path:
        return self._path

    async def __aenter__(self) -> "BuildTracer":
        self._token = _current_tracer.set(self)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            self._payload["status"] = self._payload.get("status") or (
                "failed" if exc_type else "finished"
            )
            self._payload["duration_ms"] = int((time.perf_counter() - self._t0) * 1000)
            self._payload["finished_at"] = datetime.now(tz=timezone.utc).isoformat()
            self._flush()
        finally:
            if self._token is not None:
                _current_tracer.reset(self._token)

    # ── Recording API ──────────────────────────────────────────────────

    def record_step(
        self,
        node: str,
        *,
        duration_ms: Optional[int] = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Append one graph step. Returns the dict so caller can attach to
        SSE event for live debug. Use begin_step/end_step for auto-duration.
        """
        entry: dict[str, Any] = {
            "node": node,
            "ts": _iso_now(),
        }
        if duration_ms is not None:
            entry["duration_ms"] = duration_ms
        for k, v in fields.items():
            entry[k] = _safe_jsonable(v)
        self._payload["graph_steps"].append(entry)
        return entry

    def begin_step(self, node: str) -> None:
        self._step_starts[node] = time.perf_counter()

    def end_step(self, node: str, **fields: Any) -> dict[str, Any]:
        t0 = self._step_starts.pop(node, None)
        ms = int((time.perf_counter() - t0) * 1000) if t0 is not None else None
        return self.record_step(node, duration_ms=ms, **fields)

    def record_llm(
        self,
        node: str,
        *,
        system: Optional[str] = None,
        user_msg: Optional[str] = None,
        raw_response: Optional[str] = None,
        parsed: Optional[Any] = None,
        attempt: Optional[int] = None,
        **extra: Any,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "node": node,
            "ts": _iso_now(),
            "system_chars": len(system) if system else 0,
            "user_msg": _truncate(user_msg, 8000),
            "raw_response": _truncate(raw_response, 8000),
        }
        if attempt is not None:
            entry["attempt"] = attempt
        if parsed is not None:
            entry["parsed"] = _safe_jsonable(parsed)
        for k, v in extra.items():
            entry[k] = _safe_jsonable(v)
        self._payload["llm_calls"].append(entry)
        return entry

    def set_final_pipeline(self, pipeline: Any) -> None:
        self._payload["final_pipeline"] = _safe_jsonable(pipeline)

    def set_status(self, status: str) -> None:
        self._payload["status"] = status

    # ── Flush ─────────────────────────────────────────────────────────

    def _flush(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(
                "BuildTracer: wrote trace %s (%d steps, %d llm calls, %dB)",
                self._path.name,
                len(self._payload["graph_steps"]),
                len(self._payload["llm_calls"]),
                self._path.stat().st_size,
            )
        except Exception as ex:  # noqa: BLE001
            logger.warning("BuildTracer: write to %s failed: %s", self._path, ex)


# ── Module-level helpers used by graph nodes ─────────────────────────


def make_tracer(
    *,
    instruction: str,
    session_id: str,
    skip_confirm: bool,
    skill_step_mode: bool,
    base_pipeline: Optional[dict],
) -> Optional[BuildTracer]:
    """Build tracer if BUILDER_TRACE_DIR is set; else None (no-op)."""
    d = _trace_dir()
    if d is None:
        return None
    declared = []
    if isinstance(base_pipeline, dict):
        raw_inputs = base_pipeline.get("inputs") or []
        if isinstance(raw_inputs, list):
            declared = raw_inputs
    return BuildTracer(
        instruction=instruction,
        session_id=session_id,
        skip_confirm=skip_confirm,
        skill_step_mode=skill_step_mode,
        declared_inputs=declared,
        trace_dir=d,
    )


def trace_event_to_sse(entry: dict[str, Any], kind: str) -> Optional[dict[str, Any]]:
    """Convert a recorded step / llm entry into a debug_trace SSE event
    (only when BUILDER_TRACE_SSE=1). Returns event dict or None when
    disabled. Caller appends to state["sse_events"]."""
    if not _sse_debug_enabled():
        return None
    return {
        "event": "debug_trace",
        "data": {"kind": kind, **entry},
    }


# ── Internals ─────────────────────────────────────────────────────────


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _truncate(s: Optional[str], cap: int) -> Optional[str]:
    if s is None:
        return None
    if len(s) <= cap:
        return s
    return s[:cap] + f"…[truncated {len(s) - cap} chars]"


def _safe_jsonable(value: Any) -> Any:
    """Recursively coerce to JSON-safe; fall back to str() for opaque types.
    Caps oversized strings at 8KB inside nested structures."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 8000 else value[:8000] + "…"
    if isinstance(value, dict):
        return {str(k): _safe_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_jsonable(v) for v in value]
    # pydantic models
    if hasattr(value, "model_dump"):
        try:
            return _safe_jsonable(value.model_dump(by_alias=True))
        except Exception:  # noqa: BLE001
            pass
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)[:500]
