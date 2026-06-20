"""phase_verifier — deterministic build-time structural check.

v30.23 (2026-05-20) — covers gate moved behind feature flag (default OFF).
Verifier now does:

  (A) covers gate    — OFF by default. Block output port covers must
                        include phase.expected. Set
                        BUILDER_VERIFIER_COVERS_GATE=1 to re-enable.
                        When off, FF chain also disabled — one phase
                        advance per verify call.
  (B) validation_error / failed — block executor short-circuited
  (C) orphan check   — non-source block has 0 inbound edges

Why covers off by default: empirically covers mismatch caused most of
the agent build failures (cpk added as side-branch rejected whole
chart phase, filter→step_check rejected because filter is transform
mid-chain). The phase.expected kind stays in plan + agent prompt as a
HINT, but doesn't gate advance. Whether canvas actually produces the
right output is a runtime concern (already deferred in v30.20).

v30.20 (2026-05-19) — earlier cut moved these to runtime:
  - LLM-judge (_judge_task_progress / _llm_judge_phase_outcome)
  - rows quality gate (rows < 1 reject for raw_data/transform/table)
  - deficit detection (rows < requested_n * 0.8 pause)
  - empty_data routing (source_empty / filter_empty)

Verifier output remains:
  - advance phase + emit phase_completed when structural checks pass
  - emit phase_verifier_no_match with deterministic missing_for_phase
    hint when blocked
"""
from __future__ import annotations

import logging
import os
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry


logger = logging.getLogger(__name__)


# Cap fast-forward chain so a single composite block can't accidentally
# close the whole build silently. Only used when covers gate is ON.
MAX_FAST_FORWARD_CHAIN = 4

# Item 2 (2026-06-13, ENABLE_STRICT_PHASE_VERIFY): the "specific deliverable"
# kinds. When a phase declares one of these but the canvas terminal doesn't
# cover it, REJECT (don't advance). Intermediate kinds (raw_data / transform /
# verdict) stay loose — a transform phase legitimately ends on many block types.
# Mirrors finalize._PRESENTATION_KINDS (C2) but applied per-phase, earlier.
_STRICT_VERIFY_KINDS: frozenset[str] = frozenset({"chart", "table", "scalar", "alarm"})


def _covers_gate_enabled() -> bool:
    """Feature flag: covers gate gates phase advance + enables FF chain.
    Default OFF (env var unset or "0"). Set BUILDER_VERIFIER_COVERS_GATE=1
    to enable.
    """
    return os.environ.get("BUILDER_VERIFIER_COVERS_GATE", "0").strip() == "1"


