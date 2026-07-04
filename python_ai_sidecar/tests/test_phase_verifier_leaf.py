"""2026-06-20/23 — phase_verifier non-output leaf check (Fix C + bounded prune).

A non-output node (source/transform/...) left as a LEAF (0 outbound) can never
feed the deliverable. ooc-ranking: a 3rd process_history was left dangling when
the agent unioned only 2 → finalize failed_structural. The check catches it
DURING the build (REJECT → agent connects/removes next round).

2026-06-23: bounded-reject. The agent sometimes can't fix it (re-adds leaves
instead of wiring — apc-recipe-compare looped 20 rounds → handover). So after
LEAF_PRUNE_AFTER consecutive rejects the verifier DETERMINISTICALLY prunes the
dead leaf (`_prune_nodes`) so the build converges. Detection (`_nonoutput_leaves`)
is split from the reject/prune decision (in the verifier node).
"""
from __future__ import annotations

from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import (
    _nonoutput_leaves,
    _prune_nodes,
)


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
    "block_pluck": "transform",
    "block_bar_chart": "output",
    "block_box_plot": "output",
    "block_spc_panel": "output",
}


def _state(nodes, edges):
    return {"final_pipeline": {"nodes": nodes, "edges": edges},
            "v30_phases": [{"id": "p1", "expected": "raw_data"}],
            "v30_current_phase_idx": 0}


def _leaves(nodes, edges, standalone=None):
    _, ab = _nonoutput_leaves(_state(nodes, edges),
                              FakeRegistry(_CATS, standalone=standalone))
    return ab


# ── detection (_nonoutput_leaves) ───────────────────────────────────

def test_abandoned_non_output_leaf_detected():
    # ooc-ranking shape: n3 process_history dangling; n7 bar_chart is the output.
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_process_history"),
             _node("n3", "block_process_history"), _node("n4", "block_union"),
             _node("n5", "block_filter"), _node("n6", "block_groupby_agg"),
             _node("n7", "block_bar_chart")]
    edges = [_edge("n1", "n4"), _edge("n2", "n4"), _edge("n4", "n5"),
             _edge("n5", "n6"), _edge("n6", "n7")]
    ab = _leaves(nodes, edges)
    assert [nid for nid, _ in ab] == ["n3"]


def test_output_leaf_is_fine():
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_bar_chart")]
    assert _leaves(nodes, [_edge("n1", "n2")]) == []


def test_in_progress_no_output_yet_not_flagged():
    # fetch → filter, NO output yet: filter is a pending frontier leaf, not flagged.
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_filter")]
    assert _leaves(nodes, [_edge("n1", "n2")]) == []


def test_standalone_capable_leaf_exempt():
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_bar_chart"),
             _node("n3", "block_spc_panel")]
    assert _leaves(nodes, [_edge("n1", "n2")], standalone={"block_spc_panel"}) == []


def test_clean_linear_pipeline_no_leaves():
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_filter"),
             _node("n3", "block_bar_chart")]
    assert _leaves(nodes, [_edge("n1", "n2"), _edge("n2", "n3")]) == []


def test_single_node_skipped():
    assert _leaves([_node("n1", "block_spc_panel")], []) == []


def test_apc_recipe_shape_pluck_dangling_detected():
    # apc-recipe-compare loop shape: pluck (n3) dangling off the box_plot chain.
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_union"),
             _node("n3", "block_pluck"), _node("n5", "block_box_plot")]
    edges = [_edge("n1", "n2"), _edge("n2", "n5")]  # n3 pluck has no out edge
    ab = _leaves(nodes, edges)
    assert [nid for nid, _ in ab] == ["n3"]


# ── prune (_prune_nodes) ────────────────────────────────────────────

def test_prune_removes_node_and_touching_edges():
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_union"),
             _node("n3", "block_pluck"), _node("n5", "block_box_plot")]
    edges = [_edge("n1", "n2"), _edge("n2", "n5"), _edge("n1", "n3")]
    cleaned = _prune_nodes({"nodes": nodes, "edges": edges}, ["n3"])
    assert [n["id"] for n in cleaned["nodes"]] == ["n1", "n2", "n5"]
    # the n1→n3 edge is gone; the box_plot chain stays intact
    pairs = [(e["from"]["node"], e["to"]["node"]) for e in cleaned["edges"]]
    assert ("n1", "n3") not in pairs
    assert ("n1", "n2") in pairs and ("n2", "n5") in pairs


