"""Heuristic: when the caller didn't pass event_filter and time_range
spans 24h+, _ParamPanelBase should default to 'all' (trend mode) so the
chart comes out as a line, not the bar fallback that single-timestamp
modes produce.

Regression context: builder trace 20260528-004149 — user asked for
"EQP-01 過去 7 天 STEP_001/002/003 的 xbar 趨勢", the LLM picked
block_spc_panel without event_filter, default 'latest_ooc' collapsed
each panel to one timestamp, and chart rendered as bar.
"""

from __future__ import annotations

import pytest

from python_ai_sidecar.pipeline_builder.blocks._param_panel_base import (
    _time_range_hours,
)


def test_time_range_hours_units():
    assert _time_range_hours("1h") == 1.0
    assert _time_range_hours("24h") == 24.0
    assert _time_range_hours("1d") == 24.0
    assert _time_range_hours("7d") == 168.0
    assert _time_range_hours("30d") == 720.0


def test_time_range_hours_tolerant_whitespace_and_case():
    assert _time_range_hours(" 7D ") == 168.0
    assert _time_range_hours("12H") == 12.0


def test_time_range_hours_unknown_returns_zero():
    """Returns 0 — caller treats that as 'short window, keep default'."""
    assert _time_range_hours(None) == 0.0
    assert _time_range_hours("") == 0.0
    assert _time_range_hours("garbage") == 0.0
    assert _time_range_hours(42) == 0.0


@pytest.mark.parametrize("tr,expected_to_trigger", [
    ("24h", True),
    ("48h", True),
    ("7d", True),
    ("1d", True),
    ("23h", False),
    ("1h", False),
    ("", False),
    (None, False),
])
def test_heuristic_threshold_at_24h(tr, expected_to_trigger):
    """The 24h cutoff is the contract — flipping mode below it would
    break the latest_ooc inspection use case for short windows."""
    triggered = _time_range_hours(tr) >= 24
    assert triggered is expected_to_trigger