async def phase_spanning_verifier_node(state: BuildGraphState) -> dict[str, Any]:
    """Build-time structural verifier.

    State reads:
      v30_last_mutated_logical_id, exec_trace, v30_phases,
      v30_current_phase_idx, pipeline_json, logical_to_real
    State writes:
      v30_current_phase_idx, v30_phase_outcomes, v30_fast_forward_log,
      v30_phase_messages (clears advanced phases), v30_phase_round,
      v30_subphase reset, v30_last_verifier_reject
    """
    from python_ai_sidecar.agent_builder.graph_build.trace import (
        get_current_tracer,
    )

    last_lid = state.get("v30_last_mutated_logical_id")
    if not last_lid:
        # Round was inspect_*/no-op — nothing to verify.
        return {}

    snapshot = (state.get("exec_trace") or {}).get(last_lid) or {}
    block_id = snapshot.get("block_id")
    real_id = snapshot.get("real_id") or last_lid
    rows = snapshot.get("rows")
    snap_status = (snapshot.get("status") or "").lower()
    snap_error = snapshot.get("error") or ""

    phases = state.get("v30_phases") or []
    idx = state.get("v30_current_phase_idx", 0)
    if idx >= len(phases):
        return {}

    cur_phase = phases[idx]
    cur_expected = (cur_phase.get("expected") or "").strip()

    # ── (B) Validation-error / executor failure path ────────────────
    # Fires when:
    #   - executor short-circuited before block ran (no block_id captured), OR
    #   - auto_preview returned status in {validation_error, failed, error}.
    # Either way the block didn't really execute; agent needs to fix params
    # (or pick another block) before any advance can happen.
    if (
        not block_id
        or snap_status in {"validation_error", "failed", "error"}
    ):
        return _emit_reject(
            state=state,
            cur_phase=cur_phase,
            block_id=block_id or "(executor short-circuited)",
            covers=[],
            rows=None,
            result=snap_status or "validation_error",
            error_message=(snap_error or "")[:300] or "(no error message captured)",
            missing_for_phase=[
                f"fix {block_id or 'block'} params (look at error_message) "
                f"or pick a different block"
            ],
        )

    # ── Block + covers metadata ──────────────────────────────────────
    registry = SeedlessBlockRegistry()
    registry.load()
    block_spec = registry.get_spec(block_id, "1.0.0") or {}
    covers_output = _resolve_covers(block_spec, kind="output")
    covers_internal = _resolve_covers(block_spec, kind="internal")
    extractors = (block_spec.get("produces") or {}).get("outcome_extractors") or []
    preview_blob = state.get("v30_last_preview") or {}

    # ── (C) Orphan check — always runs (covers gate or not). ────────
    # Non-source block with 0 inbound edges = structurally broken.
    orphan_reject = _check_orphan(
        state=state, block_spec=block_spec,
        last_lid=last_lid, block_id=block_id,
    )
    if orphan_reject is not None:
        return orphan_reject

    # ── (C2) Leaf check — symmetric to (C): a non-output node that is a
    # LEAF (0 outbound) is structurally broken. Catches the abandoned-fetch
    # case (ooc-ranking: a 3rd process_history left dangling when the agent
    # unioned only 2). The just-added frontier node is legitimately a leaf
    # until wired, so this only fires once an OUTPUT node exists in the
    # pipeline (deliverable chain complete) — at which point any leftover
    # non-output leaf is a confirmed dead branch, not an in-progress frontier.
    leaf_reject = _check_leaf(state=state, registry=registry)
    if leaf_reject is not None:
        return leaf_reject

    # ── (A) Cover-gate walk — gated by feature flag ──────────────────
    advanced: list[dict[str, Any]] = []
    cur = idx
    covers_gate_on = _covers_gate_enabled()

    if covers_gate_on:
        # Original v30.20 covers walk + FF chain.
        seen_kinds_in_chain: set[str] = set()
        while cur < len(phases) and len(advanced) < MAX_FAST_FORWARD_CHAIN:
            phase = phases[cur]
            ph_expected = (phase.get("expected") or "").strip()
            if ph_expected not in covers_internal:
                break
            if ph_expected in seen_kinds_in_chain:
                logger.info(
                    "phase_verifier: FF chain stop — already advanced a %s "
                    "phase by block %s; same-kind stacking not allowed",
                    ph_expected, block_id,
                )
                break
            outcome = _extract_outcome(phase, snapshot, preview_blob, extractors, block_id)
            advanced.append({
                "id": phase["id"],
                "expected": ph_expected,
                "goal": phase.get("goal"),
                "outcome": outcome["text"],
                "evidence": outcome["evidence"],
                "plan_target": phase.get("expected_output") or {},
            })
            seen_kinds_in_chain.add(ph_expected)
            cur += 1
    else:
        # v30.23: covers gate OFF — advance ONE phase (current). No FF.
        # phase.expected stays in plan/prompt as a hint but doesn't gate.
        # If validation_error + orphan both passed, agent's canvas is
        # structurally OK; whether it semantically matches expected is
        # a runtime concern.
        phase = phases[idx]
        ph_expected = (phase.get("expected") or "").strip()
        # Item 2 (ENABLE_STRICT_PHASE_VERIFY): the candidate terminal (block_id /
        # covers_output) is the BEST match _find_canvas_terminal could find — it
        # prefers a terminal whose covers include phase.expected. So if even this
        # best terminal doesn't cover a *specific deliverable* kind, then NO
        # terminal does → the deliverable isn't built → REJECT instead of the
        # default unconditional advance. This is what catches spc-cpk: a chart
        # phase whose only terminal is block_filter (covers=transform) is bounced
        # back so the agent adds the chart, instead of silently advancing.
        from python_ai_sidecar.feature_flags import is_strict_phase_verify_enabled
        if (
            is_strict_phase_verify_enabled()
            and ph_expected in _STRICT_VERIFY_KINDS
            and ph_expected not in covers_output
        ):
            would_pass = _would_pass_blocks(registry, ph_expected)
            logger.info(
                "phase_verifier: STRICT reject — phase %s wants '%s' but terminal "
                "%s covers=%s",
                phase.get("id"), ph_expected, block_id, list(covers_output),
            )
            return _emit_reject(
                state=state,
                cur_phase=cur_phase,
                block_id=block_id or "(unknown)",
                covers=list(covers_output),
                rows=rows,
                result="missing expected output kind",
                missing_for_phase=[
                    f"phase needs a '{ph_expected}' block but the canvas terminal "
                    f"is '{block_id}' (covers={list(covers_output)}). Add a block "
                    f"whose output covers '{ph_expected}'"
                    + (f" (e.g. {', '.join(would_pass[:3])})" if would_pass else "")
                ],
                would_have_passed_with=would_pass,
            )
        outcome = _extract_outcome(phase, snapshot, preview_blob, extractors, block_id)
        advanced.append({
            "id": phase["id"],
            "expected": ph_expected,
            "goal": phase.get("goal"),
            "outcome": outcome["text"],
            "evidence": outcome["evidence"],
            "plan_target": phase.get("expected_output") or {},
        })

    tracer = get_current_tracer()

    if not advanced:
        # Only reachable when covers gate ON. Emit covers mismatch reject.
        would_pass = _would_pass_blocks(registry, cur_expected)
        return _emit_reject(
            state=state,
            cur_phase=cur_phase,
            block_id=block_id or "(unknown)",
            covers=list(covers_output),
            rows=rows,
            result="covers mismatch",
            missing_for_phase=[
                f"pick a block whose covers includes '{cur_expected}' "
                f"(e.g. {', '.join(would_pass[:3]) if would_pass else 'see catalog'})"
            ],
            would_have_passed_with=would_pass,
        )

    # ── Advance ──────────────────────────────────────────────────────
    outcomes = dict(state.get("v30_phase_outcomes") or {})
    for adv in advanced:
        outcomes[adv["id"]] = {
            "status": "completed",
            "rationale": adv["outcome"],
            "evidence": adv["evidence"],
            "advanced_by_block": block_id,
            "advanced_by_node": real_id,
            "auto_completed": True,
            "plan_target": adv.get("plan_target") or {},
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
        "v30_last_judge_reject_reason": None,
        "v30_last_verifier_reject": None,
        "v30_subphase": "pick",
        "v30_subphase_round": 0,
        "v30_pending_block": None,
        "v30_pending_node_id": None,
        "v30_refine_cycle": 0,
    }

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
        try:
            for adv in advanced:
                tracer.record_verifier_decision(
                    phase_id=adv["id"],
                    phase_expected=adv["expected"],
                    candidate_block=block_id or "(unknown)",
                    candidate_block_covers=covers_output,
                    comparison={
                        "expected_in_covers": True,
                        "rows": rows,
                        "result": "advanced",
                    },
                    verdict="advanced",
                    advanced_phases=[a["id"] for a in advanced],
                    outcome_extracted=adv.get("evidence", {}).get("extracted") or {},
                )
        except Exception as ex:  # noqa: BLE001
            logger.info("trace.record_verifier_decision failed (non-fatal): %s", ex)

    update["sse_events"] = sse_events
    return update


