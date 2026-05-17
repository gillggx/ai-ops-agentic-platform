"""v30.17d — _maybe_inject_chart_phase: deterministic chart phase auto-inject.

Trigger: user prompt has chart/圖/趨勢 keywords but LLM-emitted phases
have no expected=chart phase. Append one so agentic_phase_loop can pick
a chart block (block_line_chart / block_spc_panel / etc) instead of
floundering on data_view + step_check.
"""
from __future__ import annotations

import pytest

from python_ai_sidecar.agent_builder.graph_build.nodes.goal_plan import (
    _maybe_inject_chart_phase,
)


# ── Positive cases (should inject) ──────────────────────────────────

def test_english_chart_keyword_injects():
    phases = [
        {"id": "p1", "goal": "fetch", "expected": "raw_data"},
        {"id": "p2", "goal": "filter", "expected": "transform"},
    ]
    n_before = len(phases)
    injected = _maybe_inject_chart_phase(phases, "show me the SPC chart trend")
    assert injected is True
    assert len(phases) == n_before + 1
    new = phases[-1]
    assert new["expected"] == "chart"
    assert new["auto_injected"] is True
    assert new["id"] == "p3"
    assert (new.get("expected_output") or {}).get("kind") == "chart_spec"


def test_chinese_chart_keyword_injects():
    phases = [
        {"id": "p1", "goal": "取資料", "expected": "raw_data"},
        {"id": "p2", "goal": "找 OOC", "expected": "transform"},
        {"id": "p3", "goal": "count", "expected": "scalar"},
    ]
    injected = _maybe_inject_chart_phase(phases, "顯示該 SPC charts 並標示異常")
    assert injected is True
    assert phases[-1]["expected"] == "chart"
    assert phases[-1]["id"] == "p4"


def test_chinese_only_keyword_injects():
    phases = [{"id": "p1", "goal": "x", "expected": "raw_data"}]
    injected = _maybe_inject_chart_phase(phases, "我要看趨勢")
    assert injected is True


def test_trend_keyword_injects():
    phases = [{"id": "p1", "goal": "x", "expected": "transform"}]
    assert _maybe_inject_chart_phase(phases, "plot the trend over time") is True


def test_visualize_keyword_injects():
    phases = [{"id": "p1", "goal": "x", "expected": "raw_data"}]
    assert _maybe_inject_chart_phase(phases, "Visualize the result") is True


def test_id_continuation_skips_existing_max():
    """If phase ids are non-contiguous, use max+1."""
    phases = [
        {"id": "p1", "goal": "x", "expected": "raw_data"},
        {"id": "p5", "goal": "y", "expected": "transform"},
    ]
    assert _maybe_inject_chart_phase(phases, "plot it") is True
    assert phases[-1]["id"] == "p6"


def test_id_continuation_handles_non_numeric():
    """Phase ids that aren't pN: skip them in max calc."""
    phases = [
        {"id": "alarm-phase", "goal": "x", "expected": "alarm"},
        {"id": "p2", "goal": "y", "expected": "transform"},
    ]
    assert _maybe_inject_chart_phase(phases, "show chart") is True
    assert phases[-1]["id"] == "p3"


# ── Negative cases (must NOT inject) ──────────────────────────────

def test_no_chart_keyword_no_inject():
    phases = [{"id": "p1", "goal": "x", "expected": "transform"}]
    assert _maybe_inject_chart_phase(phases, "just count the rows") is False
    assert len(phases) == 1


def test_existing_chart_phase_no_inject():
    phases = [
        {"id": "p1", "goal": "x", "expected": "raw_data"},
        {"id": "p2", "goal": "y", "expected": "chart"},  # already has chart
    ]
    assert _maybe_inject_chart_phase(phases, "show me a chart") is False
    assert len(phases) == 2


def test_empty_instruction_no_inject():
    phases = [{"id": "p1", "goal": "x", "expected": "raw_data"}]
    assert _maybe_inject_chart_phase(phases, "") is False
    assert _maybe_inject_chart_phase(phases, None) is False
    assert len(phases) == 1


def test_empty_phases_with_chart_intent_still_injects():
    """Edge: phases empty + chart intent → still inject (p1)."""
    phases = []
    assert _maybe_inject_chart_phase(phases, "show chart") is True
    assert len(phases) == 1
    assert phases[0]["id"] == "p1"
    assert phases[0]["expected"] == "chart"


def test_view_keyword_does_not_falsely_trigger():
    """'view' / 'show' alone (no chart-specific) — not in keyword list."""
    phases = [{"id": "p1", "goal": "x", "expected": "transform"}]
    # 'view' isn't a chart keyword in our conservative list. 'show' alone
    # isn't either. Only 'show chart'/'show 圖' would.
    assert _maybe_inject_chart_phase(phases, "view the data") is False
    assert _maybe_inject_chart_phase(phases, "看資料") is False


def test_case_insensitive_english():
    phases = [{"id": "p1", "goal": "x", "expected": "transform"}]
    assert _maybe_inject_chart_phase(phases, "PLOT THIS") is True
