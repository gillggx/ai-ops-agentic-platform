"""RoleAgent contract — the multi-agent build plane's agent anatomy (Phase 0).

Spec: docs/MULTI_AGENT_PHASE0_SPEC.md §3 (11 elements). This module defines
elements 1-8 as concrete fields/methods and elements 9-11 (memory / record /
trace hooks) as no-op slots that later phases fill WITHOUT changing this
skeleton. Phase 0 is behaviour-neutral: graph nodes progressively delegate to
RoleAgent implementations (Planner/Builder/Repair) in later steps; routing
stays 100% in the graph's conditional edges (flow-in-graph).

Deliberately dependency-free (stdlib only): agents import their own tools /
llm client inside run(); the contract itself must stay cheap to import and
trivially unit-testable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

# A View is the compact slice of BuildGraphState an agent reads (element 5).
# Kept as a plain dict so existing observation builders
# (_build_observation_md / _build_canvas_diff_md) plug in unchanged.
View = dict[str, Any]

# A StatePatch is exactly what a LangGraph node returns today: a partial
# BuildGraphState update dict (element 6). Reducers in state.py still apply.
StatePatch = dict[str, Any]


@dataclass(frozen=True)
class ModelCfg:
    """Element 3 — which LLM drives this agent.

    model=None means "inherit the session default" (get_llm_client() as-is).
    A future tier-router = swapping this per agent in the registry; nothing
    else changes.
    """

    model: Optional[str] = None
    reasoning_effort: Optional[str] = None  # None = inherit LLM_REASONING_EFFORT
    prompt_cache: bool = True


@dataclass(frozen=True)
class Budgets:
    """Element 7 — graph-enforced loop bounds (never enforced via prompt).

    Values mirror the constants that live in the nodes today
    (MAX_REACT_ROUNDS / MAX_REVISE_ATTEMPTS_PER_PHASE / ...). The graph reads
    these; the LLM never sees them as instructions to obey.
    """

    react_rounds: int = 32          # per phase (agentic_phase_loop)
    revise_attempts: int = 1        # per phase (phase_revise)
    replan_count: int = 2           # per build (planner REPLAN, Phase 2+)
    repair_iterations: int = 3      # per repair ticket (Phase 2+)


@dataclass(frozen=True)
class RecordRule:
    """Element 10 slot — one deterministic record trigger (Phase 4 fills).

    Mirrors AGENT_HARNESS_DESIGN §12: the *event* is detected by the graph;
    the LLM only fills a structured memo template when the rule fires.
    """

    event: str          # e.g. "plan_feedback", "param_reject_then_pass"
    memo_class: str     # domain|preference|presentation|correction|episodic|procedure
    description: str = ""


@dataclass(frozen=True)
class MemoryHit:
    """Element 9 slot — one recalled knowledge row (Phase 3 fills)."""

    memo_class: str
    title: str
    body: str
    score: float = 0.0


class RoleAgent(ABC):
    """The role-agent contract (spec §3.2).

    Concrete agents (Planner/Builder/Repair) wrap logic that today lives in
    goal_plan / agentic_phase_loop / phase_revise nodes. A graph node becomes
    a thin shell: take agent → state_view → run → apply patch; the node/edge
    topology decides all routing.
    """

    #: element 1+2 anchor — unique role name ("planner" | "builder" | "repair")
    name: str = "role"
    #: element 1 — charter: role definition + hard rules (prepended to prompt)
    charter: str = ""
    #: element 3
    model_cfg: ModelCfg = ModelCfg()
    #: element 4 — tool names this agent may call (enforced by its toolset)
    allowed_tools: tuple[str, ...] = ()
    #: element 7
    budgets: Budgets = Budgets()

    # ── element 5: compact read view ──────────────────────────────────
    @abstractmethod
    def state_view(self, state: dict[str, Any]) -> View:
        """Extract the compact slice of BuildGraphState this agent reads.

        MUST reuse the existing compact builders (observation md / canvas
        diff); never re-expand the full context (spec §9 token risk).
        """

    # ── element 2: prompt assembly (charter + role prompt) ────────────
    @abstractmethod
    def system_prompt(self, view: View) -> str:
        """Assemble the role-scoped system prompt for this view."""

    # ── element 6: the narrow LLM step ────────────────────────────────
    @abstractmethod
    async def run(self, view: View) -> StatePatch:
        """One narrow reasoning step: view in, state patch out.

        The LLM call happens here. The patch is applied by the calling
        graph node; the agent NEVER routes (no next-node decisions).
        """

    # ── elements 9-11: slots (no-op in Phase 0; later phases override) ─
    async def memory_query(self, view: View) -> list[MemoryHit]:
        """Element 9 — recall knowledge for this view (Phase 3)."""
        return []

    def record_triggers(self) -> list[RecordRule]:
        """Element 10 — deterministic record rules (Phase 4)."""
        return []

    def trace_fields(self, view: View, patch: StatePatch) -> dict[str, Any]:
        """Element 11 — extra fields to stamp into the Episode (Phase 2)."""
        return {}
