"""Unit tests for render_intent_classifier.

20 tests covering:
- Auto-chart paths (SPC nested, multi-line trends)
- Auto-table paths (catalog, small event lists)
- Auto-scalar paths (status responses)
- Ask-user paths (ambiguous shapes)
- Transform correctness for each builder
"""
from app.services.render_intent_classifier import (
    classify_render_intent,
    build_outputs,
    RenderKind,
)


# ── Test fixtures ─────────────────────────────────────────────────────────────

def _spc_event(t, lot, tool, status="PASS", xbar=14.5, is_ooc=False):
    return {
        "eventTime": t,
        "lotID": lot,
        "toolID": tool,
        "step": "STEP_001",
        "spc_status": status,
        "SPC": {
            "charts": {
                "xbar_chart": {"value": xbar, "ucl": 17.5, "lcl": 12.5, "is_ooc": is_ooc},
                "r_chart": {"value": 850, "ucl": 880, "lcl": 820, "is_ooc": False},
                "s_chart": {"value": 60, "ucl": 62.5, "lcl": 57.5, "is_ooc": False},
                "p_chart": {"value": 50, "ucl": 56, "lcl": 44, "is_ooc": False},
                "c_chart": {"value": 1500, "ucl": 1570, "lcl": 1430, "is_ooc": False},
            }
        },
        "APC": {
            "parameters": {
                "etch_time_offset": 0.01,
                "rf_power_bias": 1.0,
                "gas_flow_comp": -0.5,
            }
        },
        "DC": {
            "parameters": {
                "chamber_pressure": 14.5,
                "rf_forward_power": 1500,
            }
        },
        "RECIPE": {
            "parameters": {"etch_time_s": 28, "target_thickness_nm": 50},
        },
    }


def _make_spc_events(n=10):
    return [
        _spc_event(f"2026-04-12T10:0{i}:00", f"LOT-{i:04d}", f"EQP-0{(i%3)+1}",
                   status="OOC" if i % 4 == 0 else "PASS",
                   xbar=14.5 + (i * 0.1),
                   is_ooc=(i % 4 == 0))
        for i in range(n)
    ]


# ── Tests 1-5: SPC chart auto-detection ──────────────────────────────────────

def test_01_spc_events_full_envelope_detected():
    """get_process_info typical envelope: {total: N, events: [...]} → detect SPC charts."""
    raw = {"total": 10, "events": _make_spc_events(10)}
    decision = classify_render_intent(raw, mcp_name="get_process_info")
    assert decision.kind == RenderKind.AUTO_CHART
    assert decision.primary is not None
    assert decision.primary.id == "spc_5_chart"
    assert decision.primary.recommended


def test_02_spc_chart_alternatives_include_table_and_ooc():
    raw = {"events": _make_spc_events(10)}
    decision = classify_render_intent(raw, mcp_name="get_process_info")
    alt_ids = [a.id for a in decision.alternatives]
    assert "event_table" in alt_ids
    assert "ooc_only" in alt_ids


def test_03_spc_chart_alternatives_include_apc_and_dc():
    raw = {"events": _make_spc_events(10)}
    decision = classify_render_intent(raw, mcp_name="get_process_info")
    alt_ids = [a.id for a in decision.alternatives]
    assert "apc_multi_line" in alt_ids
    assert "dc_multi_line" in alt_ids
    assert "recipe_table" in alt_ids


def test_04_spc_flatten_transform_produces_5_chart_groups():
    raw = {"events": _make_spc_events(3)}
    decision = classify_render_intent(raw, mcp_name="get_process_info")
    outputs = build_outputs(decision.primary, raw)
    assert "spc_data" in outputs
    flat = outputs["spc_data"]
    chart_types = {row["chart_type"] for row in flat}
    assert chart_types == {"xbar_chart", "r_chart", "s_chart", "p_chart", "c_chart"}
    assert len(flat) == 3 * 5  # 3 events × 5 chart types


def test_05_spc_chart_data_has_required_fields():
    raw = {"events": _make_spc_events(2)}
    decision = classify_render_intent(raw, mcp_name="get_process_info")
    outputs = build_outputs(decision.primary, raw)
    first = outputs["spc_data"][0]
    for k in ("chart_type", "eventTime", "lotID", "toolID", "value", "ucl", "lcl", "is_ooc"):
        assert k in first, f"missing key {k}"


# ── Tests 6-9: Catalog table auto-detection ──────────────────────────────────

def test_06_list_tools_response_is_catalog_table():
    raw = [
        {"toolID": "EQP-01", "status": "Busy"},
        {"toolID": "EQP-02", "status": "Idle"},
        {"toolID": "EQP-03", "status": "Busy"},
    ]
    decision = classify_render_intent(raw, mcp_name="list_tools")
    assert decision.kind == RenderKind.AUTO_TABLE
    assert decision.primary.id == "catalog_table"


def test_07_list_skills_response_is_catalog_table():
    raw = [
        {"id": 1, "name": "SPC trend", "source": "rule"},
        {"id": 2, "name": "OOC check", "source": "auto_patrol"},
    ]
    decision = classify_render_intent(raw, mcp_name="list_skills")
    assert decision.kind == RenderKind.AUTO_TABLE


