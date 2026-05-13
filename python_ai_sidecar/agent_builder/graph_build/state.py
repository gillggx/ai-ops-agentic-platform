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
    # Trigger payload that production /run will fire the pipeline with.
    # When provided (e.g. from a skill's stored sample / harness test),
    # finalize's dry-run passes it to PipelineExecutor.execute(inputs=...)
    # so the dry-run mirrors production behaviour. Without it, the executor
    # falls back to _CANONICAL_INPUT_FALLBACKS — which often differ from
    # the actual trigger and let runtime-only failures slip past inspect.
    trigger_payload: Optional[dict]

    # ── Plan stage ────────────────────────────────────────────────────
    plan: list[dict]                # list[Op] dumped
    plan_validation_errors: list[str]
    plan_repair_attempts: int
    # User-facing description of what artifacts will be produced — shown
    # in the confirm card so the user knows what to expect before approving.
    expected_outputs: list[str]
    # v15 G2 (2026-05-13): structured version of expected_outputs. Each item
    # carries {kind: "table"|"chart"|"scalar"|"alert", title, format,
    # columns?, reason}. Renders in the confirm card as concrete artifact
    # previews — user can spot mismatches (e.g. "I wanted a snapshot table,
    # this says trend chart") before approving + clicking "改".
    expected_outputs_structured: list[dict]

    # ── v15 G1: Pre-plan clarification (2026-05-13) ───────────────────
    # clarify_intent_node may pause the graph with 1-3 questions; user's
    # answers come back via /agent/build/clarify-respond and are stored
    # here so plan_node sees them. Shape: {"q1": "snapshot_table", "q2": "7d"}.
    clarifications: dict[str, str]
    # Bound to 1 — clarify only fires once per build.
    clarify_attempts: int

    # ── v15 G2: Post-plan modify request (2026-05-13) ─────────────────
    # When user clicks "改 Step N" on the confirm card, the natural-language
    # request lands here. plan_node weaves it into its next attempt as
    # additional context. Bounded by MAX_MODIFY_CYCLES=3.
    modify_requests: list[dict]
    modify_cycles: int
    # v13 (2026-05-13): per-node contracts the agent declares while writing
    # the plan. Runtime auto-preview compares each node's actual snapshot
    # to its contract; mismatch fires a targeted reflect_op (changes only
    # that node), not a full-plan rewrite. Shape:
    #   {"<logical_id>": {
    #       "rows_min"?: int, "rows_max"?: int,
    #       "cols_must_have"?: list[str],
    #       "output_type"?: "dataframe"|"chart_spec"|"scalar"|"bool",
    #       "value_type"?: "number"|"string"|"boolean",
    #       "distinct_x_min"?: int,
    #       "reason"?: str,
    #   }}
    node_contracts: dict[str, dict]

    # ── Confirm stage ─────────────────────────────────────────────────
    is_from_scratch: bool
    user_confirmed: Optional[bool]  # None = not yet asked / waiting
    # When True, _route_after_validate skips confirm_gate entirely. Used by
    # Chat Mode (in-process build_pipeline_live tool) where the chat
    # conversation IS the confirmation; pausing the chat orchestrator
    # mid-tool to wait for a UI click would break the conversational flow.
    skip_confirm: bool
    # Phase 11 — Skill step mode. When True, plan_node prompt forces the
    # pipeline to end with block_step_check (the Skill terminal block).
    skill_step_mode: bool

    # ── Execute stage ─────────────────────────────────────────────────
    cursor: int                          # plan[cursor] is the next op
    logical_to_real: dict[str, str]      # {"n1": "n3", ...} after add_node
    failed_op_idx: Optional[int]         # index of op that escalated to repair_plan

    # ── Output / streaming ────────────────────────────────────────────
    final_pipeline: Optional[dict]       # PipelineJSON dump after finalize
    sse_events: list[dict]               # accumulated events for runner to flush
    status: GraphStatus
    summary: Optional[str]

    # ── Self-correction loop (2026-05-13) ─────────────────────────────
    # finalize_node persists executor.execute() return value here so
    # inspect_execution can scan node_results for semantic issues (e.g.
    # single-point charts) without re-running the executor.
    dry_run_results: Optional[dict]
    # inspect_execution writes issues; reflect_plan reads them; cleared
    # when route_after_inspect decides to loop.
    inspection_issues: list[dict]
    # Bounded by MAX_REFLECT in reflect_plan_node — incremented each cycle.
    reflect_attempts: int

    # finalize_node persists validator structural errors (orphan / source-less /
    # missing-param) found AFTER all plan ops applied. inspect_execution merges
    # these into inspection_issues so reflect_plan can self-correct structurally
    # broken pipelines (the most common LLM failure mode in practice).
    structural_issues: list[dict]

    # ── Per-op reflection (v8, 2026-05-13) ────────────────────────────
    # Each entry counts how many reflect_op cycles we've spent on a given
    # logical id. Bounded by MAX_REFLECT_OP (see reflect_op.py) to avoid
    # cascading. Persists across the whole build — if op@n3 took 1 attempt
    # and we later need to reflect_op on n5, n3's counter is unaffected.
    reflect_op_attempts: dict[str, int]
    # Set by _detect_op_issue right after call_tool when the just-completed
    # op's exec_trace snapshot looks broken (rows=0, executor error, etc).
    # reflect_op_node reads this, then clears it; cleared also when normal
    # dispatch continues. Shape = ErrorEnvelope dict.
    last_op_issue: Optional[dict]

    # ── Execution trace (Phase F, 2026-05-13) ─────────────────────────
    # call_tool_node populates after every successful connect/add op:
    #   exec_trace[logical_id] = {
    #       "block_id": str, "rows": int|None, "cols": list[str],
    #       "sample": dict|None, "error": str|None,
    #       "after_cursor": int   # which op finished when this snapshot taken
    #   }
    # reflect_op + reflect_plan read this to build a "NODE TRACE" that
    # shows the LLM real data shape at each step — not just symptoms.
    # See trace.py serializer in this package.
    exec_trace: dict[str, dict]


def initial_state(
    *,
    session_id: str,
    instruction: str,
    base_pipeline: Optional[dict],
    user_id: Optional[int] = None,
    skip_confirm: bool = False,
    skill_step_mode: bool = False,
    trigger_payload: Optional[dict] = None,
) -> BuildGraphState:
    return BuildGraphState(
        session_id=session_id,
        instruction=instruction,
        base_pipeline=base_pipeline,
        user_id=user_id,
        plan=[],
        plan_validation_errors=[],
        plan_repair_attempts=0,
        expected_outputs=[],
        is_from_scratch=False,
        user_confirmed=None,
        skip_confirm=skip_confirm,
        skill_step_mode=skill_step_mode,
        cursor=0,
        logical_to_real={},
        failed_op_idx=None,
        final_pipeline=None,
        sse_events=[],
        status="running",
        summary=None,
        exec_trace={},
        structural_issues=[],
        trigger_payload=trigger_payload,
        reflect_op_attempts={},
        last_op_issue=None,
        node_contracts={},
        expected_outputs_structured=[],
        clarifications={},
        clarify_attempts=0,
        modify_requests=[],
        modify_cycles=0,
    )
