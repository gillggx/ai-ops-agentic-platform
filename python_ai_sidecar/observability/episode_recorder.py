"""EpisodeRecorder — agent behavioural event side-channel (V69).

Spec: docs/MULTI_AGENT_OBSERVABILITY_SPEC.md §4.3.

Design constraints (all hard):
- FAIL-OPEN: Java/PG being down must never affect a build. Every network hop
  is wrapped; after the first failure the recorder goes dead-silent (one log
  line) and keeps swallowing events for the rest of the build.
- SIDE-CHANNEL: no prompt / cache-prefix impact; events are emitted by
  deterministic graph code, never by the LLM.
- CHEAP: record() is a sync in-memory append; network happens only on
  flush() at phase boundaries / finalize, batched.

Two ContextVars mirror BuildTracer's pattern:
- _current_recorder: the per-build recorder (None = flag off / not a build)
- _current_agent:    which RoleAgent is running (set by graph delegates) so
  cross-cutting hooks (llm_usage in llm_client) can attribute cost.
"""
from __future__ import annotations

import contextvars
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_current_recorder: contextvars.ContextVar[Optional["EpisodeRecorder"]] = (
    contextvars.ContextVar("episode_recorder", default=None)
)
_current_agent: contextvars.ContextVar[str] = contextvars.ContextVar(
    "episode_agent", default="system"
)

FLUSH_BATCH_SIZE = 25


def get_current_recorder() -> Optional["EpisodeRecorder"]:
    return _current_recorder.get()


def set_current_recorder(rec: Optional["EpisodeRecorder"]) -> None:
    _current_recorder.set(rec)


def get_current_agent() -> str:
    return _current_agent.get()


def set_current_agent(agent: str) -> contextvars.Token:
    return _current_agent.set(agent)


def reset_current_agent(token: contextvars.Token) -> None:
    _current_agent.reset(token)


def make_recorder(
    *, session_id: str, instruction: str, user_id: Optional[int]
) -> Optional["EpisodeRecorder"]:
    """Factory — returns None when the flag is off (all call sites no-op)."""
    from python_ai_sidecar.feature_flags import is_agent_episodes_enabled

    if not is_agent_episodes_enabled():
        return None
    return EpisodeRecorder(session_id=session_id, instruction=instruction, user_id=user_id)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EpisodeRecorder:
    def __init__(self, *, session_id: str, instruction: str, user_id: Optional[int]):
        self.episode_key = session_id
        self._instruction = instruction
        self._user_id = user_id
        self._buffer: list[dict[str, Any]] = []
        self._created = False
        self._dead = False          # first network failure → silent for the build
        self._finalized = False
        # per-agent cost rollup, aggregated locally so finalize can write
        # cost_json even if some step batches were lost.
        self._cost: dict[str, dict[str, int]] = {}
        # per-phase verifier rejects — consumed at phase_done to emit the
        # param_reject_fix approximation (spec §4.2; C4).
        self._phase_rejects: dict[str, list[dict[str, Any]]] = {}

    # ── per-phase reject tracking (graph wrappers call these) ──────────
    def note_verifier_reject(self, phase_id: str, payload: dict[str, Any]) -> None:
        self._phase_rejects.setdefault(phase_id, []).append(payload)

    def take_phase_rejects(self, phase_id: str) -> list[dict[str, Any]]:
        return self._phase_rejects.pop(phase_id, [])

    # ── sync, hot-path safe ────────────────────────────────────────────
    def record(
        self,
        event_type: str,
        *,
        agent: Optional[str] = None,
        phase_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cache_read: Optional[int] = None,
        latency_ms: Optional[int] = None,
    ) -> None:
        """Append one behavioural event (in-memory; no I/O)."""
        who = agent or get_current_agent()
        self._buffer.append({
            "agent": who,
            "phase_id": phase_id,
            "event_type": event_type,
            "payload": payload,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read": cache_read,
            "latency_ms": latency_ms,
            "ts": _now_iso(),
        })
        if event_type == "llm_usage":
            c = self._cost.setdefault(who, {"input": 0, "output": 0, "cache_read": 0, "calls": 0})
            c["input"] += input_tokens or 0
            c["output"] += output_tokens or 0
            c["cache_read"] += cache_read or 0
            c["calls"] += 1

    def pending(self) -> int:
        return len(self._buffer)

    def cost_rollup(self) -> dict[str, dict[str, int]]:
        return self._cost

    # ── async, batched network (fail-open) ─────────────────────────────
    async def maybe_flush(self) -> None:
        """Flush when the buffer is big enough — call at phase boundaries."""
        if len(self._buffer) >= FLUSH_BATCH_SIZE:
            await self.flush()

    async def flush(self) -> None:
        if self._dead or not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        try:
            await self._ensure_created()
            await self._post(f"/internal/agent-episodes/{self.episode_key}/steps",
                             {"steps": batch})
        except Exception as ex:  # noqa: BLE001 — fail-open by design
            self._dead = True
            logger.warning(
                "EpisodeRecorder: flush failed (%s) — recording disabled for "
                "episode %s (%d events dropped)", ex, self.episode_key, len(batch))

    async def finalize(
        self,
        *,
        status: str,
        self_assessment: Optional[dict[str, Any]] = None,
        plan_json: Optional[Any] = None,
        trace_file: Optional[str] = None,
    ) -> None:
        if self._finalized:
            return
        self._finalized = True
        await self.flush()
        if self._dead:
            return
        try:
            await self._post(f"/internal/agent-episodes/{self.episode_key}/finalize", {
                "status": status,
                "self_assessment": self_assessment,
                "plan_json": plan_json,
                "cost_json": self._cost,
                # tracer hands us a PosixPath — coerce, or json serialization dies
                "trace_file": str(trace_file) if trace_file is not None else None,
                "finished_at": _now_iso(),
            })
        except Exception as ex:  # noqa: BLE001
            self._dead = True
            logger.warning("EpisodeRecorder: finalize failed (%s) for %s",
                           ex, self.episode_key)

    # ── plumbing ────────────────────────────────────────────────────────
    async def _ensure_created(self) -> None:
        if self._created:
            return
        await self._post("/internal/agent-episodes", {
            "episode_key": self.episode_key,
            "user_id": self._user_id,
            "instruction": self._instruction,
            "started_at": _now_iso(),
        })
        self._created = True

    async def _post(self, path: str, body: dict[str, Any]) -> None:
        import httpx

        from python_ai_sidecar.config import CONFIG

        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{CONFIG.java_api_url}{path}",
                json=body,
                headers={"X-Internal-Token": CONFIG.java_internal_token},
            )
            resp.raise_for_status()
