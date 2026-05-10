"""tool_execute node — runs tools via the existing ToolDispatcher.

Handles:
  - Preflight validation (MISSING_MCP_NAME, MISSING_PARAMS, etc.)
  - Tool execution via dispatcher.execute()
  - Programmatic data distillation
  - Render card building (for SSE tool_done events)
  - Chart rendered notification (sets chart_already_rendered flag)
  - Result trimming for LLM context (large results truncated)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List
from langchain_core.runnables import RunnableConfig

from langchain_core.messages import AIMessage, ToolMessage

logger = logging.getLogger(__name__)


async def _execute_build_pipeline(
    db: Any,
    tool_input: Dict[str, Any],
    event_emit: Any = None,
) -> Dict[str, Any]:
    """Phase 5: run an LLM-built pb_pipeline via Pipeline Builder's executor.

    Returns the same contract as /api/v1/pipeline-builder/execute so the chat
    render card can display result_summary (triggered / evidence / charts /
    data_views) — identical to what the /admin/pipeline-builder "Run Full"
    button produces.

    Phase 5-UX-5: `event_emit` is a sync callback taking dict events emitted
    by the executor (pb_run_start / pb_node_start / pb_node_done / pb_run_done).
    Used to stream per-node progress into the chat SSE channel so the canvas
    can animate node-by-node.
    """
    from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
    from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry
    from python_ai_sidecar.pipeline_builder.executor import PipelineExecutor
    from python_ai_sidecar.pipeline_builder.validator import PipelineValidator

    raw_pipeline = tool_input.get("pipeline_json") or {}
    inputs_map = tool_input.get("inputs") or {}

    try:
        pipeline_json = PipelineJSON.model_validate(raw_pipeline)
    except Exception as e:  # noqa: BLE001
        return {
            "status": "validation_error",
            "error_message": f"pipeline_json failed schema parse: {e}",
        }

    # Phase 5-UX-5: emit the DAG structure before we validate/run so the
    # frontend can render grey-pending nodes immediately.
    if event_emit is not None:
        try:
            event_emit({
                "type": "pb_structure",
                "pipeline_json": raw_pipeline,
            })
        except Exception:  # noqa: BLE001
            pass

    # Load registry (reuse session's DB)
    registry = BlockRegistry()
    try:
        await registry.load_from_db(db)
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error_message": f"BlockRegistry load failed: {e}"}

    # Validate first — return structured errors so LLM can retry
    validator = PipelineValidator(registry.catalog)
    errors = validator.validate(pipeline_json)
    if errors:
        return {
            "status": "validation_error",
            "errors": errors,
            "error_message": (
                f"Pipeline validation failed ({len(errors)} error(s)). "
                "Fix the nodes/edges and call build_pipeline again."
            ),
        }

    # Execute — ad-hoc (pipeline_id=None, no telemetry bump)
    executor = PipelineExecutor(registry)
    try:
        result = await executor.execute(
            pipeline_json,
            inputs=inputs_map or None,
            on_event=event_emit,  # Phase 5-UX-5: stream per-node events
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("build_pipeline executor crash")
        return {"status": "failed", "error_message": f"Executor crashed: {type(e).__name__}: {e}"}

    # Shape result to match dispatcher's expected envelope
    return {
        "status": result.get("status", "failed"),
        "run_id": result.get("run_id"),
        "node_results": result.get("node_results") or {},
        "error_message": result.get("error_message"),
        "result_summary": result.get("result_summary"),
        # Compact summary for LLM context (avoid dumping full evidence table)
        "llm_readable_data": _summarize_for_llm(result),
    }


# ── Phase 11 v18: chat-injected notes scrubber ───────────────────────
#
# The chat orchestrator's LLM auto-fills `notes` when calling
# build_pipeline_live, often pulling from active_alarms / context snapshot.
# That content frequently contradicts the user's actual instruction
# (e.g. user said「用 $tool_id parametric」but chat agent appended
# 「當前告警涉及 EQP-09 / EQP-03，需對各機台分別查詢」).
#
# This helper applies deterministic filters on `notes` BEFORE it reaches
# the inner builder. Two layers:
#   (1) Drop lines containing literal tool/lot/step IDs IF the canvas
#       already has a declared input of the same role (so $tool_id is
#       respected, not overridden).
#   (2) Drop lines that prescribe a specific block_X to use OR contain
#       structural directives like「需對各機台分別查詢」— those are
#       builder's responsibility.
#
# Conservative — only matches well-known patterns. User's legitimate
# qualitative notes (time-range, qualitative filter) pass through.

_LITERAL_ID_PATTERNS = [
    # role  -> regex to detect literal IDs of that kind
    ("tool_id",     re.compile(r"\bEQP-\d+\b", re.IGNORECASE)),
    ("equipment_id", re.compile(r"\bEQP-\d+\b", re.IGNORECASE)),
    ("lot_id",      re.compile(r"\bLOT-\d+\b", re.IGNORECASE)),
    ("step",        re.compile(r"\bSTEP_\d+\b", re.IGNORECASE)),
    ("chamber_id",  re.compile(r"\bCH-[A-Z0-9]+\b", re.IGNORECASE)),
    ("recipe_id",   re.compile(r"\bRECIPE-[A-Z0-9-]+\b", re.IGNORECASE)),
]

_BLOCK_REC_RE = re.compile(r"\bblock_[a-z_][a-z0-9_]*\b", re.IGNORECASE)
_DIRECTIVE_PATTERNS = [
    re.compile(r"需對各機台.*?查詢"),
    re.compile(r"分別查詢"),
    re.compile(r"預期用\s*block_"),
    re.compile(r"建議用\s*block_"),
    re.compile(r"應該用\s*block_"),
    re.compile(r"請用\s*block_"),
]


def _scrub_chat_notes(notes: str, base_pipeline: dict | None) -> tuple[str, list[str]]:
    """Filter chat-injected notes against canvas-declared inputs + structural
    directives. Returns (scrubbed_notes, dropped_lines). When notes is empty
    or no filters trigger, returns the input unchanged."""
    if not notes:
        return notes, []
    declared_names: set[str] = set()
    if isinstance(base_pipeline, dict):
        for inp in (base_pipeline.get("inputs") or []):
            if isinstance(inp, dict):
                nm = inp.get("name")
                if nm:
                    declared_names.add(nm)

    kept: list[str] = []
    dropped: list[str] = []
    for raw_line in notes.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            kept.append(line)
            continue
        drop_reason = None

        # (1) literal IDs that conflict with declared inputs
        for role, pat in _LITERAL_ID_PATTERNS:
            if role in declared_names and pat.search(line):
                drop_reason = f"literal {role} conflicts with declared $name"
                break

        # (2) explicit block prescription
        if drop_reason is None and _BLOCK_REC_RE.search(line):
            drop_reason = "prescribes specific block_X (builder decides)"

        # (3) structural directives
        if drop_reason is None:
            for pat in _DIRECTIVE_PATTERNS:
                if pat.search(line):
                    drop_reason = "structural directive (builder decides)"
                    break

        if drop_reason:
            dropped.append(f"{line}    # dropped: {drop_reason}")
        else:
            kept.append(line)

    return "\n".join(kept).strip(), dropped


_CONJUNCTION_DEDUPE_PATTERNS = [
    # Pairs of "$X 和 $X" / "$X 與 $X" / "$X、$X" / "$X, $X" → "$X"
    # Run these AFTER substitution so we collapse repeated parametric refs.
    (re.compile(r"(\$\w+)\s*[、,]\s*\$\w+"), r"\1"),
    (re.compile(r"(\$\w+)\s*[和與]\s*\$\w+"), r"\1"),
    (re.compile(r"(\$\w+)\s+and\s+\$\w+", re.IGNORECASE), r"\1"),
]

# Map of declared-input ROLE → regex for the corresponding literal ID kind.
# Used by _scrub_chat_goal: when role is in declared_names, replace each
# literal match with `$<role>` so the LLM uses parametric refs.
_LITERAL_ROLE_PATTERNS = [
    ("tool_id",      re.compile(r"\bEQP-\d+\b", re.IGNORECASE)),
    ("equipment_id", re.compile(r"\bEQP-\d+\b", re.IGNORECASE)),
    ("lot_id",       re.compile(r"\bLOT-\d+\b", re.IGNORECASE)),
    ("step",         re.compile(r"\bSTEP_\d+\b", re.IGNORECASE)),
    ("chamber_id",   re.compile(r"\bCH-[A-Z0-9]+\b", re.IGNORECASE)),
    ("recipe_id",    re.compile(r"\bRECIPE-[A-Z0-9-]+\b", re.IGNORECASE)),
]


def _scrub_chat_goal(goal: str, base_pipeline: dict | None) -> tuple[str, list[str]]:
    """Replace literal IDs in `goal` with $name refs when canvas has
    a declared input of the same role. Then dedupe conjunctions like
    「$tool_id 和 $tool_id」 down to a single ref.

    Per CLAUDE.md「flow 由 graph 決定」: chat orchestrator may auto-
    expand「EQP」→「EQP-09 和 EQP-03」(active alarm context), but the
    inner builder is single-tool parametric (scheduler fan-out handles
    multi-tool). This scrubber enforces that invariant deterministically.

    Returns (scrubbed_goal, change_log).
    """
    if not goal or not isinstance(base_pipeline, dict):
        return goal, []
    declared_names: set[str] = set()
    for inp in (base_pipeline.get("inputs") or []):
        if isinstance(inp, dict):
            nm = inp.get("name")
            if nm:
                declared_names.add(nm)
    if not declared_names:
        return goal, []

    changes: list[str] = []
    out = goal
    for role, pat in _LITERAL_ROLE_PATTERNS:
        if role not in declared_names:
            continue
        matches = list(pat.finditer(out))
        if not matches:
            continue
        # Replace each match with $role
        unique_literals = sorted({m.group(0) for m in matches})
        out = pat.sub(f"${role}", out)
        changes.append(
            f"replaced {unique_literals} → ${role} (declared input)"
        )

    # Dedupe collapsed conjunctions iteratively until stable
    for _ in range(5):  # safety cap
        prev = out
        for dedupe_pat, repl in _CONJUNCTION_DEDUPE_PATTERNS:
            out = dedupe_pat.sub(repl, out)
        if out == prev:
            break
    if out != goal and not changes:
        # Conjunction-only collapse without literal replacement (rare)
        changes.append("collapsed redundant $name conjunctions")
    elif out != goal:
        # Note that conjunctions were also collapsed (informational)
        if any(c in goal for c in ("和", "與", "、", ", ")):
            changes.append("collapsed conjunctions like「X 和 Y」 → single $ref")

    return out, changes


async def _execute_build_pipeline_live(
    db: Any,
    tool_input: Dict[str, Any],
    event_emit: Any = None,
    chat_session_id: Any = None,
    chat_user_id: Any = None,
    chat_user_message: str = "",
) -> Dict[str, Any]:
    """Phase 10-B: unified build via graph_build (LangGraph 10-node state machine).

    Both Builder Mode (/agent/build) and Chat Mode (this tool) share the
    same engine. Chat passes skip_confirm=True so the graph never pauses
    on confirm_gate — the chat conversation IS the confirmation.

    show_plan=True: dry-run only — runs plan_node + validate_plan_node,
    returns the plan as a tool result for the chat LLM to narrate. No
    canvas mutation, no SSE events. Used when user explicitly asks
    "先給我看 plan".
    """
    from python_ai_sidecar.agent_builder.graph_build import (
        stream_graph_build, dry_run_plan,
    )
    from python_ai_sidecar.agent_builder.event_wrapper import wrap_build_event_for_chat
    from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON

    goal = (tool_input.get("goal") or "").strip()
    notes = (tool_input.get("notes") or "").strip()
    base_pipeline_id = tool_input.get("base_pipeline_id")
    show_plan = bool(tool_input.get("show_plan"))
    # Phase 11 v6 — set by tool_execute when canvas snapshot _kind="skill_step".
    # Threads through to stream_graph_build so validate node enforces
    # block_step_check terminator (= what SkillRunner reads pass/fail from).
    skill_step_mode = bool(tool_input.get("_skill_step_mode"))
    if not goal:
        return {"status": "validation_error", "error_message": "goal is required"}

    # ── Resolve base pipeline ─────────────────────────────────────────
    # Same precedence as before: explicit base_pipeline_id (Java DB lookup) >
    # builder-mode canvas snapshot > clean slate.
    from python_ai_sidecar.clients.java_client import JavaAPIClient
    from python_ai_sidecar.config import CONFIG
    java = JavaAPIClient(
        CONFIG.java_api_url,
        CONFIG.java_internal_token,
        timeout_sec=CONFIG.java_timeout_sec,
    )

    base_pipeline_dict: Any = None
    base_source = "none"
    if base_pipeline_id is not None:
        try:
            import json as _json
            row = await java.get_pipeline(int(base_pipeline_id))
            raw = (row or {}).get("pipelineJson") or (row or {}).get("pipeline_json")
            if raw:
                pj = PipelineJSON.model_validate(_json.loads(raw))
                base_pipeline_dict = pj.model_dump(by_alias=True)
                base_source = f"pipeline#{base_pipeline_id}"
        except Exception as e:  # noqa: BLE001
            logger.warning("base_pipeline load failed (ignored): %s", e)

    if base_pipeline_dict is None:
        canvas_snap = tool_input.get("_state_pipeline_snapshot")
        if canvas_snap and (canvas_snap.get("nodes") or canvas_snap.get("inputs")):
            try:
                pj = PipelineJSON.model_validate(canvas_snap)
                base_pipeline_dict = pj.model_dump(by_alias=True)
                base_source = "canvas_snapshot"
            except Exception as e:  # noqa: BLE001
                logger.warning("canvas_snapshot validate failed (ignored): %s", e)

    logger.info("build_pipeline_live: base=%s, show_plan=%s, goal=%r",
                base_source, show_plan, goal[:80])

    # ── Phase 11 v18: deterministic notes filter ──────────────────────
    # Strip auto-generated chat-context that conflicts with user intent
    # (literal tool/lot/step IDs that override declared $name parametric
    # inputs; specific block recommendations that override builder's choice;
    # 「需對各機台分別查詢」-style structural directives). Per CLAUDE.md
    # 「flow 由 graph 決定」: chat agent's free interpretation is bounded
    # by this graph-level filter, not by prompt rules alone.
    filtered_notes, dropped_lines = _scrub_chat_notes(notes, base_pipeline_dict)
    if dropped_lines:
        logger.info("notes_filter raw=%r filtered=%r dropped=%r",
                    notes, filtered_notes, dropped_lines)

    # ── Phase 11 v19: scrub `goal` itself ─────────────────────────────
    # The chat orchestrator sometimes hardcodes literal tool IDs INTO the
    # goal field (not just notes), e.g. user said「過去 EQP 24h」→ chat
    # expands to「EQP-09 和 EQP-03 過去 24h」using active-alarm context.
    # Replace such literals with `$name` when matching declared input
    # exists, then collapse「$X 和 $X」conjunctions.
    scrubbed_goal, goal_changes = _scrub_chat_goal(goal, base_pipeline_dict)
    if goal_changes:
        logger.info("goal_scrub raw=%r scrubbed=%r changes=%r",
                    goal, scrubbed_goal, goal_changes)

    # 2026-05-11: parse [intent_confirmed:<id> dim=val ...] resolutions from
    # the user's follow-up message and splice deterministic guidance into
    # the goal. This is how Plan-Mode-style multi-choice picks reach the
    # builder — without LLM having to remember to translate them.
    from python_ai_sidecar.agent_orchestrator_v2.dimensional_clarifier import (
        parse_resolutions_from_prefix, augment_goal_for_resolutions,
    )
    resolutions = parse_resolutions_from_prefix(chat_user_message)
    if resolutions:
        scrubbed_goal = augment_goal_for_resolutions(scrubbed_goal, resolutions)
        logger.info("build_pipeline_live: applied %d resolution hints: %s",
                    len(resolutions), resolutions)

    prompt = scrubbed_goal if not filtered_notes else f"{scrubbed_goal}\n\n補充 context:\n{filtered_notes}"

    # ── show_plan path: dry-run, no mutation, no SSE ──────────────────
    if show_plan:
        try:
            dr = await dry_run_plan(
                instruction=prompt,
                base_pipeline=base_pipeline_dict,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("build_pipeline_live dry_run_plan crashed")
            return {"status": "failed",
                    "error_message": f"plan dry-run crashed: {type(e).__name__}: {e}"}

        # Compact plan summary the chat LLM can read aloud.
        ops_summaries = [_op_one_liner(op) for op in (dr.get("plan") or [])]
        return {
            "status": "plan_only",
            "plan_summary": dr.get("summary") or "",
            "ops": ops_summaries,
            "n_ops": dr.get("n_ops") or 0,
            "validation_errors": dr.get("validation_errors") or [],
            "ok": bool(dr.get("ok")),
            "next_step_hint": (
                "念出 plan 給 user，問他要不要 build。同意 → 再呼叫一次 build_pipeline_live "
                "（show_plan=false 或省略），相同 goal。"
            ),
        }

    # ── Normal build path: stream graph with skip_confirm=True ────────
    import uuid as _uuid
    sid = str(_uuid.uuid4())

    if event_emit is not None:
        try:
            event_emit({"type": "pb_glass_start", "session_id": sid, "goal": goal})
        except Exception:  # noqa: BLE001
            pass

    op_count = 0
    last_status: str = "running"
    final_pipeline: Any = base_pipeline_dict
    try:
        async for evt in stream_graph_build(
            instruction=prompt,
            base_pipeline=base_pipeline_dict,
            session_id=sid,
            skip_confirm=True,  # chat conversation IS the confirmation
            skill_step_mode=skill_step_mode,
        ):
            payload = wrap_build_event_for_chat(evt, sid)
            if payload is None:
                continue
            if payload["type"] == "pb_glass_op":
                op_count += 1
            elif payload["type"] == "pb_glass_done":
                last_status = payload.get("status") or last_status
            if event_emit is not None:
                try:
                    event_emit(payload)
                except Exception:  # noqa: BLE001
                    pass
            # The graph's `done` StreamEvent carries the final pipeline_json —
            # capture from it when wrap returned a pb_glass_done.
            if evt.type == "done" and evt.data:
                final_pipeline = evt.data.get("pipeline_json") or final_pipeline
                last_status = evt.data.get("status") or last_status
    except Exception as e:  # noqa: BLE001
        logger.exception("build_pipeline_live graph crashed")
        return {"status": "failed",
                "error_message": f"graph crashed: {type(e).__name__}: {e}"}

    if final_pipeline is None:
        # Graph never finalized — return what we have.
        final_pipeline = base_pipeline_dict or {
            "version": "1.0", "nodes": [], "edges": [], "metadata": {}, "inputs": [],
        }

    # Safety net: scan once more for undeclared $placeholder refs. The graph's
    # call_tool_node already rejects bad refs at add_node/set_param time, but
    # if the base_pipeline came in with stale placeholders this catches them.
    placeholder_errors: list[dict[str, Any]] = []
    try:
        from python_ai_sidecar.pipeline_builder.validator import PipelineValidator
        from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
        seedless = SeedlessBlockRegistry()
        seedless.load()
        validator_safety = PipelineValidator(seedless.catalog)
        all_errors = validator_safety.validate(final_pipeline)
        placeholder_errors = [
            e for e in all_errors if e.get("rule") == "C10_UNDECLARED_INPUT_REF"
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("post-build safety validator crashed: %s", exc)

    if placeholder_errors:
        last_status = "validation_error"
        if event_emit is not None:
            try:
                event_emit({
                    "type": "pb_glass_error",
                    "session_id": sid,
                    "op": "post_build_validate",
                    "message": (
                        f"Pipeline has {len(placeholder_errors)} undeclared "
                        f"placeholder reference(s). Canvas not committed."
                    ),
                    "hint": "; ".join(e["message"] for e in placeholder_errors[:3]),
                })
            except Exception:  # noqa: BLE001
                pass

    nodes_n = len(final_pipeline.get("nodes") or [])
    summary_text = f"已建立 pipeline（{nodes_n} nodes, {op_count} operations）"
    result_dict: Dict[str, Any] = {
        "status": last_status,
        "pipeline_json": final_pipeline,
        "summary": summary_text,
        "node_count": nodes_n,
        "edge_count": len(final_pipeline.get("edges") or []),
        "run_status": last_status,
        "llm_readable_data": {
            "goal": goal,
            "final_status": last_status,
            "nodes_built": nodes_n,
            "operations_taken": op_count,
            "summary_for_user": summary_text,
        },
    }
    if placeholder_errors:
        result_dict["validation_errors"] = placeholder_errors
        result_dict["error_message"] = (
            f"Build rejected — {len(placeholder_errors)} placeholder reference(s) "
            "are undeclared. Either declare the input via declare_input(), "
            "rewrite to a literal value, or use canonical $tool_id."
        )
    return result_dict


def _op_one_liner(op_dict: Dict[str, Any]) -> str:
    """Compact human-readable summary of one Op (for show_plan tool result)."""
    t = op_dict.get("type", "?")
    if t == "add_node":
        return f"add {op_dict.get('block_id')} (as {op_dict.get('node_id', '?')})"
    if t == "connect":
        return (
            f"connect {op_dict.get('src_id')}.{op_dict.get('src_port')} → "
            f"{op_dict.get('dst_id')}.{op_dict.get('dst_port')}"
        )
    if t == "set_param":
        p = op_dict.get("params") or {}
        return f"{op_dict.get('node_id')}.{p.get('key', '?')} = {p.get('value', '?')!r}"
    if t == "remove_node":
        return f"remove {op_dict.get('node_id')}"
    if t == "run_preview":
        return f"preview {op_dict.get('node_id')}"
    return t


async def _execute_propose_pipeline_patch(
    db: Any,
    tool_input: Dict[str, Any],
) -> Dict[str, Any]:
    """Phase 5-UX-5 Copilot: validate patches + return a proposal envelope.

    Does NOT mutate anything — frontend renders the proposal card and the user
    clicks 'Apply' to actually touch the canvas.

    Validates:
      - patches non-empty
      - each op is one of the allowed verbs
      - block_id (for insert_*) exists in the registry
    Returns:
      {status, patches, reason, errors?} — frontend surfaces to user.
    """
    from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry

    raw_patches = tool_input.get("patches") or []
    reason = tool_input.get("reason") or ""
    if not isinstance(raw_patches, list) or not raw_patches:
        return {"status": "validation_error", "error_message": "patches must be a non-empty list"}

    registry = BlockRegistry()
    try:
        await registry.load_from_db(db)
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error_message": f"BlockRegistry load failed: {e}"}

    allowed_ops = {"insert_after", "insert_before", "update_params", "delete_node", "connect_edge"}
    errors: list[dict[str, Any]] = []
    for i, p in enumerate(raw_patches):
        if not isinstance(p, dict):
            errors.append({"index": i, "message": "patch must be an object"})
            continue
        op = p.get("op")
        if op not in allowed_ops:
            errors.append({"index": i, "message": f"invalid op '{op}'"})
            continue
        if op in ("insert_after", "insert_before"):
            block_id = p.get("block_id")
            block_version = p.get("block_version") or "1.0.0"
            if not block_id:
                errors.append({"index": i, "message": f"{op} requires block_id"})
                continue
            if registry.get_spec(block_id, block_version) is None:
                errors.append({"index": i, "message": f"block_id '{block_id}@{block_version}' not found"})

    if errors:
        return {
            "status": "validation_error",
            "errors": errors,
            "error_message": f"{len(errors)} patch(es) failed validation",
        }

    # Proposal is valid structurally; return for frontend rendering.
    return {
        "status": "success",
        "reason": reason,
        "patches": raw_patches,
        "llm_readable_data": {
            "proposal_submitted": True,
            "patch_count": len(raw_patches),
            "ops": [p.get("op") for p in raw_patches],
            "awaiting_user_approval": True,
            # Hint to LLM: don't repeat the proposal next turn, wait for user response.
        },
    }


def _summarize_for_llm(result: Dict[str, Any]) -> Dict[str, Any]:
    """Condensed result for LLM — skip raw rows, keep key facts."""
    summary = result.get("result_summary") or {}
    charts = summary.get("charts") or [] if isinstance(summary, dict) else []
    data_views = summary.get("data_views") or [] if isinstance(summary, dict) else []
    return {
        "triggered": bool(summary.get("triggered")) if isinstance(summary, dict) else False,
        "evidence_rows": summary.get("evidence_rows", 0) if isinstance(summary, dict) else 0,
        "evidence_node_id": summary.get("evidence_node_id") if isinstance(summary, dict) else None,
        "chart_count": len(charts),
        "chart_titles": [c.get("title") for c in charts][:5],
        "data_view_count": len(data_views),
        "data_view_titles": [v.get("title") for v in data_views][:5],
        "node_status_counts": {
            s: sum(1 for nr in (result.get("node_results") or {}).values() if nr.get("status") == s)
            for s in ("success", "failed", "skipped")
        },
    }


async def tool_execute_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Execute all tool_calls from the last AIMessage.

    Returns tool result messages + updated state (tools_used, render_cards, flags).
    """
    db = config["configurable"]["db"]
    base_url = config["configurable"]["base_url"]
    auth_token = config["configurable"]["auth_token"]
    user_id = config["configurable"]["user_id"]
    # Phase 5-UX-5: optional SSE event sink — agent_chat_router injects a sync
    # callback here so tool-level lifecycle events (pb_structure / pb_node_*)
    # can stream out to the chat UI for progressive canvas animation.
    event_emit = config["configurable"].get("pb_event_emit")

    # Import here to avoid circular imports at module level
    from python_ai_sidecar.agent_orchestrator_v2.helpers import (
        _preflight_validate,
        _is_spc_result,
        _result_summary,
    )
    from python_ai_sidecar.agent_orchestrator_v2.render_card import _build_render_card
    from python_ai_sidecar.agent_helpers_native.data_distillation_service import DataDistillationService
    from python_ai_sidecar.agent_helpers.tool_dispatcher import ToolDispatcher

    # Get the last AI message's tool_calls
    messages = state["messages"]
    last_msg = messages[-1] if messages else None
    if not last_msg or not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return {}

    # Phase 8-A-1d: ToolDispatcher accepts a Java client so its mcp_id /
    # save_memory / search_memory paths can route through Java when no
    # local AsyncSession is supplied (chat native mode).
    from python_ai_sidecar.clients.java_client import JavaAPIClient
    from python_ai_sidecar.config import CONFIG
    java = JavaAPIClient(
        CONFIG.java_api_url, CONFIG.java_internal_token,
        timeout_sec=CONFIG.java_timeout_sec,
    )
    dispatcher = ToolDispatcher(
        db=db,
        base_url=base_url,
        auth_token=auth_token,
        user_id=user_id,
        java=java,
    )
    distill_svc = DataDistillationService()

    # Allow AIMessage too (e.g. clean follow-up text after confirm_pipeline_intent
    # so synthesis doesn't dump the raw tool-result JSON as the final answer).
    tool_messages: List[Any] = []
    new_tools_used: List[Dict[str, Any]] = []
    new_render_cards: List[Dict[str, Any]] = []
    chart_rendered = state.get("chart_already_rendered", False)
    last_spc = state.get("last_spc_result")
    force_synth = False
    # v1.4 Plan Panel — accumulated across tool calls in this node invocation.
    # Carries forward whatever was already in state.plan_items so updates
    # apply to existing items.
    plan_items: List[Dict[str, Any]] = list(state.get("plan_items") or [])

    # Self-test: detect a degenerate "for-loop calls same MCP repeatedly"
    # pattern by walking state.tools_used (history of THIS run) for the same
    # signature. Threshold = 3; the warning is appended to the result so the
    # LLM sees it next iteration and can break the loop.
    prior_calls = state.get("tools_used") or []
    repeat_warnings: dict[str, str] = {}  # tc_id → warning string

    def _sig(name: str, args: dict[str, Any]) -> str:
        try:
            return name + ":" + json.dumps(args, sort_keys=True, default=str)
        except Exception:
            return name + ":" + str(args)

    LOOP_THRESHOLD = 3
    LOOP_WATCHED = ("execute_mcp", "execute_skill", "search_published_skills",
                    "invoke_published_skill")
    if last_msg.tool_calls:
        # Build signature counter from prior_calls (sigs already saved).
        prior_sig_count: dict[str, int] = {}
        for prev in prior_calls:
            n = prev.get("name") or prev.get("tool_name") or ""
            a = prev.get("input") or prev.get("args") or {}
            if n in LOOP_WATCHED:
                s = _sig(n, a)
                prior_sig_count[s] = prior_sig_count.get(s, 0) + 1
        for tc in last_msg.tool_calls:
            n = tc.get("name") or ""
            if n not in LOOP_WATCHED:
                continue
            s = _sig(n, tc.get("args") or {})
            if prior_sig_count.get(s, 0) + 1 >= LOOP_THRESHOLD:
                repeat_warnings[tc.get("id", "")] = (
                    f"⚠ You've called {n} with these exact arguments "
                    f"{prior_sig_count.get(s, 0) + 1} times in this run — likely a "
                    f"degenerate loop. Most MCPs return ALL matching rows in one "
                    f"call (see the MCP description); change params, aggregate "
                    f"upstream with block_groupby_agg, or stop and synthesize "
                    f"with what you have."
                )

    for tc in last_msg.tool_calls:
        tool_name = tc["name"]
        tool_input = tc.get("args", {})
        tc_id = tc.get("id", "")

        # Preflight validation
        preflight_err = await _preflight_validate(
            db, tool_name, tool_input,
            caller_roles=config["configurable"].get("caller_roles") or (),
        )
        if preflight_err:
            result = preflight_err
        elif tool_name == "confirm_pipeline_intent":
            # Builder-mode "ask before act" mechanism. The LLM has decided the
            # prompt is too ambiguous to translate into a pipeline directly;
            # it's writing down its understanding (inputs / logic / presentation)
            # for the user to confirm via a copilot card. We don't actually
            # build anything here — just emit the SSE event and force this
            # turn to synthesis so the agent stops and waits for the user's
            # next message (which carries [intent_confirmed:<id>] prefix).
            import uuid as _uuid
            card_id = f"intent-{_uuid.uuid4().hex[:8]}"
            # 2026-05-11: Plan-mode-style multi-choice clarifications.
            # Detectors are deterministic Python (scope conflict / metric
            # ambiguity / bar x-axis / time grain); LLM only fills in
            # localized question + label/hint. Per CLAUDE.md "graph-heavy"
            # preference: detection logic stays out of LLM.
            from python_ai_sidecar.agent_orchestrator_v2.dimensional_clarifier import (
                build_clarifications,
            )
            snap = state.get("pipeline_snapshot") or {}
            try:
                clarifications = await build_clarifications(
                    user_msg=state.get("user_message") or "",
                    declared_inputs=snap.get("inputs") if isinstance(snap, dict) else None,
                    pipeline_snapshot=snap if isinstance(snap, dict) else None,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("build_clarifications failed (%s) — card without dims", e)
                clarifications = []
            spec_payload = {
                "card_id": card_id,
                "inputs": tool_input.get("inputs") or [],
                "logic": tool_input.get("logic") or "",
                "presentation": tool_input.get("presentation") or "mixed",
                "alternatives": tool_input.get("alternatives") or [],
                "clarifications": clarifications,
            }
            if event_emit is not None:
                try:
                    event_emit({
                        "type": "design_intent_confirm",
                        **spec_payload,
                    })
                except Exception:  # noqa: BLE001
                    pass
            result = {
                "status": "awaiting_user_confirmation",
                "card_id": card_id,
                "clarifications_count": len(clarifications),
                "message": (
                    "Design-intent card emitted to user. STOP this turn — do not "
                    "call build_pipeline_live yet. Wait for the user's next message; "
                    "if it begins with [intent_confirmed:<id>] then call "
                    "build_pipeline_live with the spec."
                ),
                "_force_synthesis": True,
            }
        elif tool_name == "build_pipeline_live":
            # Phase 5-UX-6: Glass Box pipeline build — spawns agent_builder
            # sub-agent, streams per-operation events to chat SSE.
            # Pass chat session context so the sub-agent carries canvas snapshot
            # across follow-up turns.
            snap = state.get("pipeline_snapshot")

            # 2026-05-11: graph-level intercept. Run dimension detectors
            # against the user's prompt + declared inputs. If any dimension
            # fires AND the user hasn't already confirmed (no
            # [intent_confirmed:] prefix), force a confirm card BEFORE
            # building. This is the "graph not prompt" fix per CLAUDE.md —
            # the LLM doesn't have to remember to call confirm_pipeline_intent;
            # the graph guarantees it.
            forced_clars: list[dict[str, Any]] = []
            user_msg_for_check = state.get("user_message") or ""
            if not user_msg_for_check.startswith("[intent_confirmed:"):
                from python_ai_sidecar.agent_orchestrator_v2.dimensional_clarifier import (
                    build_clarifications,
                )
                snap_dict = snap if isinstance(snap, dict) else {}
                try:
                    forced_clars = await build_clarifications(
                        user_msg=user_msg_for_check,
                        declared_inputs=snap_dict.get("inputs"),
                        pipeline_snapshot=snap_dict,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("forced clarifier failed (%s)", e)
                    forced_clars = []

            if forced_clars:
                import uuid as _uuid
                card_id = f"intent-{_uuid.uuid4().hex[:8]}"
                spec_payload = {
                    "card_id": card_id,
                    "inputs": [],
                    "logic": (tool_input.get("goal") or "")[:200],
                    "presentation": "mixed_chart_alert",
                    "alternatives": [],
                    "clarifications": forced_clars,
                }
                if event_emit is not None:
                    try:
                        event_emit({"type": "design_intent_confirm", **spec_payload})
                    except Exception:  # noqa: BLE001
                        pass
                result = {
                    "status": "awaiting_user_confirmation",
                    "card_id": card_id,
                    "clarifications_count": len(forced_clars),
                    "message": (
                        f"Detected {len(forced_clars)} ambiguous dimension(s). "
                        "Showing confirm card for user to pick. STOP this turn — "
                        "do not retry build_pipeline_live; wait for the user's "
                        "next message with [intent_confirmed:<id> dim=val ...] "
                        "prefix."
                    ),
                    "_force_synthesis": True,
                }
                logger.info("build_pipeline_live: intercepted by clarifier (%d dims)",
                            len(forced_clars))
            else:
                if snap and not tool_input.get("base_pipeline_id"):
                    tool_input = {**tool_input, "_state_pipeline_snapshot": snap}
                # Phase 11 v6 — when canvas snapshot says _kind="skill_step",
                # forward skill_step_mode=True so graph_build's validate node
                # enforces block_step_check terminator.
                snap_kind = snap.get("_kind") if isinstance(snap, dict) else None
                logger.info("tool_execute build_pipeline_live: snap_kind=%r snap_keys=%s",
                            snap_kind,
                            list(snap.keys())[:10] if isinstance(snap, dict) else None)
                if snap_kind == "skill_step":
                    tool_input = {**tool_input, "_skill_step_mode": True}
                result = await _execute_build_pipeline_live(
                    db,
                    tool_input,
                    event_emit=event_emit,
                    chat_session_id=state.get("session_id"),
                    chat_user_id=user_id,
                    chat_user_message=state.get("user_message") or "",
                )
        else:
            # Inject flat_data into execute_analysis so sandbox can read it directly
            if tool_name == "execute_analysis" and state.get("flat_data"):
                tool_input = {**tool_input, "_flat_data": state["flat_data"]}
            result = await dispatcher.execute(tool_name, tool_input)

        # ── v1.4 Plan Panel — emit plan / plan_update SSE events ─────
        if (tool_name == "update_plan" and isinstance(result, dict)
                and result.get("_plan_action")):
            action = result["_plan_action"]
            if action == "create":
                items = result.get("items") or []
                plan_items = [dict(it) for it in items]
                if event_emit is not None:
                    try:
                        event_emit({"type": "plan", "items": plan_items})
                    except Exception:  # noqa: BLE001
                        pass
            elif action == "update":
                pid = result.get("id")
                new_status = result.get("status_value")
                note = result.get("note")

                # Phase E3 follow-up — Builder-mode anti-pattern guard.
                # In builder mode the agent must not mark a plan item "done"
                # with a note that says it's waiting for the user. The user
                # is on a canvas with declared inputs — the right move is
                # to reuse the $name and call build_pipeline_live, not park
                # waiting for clarification. Mutate the tool result into an
                # error so the LLM sees "you can't do that, try again" and
                # the graph routes back through llm_call instead of going
                # to synthesis with a half-finished plan.
                anti_pattern = (
                    state.get("mode") == "builder"
                    and new_status == "done"
                    and isinstance(note, str)
                    and any(kw in note for kw in (
                        "等待使用者", "需要使用者", "等待用戶", "需要用戶",
                        "請使用者提供", "請用戶提供", "等候使用者",
                    ))
                )
                if anti_pattern:
                    # Mutate result into an error so the LLM sees "you can't
                    # do that, try again" — graph routes back through
                    # llm_call. Do NOT mutate plan_items or emit plan_update
                    # so the UI doesn't flash a misleading 'done' state.
                    result.clear()
                    result.update({
                        "status": "error",
                        "code": "BUILDER_WAITS_USER_FORBIDDEN",
                        "message": (
                            "Builder mode forbids marking a plan item 'done' "
                            "while waiting on the user. The canvas already "
                            "has declared inputs (see the user opening's "
                            "'當前 canvas 已宣告的 inputs' section) — REUSE "
                            "those $names and call build_pipeline_live to "
                            "build the pipeline structure now. Do NOT stop. "
                            "Re-call update_plan with status='in_progress' "
                            "(NOT 'done', and NO 'waiting for user' note) and "
                            "immediately invoke build_pipeline_live."
                        ),
                    })
                    logger.warning(
                        "tool_execute: blocked builder-mode 'waiting for user' "
                        "anti-pattern on plan item id=%s note=%r",
                        pid, note,
                    )

                if not anti_pattern:
                    for it in plan_items:
                        if it.get("id") == pid:
                            if new_status:
                                it["status"] = new_status
                            if note is not None:
                                it["note"] = note
                            break
                    if event_emit is not None:
                        try:
                            event_emit({
                                "type": "plan_update",
                                "id": pid,
                                "status": new_status,
                                "note": note,
                            })
                        except Exception:  # noqa: BLE001
                            pass

        # ── v1.4 Auto-Run — chain execute after build_pipeline_live success ─
        if (tool_name == "build_pipeline_live"
                and isinstance(result, dict)
                and result.get("status") in {"finished", "success"}
                and result.get("pipeline_json")):
            pipeline_json = result["pipeline_json"]
            node_count = len((pipeline_json.get("nodes") or []) if isinstance(pipeline_json, dict) else [])
            if event_emit is not None:
                try:
                    event_emit({
                        "type": "pb_run_start",
                        "node_count": node_count,
                    })
                except Exception:  # noqa: BLE001
                    pass
            try:
                from python_ai_sidecar.executor.real_executor import (
                    execute_native, all_blocks_native,
                )
                if all_blocks_native(pipeline_json):
                    run_result = await execute_native(
                        pipeline_json, inputs={}, run_id=None,
                    )
                    run_status = run_result.get("status") or "error"
                    if run_status == "success":
                        # Attach run result to the build result so synthesis
                        # can summarise; also surface via SSE for AnalysisPanel.
                        result["auto_run"] = {
                            "status": "success",
                            "node_results": run_result.get("node_results") or {},
                            "result_summary": run_result.get("result_summary"),
                            "duration_ms": run_result.get("duration_ms"),
                        }
                        if event_emit is not None:
                            try:
                                event_emit({
                                    "type": "pb_run_done",
                                    "status": "success",
                                    "node_results": run_result.get("node_results") or {},
                                    "result_summary": run_result.get("result_summary"),
                                    "duration_ms": run_result.get("duration_ms"),
                                })
                            except Exception:  # noqa: BLE001
                                pass
                    else:
                        err = run_result.get("error_message") or "execution failed"
                        result["auto_run"] = {"status": "error", "error_message": err}
                        if event_emit is not None:
                            try:
                                event_emit({
                                    "type": "pb_run_error",
                                    "error_message": err,
                                })
                            except Exception:  # noqa: BLE001
                                pass
                else:
                    # Hybrid pipeline (non-native blocks) — skip auto-run
                    # for now; user can hit Run Full manually.
                    result["auto_run"] = {"status": "skipped", "reason": "non-native blocks"}
            except Exception as exc:  # noqa: BLE001
                logger.warning("auto-run after build_pipeline_live failed: %s", exc)
                result["auto_run"] = {"status": "error", "error_message": str(exc)[:300]}
                if event_emit is not None:
                    try:
                        event_emit({
                            "type": "pb_run_error",
                            "error_message": str(exc)[:300],
                        })
                    except Exception:  # noqa: BLE001
                        pass

        # Track SPC results for auto-contract fallback
        if (tool_name == "execute_mcp" and isinstance(result, dict)
                and _is_spc_result(result)):
            last_spc = (result.get("mcp_name", tool_name), result)

        # Distillation for execute_mcp results
        if tool_name == "execute_mcp" and isinstance(result, dict) and result.get("status") == "success":
            result = await distill_svc.distill_mcp_result(result)

            # Inject data overview so LLM knows the full picture even when raw data is truncated.
            # get_process_info returns {total, events:[...]} wrapped in dataset list.
            od = result.get("output_data") or {}
            ds = od.get("dataset") or od.get("_raw_dataset") or []
            if isinstance(ds, list) and len(ds) == 1 and isinstance(ds[0], dict):
                inner = ds[0]
                events = inner.get("events")
                if isinstance(events, list) and len(events) > 5:
                    ooc_n = sum(1 for e in events if isinstance(e, dict) and e.get("spc_status") == "OOC")
                    ooc_steps: dict = {}
                    for e in events:
                        if isinstance(e, dict) and e.get("spc_status") == "OOC":
                            s = e.get("step", "?")
                            ooc_steps[s] = ooc_steps.get(s, 0) + 1
                    step_summary = ", ".join(f"{s}:{n}" for s, n in sorted(ooc_steps.items(), key=lambda x: -x[1])[:5])
                    overview = (
                        f"\n═══ DATA OVERVIEW ═══\n"
                        f"total_events: {len(events)}, ooc_count: {ooc_n}, ooc_rate: {ooc_n/len(events)*100:.1f}%\n"
                        f"ooc_by_step: {step_summary or 'none'}\n"
                        f"═════════════════════\n"
                    )
                    # Prepend to llm_readable_data
                    lrd = result.get("llm_readable_data")
                    if isinstance(lrd, str):
                        result["llm_readable_data"] = overview + lrd
                    elif isinstance(lrd, dict):
                        result["llm_readable_data"] = {**lrd, "_data_overview": overview}
                    else:
                        result["_data_overview"] = overview

        # Phase 5-UX-6: build_pipeline_live persists final canvas snapshot to
        # agent_sessions so /chat/[id] can restore on page reload.
        # In builder mode the canvas overlay already shows everything live, so
        # we don't push a render_card. In chat mode the user has no canvas in
        # front of them — the pipeline result + run output need to render
        # inline as a PbPipelineCard, otherwise the build "disappears" from
        # the chat thread and the user can't review/edit/run it.
        # Phase 8-A-1d: native chat path (db=None) routes via Java upsert.
        if tool_name == "build_pipeline_live" and isinstance(result, dict) and result.get("status") in {"finished", "success"}:
            sid = state.get("session_id")
            pipeline_json = result.get("pipeline_json")
            if sid and pipeline_json:
                try:
                    if db is None:
                        # Anonymous caller — skip persist (Java requires userId).
                        if not user_id or user_id <= 0:
                            pass
                        else:
                            # Java upsert — minimal payload preserves prior fields.
                            await java.upsert_agent_session(str(sid), {
                                "userId": user_id,
                                "lastPipelineJson": json.dumps(pipeline_json, ensure_ascii=False),
                            })
                    else:
                        from python_ai_sidecar.agent_helpers._model_stubs import AgentSessionModel
                        from sqlalchemy import select as _select
                        _sess_row = (await db.execute(
                            _select(AgentSessionModel).where(
                                AgentSessionModel.session_id == sid,
                                AgentSessionModel.user_id == user_id,
                            )
                        )).scalar_one_or_none()
                        if _sess_row is not None:
                            _sess_row.last_pipeline_json = json.dumps(pipeline_json, ensure_ascii=False)
                            await db.flush()
                except Exception as e:  # noqa: BLE001
                    logger.warning("session pipeline snapshot writeback failed: %s", e)

            # Chat-mode render_card so PbPipelineCard renders inline with
            # Edit-in-Builder / Save-as-Skill / Expand CTAs. Builder mode
            # skips this — the canvas overlay already presents everything.
            # Card shape mirrors PbPipelineAdHocCard (PbPipelineCard.tsx):
            #   { type, pipeline_json, node_results, result_summary, run_id }
            # node_results / result_summary come from the auto-run (above).
            # Empty dict for node_results when auto_run skipped/failed — UI
            # falls back to "no results yet, hit Edit in Builder to run".
            if state.get("mode") != "builder" and pipeline_json:
                ar = result.get("auto_run") or {}
                new_render_cards.append({
                    "type": "pb_pipeline",
                    "pipeline_json": pipeline_json,
                    "node_results": ar.get("node_results") or {},
                    "result_summary": ar.get("result_summary"),
                    "run_id": None,
                })

        # PR-C: invoke_published_skill also returns a pb pipeline summary
        if tool_name == "invoke_published_skill" and isinstance(result, dict) and result.get("status") == "success":
            card = {
                "type": "pb_pipeline_published",
                "slug": result.get("slug"),
                "skill_name": result.get("skill_name"),
                "charts": result.get("charts") or [],
                "triggered": result.get("triggered"),
                "evidence_rows": result.get("evidence_rows"),
                "run_id": result.get("run_id"),
            }
            new_render_cards.append(card)

        # Handle query_data: stash flat_data in state + build render_card with ui_config
        elif tool_name == "query_data" and isinstance(result, dict) and result.get("_flat_data"):
            _flat_data = result.get("_flat_data")
            _flat_meta = result.get("_flat_metadata")
            _viz_hint = result.get("_visualization_hint")
            # Build UI config from viz_hint
            _ui_config = None
            if _viz_hint and isinstance(_viz_hint, dict):
                _ui_config = {
                    "ui_component": "ChartExplorer",
                    "initial_view": _viz_hint,
                    "available_datasets": _flat_meta.get("available_datasets", []) if _flat_meta else [],
                }
            # Build render card for SSE
            # Build query info for frontend display
            _query_params = tool_input.get("params", {})
            _total = _flat_meta.get("total_events", 0) if _flat_meta else 0
            _ooc = _flat_meta.get("ooc_count", 0) if _flat_meta else 0
            _ooc_rate = _flat_meta.get("ooc_rate", 0) if _flat_meta else 0
            card = {
                "type": "query_data",
                "mcp_name": result.get("mcp_name", ""),
                "flat_data": _flat_data,
                "flat_metadata": _flat_meta,
                "ui_config": _ui_config,
                "query_info": {
                    "mcp": result.get("mcp_name", ""),
                    "params": _query_params,
                    "result_summary": f"{_total} events, {_ooc} OOC ({_ooc_rate}%)",
                },
            }
            new_render_cards.append(card)
        # Handle execute_skill returning pipeline result (Pipeline Skill)
        elif (tool_name == "execute_skill" and isinstance(result, dict)
              and result.get("is_pipeline_skill")):
            card = {
                "type": "pipeline",
                "pipeline_cards": result.get("pipeline_cards", []),
                "flat_data": result.get("flat_data"),
                "flat_metadata": result.get("flat_metadata"),
                "ui_config": result.get("ui_config"),
            }
            new_render_cards.append(card)
        else:
            # Build render card (for SSE events)
            render_card = _build_render_card(tool_name, tool_input, result)
            if render_card:
                new_render_cards.append(render_card)

        # Check if chart was rendered (via _notify_chart_rendered side effect)
        if isinstance(result, dict) and result.get("_chart_rendered"):
            chart_rendered = True

        # Track successful tool uses (for memory lifecycle)
        if isinstance(result, dict) and result.get("status") == "success":
            try:
                result_text = json.dumps(result, ensure_ascii=False, default=str)[:20000]
            except Exception:
                result_text = str(result)[:20000]
            new_tools_used.append({
                "tool": tool_name,
                "mcp_name": tool_input.get("mcp_name", ""),
                "params": {k: v for k, v in tool_input.items()
                           if k not in ("mcp_id", "mcp_name", "python_code", "params")},
                "result_text": result_text,
            })

        # Force synthesis on unrecoverable MCP/skill errors
        if isinstance(result, dict) and result.get("status") == "error":
            if tool_name in ("execute_mcp", "execute_skill"):
                if result.get("code") != "MISSING_PARAMS":
                    force_synth = True

        # Phase F1: confirm_pipeline_intent always force-synthesises so the
        # agent stops this turn and waits for the user's confirmation message.
        if isinstance(result, dict) and result.get("_force_synthesis"):
            force_synth = True

        # Loop self-test: if this exact tool+args was called >=3 times this
        # run, surface the warning to the LLM by wrapping the result.
        if tc_id in repeat_warnings and isinstance(result, dict):
            result = {**result, "_loop_warning": repeat_warnings[tc_id]}

        # Convert result to ToolMessage (trimmed for LLM context)
        result_content = _trim_result_for_llm(result)
        tool_messages.append(ToolMessage(
            content=result_content,
            tool_call_id=tc_id,
            name=tool_name,
        ))

        # F1 follow-up: confirm_pipeline_intent's tool result is a JSON dict
        # carrying internal "STOP this turn" instructions for the LLM. With
        # force_synthesis=True the synthesis node would render that dict as
        # the final user-visible text. Inject a clean AIMessage *after* the
        # ToolMessage so synthesis uses this as the last message instead.
        if (tool_name == "confirm_pipeline_intent"
                and isinstance(result, dict)
                and result.get("status") == "awaiting_user_confirmation"):
            tool_messages.append(AIMessage(
                content="我已寫下要建的內容（見上方卡片），請確認 ✅ 後我會開始建。",
            ))

    # Collect flat_data/ui_config from pipeline or query_data results
    _state_flat_data = None
    _state_flat_meta = None
    _state_ui_config = None
    for card in new_render_cards:
        if card.get("type") in ("query_data", "pipeline"):
            _state_flat_data = card.get("flat_data")
            _state_flat_meta = card.get("flat_metadata")
            _state_ui_config = card.get("ui_config")

    result_state: Dict[str, Any] = {
        "messages": tool_messages,
        "tools_used": new_tools_used,
        "render_cards": new_render_cards,
        "chart_already_rendered": chart_rendered,
        "last_spc_result": last_spc,
        "force_synthesis": force_synth or state.get("force_synthesis", False),
        # v1.4 Plan Panel — propagate the running plan so subsequent nodes
        # (synthesis, memory_lifecycle) can read final state.
        "plan_items": plan_items,
    }
    if _state_flat_data:
        result_state["flat_data"] = _state_flat_data
        result_state["flat_metadata"] = _state_flat_meta
    if _state_ui_config:
        result_state["ui_config"] = _state_ui_config

    return result_state


def _trim_result_for_llm(result: Any, max_chars: int = 4000) -> str:
    """Trim tool result for LLM context — keep llm_readable_data, drop heavy payloads."""
    if not isinstance(result, dict):
        return str(result)[:max_chars]

    # Prefer llm_readable_data (designed for LLM consumption)
    lrd = result.get("llm_readable_data")
    if lrd:
        if isinstance(lrd, str):
            return lrd[:max_chars]
        try:
            return json.dumps(lrd, ensure_ascii=False, default=str)[:max_chars]
        except Exception:
            pass

    # Fallback: strip heavy keys, serialize the rest
    trimmed = dict(result)
    for key in ("output_data", "ui_render_payload", "_raw_dataset", "dataset", "_data_profile"):
        trimmed.pop(key, None)
    try:
        text = json.dumps(trimmed, ensure_ascii=False, default=str)
        return text[:max_chars]
    except Exception:
        return str(result)[:max_chars]


# ── Chart DSL → Vega-Lite converter (Python port of ChartIntentRenderer) ──

_SERIES_COLORS = ["#4299e1", "#38a169", "#d69e2e", "#9f7aea", "#ed8936", "#e53e3e"]
_RULE_COLORS = {"danger": "#e53e3e", "warning": "#dd6b20", "center": "#718096"}


def _chart_intent_to_vega_lite(intent: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a _chart DSL dict to a Vega-Lite spec.

    Python equivalent of the frontend ChartIntentRenderer.intentToVegaLite().
    Used by execute_analysis to embed charts in contract.visualization.
    """
    chart_type = intent.get("type", "line")
    title = intent.get("title", "")
    data = intent.get("data", [])
    x = intent.get("x", "index")
    y = intent.get("y", ["value"])
    rules = intent.get("rules", [])
    highlight = intent.get("highlight")
    x_label = intent.get("x_label", x)
    y_label = intent.get("y_label", y[0] if y else "value")

    layers: List[Dict[str, Any]] = []

    # Main data series
    for i, y_field in enumerate(y):
        color = _SERIES_COLORS[i % len(_SERIES_COLORS)]

        if chart_type == "line":
            layers.append({
                "mark": {"type": "line", "color": color, "strokeWidth": 1.5},
                "encoding": {
                    "x": {"field": x, "type": "ordinal", "title": x_label,
                          "axis": {"labelAngle": -60, "labelFontSize": 7}},
                    "y": {"field": y_field, "type": "quantitative", "title": y_label,
                          "scale": {"zero": False}},
                },
            })
            # Point overlay
            point_encoding: Dict[str, Any] = {
                "x": {"field": x, "type": "ordinal"},
                "y": {"field": y_field, "type": "quantitative"},
            }
            if highlight:
                point_encoding["color"] = {
                    "condition": {
                        "test": f"datum.{highlight['field']} === {json.dumps(highlight['eq'])}",
                        "value": "#e53e3e",
                    },
                    "value": color,
                }
            else:
                point_encoding["color"] = {"value": color}
            layers.append({
                "mark": {"type": "point", "size": 50, "filled": True},
                "encoding": point_encoding,
            })
        elif chart_type == "bar":
            layers.append({
                "mark": {"type": "bar", "color": color},
                "encoding": {
                    "x": {"field": x, "type": "nominal", "title": x_label,
                          "axis": {"labelAngle": -45, "labelFontSize": 8}},
                    "y": {"field": y_field, "type": "quantitative", "title": y_label,
                          "scale": {"zero": False}},
                },
            })
        else:  # scatter
            layers.append({
                "mark": {"type": "point", "size": 60, "filled": True, "color": color},
                "encoding": {
                    "x": {"field": x, "type": "ordinal", "title": x_label},
                    "y": {"field": y_field, "type": "quantitative", "title": y_label,
                          "scale": {"zero": False}},
                },
            })

    # Rule lines (UCL, LCL, CL)
    for rule in rules:
        rule_color = _RULE_COLORS.get(rule.get("style", "danger"), "#e53e3e")
        dash = [3, 3] if rule.get("style") == "center" else [6, 4]
        layers.append({
            "mark": {"type": "rule", "color": rule_color, "strokeDash": dash, "strokeWidth": 1.5},
            "encoding": {"y": {"datum": rule["value"]}},
        })
        layers.append({
            "mark": {"type": "text", "align": "right", "dx": -2, "fontSize": 9,
                     "color": rule_color, "fontWeight": "bold"},
            "encoding": {
                "y": {"datum": rule["value"]},
                "text": {"value": f"{rule.get('label', '')}={rule['value']}"},
                "x": {"value": 0},
            },
        })

    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": "container",
        "height": 280,
        "title": {"text": title, "fontSize": 13, "anchor": "start"},
        "data": {"values": data},
        "layer": layers,
    }