# ─────────────────────────────────────────────────────────────────────
# Reject emission — single path for all three blockers.
# ─────────────────────────────────────────────────────────────────────


def _emit_reject(
    *,
    state: BuildGraphState,
    cur_phase: dict,
    block_id: str,
    covers: list[str],
    rows: int | None,
    result: str,
    missing_for_phase: list[str],
    error_message: str | None = None,
    would_have_passed_with: list[str] | None = None,
) -> dict[str, Any]:
    """Common reject path. Writes v30_last_verifier_reject for next-round
    prompt + sets deterministic refine sub-phase based on result kind."""
    from python_ai_sidecar.agent_builder.graph_build.trace import get_current_tracer

    cur_expected = cur_phase.get("expected") or ""
    verifier_reject_info = {
        "block_id": block_id,
        "expected": cur_expected,
        "covers": covers,
        "rows": rows,
        "result": result,
        "error_message": error_message,
        "missing_for_phase": missing_for_phase,
        "would_have_passed_with": (would_have_passed_with or [])[:10],
        # Kept None for back-compat with prompt code that still reads it.
        "judge_reject_reason": None,
    }
    # Deterministic refine routing:
    #   covers mismatch  → pick another block
    #   validation_error → tune (fix params) — but if block_id missing, pick
    #   orphan           → construct (connect the block)
    if "orphan" in result or any("connect" in m for m in missing_for_phase):
        next_sub = "construct"
    elif result in {"validation_error", "failed", "error"}:
        next_sub = "tune" if block_id != "(executor short-circuited)" else "pick"
    else:
        next_sub = "pick"
    refine_cycle = (state.get("v30_refine_cycle") or 0) + 1

    tracer = get_current_tracer()
    if tracer is not None:
        tracer.record_step(
            "phase_verifier", status="no_match",
            phase_id=cur_phase.get("id"), expected=cur_expected,
            block_id=block_id, covers=covers, rows=rows,
            result=result,
        )
        try:
            tracer.record_verifier_decision(
                phase_id=cur_phase.get("id"),
                phase_expected=cur_expected,
                candidate_block=block_id,
                candidate_block_covers=covers,
                comparison={
                    "expected_in_covers": False if result == "covers mismatch" else True,
                    "result": result,
                    "rows": rows,
                },
                verdict="no_match",
                would_have_passed_with=would_have_passed_with or [],
            )
        except Exception as ex:  # noqa: BLE001
            logger.info("trace.record_verifier_decision failed (non-fatal): %s", ex)

    return {
        "v30_last_mutated_logical_id": None,
        "v30_last_preview": None,
        "v30_last_judge_reject_reason": None,
        "v30_last_verifier_reject": verifier_reject_info,
        "v30_subphase": next_sub,
        "v30_subphase_round": 0,
        "v30_refine_cycle": refine_cycle,
        "sse_events": [_event("phase_verifier_no_match", {
            "current_phase_id": cur_phase.get("id"),
            "expected": cur_expected,
            "block_id": block_id,
            "covers": covers,
            "rows": rows,
            "result": result,
            "error_message": error_message,
            "missing_for_phase": missing_for_phase,
            "refine_next_subphase": next_sub,
            "refine_cycle": refine_cycle,
        })],
    }


