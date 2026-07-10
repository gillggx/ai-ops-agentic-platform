"""Planner — goal planning + the plan-confirm card contract (public API).

Implementation: python_ai_sidecar/agent_builder/graph_build/nodes/goal_plan.py
and the confirm-gate machinery in the graph runner. The plan card pauses at
goal_plan_confirm_gate; resume via builder.resume_graph_v30.
"""
from python_ai_sidecar.agent_builder.graph_build.runner import (  # noqa: F401
    stream_graph_build,
)

__all__ = ["stream_graph_build"]
