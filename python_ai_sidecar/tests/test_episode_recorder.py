"""EpisodeRecorder unit tests (spec §6 Step 2): buffer, fail-open, flag gate,
cost rollup, per-phase reject tracking."""
from __future__ import annotations

import asyncio

import pytest

from python_ai_sidecar.observability.episode_recorder import (
    EpisodeRecorder,
    make_recorder,
)


def _rec() -> EpisodeRecorder:
    return EpisodeRecorder(session_id="s-test", instruction="查 xbar", user_id=1)


def test_flag_off_returns_none(monkeypatch):
    import python_ai_sidecar.feature_flags as ff

    monkeypatch.setattr(ff, "is_agent_episodes_enabled", lambda: False)
    assert make_recorder(session_id="s", instruction="i", user_id=None) is None


def test_flag_on_returns_recorder(monkeypatch):
    import python_ai_sidecar.feature_flags as ff

    monkeypatch.setattr(ff, "is_agent_episodes_enabled", lambda: True)
    rec = make_recorder(session_id="s", instruction="i", user_id=None)
    assert isinstance(rec, EpisodeRecorder)


def test_record_is_pure_buffer_and_attributes_agent():
    rec = _rec()
    rec.record("phase_started", agent="builder", phase_id="p1")
    rec.record("llm_usage", agent="planner", input_tokens=100, output_tokens=10,
               cache_read=50)
    assert rec.pending() == 2
    # cost rollup aggregates llm_usage locally
    assert rec.cost_rollup()["planner"] == {
        "input": 100, "output": 10, "cache_read": 50, "calls": 1}


def test_default_agent_comes_from_contextvar():
    from python_ai_sidecar.observability import reset_current_agent, set_current_agent

    rec = _rec()
    tok = set_current_agent("repair")
    try:
        rec.record("repair_triggered")
    finally:
        reset_current_agent(tok)
    assert rec._buffer[0]["agent"] == "repair"


def test_flush_failopen_goes_dead_and_swallows(monkeypatch):
    rec = _rec()
    rec.record("phase_started", agent="builder", phase_id="p1")

    async def _boom(path, body):
        raise RuntimeError("java down")

    monkeypatch.setattr(rec, "_post", _boom)
    asyncio.run(rec.flush())          # must not raise
    assert rec._dead is True
    assert rec.pending() == 0         # dropped, not retried
    rec.record("phase_done", agent="builder", phase_id="p1")
    asyncio.run(rec.flush())          # dead → silent no-op, still no raise
    asyncio.run(rec.finalize(status="finished"))  # also silent


def test_flush_batches_and_creates_episode_once(monkeypatch):
    rec = _rec()
    calls: list[tuple[str, dict]] = []

    async def _capture(path, body):
        calls.append((path, body))

    monkeypatch.setattr(rec, "_post", _capture)
    rec.record("phase_started", agent="builder", phase_id="p1")
    rec.record("block_picked", agent="builder", phase_id="p1",
               payload={"block": "block_filter"})
    asyncio.run(rec.flush())
    rec.record("phase_done", agent="builder", phase_id="p1")
    asyncio.run(rec.flush())

    paths = [p for p, _ in calls]
    assert paths.count("/internal/agent-episodes") == 1        # created once
    step_batches = [b for p, b in calls if p.endswith("/steps")]
    assert len(step_batches) == 2
    assert len(step_batches[0]["steps"]) == 2
    assert step_batches[0]["steps"][1]["payload"] == {"block": "block_filter"}


def test_finalize_sends_cost_and_assessment(monkeypatch):
    rec = _rec()
    calls: list[tuple[str, dict]] = []

    async def _capture(path, body):
        calls.append((path, body))

    monkeypatch.setattr(rec, "_post", _capture)
    rec.record("llm_usage", agent="builder", input_tokens=10, output_tokens=2)
    asyncio.run(rec.finalize(status="finished",
                             self_assessment={"ok": True},
                             plan_json=[{"id": "p1"}]))
    fin = [b for p, b in calls if p.endswith("/finalize")]
    assert len(fin) == 1
    assert fin[0]["status"] == "finished"
    assert fin[0]["self_assessment"] == {"ok": True}
    assert fin[0]["cost_json"]["builder"]["input"] == 10
    # idempotent — second finalize is a no-op
    asyncio.run(rec.finalize(status="finished"))
    assert len([b for p, b in calls if p.endswith("/finalize")]) == 1


def test_phase_reject_tracking():
    rec = _rec()
    rec.note_verifier_reject("p2", {"block_id": "block_filter", "reason": "param"})
    rec.note_verifier_reject("p2", {"block_id": "block_filter", "reason": "again"})
    assert len(rec.take_phase_rejects("p2")) == 2
    assert rec.take_phase_rejects("p2") == []  # consumed


def test_maybe_flush_threshold(monkeypatch):
    rec = _rec()
    flushed = []

    async def _capture(path, body):
        flushed.append(path)

    monkeypatch.setattr(rec, "_post", _capture)
    for i in range(24):
        rec.record("llm_usage", agent="builder", input_tokens=1)
    asyncio.run(rec.maybe_flush())
    assert flushed == []              # below threshold
    rec.record("llm_usage", agent="builder", input_tokens=1)
    asyncio.run(rec.maybe_flush())
    assert any(p.endswith("/steps") for p in flushed)