def _check_orphan(
    *, state: BuildGraphState, block_spec: dict,
    last_lid: str, block_id: str,
) -> dict[str, Any] | None:
    """Reject if non-source block has 0 inbound edges and isn't marked
    standalone_capable. Returns reject dict or None."""
    cat = (block_spec.get("category") or "").lower()
    meta = block_spec.get("meta") or {}
    if cat == "source" or meta.get("standalone_capable"):
        return None
    # Canvas state lives in final_pipeline during the build loop;
    # pipeline_json is only set by the executor path. Falling back to
    # base_pipeline handles the first-ever-block case.
    pipeline_now = (
        state.get("final_pipeline")
        or state.get("pipeline_json")
        or state.get("base_pipeline")
        or {}
    )
    logical_to_real = state.get("logical_to_real") or {}
    target_real = logical_to_real.get(last_lid, last_lid)
    in_count = 0
    for e in (pipeline_now.get("edges") or []):
        # Edges are dumped via model_dump(by_alias=True) → {"from": {...}, "to": {...}}.
        to_field = e.get("to") or {}
        to_node = to_field.get("node") if isinstance(to_field, dict) else None
        if to_node == target_real:
            in_count += 1
    if in_count > 0:
        return None
    # Find current phase for the reject context
    phases = state.get("v30_phases") or []
    idx = state.get("v30_current_phase_idx", 0)
    cur_phase = phases[idx] if idx < len(phases) else {}
    return _emit_reject(
        state=state, cur_phase=cur_phase, block_id=block_id, covers=[],
        rows=None, result="orphan: no inbound edge",
        missing_for_phase=[
            f"connect upstream → {last_lid}.<input port> "
            f"(block {block_id} needs data from upstream)"
        ],
    )


