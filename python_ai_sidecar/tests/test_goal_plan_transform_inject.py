"""v30.17i — deterministic transform-phase injection.

Triggered when user points at a SINGLE nested item (SPC chart name,
APC/DC/RECIPE param, etc.) but the LLM-emitted plan jumps raw_data →
(chart|scalar|verdict|table) with no transform phase between. Without
the injection, unnest/filter blocks (covers=['transform']) can't land
anywhere → verifier rejects → build stuck.

Real-world case that motivated this (2026-05-17):
  user: "查 EQP-01 STEP_001 最近 100 筆 xbar 趨勢"
  plan: p1[raw_data] → p2[chart]
  → LLM tried block_unnest in p1, p2 — all rejected as covers mismatch
"""
from __future__ import annotations

from python_ai_sidecar.agent_builder.graph_build.nodes.goal_plan import (
    _maybe_inject_transform_phase,
)


# ── Positive: should inject ────────────────────────────────────────


def test_xbar_chart_keyword_injects():
    phases = [
        {"id": "p1", "goal": "fetch", "expected": "raw_data"},
        {"id": "p2", "goal": "plot", "expected": "chart"},
    ]
    n_before = len(phases)
    injected = _maybe_inject_transform_phase(phases, "畫 EQP-01 的 xbar chart 趨勢")
    assert injected is True
    assert len(phases) == n_before + 1
    # Must be inserted RIGHT AFTER raw_data (chronological order matters)
    assert phases[0]["expected"] == "raw_data"
    assert phases[1]["expected"] == "transform"
    assert phases[1]["auto_injected"] is True
    assert phases[2]["expected"] == "chart"


def test_imr_chart_keyword_injects():
    phases = [
        {"id": "p1", "goal": "fetch", "expected": "raw_data"},
        {"id": "p2", "goal": "judge", "expected": "verdict"},
    ]
    assert _maybe_inject_transform_phase(phases, "EQP-08 imr chart 有沒有 OOC")
    assert phases[1]["expected"] == "transform"


def test_apc_param_keyword_injects():
    phases = [
        {"id": "p1", "goal": "fetch", "expected": "raw_data"},
        {"id": "p2", "goal": "count", "expected": "scalar"},
    ]
    assert _maybe_inject_transform_phase(phases, "看 EQP-08 的 etch_time APC 參數有幾次超標")
    assert phases[1]["expected"] == "transform"


def test_table_downstream_also_triggers():
    phases = [
        {"id": "p1", "goal": "fetch", "expected": "raw_data"},
        {"id": "p2", "goal": "list", "expected": "table"},
    ]
    assert _maybe_inject_transform_phase(phases, "列出 xbar 圖表的詳細記錄")
    assert phases[1]["expected"] == "transform"


def test_id_uses_max_plus_one():
    phases = [
        {"id": "p1", "expected": "raw_data"},
        {"id": "p5", "expected": "chart"},
    ]
    assert _maybe_inject_transform_phase(phases, "xbar trend")
    # New transform should get id=p6 even though it's inserted at index 1
    assert phases[1]["id"] == "p6"
    assert phases[1]["expected"] == "transform"


# ── Negative: must NOT inject ──────────────────────────────────────


def test_no_nested_keyword_no_inject():
    phases = [
        {"id": "p1", "goal": "fetch", "expected": "raw_data"},
        {"id": "p2", "goal": "count rows", "expected": "scalar"},
    ]
    assert not _maybe_inject_transform_phase(
        phases, "EQP-01 過去 7 天總共幾筆事件",  # no specific chart/param
    )
    assert len(phases) == 2


def test_existing_transform_no_inject():
    phases = [
        {"id": "p1", "expected": "raw_data"},
        {"id": "p2", "expected": "transform"},  # already there
        {"id": "p3", "expected": "chart"},
    ]
    assert not _maybe_inject_transform_phase(phases, "xbar trend chart")
    assert len(phases) == 3


def test_no_raw_data_no_inject():
    """Without raw_data phase there's no anchor point — skip."""
    phases = [
        {"id": "p1", "expected": "chart"},
    ]
    assert not _maybe_inject_transform_phase(phases, "畫 xbar 趨勢")
    assert len(phases) == 1


def test_no_downstream_phase_no_inject():
    """raw_data alone — no chart/scalar/verdict to feed → skip."""
    phases = [
        {"id": "p1", "expected": "raw_data"},
    ]
    assert not _maybe_inject_transform_phase(phases, "xbar trend")
    assert len(phases) == 1


def test_empty_instruction_no_inject():
    phases = [
        {"id": "p1", "expected": "raw_data"},
        {"id": "p2", "expected": "chart"},
    ]
    assert not _maybe_inject_transform_phase(phases, "")
    assert not _maybe_inject_transform_phase(phases, None)
    assert len(phases) == 2


def test_event_level_keyword_no_inject():
    """User asks only for event-level data (no nested focus) → no transform."""
    phases = [
        {"id": "p1", "expected": "raw_data"},
        {"id": "p2", "expected": "table"},
    ]
    assert not _maybe_inject_transform_phase(
        phases, "列出 EQP-01 今天的所有 process events",
    )
    assert len(phases) == 2
