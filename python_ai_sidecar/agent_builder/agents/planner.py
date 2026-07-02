"""PlannerAgent — owns goal planning (wraps nodes/goal_plan.py).

Spec §4: Planner is the requirement owner (+ judge from Phase 2). Phase 0:
run() delegates to the existing goal_plan_node unchanged (behaviour-neutral);
what moves HERE now is the agent's identity: charter, model_cfg, budgets.
Prompt assembly migrates in a later step — system_prompt() already exposes
the node's _SYSTEM so callers have one lookup point.
"""
from __future__ import annotations

from typing import Any

from python_ai_sidecar.agent_builder.agents.base import (
    Budgets,
    ModelCfg,
    RoleAgent,
    StatePatch,
    View,
)

#: Single source for planner collaboration budgets (spec §2/§4.2).
#: replan_count is read by the Phase 2+ REPLAN loop; react/revise/repair
#: budgets are not the planner's to spend.
PLANNER_BUDGETS = Budgets(react_rounds=0, revise_attempts=0,
                          replan_count=2, repair_iterations=0)


class PlannerAgent(RoleAgent):
    name = "planner"
    charter = (
        "你是 pipeline architect（Planner）。把 user 需求拆成 goal-oriented "
        "phases（意圖，不挑 block）；Phase 2+ 起並擔任語意裁判"
        "（APPROVE / REVISE / REPLAN）。"
    )
    model_cfg = ModelCfg()          # inherit session default (GLM-5.2 today)
    allowed_tools = ()              # planner emits JSON only — no canvas tools
    budgets = PLANNER_BUDGETS

    def state_view(self, state: dict[str, Any]) -> View:
        """The compact slice goal_plan actually reads (spec §2 Phase fields).

        Phase 0: run() still receives the full state because the legacy node
        body needs it; this view documents + tests the true read-surface, and
        becomes the real input once prompt assembly moves into the agent.
        """
        return {
            "instruction": state.get("instruction") or "",
            "base_pipeline": state.get("base_pipeline") or {},
            "skill_step_mode": bool(state.get("skill_step_mode")),
            "v30_replan_hint": state.get("v30_replan_hint"),
            "user_id": state.get("user_id"),
        }

    def system_prompt(self, view: View) -> str:
        # Lazy import: nodes/goal_plan imports llm_client etc.; the contract
        # module stays light and there is no import cycle.
        from python_ai_sidecar.agent_builder.graph_build.nodes import goal_plan
        return goal_plan._SYSTEM

    async def run(self, view: View) -> StatePatch:
        # Phase 0 delegation: view IS the full BuildGraphState (passthrough).
        # Module-attr call keeps this monkeypatch-friendly in tests.
        from python_ai_sidecar.agent_builder.graph_build.nodes import goal_plan
        return await goal_plan.goal_plan_node(view)  # type: ignore[arg-type]