def _check_leaf(
    *, state: BuildGraphState, registry: Any,
) -> dict[str, Any] | None:
    """Reject if a non-output node is a LEAF (0 outbound edges) — a
    data/transform/source block with no downstream consumer can never
    contribute to the deliverable. Symmetric to _check_orphan's inbound rule.

    Scoped to fire ONLY once an output-category node exists in the pipeline:
    before the deliverable chain reaches an output, the just-added frontier
    node is legitimately a pending leaf, so flagging it would be a false
    positive. Once an output exists, any leftover non-output leaf is a
    confirmed dead branch. Returns reject dict (routes to 'construct' so the
    agent connects-or-removes it next round) or None.
    """
    pipeline_now = (
        state.get("final_pipeline")
        or state.get("pipeline_json")
        or state.get("base_pipeline")
        or {}
    )
    nodes = pipeline_now.get("nodes") or []
    if len(nodes) <= 1:
        return None
    edges = pipeline_now.get("edges") or []

    out_count: dict[str, int] = {}
    for e in edges:
        from_field = e.get("from") or {}
        from_node = from_field.get("node") if isinstance(from_field, dict) else None
        if from_node:
            out_count[from_node] = out_count.get(from_node, 0) + 1

    def _cat_meta(block_id: str) -> tuple[str, dict]:
        spec = registry.get_spec(block_id, "1.0.0") or {}
        return (spec.get("category") or "").lower(), (spec.get("meta") or {})

    # Gate: only fire once the deliverable chain has reached an output node.
    if not any(_cat_meta(n.get("block_id"))[0] == "output" for n in nodes):
        return None

    abandoned: list[tuple[str, str]] = []
    for n in nodes:
        nid = n.get("id")
        bid = n.get("block_id") or ""
        cat, meta = _cat_meta(bid)
        # Output blocks are legitimate leaves; standalone composites opt out
        # the same way C14 exempts them.
        if cat == "output" or meta.get("standalone_capable"):
            continue
        if out_count.get(nid, 0) == 0:
            abandoned.append((nid, bid))

    if not abandoned:
        return None

    phases = state.get("v30_phases") or []
    idx = state.get("v30_current_phase_idx", 0)
    cur_phase = phases[idx] if idx < len(phases) else {}
    return _emit_reject(
        state=state, cur_phase=cur_phase, block_id=abandoned[0][1], covers=[],
        rows=None, result="orphan: data node is a leaf (no downstream)",
        missing_for_phase=[
            f"node {nid} ({bid}) produces data but has no downstream consumer — "
            f"connect its output into the chain, or remove it"
            for nid, bid in abandoned
        ],
    )


def _would_pass_blocks(registry: Any, expected: str) -> list[str]:
    """List non-deprecated block names whose covers_output includes expected."""
    if not expected:
        return []
    out: list[str] = []
    try:
        for (n, _v), s in (registry.catalog or {}).items():
            if str(s.get("status") or "").lower() == "deprecated":
                continue
            if expected in _resolve_covers(s, kind="output"):
                out.append(n)
    except Exception as ex:  # noqa: BLE001
        logger.info("would_pass computation failed: %s", ex)
    return out


# ─────────────────────────────────────────────────────────────────────
# Covers resolution + outcome extraction (kept from v30.5/v30.10).
# ─────────────────────────────────────────────────────────────────────


def _resolve_covers(spec: dict, kind: str = "output") -> list[str]:
    """v30.5: resolve produces.covers per intent kind.

    Two semantically distinct fields:
      - covers_output: what the OUTPUT PORT yields (verifier gate).
      - covers_internal: full capability (FF chain walk through
        intermediate phases composite blocks claim internally).

    Backward compat: if produces only has `covers` (old single field),
    treat it as both. Missing output → infer from category+output_schema;
    missing internal → fall back to output.
    """
    produces = spec.get("produces") or {}
    if kind == "output":
        v = produces.get("covers_output")
        if v is not None:
            return list(v)
        v = produces.get("covers")
        if v is not None:
            return list(v)
        return _infer_covers_from_block_spec(spec)
    if kind == "internal":
        v = produces.get("covers_internal")
        if v is not None:
            return list(v)
        v = produces.get("covers")
        if v is not None:
            return list(v)
        return _infer_covers_from_block_spec(spec)
    raise ValueError(f"unknown kind={kind!r} (expected 'output' or 'internal')")


def _infer_covers_from_block_spec(spec: dict) -> list[str]:
    """Fallback when produces.covers is missing. Conservative — only
    returns kinds we're sure of based on category + output types + name."""
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
    Pulls values via block.produces.outcome_extractors restricted by
    phase.expected_output.outcome_keys when set."""
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
        val = _resolve_path(port_blob, path)
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
    """Resolve simple json path: 'meta.ooc_count' / 'rows[0].pass' / '$.'."""
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
                pidx = int(idx_str)
            except ValueError:
                return None
            if name:
                cur = cur.get(name) if isinstance(cur, dict) else None
            if isinstance(cur, list) and 0 <= pidx < len(cur):
                cur = cur[pidx]
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
