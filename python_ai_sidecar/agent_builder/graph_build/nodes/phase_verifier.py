"""v30.1 phase_spanning_verifier_node — deterministic post-action check.

Runs after every agentic_phase_loop_node round. Reads the just-mutated node
(via state.v30_last_mutated_logical_id + state.v30_last_preview) and walks
forward through phases starting from current_phase_idx to detect:

  - phase[k] is satisfied → advance idx
  - phase[k+1..k+N] also satisfied by SAME block → fast-forward (auto-mark)

Block coverage decided by:
  1. block.produces.covers (DB-driven, preferred)
  2. fallback inferred from block category + output_schema types

Outcome values extracted via block.produces.outcome_extractors with simple
JSON path resolution against the preview blob. Used to populate the
fast-forward report SSE so user sees concrete numbers, not just "auto-completed".

This node REPLACES the auto_phase_complete + _check_phase_done logic that
previously lived inside agentic_phase_loop. Keeping verifier separate makes
fast-forward testable in isolation and SSE granularity cleaner.
"""
from __future__ import annotations

import logging
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry


logger = logging.getLogger(__name__)


# Cap fast-forward chain so a single block can't accidentally close the
# whole build. If user has 8 phases and one composite covers them all,
# we still pause to let LLM/user inspect at most every 4 phases.
MAX_FAST_FORWARD_CHAIN = 4


async def phase_spanning_verifier_node(state: BuildGraphState) -> dict[str, Any]:
    """Decide whether the just-touched node satisfies one or more phases.

    State reads:
      v30_last_mutated_logical_id, v30_last_preview, exec_trace,
      v30_phases, v30_current_phase_idx, v30_phase_outcomes
    State writes:
      v30_current_phase_idx, v30_phase_outcomes, v30_fast_forward_log,
      v30_phase_messages (clears advanced phases), v30_phase_round (resets to 0)
    """
    from python_ai_sidecar.agent_builder.graph_build.trace import (
        get_current_tracer,
    )

    last_lid = state.get("v30_last_mutated_logical_id")
    if not last_lid:
        # Round was inspect_*/no-op — nothing to verify
        return {}

    snapshot = (state.get("exec_trace") or {}).get(last_lid) or {}
    block_id = snapshot.get("block_id")
    real_id = snapshot.get("real_id") or last_lid
    rows = snapshot.get("rows")
    preview_blob = state.get("v30_last_preview") or {}

    phases = state.get("v30_phases") or []
    idx = state.get("v30_current_phase_idx", 0)
    if idx >= len(phases) or not block_id:
        return {}

    registry = SeedlessBlockRegistry()
    registry.load()
    block_spec = registry.get_spec(block_id, "1.0.0") or {}
    produces = block_spec.get("produces") or {}
    covers = list(produces.get("covers") or [])
    if not covers:
        covers = _infer_covers_from_block_spec(block_spec)
    extractors = produces.get("outcome_extractors") or []

    # Walk phases starting at current; advance while block covers
    advanced: list[dict[str, Any]] = []
    cur = idx
    while cur < len(phases) and len(advanced) < MAX_FAST_FORWARD_CHAIN:
        phase = phases[cur]
        ph_expected = (phase.get("expected") or "").strip()
        if ph_expected not in covers:
            break
        # Quality gate: data-bearing phases must have rows>=1.
        # (raw_data/transform/table) Without this, an empty filter would
        # pass verifier and fast-forward through downstream phases.
        if ph_expected in {"raw_data", "transform", "table"} and (rows is None or rows < 1):
            logger.info(
                "phase_verifier: phase %s expected=%s but rows=%s — block %s NOT counted",
                phase.get("id"), ph_expected, rows, block_id,
            )
            break
        outcome = _extract_outcome(phase, snapshot, preview_blob, extractors, block_id)
        advanced.append({
            "id": phase["id"],
            "expected": ph_expected,
            "goal": phase.get("goal"),
            "outcome": outcome["text"],
            "evidence": outcome["evidence"],
        })
        cur += 1

    tracer = get_current_tracer()

    if not advanced:
        # Block didn't satisfy current phase — let the loop continue rounds.
        # Don't emit phase_completed; stay on same idx, increment nothing.
        if tracer is not None:
            tracer.record_step(
                "phase_verifier", status="no_match",
                phase_id=phases[idx].get("id"),
                expected=phases[idx].get("expected"),
                block_id=block_id, covers=covers, rows=rows,
            )
        return {
            # Clear handoff fields so next round can fill them again
            "v30_last_mutated_logical_id": None,
            "v30_last_preview": None,
            "sse_events": [_event("phase_verifier_no_match", {
                "current_phase_id": phases[idx].get("id"),
                "expected": phases[idx].get("expected"),
                "block_id": block_id,
                "covers": covers,
                "rows": rows,
            })],
        }

    # Build outcomes ledger entries
    outcomes = dict(state.get("v30_phase_outcomes") or {})
    for adv in advanced:
        outcomes[adv["id"]] = {
            "status": "completed",
            "rationale": adv["outcome"],
            "evidence": adv["evidence"],
            "advanced_by_block": block_id,
            "advanced_by_node": real_id,
            "auto_completed": True,
        }

    new_idx = idx + len(advanced)
    cleared_msgs = dict(state.get("v30_phase_messages") or {})
    for adv in advanced:
        cleared_msgs[adv["id"]] = []

    sse_events: list[dict[str, Any]] = []
    for adv in advanced:
        sse_events.append(_event("phase_completed", {
            "phase_id": adv["id"],
            "rationale": adv["outcome"],
            "evidence": adv["evidence"],
            "auto_completed": True,
            "advanced_by_block": block_id,
            "advanced_by_node": real_id,
        }))

    update: dict[str, Any] = {
        "v30_current_phase_idx": new_idx,
        "v30_phase_round": 0,
        "v30_phase_outcomes": outcomes,
        "v30_phase_messages": cleared_msgs,
        "v30_last_mutated_logical_id": None,
        "v30_last_preview": None,
    }

    # Fast-forward report when >= 2 phases at once — user-visible card
    if len(advanced) >= 2:
        ff_log = list(state.get("v30_fast_forward_log") or [])
        report = {
            "trigger_phase_id": phases[idx].get("id"),
            "advanced_by_node": real_id,
            "advanced_by_block": block_id,
            "phases_completed": advanced,
        }
        ff_log.append(report)
        update["v30_fast_forward_log"] = ff_log
        sse_events.append(_event("phase_fast_forward_report", report))
        logger.info(
            "phase_verifier: FAST-FORWARD %d phases (%s..%s) by %s [%s]",
            len(advanced), advanced[0]["id"], advanced[-1]["id"],
            real_id, block_id,
        )

    if tracer is not None:
        tracer.record_step(
            "phase_verifier", status="advanced",
            phases_advanced=[a["id"] for a in advanced],
            block_id=block_id, advanced_by_node=real_id,
            fast_forward=(len(advanced) >= 2),
        )

    update["sse_events"] = sse_events
    return update


