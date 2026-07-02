"""RepairAgent — feedback-driven corrector (wraps nodes/phase_revise.py).

Spec §6: Repair is NOT auto-chained after build; it is feedback-driven
(in_build escalation / post_delivery user feedback, Phase 2+). Phase 0:
RepairAgent inherits the existing in-build self-reflection (phase_revise)
unchanged — the diagnose (build_level vs plan_level) + direct-patch /
re-plan exits are interface-only until Phase 2.

Single-source budget: MAX_REVISE_ATTEMPTS_PER_PHASE in the node module now
reads REPAIR_BUDGETS.revise_attempts from here.
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

#: Single source. revise_attempts = production MAX_REVISE_ATTEMPTS_PER_PHASE
#: (1); repair_iterations bounds the Phase 2+ ticket loop (spec §6.4).
REPAIR_BUDGETS = Budgets(react_rounds=0, revise_attempts=1,
                         replan_count=0, repair_iterations=3)


class RepairAgent(RoleAgent):
    name = "repair"
    charter = (
        "你是 repair agent。對齊三路輸入：原始需求、目前 pipeline 結果、"
        "user feedback。先診斷層級（build_level → 直接 patch canvas；"
        "plan_level → 產修正 plan 交回 Planner），再最小範圍修正。"
    )
    model_cfg = ModelCfg()          # inherit session default
    allowed_tools = (
        "inspect_node_output", "add_node", "connect", "set_param",
        "remove_node", "run_verifier",
    )
    budgets = REPAIR_BUDGETS

    def state_view(self, state: dict[str, Any]) -> View:
        """Three-way input slice (spec §6.2) + current stuck context."""
        idx = state.get("v30_current_phase_idx") or 0
        phases = state.get("v30_phases") or []
        return {
            "instruction": state.get("instruction") or "",
            "phase": phases[idx] if idx < len(phases) else None,
            "canvas": state.get("base_pipeline") or {},
            "last_verifier_reject": state.get("v30_last_verifier_reject"),
            "repair_ticket": state.get("ma_repair_ticket"),
            "phase_outcomes": state.get("v30_phase_outcomes") or {},
        }

    def system_prompt(self, view: View) -> str:
        # phase_revise builds its prompt inline per call; the charter is the
        # stable role definition. Prompt assembly moves here in a later step.
        return self.charter

    async def run(self, view: View) -> StatePatch:
        # Phase 0 delegation (full-state passthrough; see planner.py note).
        from python_ai_sidecar.agent_builder.graph_build.nodes import phase_revise
        return await phase_revise.phase_revise_node(view)  # type: ignore[arg-type]