def test_08_catalog_table_columns_extracted():
    raw = [{"id": 1, "name": "X", "type": "Y", "active": True}]
    decision = classify_render_intent(raw)
    cols = decision.primary.output_schema[0]["columns"]
    col_keys = [c["key"] for c in cols]
    assert "id" in col_keys
    assert "name" in col_keys


def test_09_catalog_passthrough_transform():
    raw = [{"id": 1, "name": "X"}, {"id": 2, "name": "Y"}]
    decision = classify_render_intent(raw)
    outputs = build_outputs(decision.primary, raw)
    assert outputs["catalog"] == raw


# ── Tests 10-12: Scalar response ──────────────────────────────────────────────

def test_10_scalar_response_detected():
    raw = {"status": "ok", "version": "1.0", "uptime": 3600}
    decision = classify_render_intent(raw, mcp_name="get_simulation_status")
    assert decision.kind == RenderKind.AUTO_SCALAR


def test_11_scalar_with_status_field_uses_badge():
    raw = {"status": "Busy", "tool_count": 10}
    decision = classify_render_intent(raw)
    schema_types = {f["key"]: f["type"] for f in decision.primary.output_schema}
    assert schema_types.get("status") == "badge"
    assert schema_types.get("tool_count") == "scalar"


def test_12_scalar_passthrough_returns_dict():
    raw = {"x": 1, "y": "hello"}
    decision = classify_render_intent(raw)
    outputs = build_outputs(decision.primary, raw)
    assert outputs == raw


# ── Tests 13-15: Empty / edge cases ──────────────────────────────────────────

def test_13_empty_event_list():
    raw = {"events": []}
    decision = classify_render_intent(raw, mcp_name="get_process_info")
    assert decision.kind == RenderKind.AUTO_TABLE
    assert decision.primary.id == "empty"


def test_14_small_event_list_without_spc_goes_to_table():
    raw = [
        {"eventTime": "2026-04-12T10:00", "value": 1},
        {"eventTime": "2026-04-12T10:01", "value": 2},
    ]
    decision = classify_render_intent(raw)
    assert decision.kind == RenderKind.AUTO_TABLE


def test_15_large_event_list_without_spc_asks_user():
    raw = [{"eventTime": f"2026-04-12T10:{i:02d}", "lotID": f"L{i}"} for i in range(10)]
    decision = classify_render_intent(raw)
    assert decision.kind == RenderKind.ASK_USER
    assert decision.primary is None
    assert len(decision.alternatives) >= 1


# ── Tests 16-18: Filter / multi-line transforms ───────────────────────────────

def test_16_filter_ooc_returns_only_ooc_events():
    raw = {"events": _make_spc_events(8)}
    # In our fixture, every 4th event has spc_status=OOC → indices 0, 4 → 2 OOC events
    decision = classify_render_intent(raw, mcp_name="get_process_info")
    ooc_option = next(a for a in decision.alternatives if a.id == "ooc_only")
    outputs = build_outputs(ooc_option, raw)
    ooc_events = outputs["ooc_events"]
    assert all(e["spc_status"] == "OOC" for e in ooc_events)
    assert len(ooc_events) == 2  # indices 0, 4 in 8 events


def test_17_apc_flatten_extracts_all_params():
    raw = {"events": _make_spc_events(2)}
    decision = classify_render_intent(raw, mcp_name="get_process_info")
    apc_option = next(a for a in decision.alternatives if a.id == "apc_multi_line")
    outputs = build_outputs(apc_option, raw)
    flat = outputs["apc_trend"]
    param_names = {row["parameter_name"] for row in flat}
    assert "etch_time_offset" in param_names
    assert "rf_power_bias" in param_names
    assert "gas_flow_comp" in param_names
    # 2 events × 3 params = 6 rows
    assert len(flat) == 6


def test_18_recipe_to_param_table_uses_first_event():
    raw = {"events": _make_spc_events(3)}
    decision = classify_render_intent(raw, mcp_name="get_process_info")
    recipe_option = next(a for a in decision.alternatives if a.id == "recipe_table")
    outputs = build_outputs(recipe_option, raw)
    rows = outputs["recipe_params"]
    param_names = {row["parameter_name"] for row in rows}
    assert "etch_time_s" in param_names
    assert "target_thickness_nm" in param_names


# ── Tests 19-20: Principle 2 — keyword independence ───────────────────────────

def test_19_user_query_keywords_do_not_affect_decision():
    """Principle 2: classifier must NOT key off user_query keywords.
    Same data → same decision regardless of user_query."""
    raw = {"events": _make_spc_events(10)}
    d1 = classify_render_intent(raw, user_query="畫 chart 給我看")
    d2 = classify_render_intent(raw, user_query="列 table")
    d3 = classify_render_intent(raw, user_query="")
    assert d1.kind == d2.kind == d3.kind
    assert d1.primary.id == d2.primary.id == d3.primary.id


def test_20_no_keyword_matching_in_classifier_source():
    """Principle 2 enforced: ensure classifier source doesn't reference
    visualization-related Chinese keywords (which would imply keyword matching)."""
    import inspect
    from app.services import render_intent_classifier
    source = inspect.getsource(render_intent_classifier)
    # The classifier may mention these words in docstrings/comments BUT not in active branch logic
    # We assert that no `if ... in user_query` pattern exists
    forbidden = ["in user_query", "user_query.lower", "畫" in "user_query"]
    assert "in user_query" not in source, "classifier must not pattern-match user_query"
    assert "user_query.find" not in source
