"""Unit tests for C2 ENABLE_STRICT_PHASE_OUTPUT — the finalize_node strict
plan-deliverable check + its flag round-trip.

The decision logic lives in `finalize._missing_deliverable_reason` (a pure
helper); the matcher it calls (`_terminal_block_matches_expected`) is covered
by test_auto_verifier_trigger.py, so here we focus on the deliverable gate:
which (plan, canvas) shapes flip a finished build to failed_missing_output.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# --- shared fixtures: mirror test_auto_verifier_trigger's minimal shapes -----

def _make_pipeline(node_ids_with_blocks, edges=None):
    nodes = [
        SimpleNamespace(id=nid, block_id=bid, block_version="1.0.0")
        for nid, bid in node_ids_with_blocks
    ]
    edges_list = []
    for fr, to in edges or []:
        edges_list.append(SimpleNamespace(
            from_=SimpleNamespace(node=fr, port="data"),
            to=SimpleNamespace(node=to, port="data"),
        ))
    return SimpleNamespace(nodes=nodes, edges=edges_list)


def _registry_with(block_to_covers: dict[str, list[str]]):
    reg = MagicMock()
    def get_spec(block_id, _ver):
        return {"produces": {"covers_output": block_to_covers.get(block_id, [])}}
    reg.get_spec.side_effect = get_spec
    return reg


# --- (a) chart deliverable satisfied → no failure -----------------------------

def test_chart_deliverable_satisfied_returns_empty():
    from python_ai_sidecar.agent_builder.graph_build.nodes.finalize import (
        _missing_deliverable_reason,
    )
    pipeline = _make_pipeline(
        [("n1", "block_process_history"), ("n2", "block_box_plot")],
        edges=[("n1", "n2")],
    )
    reg = _registry_with({
        "block_process_history": ["raw_data"],
        "block_box_plot": ["chart"],
    })
    phases = [{"id": "p1", "expected": "raw_data"}, {"id": "p2", "expected": "chart"}]
    assert _missing_deliverable_reason(pipeline, phases, reg) == ""


# --- (b) chart deliverable missing (ends in filter) → failure reason ----------

def test_chart_deliverable_missing_returns_reason():
    from python_ai_sidecar.agent_builder.graph_build.nodes.finalize import (
        _missing_deliverable_reason,
    )
    # The SLASH-13 run-2 false-success shape: plan wanted a chart, pipeline ends
    # in block_filter (a transform terminal). No chart block anywhere.
    pipeline = _make_pipeline(
        [("n1", "block_process_history"), ("n2", "block_filter")],
        edges=[("n1", "n2")],
    )
    reg = _registry_with({
        "block_process_history": ["raw_data"],
        "block_filter": ["transform"],
    })
    phases = [{"id": "p1", "expected": "raw_data"}, {"id": "p2", "expected": "chart"}]
    reason = _missing_deliverable_reason(pipeline, phases, reg)
    assert reason
    assert "chart" in reason
    assert "block_filter" in reason  # names the actual terminal so it's diagnosable


# --- (c) non-presentation final kind → never fails ----------------------------

def test_non_presentation_final_kind_returns_empty():
    """A plan whose final deliverable is raw_data legitimately ends on a source/
    transform terminal — must NOT be flagged."""
    from python_ai_sidecar.agent_builder.graph_build.nodes.finalize import (
        _missing_deliverable_reason,
    )
    pipeline = _make_pipeline([("n1", "block_process_history")])
    reg = _registry_with({"block_process_history": ["raw_data"]})
    phases = [{"id": "p1", "expected": "raw_data"}]
    assert _missing_deliverable_reason(pipeline, phases, reg) == ""


# --- intermediate presentation phase feeding a chart → no false-positive ------

def test_table_feeding_chart_not_flagged():
    """table->chart: the table is NON-terminal (feeds the chart). Because we only
    check the LAST phase (chart, satisfied), the build passes — proving we don't
    naively require every presentation phase to be terminal."""
    from python_ai_sidecar.agent_builder.graph_build.nodes.finalize import (
        _missing_deliverable_reason,
    )
    pipeline = _make_pipeline(
        [("n1", "block_select"), ("n2", "block_box_plot")],
        edges=[("n1", "n2")],
    )
    reg = _registry_with({
        "block_select": ["table", "raw_data"],
        "block_box_plot": ["chart"],
    })
    phases = [{"id": "p1", "expected": "table"}, {"id": "p2", "expected": "chart"}]
    assert _missing_deliverable_reason(pipeline, phases, reg) == ""


# --- (d) fail-open: matcher crash must NOT mask the build ----------------------

def test_matcher_crash_fails_open():
    from python_ai_sidecar.agent_builder.graph_build.nodes.finalize import (
        _missing_deliverable_reason,
    )
    reg = MagicMock()
    reg.get_spec.side_effect = RuntimeError("registry exploded")
    pipeline = _make_pipeline([("n1", "block_filter")])
    phases = [{"id": "p1", "expected": "chart"}]
    # _terminal_block_matches_expected swallows internally and returns False, so
    # the reason fires; but if the whole call raised, the helper's own guard must
    # return "". Either way: never raise.
    out = _missing_deliverable_reason(pipeline, phases, reg)
    assert isinstance(out, str)


def test_empty_phases_returns_empty():
    from python_ai_sidecar.agent_builder.graph_build.nodes.finalize import (
        _missing_deliverable_reason,
    )
    pipeline = _make_pipeline([("n1", "block_box_plot")])
    reg = _registry_with({"block_box_plot": ["chart"]})
    assert _missing_deliverable_reason(pipeline, [], reg) == ""


# --- flag round-trip ----------------------------------------------------------

def test_strict_phase_output_flag_round_trip(monkeypatch):
    """C2 (2026-06-12): strict plan-deliverable gate flag."""
    from python_ai_sidecar.feature_flags import parse_feature_flags_header
    assert parse_feature_flags_header("strict_phase_output:on") == {
        "strict_phase_output": True
    }

    monkeypatch.setenv("ENABLE_STRICT_PHASE_OUTPUT", "0")
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)
    assert ff.is_strict_phase_output_enabled() is False

    tok = ff.set_request_overrides({"strict_phase_output": True})
    try:
        assert ff.is_strict_phase_output_enabled() is True
    finally:
        ff.reset_request_overrides(tok)
    assert ff.is_strict_phase_output_enabled() is False
