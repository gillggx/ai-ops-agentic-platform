"""graph_build — Phase 10 graph-heavy Builder Mode.

Replaces the 1-node + 80-turn-free-LLM `stream_agent_build` with a
10-node LangGraph StateGraph. LLM only does narrow reasoning
(plan / repair_plan / repair_op); graph controls flow.

Public API:
    stream_graph_build(instruction, base_pipeline, registry, session_id, user_id)
        → AsyncGenerator[StreamEvent, None]

    resume_graph_build(session_id, confirmed: bool)
        → AsyncGenerator[StreamEvent, None]

See docs/PHASE_10_BUILDER_GRAPH_V2.html for the design.
"""
from python_ai_sidecar.agent_builder.graph_build.runner import (
    stream_graph_build,
    resume_graph_build,
)

__all__ = ["stream_graph_build", "resume_graph_build"]
