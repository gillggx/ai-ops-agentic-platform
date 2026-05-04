"""Glass Box's set_param now rejects column references that don't exist
in the upstream node's output schema. Pins the most common chain
(groupby_agg → sort) plus the pass-through and dynamic-output cases.
Background: production caught Glass Box writing `sort.column='count'` when
the upstream `block_groupby_agg(agg_column='spc_status', agg_func='count')`
actually emits `spc_status_count`. Auto-run failed downstream. Now the
write is rejected at set_param time with the real column list.
"""

from __future__ import annotations

import pytest

from python_ai_sidecar.agent_builder.session import AgentBuilderSession
from python_ai_sidecar.agent_builder.tools import (
    BuilderToolset, ToolError, _expected_upstream_columns,
)
from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry
from python_ai_sidecar.pipeline_builder.pipeline_schema import (
    PipelineNode, PipelineEdge, EdgeEndpoint, NodePosition,
)


def _make_registry() -> BlockRegistry:
    """Stub registry with the blocks exercised by these tests."""
    reg = BlockRegistry()
    reg._catalog[("block_process_history", "1.0.0")] = {
        "name": "block_process_history",
        "version": "1.0.0",
        "category": "source",
        "status": "production",
        "input_schema": [],
        "output_schema": [{"port": "data", "type": "dataframe"}],
        "param_schema": {
            "type": "object",
            "properties": {
                "tool_id":     {"type": "string"},
                "object_name": {"type": "string"},
            },
            "required": [],
        },
        "output_columns_hint": [
            {"name": "eventTime", "type": "datetime"},
            {"name": "lotID",     "type": "string"},
            {"name": "toolID",    "type": "string"},
            {"name": "step",      "type": "string"},
            {"name": "spc_status","type": "string"},
        ],
    }
    reg._catalog[("block_filter", "1.0.0")] = {
        "name": "block_filter",
        "version": "1.0.0",
        "category": "transform",
        "status": "production",
        "input_schema":  [{"port": "data", "type": "dataframe"}],
        "output_schema": [{"port": "data", "type": "dataframe"}],
        "param_schema": {
            "type": "object",
            "properties": {
                "column":   {"type": "string"},
                "operator": {"type": "string"},
                "value":    {"type": "string"},
            },
            "required": [],
        },
    }
    reg._catalog[("block_groupby_agg", "1.0.0")] = {
        "name": "block_groupby_agg",
        "version": "1.0.0",
        "category": "transform",
        "status": "production",
        "input_schema":  [{"port": "data", "type": "dataframe"}],
        "output_schema": [{"port": "data", "type": "dataframe"}],
        "param_schema": {
            "type": "object",
            "properties": {
                "group_by":   {"type": "string"},
                "agg_column": {"type": "string"},
                "agg_func":   {"type": "string"},
            },
            "required": [],
        },
    }
    reg._catalog[("block_sort", "1.0.0")] = {
        "name": "block_sort",
        "version": "1.0.0",
        "category": "transform",
        "status": "production",
        "input_schema":  [{"port": "data", "type": "dataframe"}],
        "output_schema": [{"port": "data", "type": "dataframe"}],
        "param_schema": {
            "type": "object",
            "properties": {
                "column":  {"type": "string"},
                "columns": {"type": "array"},
            },
            "required": [],
        },
    }
    return reg


def _toolset_with(*nodes_and_edges) -> BuilderToolset:
    sess = AgentBuilderSession.new(user_prompt="t")
    for item in nodes_and_edges:
        if isinstance(item, PipelineNode):
            sess.pipeline_json.nodes.append(item)
        elif isinstance(item, PipelineEdge):
            sess.pipeline_json.edges.append(item)
    return BuilderToolset(sess, _make_registry())


def _node(node_id: str, block_id: str, params: dict) -> PipelineNode:
    return PipelineNode(
        id=node_id, block_id=block_id, block_version="1.0.0",
        position=NodePosition(x=0, y=0), params=params,
    )


def _edge(eid: str, src: str, dst: str) -> PipelineEdge:
    return PipelineEdge(
        id=eid,
        from_=EdgeEndpoint(node=src, port="data"),
        to=EdgeEndpoint(node=dst, port="data"),
    )


# ── _expected_upstream_columns ─────────────────────────────────────────


def test_groupby_agg_dynamic_output_columns():
    """The exact failure mode from production: agg_column=spc_status,
    agg_func=count → must report 'spc_status_count', NOT 'count'."""
    ts = _toolset_with(
        _node("n1", "block_process_history", {"tool_id": "EQP-07"}),
        _node("n2", "block_groupby_agg", {
            "group_by": "step",
            "agg_column": "spc_status",
            "agg_func": "count",
        }),
        _node("n3", "block_sort", {}),
        _edge("e1", "n1", "n2"),
        _edge("e2", "n2", "n3"),
    )
    cols = _expected_upstream_columns(
        ts.session.pipeline_json,
        ts.session.pipeline_json.nodes[2],   # n3 (sort)
        ts.registry,
    )
    assert cols == ["step", "spc_status_count"]
    assert "count" not in cols