def test_prune_multiple():
    nodes = [_node("n1", "block_bar_chart"), _node("n2", "block_pluck"),
             _node("n3", "block_filter")]
    cleaned = _prune_nodes({"nodes": nodes, "edges": []}, ["n2", "n3"])
    assert [n["id"] for n in cleaned["nodes"]] == ["n1"]


# ── 2026-07-05: plan-relevant terminals are NOT dead leaves ──────────
# apc-drift WRONG ×2: p4=verdict ends in block_weco_rules (verdict block,
# nothing downstream by design). The old exemptions missed it → after 3
# leaf rejects the prune deleted the node the same verifier call advanced
# on → final pipeline shipped without the verdict node.

class FakeRegistryWithCovers(FakeRegistry):
    def __init__(self, cats, covers=None, standalone=None):
        super().__init__(cats, standalone=standalone)
        self._covers = covers or {}

    def get_spec(self, name, version):
        spec = super().get_spec(name, version)
        if spec is not None and name in self._covers:
            spec["produces"] = {"covers_output": self._covers[name]}
        return spec


_CATS_V = dict(_CATS, block_weco_rules="analysis")
_COVERS_V = {"block_weco_rules": ["verdict"]}


def test_verdict_terminal_exempt_when_plan_has_verdict_phase():
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_filter"),
             _node("n3", "block_spc_panel"), _node("n4", "block_weco_rules")]
    edges = [_edge("n1", "n2"), _edge("n2", "n3"), _edge("n2", "n4")]
    state = {"final_pipeline": {"nodes": nodes, "edges": edges},
             "v30_phases": [{"id": "p1", "expected": "raw_data"},
                            {"id": "p2", "expected": "chart"},
                            {"id": "p4", "expected": "verdict"}],
             "v30_current_phase_idx": 2}
    _, ab = _nonoutput_leaves(state, FakeRegistryWithCovers(_CATS_V, _COVERS_V))
    assert ab == []  # weco_rules is a plan-declared deliverable terminal


def test_verdict_leaf_still_flagged_when_plan_has_no_verdict_phase():
    # Same canvas, but the plan never asked for a verdict — a dangling
    # weco_rules IS abandoned then.
    nodes = [_node("n1", "block_process_history"), _node("n3", "block_spc_panel"),
             _node("n4", "block_weco_rules")]
    edges = [_edge("n1", "n3"), _edge("n1", "n4")]
    state = {"final_pipeline": {"nodes": nodes, "edges": edges},
             "v30_phases": [{"id": "p1", "expected": "raw_data"},
                            {"id": "p2", "expected": "chart"}],
             "v30_current_phase_idx": 1}
    _, ab = _nonoutput_leaves(state, FakeRegistryWithCovers(_CATS_V, _COVERS_V))
    assert [nid for nid, _ in ab] == ["n4"]


def test_current_candidate_never_pruned():
    # The node under verification this round is the phase frontier —
    # rejecting it is fine, silently deleting it while advancing is not.
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_pluck"),
             _node("n5", "block_box_plot")]
    edges = [_edge("n1", "n5")]  # n2 dangling AND is the current candidate
    state = {"final_pipeline": {"nodes": nodes, "edges": edges},
             "v30_phases": [{"id": "p1", "expected": "raw_data"}],
             "v30_current_phase_idx": 0,
             "v30_last_mutated_logical_id": "n2"}
    _, ab = _nonoutput_leaves(state, FakeRegistry(_CATS))
    assert ab == []


def test_abandoned_fetch_still_detected_with_plan_kinds():
    # Original prune motivation (ooc-ranking dangling 3rd fetch) must keep
    # working: raw_data/transform kinds are never exempt.
    nodes = [_node("n1", "block_process_history"), _node("n2", "block_process_history"),
             _node("n3", "block_union"), _node("n5", "block_bar_chart"),
             _node("n4", "block_process_history")]
    edges = [_edge("n1", "n3"), _edge("n2", "n3"), _edge("n3", "n5")]
    state = {"final_pipeline": {"nodes": nodes, "edges": edges},
             "v30_phases": [{"id": "p1", "expected": "raw_data"},
                            {"id": "p2", "expected": "chart"},
                            {"id": "p3", "expected": "verdict"}],
             "v30_current_phase_idx": 1}
    _, ab = _nonoutput_leaves(state, FakeRegistryWithCovers(_CATS_V, _COVERS_V))
    assert [nid for nid, _ in ab] == ["n4"]
