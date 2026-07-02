"""Agent registry — single source of truth for role-agent configuration.

Spec: docs/MULTI_AGENT_PHASE0_SPEC.md §3.2. Changing an agent's prompt /
model / tools happens HERE and only here. A future tier-router (e.g. Opus
escalation for hard phases) is a one-line model_cfg change per agent.

Phase 0 Step 1: skeleton only — concrete agents register in later steps
(Planner: Step 3, Builder: Step 4, Repair: Step 5). Nothing is wired into
the graph yet.
"""
from __future__ import annotations

from typing import Optional

from python_ai_sidecar.agent_builder.agents.base import RoleAgent

_REGISTRY: dict[str, RoleAgent] = {}


def register(agent: RoleAgent) -> RoleAgent:
    """Register a role agent (idempotent by name; later wins on re-register).

    Re-registration is deliberate: tests swap in stub agents, and module
    reloads (feature-flag tests reload config) must not explode.
    """
    if not agent.name or agent.name == "role":
        raise ValueError("RoleAgent must define a concrete .name")
    _REGISTRY[agent.name] = agent
    return agent


def get_agent(name: str) -> RoleAgent:
    """Fetch a registered agent; KeyError with the known names on miss."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"no agent registered under {name!r}; known={sorted(_REGISTRY)}"
        ) from None


def maybe_get_agent(name: str) -> Optional[RoleAgent]:
    """Non-throwing variant for call sites that fall back to legacy paths."""
    return _REGISTRY.get(name)


def registered_names() -> list[str]:
    return sorted(_REGISTRY)