def test_filter_passes_through_upstream_columns():
    ts = _toolset_with(
        _node("n1", "block_process_history", {}),
        _node("n2", "block_filter", {"column": "spc_status", "operator": "==", "value": "OOC"}),
        _node("n3", "block_sort", {}),
        _edge("e1", "n1", "n2"),
        _edge("e2", "n2", "n3"),
    )
    cols = _expected_upstream_columns(
        ts.session.pipeline_json,
        ts.session.pipeline_json.nodes[2],
        ts.registry,
    )
    # Sort sees process_history's columns through filter (pass-through)
    assert cols is not None
    assert "spc_status" in cols
    assert "step" in cols


def test_unknown_upstream_returns_none():
    """No edge → unknown upstream → returns None so caller skips check."""
    ts = _toolset_with(
        _node("n1", "block_sort", {}),
    )
    cols = _expected_upstream_columns(
        ts.session.pipeline_json,
        ts.session.pipeline_json.nodes[0],
        ts.registry,
    )
    assert cols is None


# ── set_param column ref ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_param_rejects_count_when_upstream_groupby_agg():
    """The bug we shipped to fix: sort.column='count' on a groupby_agg
    upstream produces COLUMN_NOT_IN_UPSTREAM with the actual column listed."""
    ts = _toolset_with(
        _node("n1", "block_process_history", {"tool_id": "EQP-07"}),
        _node("n2", "block_groupby_agg", {
            "group_by": "step",
            "agg_column": "spc_status",
            "agg_func": "count",
        }),
        _node("n3", "block_sort", {}),
        _edge("e1", "n1", "n2"),
        _edge("e2", "n2", "n3"),
    )
    with pytest.raises(ToolError) as exc:
        await ts.set_param(node_id="n3", key="column", value="count")
    assert exc.value.code == "COLUMN_NOT_IN_UPSTREAM"
    assert "spc_status_count" in exc.value.message
    # Hint guides user to run_preview if they want the canonical name list
    assert "run_preview" in (exc.value.hint or "") or "<agg_column>_<agg_func>" in (exc.value.hint or "")


@pytest.mark.asyncio
async def test_set_param_accepts_correct_aggregated_column():
    ts = _toolset_with(
        _node("n1", "block_process_history", {}),
        _node("n2", "block_groupby_agg", {
            "group_by": "step",
            "agg_column": "spc_status",
            "agg_func": "count",
        }),
        _node("n3", "block_sort", {}),
        _edge("e1", "n1", "n2"),
        _edge("e2", "n2", "n3"),
    )
    result = await ts.set_param(node_id="n3", key="column", value="spc_status_count")
    assert result["params"]["column"] == "spc_status_count"


@pytest.mark.asyncio
async def test_set_param_accepts_groupby_column_too():
    """Sort by group_by key is also legal."""
    ts = _toolset_with(
        _node("n1", "block_process_history", {}),
        _node("n2", "block_groupby_agg", {
            "group_by": "step",
            "agg_column": "spc_status",
            "agg_func": "count",
        }),
        _node("n3", "block_sort", {}),
        _edge("e1", "n1", "n2"),
        _edge("e2", "n2", "n3"),
    )
    result = await ts.set_param(node_id="n3", key="column", value="step")
    assert result["params"]["column"] == "step"


@pytest.mark.asyncio
async def test_set_param_columns_list_each_element_checked():
    """block_data_view-style columns=[...] — each element must be valid."""
    ts = _toolset_with(
        _node("n1", "block_process_history", {}),
        _node("n2", "block_groupby_agg", {
            "group_by": "step",
            "agg_column": "spc_status",
            "agg_func": "count",
        }),
        _node("n3", "block_sort", {}),
        _edge("e1", "n1", "n2"),
        _edge("e2", "n2", "n3"),
    )
    with pytest.raises(ToolError) as exc:
        # block_sort.columns is the array form
        await ts.set_param(
            node_id="n3", key="columns",
            value=[{"column": "spc_status_count", "order": "desc"},
                   {"column": "bogus_col", "order": "asc"}],
        )
    assert exc.value.code == "COLUMN_NOT_IN_UPSTREAM"
    assert "bogus_col" in exc.value.message


@pytest.mark.asyncio
async def test_set_param_skips_check_when_no_upstream():
    """No edge connecting yet (LLM still wiring) — set_param accepts;
    runtime executor catches if it never gets connected."""
    ts = _toolset_with(_node("n1", "block_sort", {}))
    result = await ts.set_param(node_id="n1", key="column", value="anything")
    assert result["params"]["column"] == "anything"


@pytest.mark.asyncio
async def test_set_param_skips_check_for_placeholder_value():
    """`$tool_id` etc. handled by the placeholder check, not column-ref."""
    ts = _toolset_with(
        _node("n1", "block_process_history", {}),
        _node("n2", "block_filter", {}),
        _edge("e1", "n1", "n2"),
    )
    # placeholder check would fire (no input declared) — but we want the
    # column-ref logic to defer. Add the input first to exercise pure
    # column-ref path.
    from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineInput
    ts.session.pipeline_json.inputs.append(
        PipelineInput(name="col", type="string", example="step"),
    )
    # $col would be substituted to "step" at runtime — column-ref check
    # skips placeholder values (validated at execute time).
    result = await ts.set_param(node_id="n2", key="column", value="$col")
    assert result["params"]["column"] == "$col"