def _infer_covers_from_block_spec(spec: dict) -> list[str]:
    """Fallback when `produces.covers` is missing.

    Derives expected-kind coverage from category + output_schema types +
    well-known block names. Conservative — only returns kinds we're sure of.
    """
    cat = (spec.get("category") or "").strip()
    out_types = [str(p.get("type") or "") for p in (spec.get("output_schema") or [])]
    name = spec.get("name", "")

    if cat == "source":
        return ["raw_data"]
    if cat == "output":
        if any("chart" in t for t in out_types):
            return ["chart"]
        if name == "block_data_view":
            return ["table"]
        if name in {"block_alert", "block_any_trigger"}:
            return ["alarm"]
        return []
    if name in {"block_step_check", "block_threshold"}:
        return ["verdict", "scalar"]
    if any(t == "dataframe" for t in out_types):
        return ["transform"]
    return []


def _extract_outcome(
    phase: dict,
    snapshot: dict,
    preview_blob: dict,
    extractors: list[dict],
    block_id: str,
) -> dict[str, Any]:
    """Build human-readable outcome text + evidence dict for one phase.

    Pulls values via block.produces.outcome_extractors. If the phase declared
    `expected_output.outcome_keys`, restrict to those keys (so verifier picks
    the SPECIFIC value the planner cared about, not all available extractors).
    Falls back to row count when no extractor matches.
    """
    eo = phase.get("expected_output") or {}
    requested_keys = set(eo.get("outcome_keys") or [])

    extracted: dict[str, Any] = {}
    for ext in extractors:
        key = ext.get("key")
        if not key:
            continue
        if requested_keys and key not in requested_keys:
            continue
        port = ext.get("from_port")
        path = ext.get("json_path") or ""
        port_blob = preview_blob.get(port) if port else None
        # Try preview blob first (richer — has chart_spec meta etc.)
        val = _resolve_path(port_blob, path)
        # Fall back to snapshot.sample (dataframe row case)
        if val is None:
            val = _resolve_path(snapshot.get("sample"), path)
        if val is not None:
            extracted[key] = val

    rows = snapshot.get("rows")
    goal = phase.get("goal", "")[:60]
    criterion = (eo.get("criterion") or "").strip()

    if extracted:
        parts = [f"{k}={_short(v)}" for k, v in extracted.items()]
        text = f"{block_id} → " + ", ".join(parts)
        if criterion:
            text += f"  ({criterion})"
    elif rows is not None:
        text = f"{block_id} → {rows} rows"
    else:
        text = f"{block_id} executed (no extractable scalar)"

    if goal:
        text = f"{text}  [phase: {goal}]"

    return {
        "text": text,
        "evidence": {
            "node_id": snapshot.get("real_id"),
            "block_id": block_id,
            "extracted": extracted,
            "rows": rows,
        },
    }


def _resolve_path(obj: Any, path: str) -> Any:
    """Resolve simple json path: 'meta.ooc_count' or 'rows[0].pass' or '$.'.

    Returns None on any failure. Special values:
      '$.'        → return the obj itself ('full output' marker)
      'foo.length' → len(obj.foo)
    """
    if path == "$.":
        return "<full output>"
    if obj is None or not path:
        return None
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if part == "length":
            try:
                return len(cur)
            except TypeError:
                return None
        if "[" in part and part.endswith("]"):
            name, rest = part.split("[", 1)
            idx_str = rest[:-1]
            try:
                idx = int(idx_str)
            except ValueError:
                return None
            if name:
                cur = cur.get(name) if isinstance(cur, dict) else None
            if isinstance(cur, list) and 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return None
        else:
            cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _short(v: Any) -> str:
    s = str(v)
    return s[:60] + ("..." if len(s) > 60 else "")


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
