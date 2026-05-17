"""BuildGraphState — LangGraph state schema for graph_build.

TypedDict not Pydantic because LangGraph reducers expect plain dicts.
Op + nested PipelineJSON are stored as model_dump() dicts so the state
is JSON-serializable for any future Redis-backed checkpointer.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, TypedDict


def _extend_sse(left: list[dict] | None, right: list[dict] | None) -> list[dict]:
    """Reducer for sse_events — append new events, never replace.

    Without a reducer, LangGraph's default behaviour for `list[dict]` is
    replace-on-update. Nodes that don't return `sse_events` then leave
    the prior list intact in state — and runner's _flush_sse_events
    re-yields it on every astream tick, producing duplicate frontend
    events ("加入 node X" appearing twice in a row). With this reducer
    the list accumulates; runner tracks an offset and only yields new
    entries.
    """
    return (left or []) + (right or [])


GraphStatus = Literal[
    "running",
    "needs_confirm",
    "plan_unfixable",
    "cancelled",
    "finished",
    "failed",
    # v18 (2026-05-14): reject-and-ask loop
    "needs_clarify",  # macro_plan said too_vague; route back to clarify_intent
    "refused",        # too_vague_attempts exhausted; tell user we don't understand
    # v30 (2026-05-16): ReAct pipeline builder
    "goal_plan_confirm_required",  # waiting on user to confirm/edit phases
    "phase_in_progress",            # currently in a ReAct round inside a phase
    "phase_revise_pending",         # max round hit; LLM self-reflect in progress
    "handover_pending",             # phase failed even after revise; user must choose
    "build_partial",                # finished some phases, user took over / aborted
    # v30.1 (2026-05-16): phase-spanning verifier + fast-forward
    "phase_verifying",              # verifier running between rounds
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

    # ── v18 (2026-05-14): reject-and-ask loop ─────────────────────────
    # When macro_plan returns too_vague, we route back to clarify_intent
    # (instead of silent failure). too_vague_reason carries the model's
    # "why I gave up" explanation so clarify_intent can ask targeted
    # questions instead of generic ones. Cap at MAX_TOO_VAGUE_ATTEMPTS=2;
    # past that we set status="refused" + a friendly message.
    too_vague_attempts: int
    too_vague_reason: Optional[str]
    # Intent bullets the model produces so user can confirm/reject each
    # — replaces the original MCQ-only clarify behavior. Each bullet:
    #   {id: "b1", text: "...", terminal_block?: "block_line_chart",
    #    preview_chart_spec?: {...}, options?: [...] (when MCQ disambiguation)}
    intent_bullets: list[dict]
    # User's per-bullet decisions echoed back from /clarify-respond.
    # Shape: {b1: {action: "ok"|"reject"|"edit", edit_text?: "..."}}
    intent_confirmations: dict[str, dict]

    # ── v15 G2: Post-plan modify request (2026-05-13) ─────────────────
    # When user clicks "改 Step N" on the confirm card, the natural-language
    # request lands here. plan_node weaves it into its next attempt as
    # additional context. Bounded by MAX_MODIFY_CYCLES=3.
    modify_requests: list[dict]
    modify_cycles: int

    # ── v16: Macro-plan + chunked compile (2026-05-14) ───────────────
    # Replaces single-shot plan_node. macro_plan_node first emits a
    # natural-language "macro plan" with 5-10 high-level steps. Each step
    # then gets compiled to 1-3 ops by compile_chunk_node in sequence.
    # Per-step validation is purely structural (no data checks) — see
    # validate_chunk in validate.py.
    #
    # Shape per item:
    #   {"step_idx": int, "text": str,
    #    "expected_kind": "table"|"chart"|"scalar"|"transform",
    #    "expected_cols": list[str] (optional, terminal steps),
    #    "completed": bool, "ops_appended": int}
    macro_plan: list[dict]
    # Cursor into macro_plan — which step compile_chunk_node will tackle next.
    current_macro_step: int
    # Per-step retry counter for compile_chunk_node failures.
    compile_attempts: dict[str, int]
    # v20 (2026-05-15): DAG schema. After each compile_chunk, record which
    # logical_ids that step produced. Downstream steps with depends_on=[parent]
    # use step_outputs[parent][-1] as the connect's src_id (instead of the
    # implicit "latest dataframe-output node" heuristic). Shape:
    #   {1: ["n1"], 2: ["n2"], 3: ["n3"], 6: ["n6"]}
    # Multi-op steps (auto-inserted unnest etc.) get all logicals appended in
    # emission order; downstream connects to the LAST element (the terminal
    # of that step's local chain).
    step_outputs: dict[int, list[str]]

    # ── v30 (2026-05-16): ReAct Pipeline Builder fields ──────────────
    # Replaces macro_plan + compile_chunk × N. See docs/spec_v30_react_pipeline_builder.md.
    #
    # phases: goal-oriented phase definitions (user-confirmed before execution).
    # Each entry: {id, goal, expected, expected_output?, why?, user_edited?}
    #   id        — phase identifier "p1"/"p2"/...
    #   goal      — natural-language outcome description ("撈 EQP-08 ...")
    #   expected  — completion category: raw_data | transform | verdict
    #               | chart | table | scalar | alarm
    #   expected_output — concrete outcome shape (v30.1, 2026-05-16):
    #       {kind: "scalar_with_context"|"chart_list"|"table"|"alarm",
    #        value_desc: str (e.g. "OOC chart 實際張數 (int)"),
    #        criterion: str (e.g. "ooc_count >= 2 視為通過"),
    #        outcome_keys: list[str] (hint for verifier extractor — keys it
    #          should try to pull from block output, e.g. ["ooc_count"])}
    #     Used by phase_spanning_verifier_node to (a) detect 1-block-multi-phase
    #     coverage and (b) populate fast-forward report with concrete values.
    #   why       — optional rationale for the phase
    #   user_edited — true when user changed the LLM-emitted goal
    v30_phases: list[dict]
    # Cursor into v30_phases — which phase react_round is operating on.
    v30_current_phase_idx: int
    # Current round counter inside the active phase. Resets per phase.
    # Bounded by MAX_REACT_ROUNDS (=8 default).
    v30_phase_round: int
    # Per-phase outcome ledger (final state when phase exits). Shape:
    #   {phase_id: {status, completed_at, rationale, verifier_check,
    #               fail_reason?, missing_capabilities?, rounds_used}}
    v30_phase_outcomes: dict[str, dict]
    # Handover state when a phase ultimately fails. None when no halt.
    # Shape: {failed_phase_id, options_offered, user_choice?, user_choice_at?,
    #         reason, tried_summary[], missing_capabilities[]}
    v30_handover: Optional[dict]
    # Track per-phase user edits for trace audit.
    # Shape: {phase_id: [{from, to, ts}]}
    v30_phase_edit_history: dict[str, list[dict]]
    # Stuck detector: last 2 actions per phase (for deterministic loop check).
    # Shape: {phase_id: [{tool, args_hash}]}
    v30_phase_recent_actions: dict[str, list[dict]]
    # v30 opt-in flag (set at request time). When True, _route_entry sends
    # the build through goal_plan_node + agentic_phase_loop instead of v27
    # macro_plan + compile_chunk path.
    v30_mode: bool
    # v30.7 (2026-05-16): debug step-mode. When True, agentic_phase_loop
    # interrupts after every ReAct round, emitting a `phase_round_paused`
    # SSE event with the full prompt + LLM response + verifier outcome +
    # canvas snapshot. Resume via POST /internal/agent/build/step-continue
    # with body {sessionId, action: "continue"|"abort"}. Lets debug step
    # through builds round-by-round without re-running the full graph.
    debug_step_mode: bool
    # Counter for emitted pauses (so resume payload can echo the round
    # being unblocked).
    v30_step_paused_at_round: Optional[int]
    # v30 C-A1: per-phase Anthropic message stack for conversation memory
    # across ReAct rounds. Without this each round is a fresh LLM call and
    # the LLM forgets what it just learned (re-inspects same blocks etc).
    # Shape: {phase_id: [{"role":"user"|"assistant", "content": [...]}]}
    # Reset to [] when current_phase_idx advances.
    v30_phase_messages: dict[str, list[dict]]
    # v30.1 (2026-05-16): fast-forward audit log. phase_spanning_verifier_node
    # appends one entry every time it auto-completes >=2 phases at once.
    # Shape: [{trigger_phase_id, advanced_by_node, advanced_by_block,
    #          phases_completed: [{id, expected, outcome, evidence: {...}}]}]
    # Read by frontend to render the fast-forward report card.
    v30_fast_forward_log: list[dict]
    # v30.1 (2026-05-16): handoff fields between agentic_phase_loop and the
    # downstream phase_spanning_verifier_node. Loop sets these after a
    # mutating action; verifier reads + clears them.
    #   v30_last_mutated_logical_id — node id touched by the just-finished
    #     tool call. None when the round did inspect_*/no-op only.
    #   v30_last_preview — full pv dict from toolset.preview() (per-port
    #     blob with chart meta etc.). Verifier extracts outcome values from
    #     this; richer than exec_trace[lid].sample which is dataframe-only.
    v30_last_mutated_logical_id: Optional[str]
    v30_last_preview: Optional[dict]
    # v30.10 (2026-05-16): B2 verifier LLM-judge rejection reason. When
    # rule-based check passes but LLM-judge says "this output doesn't satisfy
    # phase.expected_output.value_desc", the reason is stored here so the
    # CURRENT phase's next round prompt can surface it ("⚠ Verifier rejected:
    # expected '最後一次' but got 87 rows; need sort+limit") guiding LLM
    # toward completion. Cleared once phase actually advances.
    v30_last_judge_reject_reason: Optional[str]
    # v30.17j (2026-05-17): Judge deficit pause — set by phase_verifier_node
    # when actual rows are significantly below the requested count
    # quantifier in value_desc (e.g. user asked '最近 100 筆' but data source
    # only has 7). Pauses the graph via judge_clarify_pause_node + emits
    # pb_judge_clarify SSE so user can pick: continue / replan / cancel.
    # Shape: {"phase_id", "requested_n", "actual_rows", "ratio",
    #         "value_desc", "block_id"} or None.
    v30_judge_pause: Optional[dict]
    # v30.17j — record user decisions per phase so the same phase doesn't
    # ask twice if LLM tries another block that also hits deficit.
    # Shape: {"<phase_id>": "continue" | "replan" | "cancel"}.
    v30_judge_decisions: dict[str, str]
    # v30.17j — when user picks 'replan' on judge clarify, this hint is
    # prepended to the next goal_plan call so the LLM knows to relax the
    # count quantifier. Cleared after goal_plan reads it.
    v30_replan_hint: Optional[str]
    # v30.17j — how many times user has picked 'replan' on judge clarify.
    # Cap at MAX_JUDGE_REPLAN (currently 1) — past that, force-treat as
    # 'continue' so the build doesn't loop forever when LLM keeps emitting
    # the same plan that triggers deficit again.
    v30_judge_replan_count: int
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
    sse_events: Annotated[list[dict], _extend_sse]  # accumulated events for runner to flush (extend-only)
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
    debug_step_mode: bool = False,
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
        too_vague_attempts=0,
        too_vague_reason=None,
        intent_bullets=[],
        intent_confirmations={},
        modify_requests=[],
        modify_cycles=0,
        macro_plan=[],
        current_macro_step=0,
        compile_attempts={},
        step_outputs={},
        # v30
        v30_phases=[],
        v30_current_phase_idx=0,
        v30_phase_round=0,
        v30_phase_outcomes={},
        v30_handover=None,
        v30_phase_edit_history={},
        v30_phase_recent_actions={},
        v30_phase_messages={},
        v30_fast_forward_log=[],
        debug_step_mode=debug_step_mode,
        v30_step_paused_at_round=None,
        v30_last_judge_reject_reason=None,
        v30_judge_pause=None,
        v30_judge_decisions={},
        v30_replan_hint=None,
        v30_judge_replan_count=0,
    )
