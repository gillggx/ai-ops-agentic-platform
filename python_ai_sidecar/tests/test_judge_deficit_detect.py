"""v30.17j — deterministic deficit detector for the judge-pause user
interaction. Triggers ONLY when value_desc has a clear count quantifier
AND actual rows are below the threshold but > 0.

EQP-01 motivating case: user "最近 100 筆 xbar 趨勢", simulator returned 7.
"""
from __future__ import annotations

from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import (
    _detect_deficit,
    DEFICIT_AUTO_ABOVE,
)


# ── Positive (should detect deficit + ask user) ─────────────────────


def test_eqp01_100_筆_7_rows_detects():
    """The motivating case — 7/100 = 7%, well below 80%."""
    d = _detect_deficit("該機台該站點最近 100 筆 xbar 圖表的記錄", 7)
    assert d is not None
    assert d["requested_n"] == 100
    assert d["actual_rows"] == 7
    assert d["ratio"] == 0.07


def test_50_張_20_rows_detects():
    d = _detect_deficit("最近 50 張 SPC 圖表", 20)
    assert d is not None
    assert d["requested_n"] == 50
    assert d["actual_rows"] == 20
    assert d["ratio"] == 0.4


def test_english_records_keyword():
    d = _detect_deficit("100 records of process events", 30)
    assert d is not None
    assert d["requested_n"] == 100


def test_english_rows_keyword():
    d = _detect_deficit("the last 200 rows", 45)
    assert d is not None
    assert d["requested_n"] == 200


def test_50_個_at_threshold_minus_one_detects():
    """ratio = 39/50 = 0.78 (just below 0.8 threshold) → should detect."""
    d = _detect_deficit("最近 50 個 OOC 事件", 39)
    assert d is not None
    assert d["ratio"] < DEFICIT_AUTO_ABOVE


# ── Negative (must NOT detect — silently accept or N/A) ────────────


def test_rows_meets_target_no_detect():
    assert _detect_deficit("最近 100 筆", 100) is None
    assert _detect_deficit("最近 100 筆", 150) is None  # excess


def test_rows_at_or_above_80pct_no_detect():
    """ratio = 80/100 = 0.8 — auto-accept, don't bug user."""
    assert _detect_deficit("最近 100 筆", 80) is None
    assert _detect_deficit("最近 100 筆", 95) is None


def test_zero_rows_no_detect():
    """Zero is a separate case (filter bug?); spec defers to a later patch."""
    assert _detect_deficit("最近 100 筆", 0) is None


def test_no_quantifier_no_detect():
    """value_desc without a count quantifier → not a count-target."""
    assert _detect_deficit("最後一次 OOC 事件", 5) is None
    assert _detect_deficit("所有 OOC 圖表的清單", 3) is None
    assert _detect_deficit("(unspecified)", 7) is None
    assert _detect_deficit("", 7) is None
    assert _detect_deficit(None, 7) is None


def test_single_digit_doesnt_trigger():
    """'5 筆' is 1 digit — too easy to false-positive on small numbers
    in unrelated text. Only 2+ digit counts qualify."""
    assert _detect_deficit("第 5 筆 之後的記錄", 2) is None


def test_unrelated_number_no_match():
    """Numbers without count units shouldn't trigger."""
    assert _detect_deficit("EQP-01 STEP_001 measurements", 7) is None
    assert _detect_deficit("100 度的溫度", 7) is None  # 度 not a quantifier


def test_multiple_numbers_picks_first_count():
    """If value_desc has '100 筆 中 50 是 OOC', match first count quantifier."""
    d = _detect_deficit("100 筆中 50 是 OOC", 30)
    assert d is not None
    assert d["requested_n"] == 100  # first match


def test_rows_none_no_detect():
    assert _detect_deficit("最近 100 筆", None) is None


def test_rows_negative_no_detect():
    """Defensive — shouldn't see this but don't crash."""
    assert _detect_deficit("最近 100 筆", -1) is None


# ── Boundary at exactly DEFICIT_AUTO_ABOVE ─────────────────────────


def test_exactly_at_threshold_no_detect():
    """ratio == 0.8 EXACTLY (e.g. 80/100) → silent accept."""
    d = _detect_deficit("最近 100 筆", 80)
    assert d is None  # >= threshold means silent accept


def test_just_below_threshold_detects():
    """ratio == 0.79 (e.g. 79/100) → ask user."""
    d = _detect_deficit("最近 100 筆", 79)
    assert d is not None
    assert d["ratio"] == 0.79
