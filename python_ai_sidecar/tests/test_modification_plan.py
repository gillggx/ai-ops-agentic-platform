"""Modification-plan tests (v31.2, spec 2026-07-04).

C0 — the goal_plan prompt in modification context carries the FULL current
picture: edges topology + previous plan, not just a node list.
C4 — removal validation: hallucinated ids dropped at plan time; the
still-consumed guard protects shared upstreams at apply time.
"""
from __future__ import annotations

from python_ai_sidecar.agent_builder.graph_build.nodes.finalize import (
    apply_plan_removals,
)

PIPE = {
    "version": "1.0", "name": "t", "inputs": [],
    "nodes": [
        {"id": "n1", "block_id": "block_process_history", "params": {}},
        {"id": "n2", "block_id": "block_unnest", "params": {}},
        {"id": "n3", "block_id": "block_line_chart", "params": {"title": "合併"}},
        {"id": "n6", "block_id": "block_line_chart", "params": {"title": "R"}},
    ],
    "edges": [
        {"id": "e1", "from": {"node": "n1", "port": "data"}, "to": {"node": "n2", "port": "data"}},
        {"id": "e2", "from": {"node": "n2", "port": "data"}, "to": {"node": "n3", "port": "data"}},
        {"id": "e3", "from": {"node": "n2", "port": "data"}, "to": {"node": "n6", "port": "data"}},
    ],
}


# ── C4: apply-time guard ────────────────────────────────────────────────

def test_apply_removes_terminal_node_and_its_edges():
    out, removed, skipped = apply_plan_removals(PIPE, [{"node_id": "n3", "reason": "被取代"}])
    assert removed == ["n3"] and skipped == []
    assert [n["id"] for n in out["nodes"]] == ["n1", "n2", "n6"]
    # e2 (feeding n3) dropped; e1/e3 kept
    assert {e["id"] for e in out["edges"]} == {"e1", "e3"}


def test_apply_protects_still_consumed_upstream():
    # LLM (wrongly) lists the shared upstream n2 — n6 still consumes it.
    out, removed, skipped = apply_plan_removals(PIPE, [{"node_id": "n2", "reason": "?"}])
    assert removed == []
    assert skipped and skipped[0]["node_id"] == "n2"
    assert "n6" in skipped[0]["reason"]
    assert len(out["nodes"]) == 4  # untouched


def test_apply_removal_set_counts_as_not_consuming():
    # removing BOTH n2 and n3+n6 (all consumers in the set) allows n2 too
    out, removed, skipped = apply_plan_removals(
        PIPE, [{"node_id": "n2"}, {"node_id": "n3"}, {"node_id": "n6"}])
    assert set(removed) == {"n2", "n3", "n6"}
    assert [n["id"] for n in out["nodes"]] == ["n1"]
    assert out["edges"] == []


def test_apply_missing_node_skipped_gracefully():
    out, removed, skipped = apply_plan_removals(PIPE, [{"node_id": "ghost"}])
    assert removed == [] and skipped[0]["node_id"] == "ghost"


def test_apply_noop_on_empty():
    out, removed, skipped = apply_plan_removals(PIPE, [])
    assert out is PIPE and removed == [] and skipped == []


# ── C0: prompt carries edges + prior plan (build the prompt via the same
#        section-assembly code path goal_plan uses) ─────────────────────

def test_goal_plan_prompt_contains_topology_and_prior_plan():
    """Exercise goal_plan_node's prompt assembly up to the LLM call by
    faking the client; capture the user message."""
    import asyncio
    from unittest.mock import patch, AsyncMock, MagicMock

    from python_ai_sidecar.agent_builder.graph_build.nodes import goal_plan as gp

    captured = {}

    class _FakeResp:
        text = '{"plan_summary":"s","phases":[],"removals":[]}'
        input_tokens = 1
        output_tokens = 1
        finish_reason = "stop"
        tool_calls = None

    async def _fake_create(**kw):
        captured["system"] = kw.get("system")
        msgs = kw.get("messages") or []
        captured["user"] = msgs[0]["content"] if msgs else ""
        return _FakeResp()

    fake_client = MagicMock()
    fake_client.create = AsyncMock(side_effect=_fake_create)

    state = {
        "instruction": "我後悔了，我想改成3張",
        "prior_instruction": "比較 R、Cpk、Cpk_std 趨勢",
        "prior_phases": [
            {"id": "p1", "goal": "取得歷史資料", "expected": "raw_data"},
            {"id": "p3", "goal": "繪製三項指標趨勢圖", "expected": "chart"},
        ],
        "base_pipeline": PIPE,
        "skill_step_mode": False,
        "session_id": "t", "user_id": 1,
    }
    from python_ai_sidecar.agent_builder.graph_build.nodes import _knowledge_inject as ki
    with patch.object(gp, "get_llm_client", return_value=fake_client), \
         patch.object(ki, "build_knowledge_hint", new=AsyncMock(return_value="")):
        try:
            asyncio.run(gp.goal_plan_node(state))
        except Exception:
            pass  # empty-phases downstream handling irrelevant to this test

    user = captured.get("user") or ""
    assert "n2 → n3" in user, "edges topology missing from prompt"
    assert "上一次的 plan" in user and "繪製三項指標趨勢圖" in user
    assert "上一次建構指令" in user
    assert "removals" in (captured.get("system") or "")
