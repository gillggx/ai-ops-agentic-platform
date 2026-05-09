"""BuildGraphState — LangGraph state schema for graph_build.

TypedDict not Pydantic because LangGraph reducers expect plain dicts.
Op + nested PipelineJSON are stored as model_dump() dicts so the state
is JSON-serializable for any future Redis-backed checkpointer.
"""
from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict


GraphStatus = Literal[
    "running",
    "needs_confirm",
    "plan_unfixable",
    "cancelled",
    "finished",
    "failed",
]


class BuildGraphState(TypedDict, total=False):
    # ── Inputs ────────────────────────────────────────────────────────
    session_id: str
    instruction: str
    base_pipeline: Optional[dict]   # PipelineJSON.model_dump(by_alias=True)
    user_id: Optional[int]

    # ── Plan stage ────────────────────────────────────────────────────
    plan: list[dict]                # list[Op] dumped
    plan_validation_errors: list[str]
    plan_repair_attempts: int

    # ── Confirm stage ─────────────────────────────────────────────────
    is_from_scratch: bool
    user_confirmed: Optional[bool]  # None = not yet asked / waiting
    # When True, _route_after_validate skips confirm_gate entirely. Used by
    # Chat Mode (in-process build_pipeline_live tool) where the chat
    # conversation IS the confirmation; pausing the chat orchestrator
    # mid-tool to wait for a UI click would break the conversational flow.
    skip_confirm: bool

    # ── Execute stage ─────────────────────────────────────────────────
    cursor: int                          # plan[cursor] is the next op
    logical_to_real: dict[str, str]      # {"n1": "n3", ...} after add_node
    failed_op_idx: Optional[int]         # index of op that escalated to repair_plan

    # ── Output / streaming ────────────────────────────────────────────
    final_pipeline: Optional[dict]       # PipelineJSON dump after finalize
    sse_events: list[dict]               # accumulated events for runner to flush
    status: GraphStatus
    summary: Optional[str]


def initial_state(
    *,
    session_id: str,
    instruction: str,
    base_pipeline: Optional[dict],
    user_id: Optional[int] = None,
    skip_confirm: bool = False,
) -> BuildGraphState:
    return BuildGraphState(
        session_id=session_id,
        instruction=instruction,
        base_pipeline=base_pipeline,
        user_id=user_id,
        plan=[],
        plan_validation_errors=[],
        plan_repair_attempts=0,
        is_from_scratch=False,
        user_confirmed=None,
        skip_confirm=skip_confirm,
        cursor=0,
        logical_to_real={},
        failed_op_idx=None,
        final_pipeline=None,
        sse_events=[],
        status="running",
        summary=None,
    )
