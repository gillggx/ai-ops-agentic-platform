"""Multi-agent build plane — role agents (Planner / Builder / Repair).

Phase 0 contract + registry. See docs/MULTI_AGENT_PHASE0_SPEC.md.
Importing this package registers the three default role agents (idempotent).
"""
from python_ai_sidecar.agent_builder.agents.base import (
    Budgets,
    MemoryHit,
    ModelCfg,
    RecordRule,
    RoleAgent,
    StatePatch,
    View,
)
from python_ai_sidecar.agent_builder.agents.builder import BuilderAgent
from python_ai_sidecar.agent_builder.agents.planner import PlannerAgent
from python_ai_sidecar.agent_builder.agents.registry import (
    get_agent,
    maybe_get_agent,
    register,
    registered_names,
)
from python_ai_sidecar.agent_builder.agents.repair import RepairAgent

# Default registrations — the single place the build plane's roster lives.
register(PlannerAgent())
register(BuilderAgent())
register(RepairAgent())

__all__ = [
    "Budgets",
    "BuilderAgent",
    "MemoryHit",
    "ModelCfg",
    "PlannerAgent",
    "RecordRule",
    "RepairAgent",
    "RoleAgent",
    "StatePatch",
    "View",
    "get_agent",
    "maybe_get_agent",
    "register",
    "registered_names",
]
