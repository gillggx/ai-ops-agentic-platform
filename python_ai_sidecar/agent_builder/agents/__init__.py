"""Multi-agent build plane — role agents (Planner / Builder / Repair).

Phase 0 contract + registry. See docs/MULTI_AGENT_PHASE0_SPEC.md.
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
from python_ai_sidecar.agent_builder.agents.registry import (
    get_agent,
    maybe_get_agent,
    register,
    registered_names,
)

__all__ = [
    "Budgets",
    "MemoryHit",
    "ModelCfg",
    "RecordRule",
    "RoleAgent",
    "StatePatch",
    "View",
    "get_agent",
    "maybe_get_agent",
    "register",
    "registered_names",
]
