"""2026-06-20 — phase_verifier non-output leaf check (Fix C).

A non-output node (source/transform/...) left as a LEAF (0 outbound) can never
feed the deliverable. ooc-ranking: a 3rd process_history was left dangling when
the agent unioned only 2 → finalize failed_structural. This deterministic
build-time check catches it DURING the build (REJECT → agent connects/removes
next round) instead of failing the whole build at finalize.

Scoped: fires ONLY once an output node exists (so an in-progress frontier node,
legitimately a pending leaf, is not a false positive).
"""
from __future__ import annotations

from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import _check_leaf


class FakeRegistry:
    """get_spec(block_id, ver) -> {category, meta} from a small map."""
    def __init__(self, cats: dict[str, str], standalone: set[str] | None = None):
        self._cats = cats
        self._standalone = standalone or set()

    def get_spec(self, name, version):
        if name not in self._cats:
            return None
        return {
            "category": self._cats[name],
            "meta": {"standalone_capable": True} if name in self._standalone else {},
        }


def _node(nid, bid):
    return {"id": nid, "block_id": bid}


def _edge(frm, to):
    return {"from": {"node": frm}, "to": {"node": to}}


_CATS = {
    "block_process_history": "source",
    "block_union": "transform",
    "block_filter": "transform",
    "block_groupby_agg": "transform",
    "block_bar_chart": "output",
    "block_spc_panel": "output",
}


def _state(nodes, edges):
    return {"final_pipeline": {"nodes": nodes, "edges": edges},
            "v30_phases": [{"id": "p1", "expected": "raw_data"}],
            "v30_current_phase_idx": 0}


def test_abandoned_non_output_leaf_rejected():
    # ooc-ranking shape: n3 process_history dangling; n7 bar_chart is the output.
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_process_history"),
             _node("n3", "block_process_history"), _node("n4", "block_union"),
             _node("n5", "block_filter"), _node("n6", "block_groupby_agg"),
             _node("n7", "block_bar_chart")]
    edges = [_edge("n1", "n4"), _edge("n2", "n4"), _edge("n4", "n5"),
             _edge("n5", "n6"), _edge("n6", "n7")]
    out = _check_leaf(state=_state(nodes, edges), registry=FakeRegistry(_CATS))
    assert out is not None
    # routes to 'construct' (connect) and names n3
    assert out["v30_subphase"] == "construct"
    miss = out["sse_events"][0]["data"]["missing_for_phase"]
    assert any("n3" in m and "block_process_history" in m for m in miss)


def test_output_leaf_is_fine():
    # bar_chart leaf is legitimate; nothing else dangling.
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_bar_chart")]
    edges = [_edge("n1", "n2")]
    out = _check_leaf(state=_state(nodes, edges), registry=FakeRegistry(_CATS))
    assert out is None


def test_in_progress_no_output_yet_not_flagged():
    # Build still in progress: fetch → filter, NO output block yet. The filter
    # is a pending frontier leaf — must NOT be flagged (false-positive guard).
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_filter")]
    edges = [_edge("n1", "n2")]
    out = _check_leaf(state=_state(nodes, edges), registry=FakeRegistry(_CATS))
    assert out is None


def test_standalone_capable_leaf_exempt():
    # A standalone source+output composite as a leaf is allowed (same exemption
    # C14 uses). Pair it with a real output so the gate is open.
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_bar_chart"),
             _node("n3", "block_spc_panel")]
    edges = [_edge("n1", "n2")]
    out = _check_leaf(
        state=_state(nodes, edges),
        registry=FakeRegistry(_CATS, standalone={"block_spc_panel"}),
    )
    assert out is None


def test_clean_linear_pipeline_passes():
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_filter"),
             _node("n3", "block_bar_chart")]
    edges = [_edge("n1", "n2"), _edge("n2", "n3")]
    out = _check_leaf(state=_state(nodes, edges), registry=FakeRegistry(_CATS))
    assert out is None


def test_single_node_pipeline_skipped():
    nodes = [_node("n1", "block_spc_panel")]
    out = _check_leaf(state=_state(nodes, []), registry=FakeRegistry(_CATS))
    assert out is None
