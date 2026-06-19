"""Unit tests for schema_doc._truncate_value nested-dict collapse (2026-06-16).

Guards the cost optimization: a process_history row's nested object values
(DC/EC/RECIPE/APC) with deep `parameters` sub-dicts must collapse so the
sample dump stays small, WITHOUT touching scalar columns or the schema table.
Regression target: the old `depth == 0` guard left `DC.parameters` (~30
sensors at depth 1) fully expanded.
"""
from __future__ import annotations

from python_ai_sidecar.pipeline_builder.schema_doc import _truncate_value


def _big_params(n: int) -> dict:
    return {f"sensor_{i}": {"value": i * 1.1, "nominal": i, "status": "NORMAL"}
            for i in range(n)}


def test_deep_parameters_subdict_collapses():
    """DC has only 3 top-level keys (so depth-0 guard wouldn't fire) but its
    nested `parameters` has 30 sensors — that sub-dict MUST collapse now."""
    dc = {"chamberID": "CH-2", "objectID": "DC-1", "parameters": _big_params(30)}
    out = _truncate_value(dc)
    # DC itself (3 keys) stays expanded → scalar keys visible
    assert out["chamberID"] == "CH-2"
    assert out["objectID"] == "DC-1"
    # but the 30-sensor parameters sub-dict is collapsed to a key summary
    assert isinstance(out["parameters"], str)
    assert out["parameters"].startswith("<dict 30 keys:")
    # no raw sensor reading leaked
    assert "NORMAL" not in str(out["parameters"])


def test_small_dict_stays_expanded():
    """spc_summary-like small dicts (<= 5 keys) must NOT collapse."""
    small = {"ooc_count": 3, "last_ooc": "STEP_020", "total": 10}
    out = _truncate_value(small)
    assert out == small  # untouched


def test_top_level_large_dict_still_collapses():
    """The original depth-0 behaviour is preserved for wide top-level dicts."""
    wide = {f"k{i}": i for i in range(8)}
    out = _truncate_value(wide)
    assert isinstance(out, str) and out.startswith("<dict 8 keys:")


def test_scalars_untouched():
    for v in ("EQP-01", "OOC", 12.3, True, None):
        assert _truncate_value(v) == v


def test_list_of_chart_dicts_shrinks():
    """spc_charts: list of ~12 chart dicts (each 6 keys) — list caps to 2 + the
    inner 6-key dicts collapse, so the explosion is bounded."""
    charts = [{"name": f"c{i}", "value": i, "ucl": 1, "lcl": 0,
               "is_ooc": False, "status": "PASS"} for i in range(12)]
    out = _truncate_value(charts)
    assert isinstance(out, list)
    assert any(isinstance(x, str) and "more" in x for x in out)  # tail marker
    # the kept chart dicts (6 keys > 5) collapse to summary
    assert any(isinstance(x, str) and x.startswith("<dict 6 keys:") for x in out)
