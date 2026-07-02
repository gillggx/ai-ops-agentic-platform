"""Contract tests for the Phase 0 role-agent skeleton (spec §8 Step 1).

Covers: RoleAgent ABC shape, no-op slots (elements 9-11), registry
register/get semantics, and the frozen config dataclasses.
"""
from __future__ import annotations

import asyncio

import pytest

from python_ai_sidecar.agent_builder.agents import (
    Budgets,
    ModelCfg,
    RoleAgent,
    get_agent,
    maybe_get_agent,
    register,
    registered_names,
)
from python_ai_sidecar.agent_builder.agents import registry as registry_mod


class _StubAgent(RoleAgent):
    name = "stub"
    charter = "test charter"
    model_cfg = ModelCfg(model=None)
    allowed_tools = ("inspect_node_output",)
    budgets = Budgets(react_rounds=2)

    def state_view(self, state):
        # compact view: only what this agent needs
        return {"instruction": state.get("instruction", ""), "n": len(state)}

    def system_prompt(self, view):
        return f"{self.charter}\n\nINSTRUCTION: {view['instruction']}"

    async def run(self, view):
        return {"summary": f"saw {view['n']} keys"}


@pytest.fixture(autouse=True)
def _restore_registry():
    """Snapshot/restore — default agents (registered at package import) stay
    visible during tests; anything a test registers is rolled back after."""
    saved = dict(registry_mod._REGISTRY)
    yield
    registry_mod._REGISTRY.clear()
    registry_mod._REGISTRY.update(saved)


def test_abstract_base_cannot_instantiate():
    with pytest.raises(TypeError):
        RoleAgent()  # type: ignore[abstract]


def test_state_view_is_compact_and_run_returns_patch():
    agent = _StubAgent()
    state = {"instruction": "畫 xbar 趨勢", "canvas": {}, "exec_trace": {}}
    view = agent.state_view(state)
    assert view == {"instruction": "畫 xbar 趨勢", "n": 3}
    patch = asyncio.run(agent.run(view))
    assert patch == {"summary": "saw 3 keys"}


def test_slots_default_noop():
    agent = _StubAgent()
    assert asyncio.run(agent.memory_query({})) == []
    assert agent.record_triggers() == []
    assert agent.trace_fields({}, {}) == {}


def test_registry_roundtrip_and_reregister():
    a = register(_StubAgent())
    assert get_agent("stub") is a
    assert "stub" in registered_names()
    b = register(_StubAgent())  # re-register: later wins, no explosion
    assert get_agent("stub") is b


def test_registry_rejects_unnamed_agent():
    class _Anon(_StubAgent):
        name = "role"  # base default = not a concrete name

    with pytest.raises(ValueError):
        register(_Anon())


def test_get_agent_missing_raises_with_known_names():
    register(_StubAgent())
    with pytest.raises(KeyError) as exc:
        get_agent("nope")
    assert "stub" in str(exc.value)
    assert maybe_get_agent("nope") is None


def test_config_dataclasses_frozen():
    cfg = ModelCfg(model="z-ai/glm-5.2")
    with pytest.raises(Exception):
        cfg.model = "other"  # type: ignore[misc]
    b = Budgets()
    assert (b.react_rounds, b.revise_attempts, b.replan_count, b.repair_iterations) == (
        32, 1, 2, 3,
    )


def test_initial_state_has_collab_fields():
    """Spec §2 — Phase 0 Step 2: fields exist, no writers, safe defaults."""
    from python_ai_sidecar.agent_builder.graph_build.state import initial_state

    st = initial_state(
        session_id="s1", instruction="test", base_pipeline=None,
    )
    assert st["ma_handoff"] is None
    assert st["ma_planner_verdict"] is None
    assert st["ma_repair_ticket"] is None
    assert st["ma_replan_count"] == 0
    assert st["ma_repair_iterations"] == 0


# ── Phase 0 Steps 3-5: delegation + single-source budgets ──────────────


def test_default_agents_registered_on_import():
    import python_ai_sidecar.agent_builder.agents as agents_pkg
    assert set(agents_pkg.registered_names()) >= {"planner", "builder", "repair"}


def test_budgets_are_single_source_with_nodes():
    from python_ai_sidecar.agent_builder.agents import get_agent
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        MAX_REACT_ROUNDS,
    )
    from python_ai_sidecar.agent_builder.graph_build.nodes.phase_revise import (
        MAX_REVISE_ATTEMPTS_PER_PHASE,
    )

    assert MAX_REACT_ROUNDS == get_agent("builder").budgets.react_rounds == 32
    assert MAX_REVISE_ATTEMPTS_PER_PHASE == get_agent("repair").budgets.revise_attempts == 1


def test_planner_run_delegates_to_goal_plan_node(monkeypatch):
    from python_ai_sidecar.agent_builder.agents.planner import PlannerAgent
    from python_ai_sidecar.agent_builder.graph_build.nodes import goal_plan

    called = {}

    async def _fake(state):
        called["state"] = state
        return {"status": "goal_plan_confirm_required"}

    monkeypatch.setattr(goal_plan, "goal_plan_node", _fake)
    patch = asyncio.run(PlannerAgent().run({"instruction": "x"}))
    assert patch == {"status": "goal_plan_confirm_required"}
    assert called["state"] == {"instruction": "x"}


def test_repair_run_delegates_to_phase_revise_node(monkeypatch):
    from python_ai_sidecar.agent_builder.agents.repair import RepairAgent
    from python_ai_sidecar.agent_builder.graph_build.nodes import phase_revise

    async def _fake(state):
        return {"status": "phase_in_progress"}

    monkeypatch.setattr(phase_revise, "phase_revise_node", _fake)
    assert asyncio.run(RepairAgent().run({})) == {"status": "phase_in_progress"}


def test_state_views_are_compact_slices():
    from python_ai_sidecar.agent_builder.agents import get_agent

    state = {
        "instruction": "看 EQP-01 xbar",
        "base_pipeline": {"nodes": [], "edges": []},
        "skill_step_mode": False,
        "v30_replan_hint": None,
        "user_id": 1,
        "v30_phases": [{"id": "p1", "goal": "g", "expected": "chart"}],
        "v30_current_phase_idx": 0,
        "v30_phase_round": 3,
        "exec_trace": {"n1": {}},
        # noise the views must NOT leak through:
        "sse_events": [{"big": "blob"}],
        "v30_phase_messages": {"p1": [{"role": "user", "content": "huge"}]},
    }
    pv = get_agent("planner").state_view(state)
    bv = get_agent("builder").state_view(state)
    rv = get_agent("repair").state_view(state)
    for view in (pv, bv, rv):
        assert "sse_events" not in view
        assert "v30_phase_messages" not in view
    assert bv["phase"]["id"] == "p1" and bv["phase_round"] == 3
    assert rv["instruction"].startswith("看 EQP-01")
