"""BuilderAgent — executes the plan (wraps nodes/agentic_phase_loop.py).

Spec §5: Builder follows the Planner's phases, one phase at a time, via a
ReAct loop (inspect / add_node / connect / set_param / run_verifier). Phase 0:
run() delegates to the existing agentic_phase_loop_node unchanged.

Single-source budget: MAX_REACT_ROUNDS in the node module now reads
BUILDER_BUDGETS.react_rounds from here (spec §3.2 registry promise).
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

#: Single source for builder loop bounds. react_rounds value = the long-time
#: production MAX_REACT_ROUNDS (32, since 2026-06-13). Do NOT change casually:
#: it bounds cost per phase.
BUILDER_BUDGETS = Budgets(react_rounds=32, revise_attempts=0,
                          replan_count=0, repair_iterations=0)


class BuilderAgent(RoleAgent):
    name = "builder"
    charter = (
        "你是 pipeline builder（Builder）。follow Planner 的 phase 逐一執行：）"
        "選 block、接線、設參（param key 100% 依 param_schema）。"
        "每 round 一個 tool call；結構驗證由 deterministic verifier 把關。"
    )
    model_cfg = ModelCfg()          # inherit session default
    #: canvas mutations + inspection — mirrors the loop's tool registry
    allowed_tools = (
        "inspect_node_output", "inspect_block_doc",
        "add_node", "connect", "set_param", "remove_node",
        "run_verifier", "phase_complete",
    )
    budgets = BUILDER_BUDGETS

    def state_view(self, state: dict[str, Any]) -> View:
        """Compact slice the phase loop keys off (per-phase working set)."""
        idx = state.get("v30_current_phase_idx") or 0
        phases = state.get("v30_phases") or []
        return {
            "phase": phases[idx] if idx < len(phases) else None,
            "phase_round": state.get("v30_phase_round") or 0,
            "subphase": state.get("v30_subphase"),
            "canvas": state.get("base_pipeline") or {},
            "exec_trace_keys": sorted((state.get("exec_trace") or {}).keys()),
            "last_verifier_reject": state.get("v30_last_verifier_reject"),
        }

    def system_prompt(self, view: View) -> str:
        from python_ai_sidecar.agent_builder.graph_build.nodes import (
            agentic_phase_loop,
        )
        return agentic_phase_loop._SYSTEM

    async def run(self, view: View) -> StatePatch:
        # Phase 0 delegation (full-state passthrough; see planner.py note).
        from python_ai_sidecar.agent_builder.graph_build.nodes import (
            agentic_phase_loop,
        )
        return await agentic_phase_loop.agentic_phase_loop_node(view)  # type: ignore[arg-type]
