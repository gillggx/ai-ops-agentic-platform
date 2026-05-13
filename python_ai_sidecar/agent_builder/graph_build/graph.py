"""StateGraph assembly + checkpointer + run/resume helpers.

Topology (matches docs/PHASE_10_BUILDER_GRAPH_V2.html):

  START → plan → validate
                  ├─ has errors  → repair_plan → validate (loop, max 2)
                  └─ ok → route_after_validate
                          ├─ FROM_SCRATCH    → confirm_gate → dispatch_op
                          └─ INCREMENTAL     → dispatch_op
                                                    │
                                                    ▼
                                              call_tool
                                                    ├─ ok    → route_after_call
                                                    └─ error → repair_op → call_tool (loop, max 2)
                                                              ├─ ok → route_after_call
                                                              └─ escalate → repair_plan
                                              route_after_call:
                                                    ├─ cursor < len → dispatch_op
                                                    └─ done         → finalize → END
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_builder.graph_build.nodes.clarify_intent import (
    clarify_intent_node,
)
from python_ai_sidecar.agent_builder.graph_build.nodes.plan import plan_node
from python_ai_sidecar.agent_builder.graph_build.nodes.macro_plan import (
    macro_plan_node,
)
from python_ai_sidecar.agent_builder.graph_build.nodes.compile_chunk import (
    compile_chunk_node,
)
from python_ai_sidecar.agent_builder.graph_build.nodes.validate import validate_plan_node
from python_ai_sidecar.agent_builder.graph_build.nodes.repair_plan import (
    MAX_PLAN_REPAIR,
    repair_plan_node,
)
from python_ai_sidecar.agent_builder.graph_build.nodes.confirm import confirm_gate_node
from python_ai_sidecar.agent_builder.graph_build.nodes.canvas_reset import canvas_reset_node
from python_ai_sidecar.agent_builder.graph_build.nodes.dispatch import dispatch_op_node
from python_ai_sidecar.agent_builder.graph_build.nodes.execute import call_tool_node
from python_ai_sidecar.agent_builder.graph_build.nodes.repair_op import (
    MAX_OP_REPAIR,
    repair_op_node,
)
from python_ai_sidecar.agent_builder.graph_build.nodes.finalize import finalize_node
from python_ai_sidecar.agent_builder.graph_build.nodes.inspect_execution import (
    inspect_execution_node,
)
from python_ai_sidecar.agent_builder.graph_build.nodes.reflect_plan import (
    MAX_REFLECT,
    reflect_plan_node,
)
from python_ai_sidecar.agent_builder.graph_build.nodes.reflect_op import (
    MAX_REFLECT_OP,
    reflect_op_node,
)
from python_ai_sidecar.agent_builder.graph_build.nodes.layout import layout_node


logger = logging.getLogger(__name__)


# ── Routing functions ──────────────────────────────────────────────────────

def _route_after_validate(state: BuildGraphState) -> str:
    """Plan good? → confirm_gate (or skip to dispatch). Errors? → repair_plan.

    skip_confirm=True (Chat Mode) bypasses confirm_gate even on FROM_SCRATCH:
    the chat conversation IS the confirmation; pausing the chat orchestrator
    mid-tool to wait for a UI click would break the conversational flow.

    Phase 11 v13 — when is_from_scratch + skip_confirm, route through
    canvas_reset first so leftover nodes from earlier build_pipeline_live
    calls don't bleed into the new build (user reported orphan-node bug).

    v16 (2026-05-14): if state.macro_plan is populated this is a chunked
    build — validate is being called per-chunk during the build loop.
    Route to compile_chunk (next step) or dispatch_op (run ops just compiled).
    """
    errors = state.get("plan_validation_errors") or []
    if errors:
        attempts = state.get("plan_repair_attempts", 0)
        if attempts >= MAX_PLAN_REPAIR:
            logger.warning("route_after_validate: plan_unfixable (attempts=%d)", attempts)
            return "finalize"  # finalize will mark status=failed since no pipeline produced
        return "repair_plan"
    # v16 chunked path: macro_plan exists → after validate (post-macro_plan
    # node), straight to confirm_gate to let user review macro before
    # committing LLM tokens on compile.
    if state.get("macro_plan") and not state.get("user_confirmed"):
        return "confirm_gate"
    if state.get("is_from_scratch"):
        if state.get("skip_confirm"):
            return "canvas_reset"
        return "confirm_gate"
    return "dispatch_op"


MAX_MODIFY_CYCLES = 3


def _route_after_confirm(state: BuildGraphState) -> str:
    """User confirmed? → canvas_reset (always — user said yes to a fresh
    build) → dispatch.
    User asked to modify (user_confirmed=None + modify_requests appended)?
      → loop back to plan_node (bounded by MAX_MODIFY_CYCLES).
    Rejected? → END (finalize w/ no-op).
    """
    if state.get("user_confirmed") is True:
        return "canvas_reset"
    # v15 G2: modify path — user_confirmed=None and modify_requests appended
    modify_cycles = state.get("modify_cycles", 0)
    if state.get("user_confirmed") is None and modify_cycles > 0:
        if modify_cycles >= MAX_MODIFY_CYCLES:
            logger.warning(
                "route_after_confirm: max modify cycles (%d) reached — finalize",
                modify_cycles,
            )
            return "finalize"
        return "plan"
    return "finalize"


def _route_after_inspect(state: BuildGraphState) -> str:
    """After inspect_execution: issues found + budget left → reflect_plan loop.
    Otherwise → layout (proceed to canvas).

    Budget: reflect_attempts < MAX_REFLECT.

    2026-05-13: We DO route on status=failed_structural — that's the most
    common LLM-build failure mode (orphan / source-less nodes from a slightly
    wrong plan), and reflect_plan with the structural_issues envelope can
    usually fix it on attempt #2. Only status=failed (zero nodes built) is
    unfixable from here.

    2026-05-14: When status='finished' (dry-run executed cleanly end-to-
    end), the pipeline is by definition workable. Any remaining
    inspection_issues are data-shape signals (single-point chart, empty
    upstream) that depend on the actual data window, NOT pipeline bugs.
    reflect_plan rewriting a working pipeline based on these soft signals
    has been observed to produce schema-invalid output — losing a good
    build for a hypothetical improvement. Skip the loop in this case.
    """
    issues = state.get("inspection_issues") or []
    if not issues:
        return "layout"
    if state.get("status") == "failed":
        # No pipeline at all — reflection has nothing to repair
        return "layout"
    if state.get("status") == "finished":
        # Build engine succeeded end-to-end. ANY rewrite via reflect_plan
        # has been observed to produce schema-invalid output (LLM JSON
        # parse failures, partial mutation that drops nodes). Whether
        # the post-build issues are soft signals (single-point chart,
        # empty data) OR a single isolated runtime fail (e.g. cpk
        # MISSING_PARAM), shipping the partial pipeline beats risking
        # the whole build with a speculative rewrite.
        kinds = {i.get("kind") for i in issues}
        logger.info(
            "route_after_inspect: status=finished, %d issue(s) of kinds=%s — "
            "shipping build as-is (skipping reflect_plan)",
            len(issues), sorted(kinds),
        )
        return "layout"
    attempts = state.get("reflect_attempts", 0)
    if attempts >= MAX_REFLECT:
        logger.warning("route_after_inspect: max reflect attempts (%d) — shipping partial fix", attempts)
        return "layout"
    return "reflect_plan"


def _route_after_call(state: BuildGraphState) -> str:
    """Per-op routing after call_tool ran:
       - last op errored → repair_op (schema-level fix, existing)
       - last op ok BUT exec_trace shows data issue → reflect_op (NEW v8,
         per-op semantic patch; budgeted per logical id)
       - last op ok and more ops in current plan → dispatch_op
       - last op ok and plan done BUT more macro steps → compile_chunk
       - all done → finalize
    """
    cursor = state.get("cursor", 0)
    plan = state.get("plan") or []

    # cursor was advanced on success in call_tool_node → look at cursor-1 to
    # see what just ran. On error, cursor was NOT advanced.
    if cursor < len(plan):
        last = plan[cursor]  # current cursor still points to the failing op
        if last.get("result_status") == "error":
            attempts = int(last.get("repair_attempts") or 0)
            if attempts >= MAX_OP_REPAIR:
                logger.warning("route_after_call: cursor=%d escalating to repair_plan", cursor)
                return "repair_plan"
            return "repair_op"

    # ── v8 (2026-05-13): per-op semantic check ──────────────────────────
    # call_tool's _detect_op_issue may have set last_op_issue. Route to
    # reflect_op if there's budget left. Failed reflect_op clears the
    # flag, so we fallthrough to dispatch on next pass.
    issue = state.get("last_op_issue")
    if isinstance(issue, dict) and issue.get("node_id"):
        attempts_map = state.get("reflect_op_attempts") or {}
        lid = issue["node_id"]
        attempts = int(attempts_map.get(lid, 0))
        if attempts < MAX_REFLECT_OP:
            return "reflect_op"
        # Budget exhausted — log and fallthrough to next op or finalize.
        # Don't return now; let cursor logic decide between dispatch / finalize.
        logger.info("route_after_call: %s exceeded reflect_op budget (%d); fallthrough",
                    lid, attempts)

    # All ops done?
    if cursor >= len(plan):
        # v16: if we're in a chunked build and still have macro steps to
        # compile, route back to compile_chunk_node. current_macro_step
        # gets incremented by the route function below since compile_chunk
        # always operates on macro_plan[current_macro_step] and we just
        # finished that step's ops.
        macro_plan = state.get("macro_plan") or []
        idx = state.get("current_macro_step", 0)
        if macro_plan and idx + 1 < len(macro_plan):
            return "next_chunk"
        return "finalize"
    return "dispatch_op"


def _route_after_compile_chunk(state: BuildGraphState) -> str:
    """compile_chunk failed validation (col-ref / dedup) but hasn't hit
    MAX_COMPILE_ATTEMPTS yet → loop back to compile_chunk to retry.

    Without this, validator-rejected steps left the plan unchanged,
    cursor stayed at len(plan), and _route_after_call advanced to the
    NEXT macro step — silently skipping the filter / chart steps
    needed to make the pipeline correct. canvas ends with 3 of 5
    intended nodes and no terminal block.

    Compile_chunk_node itself enforces MAX_COMPILE_ATTEMPTS (returns
    status='failed' when exceeded), so this loop is bounded.
    """
    errors = state.get("plan_validation_errors") or []
    if errors and state.get("status") != "failed":
        return "compile_chunk"
    return "dispatch_op"


def _route_after_macro_plan(state: BuildGraphState) -> str:
    """After macro_plan_node: if too_vague (status=failed) → finalize.
    Otherwise → confirm_gate so user reviews the macro plan before any
    compile work happens.

    EXCEPTION: when skip_confirm=True (chat / skill-translate / any caller
    without a confirm UI), skip confirm_gate entirely and go straight to
    canvas_reset → compile_chunk. Without this guard the graph hits
    confirm_gate's interrupt() with no way to resume, leaving the build
    paused with 0 ops produced — but the caller thinks it succeeded
    (saw macro_plan_proposed event and returned).
    """
    if state.get("status") == "failed" or not state.get("macro_plan"):
        return "finalize"
    if state.get("skip_confirm"):
        return "canvas_reset"
    return "confirm_gate"


def _advance_macro_step(state: BuildGraphState) -> dict[str, Any]:
    """Increment current_macro_step + reset per-step state.

    Before this fix, when one step exhausted MAX_COMPILE_ATTEMPTS and
    compile_chunk returned status='failed', that status stuck to ALL
    subsequent steps. _route_after_compile_chunk's check
    `status != 'failed'` then bypassed retry for every later step on
    its first validation failure — those steps got only 1 attempt and
    couldn't recover. Result: 5/6 macro steps stuck on first error.

    Reset status and plan_validation_errors so the next step starts
    clean. compile_attempts is keyed by step_key so it doesn't need
    reset.
    """
    idx = state.get("current_macro_step", 0)
    logger.info("advance_macro_step: %d → %d", idx, idx + 1)
    return {
        "current_macro_step": idx + 1,
        "status": "running",
        "plan_validation_errors": [],
    }


# ── Build the graph (cached) ───────────────────────────────────────────────

_compiled = None


def build_graph():
    """Compile the StateGraph once and cache it. Checkpointer = MemorySaver
    (in-process). Sidecar restart drops paused sessions — same as the v1
    behaviour, see _PAUSED_SESSIONS in orchestrator.py.
    """
    global _compiled
    if _compiled is not None:
        return _compiled

    g: StateGraph = StateGraph(BuildGraphState)
    g.add_node("clarify_intent", clarify_intent_node)
    g.add_node("plan", plan_node)
    # v16 (2026-05-14): macro-plan + chunked-compile architecture
    g.add_node("macro_plan", macro_plan_node)
    g.add_node("compile_chunk", compile_chunk_node)
    g.add_node("advance_macro_step", _advance_macro_step)
    g.add_node("validate", validate_plan_node)
    g.add_node("repair_plan", repair_plan_node)
    g.add_node("confirm_gate", confirm_gate_node)
    g.add_node("canvas_reset", canvas_reset_node)
    g.add_node("dispatch_op", dispatch_op_node)
    g.add_node("call_tool", call_tool_node)
    g.add_node("repair_op", repair_op_node)
    g.add_node("finalize", finalize_node)
    g.add_node("inspect_execution", inspect_execution_node)
    g.add_node("reflect_plan", reflect_plan_node)
    g.add_node("reflect_op", reflect_op_node)
    g.add_node("layout", layout_node)

    # v15 G1 + v16: clarify_intent first; then macro_plan (replaces 1-shot
    # plan_node). plan_node remains in the graph for v15 modify-request
    # replan path (route_after_confirm → "plan") but new builds enter via
    # macro_plan. macro_plan skips validate (plan is empty at this point —
    # compile_chunk will build it up; validate runs at chunk boundaries).
    g.add_edge(START, "clarify_intent")
    g.add_edge("clarify_intent", "macro_plan")
    g.add_conditional_edges(
        "macro_plan",
        _route_after_macro_plan,
        {
            "confirm_gate": "confirm_gate",
            "canvas_reset": "canvas_reset",
            "finalize": "finalize",
        },
    )
    g.add_edge("plan", "validate")  # legacy replan path
    g.add_conditional_edges(
        "validate",
        _route_after_validate,
        {
            "repair_plan": "repair_plan",
            "confirm_gate": "confirm_gate",
            "canvas_reset": "canvas_reset",
            "dispatch_op": "dispatch_op",
            "finalize": "finalize",
        },
    )
    g.add_edge("repair_plan", "validate")
    g.add_conditional_edges(
        "confirm_gate",
        _route_after_confirm,
        {
            "canvas_reset": "canvas_reset",
            "finalize": "finalize",
            "plan": "plan",  # v15 G2: modify requested → replan
        },
    )
    # canvas_reset → compile_chunk (v16) — start the chunked compile loop.
    # First compile_chunk produces ops, dispatch_op walks them, eventually
    # call_tool routes back to compile_chunk via advance_macro_step until
    # all macro steps are done.
    g.add_edge("canvas_reset", "compile_chunk")
    # compile_chunk → dispatch_op when ops compiled cleanly; otherwise
    # loop back to compile_chunk to retry (deterministic col-ref /
    # dedup validators rejected the ops). compile_chunk_node enforces
    # MAX_COMPILE_ATTEMPTS internally, so this can't infinite-loop.
    g.add_conditional_edges(
        "compile_chunk",
        _route_after_compile_chunk,
        {
            "compile_chunk": "compile_chunk",
            "dispatch_op": "dispatch_op",
        },
    )
    # advance_macro_step → compile_chunk (bumps current_macro_step then
    # re-enters compile loop for next macro step's ops)
    g.add_edge("advance_macro_step", "compile_chunk")
    g.add_edge("dispatch_op", "call_tool")
    g.add_conditional_edges(
        "call_tool",
        _route_after_call,
        {
            "dispatch_op": "dispatch_op",
            "repair_op": "repair_op",
            "reflect_op": "reflect_op",
            "repair_plan": "repair_plan",
            "finalize": "finalize",
            "next_chunk": "advance_macro_step",  # v16: bump idx + compile next
        },
    )
    g.add_edge("repair_op", "call_tool")
    # v8: reflect_op patches the failing op + rewinds cursor; loop back
    # to dispatch so call_tool re-runs the patched op. If reflect_op
    # bails (budget / parse fail / rollback distance exceeded), cursor
    # may already be past plan length — route via _route_after_call so
    # we cleanly hand off to next_chunk / finalize / dispatch_op instead
    # of unconditionally dispatching into an out-of-bounds plan[cursor].
    g.add_conditional_edges(
        "reflect_op",
        _route_after_call,
        {
            "dispatch_op": "dispatch_op",
            "repair_op": "repair_op",
            "reflect_op": "reflect_op",
            "repair_plan": "repair_plan",
            "finalize": "finalize",
            "next_chunk": "advance_macro_step",
        },
    )
    # Self-correction loop (2026-05-13):
    #   finalize → inspect_execution
    #     ├─ no issues / budget exhausted → layout → END
    #     └─ semantic issue + budget left → reflect_plan → validate (loop)
    g.add_edge("finalize", "inspect_execution")
    g.add_conditional_edges(
        "inspect_execution",
        _route_after_inspect,
        {"reflect_plan": "reflect_plan", "layout": "layout"},
    )
    g.add_edge("reflect_plan", "validate")
    g.add_edge("layout", END)

    checkpointer = MemorySaver()
    _compiled = g.compile(checkpointer=checkpointer)
    return _compiled
