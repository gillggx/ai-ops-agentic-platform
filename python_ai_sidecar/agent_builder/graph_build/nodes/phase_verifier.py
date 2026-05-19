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
import re
from typing import Any, Optional

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry


logger = logging.getLogger(__name__)


# Cap fast-forward chain so a single block can't accidentally close the
# whole build. If user has 8 phases and one composite covers them all,
# we still pause to let LLM/user inspect at most every 4 phases.
MAX_FAST_FORWARD_CHAIN = 4


# v30.17j (2026-05-17) — deficit detection thresholds for user-interactive
# "資料源不足，要繼續嗎?" gate. Triggers when value_desc has a count quantifier
# AND actual rows >= 1 (zero is excluded; that's a separate case) AND
# rows / requested_N is below DEFICIT_ASK_BELOW. Above DEFICIT_AUTO_ABOVE
# we silently accept (close enough; no point bugging user).
DEFICIT_AUTO_ABOVE = 0.8   # rows >= 80% of requested → silent accept
DEFICIT_ASK_BELOW = 0.8    # rows <  80% of requested → ask user (if > 0)

# Quantifier pattern: "100 筆" / "50 張" / "20 個" / "10 records" / "30 rows".
# Captures the integer; demands a min of 2 digits so small numbers in
# unrelated text ("第 1 個") don't trigger. Chinese 筆/張/個 + English
# variants.
# NB: \b doesn't work after CJK chars because 筆/張/個 are \w in Python 3
# regex (Unicode word). Split alternation: CJK units need no boundary;
# English units keep \b to avoid matching "recorded" / "rowdy" etc.
_COUNT_QUANTIFIER_PATTERN = re.compile(
    r'(?P<n>\d{2,})\s*(?:筆|張|個|records?\b|rows?\b|samples?\b)',
    re.IGNORECASE,
)


def _has_chart_spec_output(preview_blob: dict | None) -> bool:
    """v30.17j — true if any port in the preview blob holds a chart_spec
    snapshot. Chart blocks output chart_spec (not rows); using this avoids
    the LLM-judge rejecting them on count quantifier rules that don't apply.
    """
    if not isinstance(preview_blob, dict):
        return False
    for blob in preview_blob.values():
        if not isinstance(blob, dict):
            continue
        if blob.get("type") == "chart_spec":
            return True
        snap = blob.get("snapshot")
        if isinstance(snap, dict) and snap.get("type") == "chart_spec":
            return True
        # block executors sometimes set type via __dsl marker
        if isinstance(snap, dict) and snap.get("__dsl") is True:
            return True
    return False


def _detect_deficit(
    value_desc: str | None,
    rows: int | None,
    count_target_override: int | None = None,
) -> Optional[dict]:
    """v30.17j (extended v30.18) — return deficit info dict when actual rows
    are significantly below the requested count; else None.

    Returns: {"requested_n": int, "actual_rows": int, "ratio": float} or None.

    Source of `requested_n` (in order):
      1. count_target_override (from task_contract.count_target) — preferred,
         set once per build, more reliable than value_desc regex
      2. value_desc regex match (legacy path)

    Triggers ONLY when ALL of:
      - we have a requested_n via either source
      - rows > 0 (zero handled separately — likely filter bug, not data ceiling)
      - rows < requested
      - ratio = rows / requested < DEFICIT_AUTO_ABOVE (i.e. < 80% — not close enough)

    Used by phase_verifier_node to decide whether to pause + ask user vs
    continue the existing rule-based + LLM-judge gate.
    """
    if not isinstance(rows, int) or rows <= 0:
        return None
    requested: int | None = None
    if isinstance(count_target_override, int) and count_target_override > 0:
        requested = count_target_override
    elif value_desc:
        m = _COUNT_QUANTIFIER_PATTERN.search(value_desc)
        if m:
            requested = int(m.group("n"))
    if requested is None:
        return None
    if rows >= requested:
        return None  # not a deficit; either meets target or excess
    ratio = rows / requested
    if ratio >= DEFICIT_AUTO_ABOVE:
        return None  # close enough — auto-accept, don't pester user
    return {
        "requested_n": requested,
        "actual_rows": rows,
        "ratio": round(ratio, 3),
    }


def _detect_empty_data(
    rows: int | None, upstream_brief: list[dict],
) -> Optional[dict]:
    """v30.18 (2026-05-19) — distinguish two flavors of rows=0:

      - **source_empty**: this block's upstream max is also 0 (or no upstream
        at all and this is a raw_data block returning 0). Data source genuinely
        empty — pause + ask user how to proceed.
      - **filter_empty**: upstream had rows > 0 but this block (filter / etc)
        narrowed to 0. Legitimate filter result (e.g. "no events match
        condition"). Advance with a data_empty badge in outcome; downstream
        scalar/verdict can still produce a meaningful answer (count=0,
        verdict=fail-threshold-not-met).

    Returns None if rows != 0.
    """
    if not isinstance(rows, int) or rows != 0:
        return None
    upstream_rows: list[int] = []
    for b in (upstream_brief or []):
        r = b.get("output_rows")
        if isinstance(r, int):
            upstream_rows.append(r)
    upstream_max = max(upstream_rows, default=0)
    if upstream_max == 0:
        return {"kind": "source_empty", "upstream_rows": upstream_max}
    return {"kind": "filter_empty", "upstream_rows": upstream_max}


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
    if idx >= len(phases):
        return {}
    if not block_id:
        # v30.18 (2026-05-19) — validation_error / failed path. Snapshot has
        # no block_id (executor short-circuited before block ran). Without
        # this branch, the early return left v30_last_verifier_reject
        # pointing at the PREVIOUS round's reject — agent then saw stale
        # info (e.g. "rejected block_unnest" after just adding a typoed
        # block_filter) and walked away from the real issue.
        cur_phase = phases[idx]
        snapshot_status = snapshot.get("status") or "unknown"
        error_msg = (snapshot.get("error") or "")[:300]
        last_block_id = snapshot.get("block_id") or "(last action errored)"
        verifier_reject_info = {
            "block_id": last_block_id,
            "expected": cur_phase.get("expected") or "",
            "covers": [],
            "rows": None,
            "result": snapshot_status,  # "validation_error" / "failed" / "unknown"
            "error_message": error_msg or "(no error message captured)",
            "judge_reject_reason": None,
            "missing_for_phase": [],
            "would_have_passed_with": [],
        }
        return {
            "v30_last_mutated_logical_id": None,
            "v30_last_preview": None,
            "v30_last_judge_reject_reason": None,
            "v30_last_verifier_reject": verifier_reject_info,
            "sse_events": [_event("phase_verifier_no_match", {
                "current_phase_id": cur_phase.get("id"),
                "expected": cur_phase.get("expected"),
                "block_id": None,
                "result": snapshot_status,
                "error_message": error_msg,
            })],
        }

    registry = SeedlessBlockRegistry()
    registry.load()
    block_spec = registry.get_spec(block_id, "1.0.0") or {}
    # Composite-aware (extends v30.5 split):
    #   covers_output: what the block's OUTPUT PORT yields (rows-gate +
    #                  LLM-judge target — strict).
    #   covers_internal: full capability (block claims to do raw_data →
    #                    transform → chart internally — used to walk FF
    #                    chain through intermediate phases).
    # For non-composite blocks the two are identical (resolver falls back).
    covers_output = _resolve_covers(block_spec, kind="output")
    covers_internal = _resolve_covers(block_spec, kind="internal")
    extractors = (block_spec.get("produces") or {}).get("outcome_extractors") or []

    # Walk phases starting at current; advance while block covers AND
    # LLM-judge confirms the output really satisfies phase.expected_output
    # (v30.10 B2: semantic check on top of rule-based).
    advanced: list[dict[str, Any]] = []
    judge_reject_reason: str | None = None
    cur = idx
    # v30.17l (2026-05-18) — track already-seen expected kinds in this FF
    # chain. Fast-forward is designed for COMPOSITE blocks that legitimately
    # cover multiple DIFFERENT kinds (e.g. block_spc_panel covers
    # raw_data+transform+chart). It must NOT be allowed to merge multiple
    # SAME-kind phases (e.g. 3 chart phases for EWMA/Box/Probability —
    # those are 3 distinct visual outputs and need 3 separate chart blocks).
    seen_kinds_in_chain: set[str] = set()
    while cur < len(phases) and len(advanced) < MAX_FAST_FORWARD_CHAIN:
        phase = phases[cur]
        ph_expected = (phase.get("expected") or "").strip()
        # FF chain membership uses covers_internal so composite blocks
        # (spc_panel: internal=[raw_data, transform, verdict, chart]) can
        # walk through intermediate phases their output port doesn't expose.
        if ph_expected not in covers_internal:
            break
        # `internal_only` = this phase is covered by the block's internal
        # capability but its output port doesn't produce this kind. Rows-
        # gate + LLM-judge are skipped on intermediates (no port to check);
        # they fire on the chain's terminal (ph_expected in covers_output).
        internal_only = ph_expected not in covers_output
        # FF guard: if we've already advanced a phase of the SAME kind by
        # this block in the current chain, stop. The block can only
        # legitimately satisfy distinct kinds (composite multi-kind), not
        # multiple same-kind phases.
        if ph_expected in seen_kinds_in_chain:
            logger.info(
                "phase_verifier: FF chain stop — already advanced a %s "
                "phase by block %s; same-kind stacking not allowed",
                ph_expected, block_id,
            )
            break
        # v30.18 (2026-05-19) — empty-data routing BEFORE rows-gate.
        # rows=0 can mean two different things:
        #  (a) filter narrowed legitimate upstream to 0 rows ("no matches") →
        #      advance + mark data_empty so downstream count/verdict can
        #      still produce a meaningful answer (count=0, verdict=fail).
        #  (b) data source itself empty → pause + ask user (data unavailable).
        empty_info = None
        if cur == idx and not internal_only:
            # Use upstream brief (computed once below for judge; do it here
            # too — cheap walk over canvas edges).
            _upstream = _build_upstream_brief(
                last_lid=last_lid, state=state, registry=registry,
            )
            empty_info = _detect_empty_data(rows, _upstream)
        data_empty_flag = False
        if empty_info:
            if empty_info["kind"] == "filter_empty":
                # Legitimate empty filter result — skip rows-gate, advance
                # with data_empty flag.
                data_empty_flag = True
                logger.info(
                    "phase_verifier: phase %s filter_empty (upstream had "
                    "%s rows, this block 0) — advancing with data_empty badge",
                    phase.get("id"), empty_info["upstream_rows"],
                )
            else:
                # source_empty — pause + ask user (reuse pb_judge_clarify channel)
                phase_id_str = phase.get("id") or ""
                prior_decisions = state.get("v30_judge_decisions") or {}
                prior_decision = prior_decisions.get(phase_id_str)
                any_prior_continue = any(
                    v == "continue" for v in prior_decisions.values()
                )
                if prior_decision == "continue" or any_prior_continue:
                    # user already said continue earlier; silently accept
                    data_empty_flag = True
                    logger.info(
                        "phase_verifier: phase %s source_empty silently "
                        "accepted (prior continue)", phase_id_str,
                    )
                elif prior_decision in ("replan", "cancel"):
                    break
                else:
                    logger.info(
                        "phase_verifier: phase %s source_empty (block %s "
                        "rows=0, no upstream rows) — pausing user clarify",
                        phase_id_str, block_id,
                    )
                    pause_state = {
                        "phase_id": phase_id_str,
                        "kind": "source_empty",
                        "block_id": block_id or "(unknown)",
                    }
                    _tracer_inline = get_current_tracer()
                    if _tracer_inline is not None:
                        _tracer_inline.record_step(
                            "phase_verifier", status="source_empty_pause",
                            **pause_state,
                        )
                    return {
                        "v30_judge_pause": pause_state,
                        "v30_last_mutated_logical_id": None,
                        "v30_last_preview": None,
                        "sse_events": [_event("pb_judge_clarify", {
                            **pause_state,
                            "reason": (
                                f"資料來源回 0 筆。block {block_id} 的上游也沒有資料 — "
                                f"data source 可能空 / 條件太嚴。"
                            ),
                            "options": [
                                {"action": "continue", "label": "用 0 筆繼續",
                                 "hint": "下游 count=0 / verdict 不觸發"},
                                {"action": "replan", "label": "改條件",
                                 "hint": "agent 重新規劃放寬"},
                                {"action": "cancel", "label": "取消"},
                            ],
                        })],
                    }
        # Rule-based quality gate: data-bearing phases must have rows>=1.
        # Skip on internal-only phases (no output port to count) and on the
        # filter_empty branch above (rows=0 is a legitimate result).
        if (
            not internal_only
            and not data_empty_flag
            and ph_expected in {"raw_data", "transform", "table"}
            and (rows is None or rows < 1)
        ):
            logger.info(
                "phase_verifier: phase %s expected=%s but rows=%s — block %s NOT counted",
                phase.get("id"), ph_expected, rows, block_id,
            )
            break

        # v30.17j (2026-05-17) — deficit gate BEFORE LLM-judge. If user
        # asked for "100 筆" but actual is 7 (and not zero), check whether
        # we've already collected a user decision for this phase. If yes
        # (continue), skip the rest of judge logic and advance. If not,
        # pause + ask user.
        eo_value_desc = (phase.get("expected_output") or {}).get("value_desc") or ""
        # v30.18: pass task_contract.count_target so deficit pause fires
        # even when value_desc lacks a count quantifier (the planner's
        # value_desc is often abstract; task_contract holds the user's
        # actual ask).
        _tc = state.get("v30_task_contract") or {}
        _count_target = _tc.get("count_target") if isinstance(_tc, dict) else None
        deficit = _detect_deficit(
            eo_value_desc, rows, count_target_override=_count_target,
        ) if cur == idx else None
        if deficit:
            phase_id_str = phase.get("id") or ""
            prior_decisions = state.get("v30_judge_decisions") or {}
            prior_decision = prior_decisions.get(phase_id_str)
            # v30.17j hotfix #2: if user already chose 'continue' for ANY
            # earlier phase in this build, auto-accept all subsequent
            # deficits silently. The data ceiling is the source's, not the
            # phase's — asking again per phase is redundant noise.
            any_prior_continue = any(v == "continue" for v in prior_decisions.values())
            if prior_decision == "continue" or any_prior_continue:
                logger.info(
                    "phase_verifier: phase %s deficit silently accepted "
                    "(prior=%s, any_continue=%s)",
                    phase_id_str, prior_decision, any_prior_continue,
                )
                judge = {
                    "match": True,
                    "reason": (
                        f"資料源僅 {deficit['actual_rows']} 筆 (要求 "
                        f"{deficit['requested_n']} 筆)；前一階段 user 已選"
                        f"繼續，自動接受"
                    ),
                    "extracted": {},
                }
            elif prior_decision in ("replan", "cancel"):
                # Shouldn't normally reach here because graph routing in
                # replan/cancel paths bypasses re-verifying. Defensive:
                # don't advance, let graph router handle.
                logger.info(
                    "phase_verifier: phase %s has prior decision=%s — break",
                    phase_id_str, prior_decision,
                )
                break
            else:
                # First time seeing deficit — pause + ask user.
                logger.info(
                    "phase_verifier: phase %s DEFICIT detected (%d/%d=%.0f%%), "
                    "pausing for user decision",
                    phase_id_str, deficit["actual_rows"],
                    deficit["requested_n"], deficit["ratio"] * 100,
                )
                pause_state = {
                    "phase_id": phase_id_str,
                    "requested_n": deficit["requested_n"],
                    "actual_rows": deficit["actual_rows"],
                    "ratio": deficit["ratio"],
                    "value_desc": eo_value_desc,
                    "block_id": block_id or "(unknown)",
                }
                # Get tracer inline — the outer `tracer` var is assigned later
                # in this function (line ~248) and isn't available here.
                _tracer_inline = get_current_tracer()
                if _tracer_inline is not None:
                    _tracer_inline.record_step(
                        "phase_verifier", status="judge_deficit_pause",
                        **pause_state,
                    )
                return {
                    "v30_judge_pause": pause_state,
                    # don't change current_phase_idx — verifier rerun after
                    # resume will pick up here
                    "v30_last_mutated_logical_id": None,
                    "v30_last_preview": None,
                    "sse_events": [_event("pb_judge_clarify", {
                        **pause_state,
                        "options": [
                            {"action": "continue", "label": "用現有資料繼續",
                             "hint": f"用 {deficit['actual_rows']} 筆繼續 build，看結果"},
                            {"action": "replan", "label": "重新規劃放寬條件",
                             "hint": "改成「可取得的最大量」"},
                            {"action": "cancel", "label": "取消"},
                        ],
                    })],
                }

        # v30.18: filter_empty short-circuit — rows=0 but legitimate,
        # advance without LLM-judge, tag extracted with data_empty=True
        # so downstream + UI know.
        if data_empty_flag:
            logger.info(
                "phase_verifier: phase %s data_empty advance (block %s)",
                phase.get("id"), block_id,
            )
            judge = {
                "match": True,
                "reason": (
                    f"{ph_expected} phase: filter 拿到 0 rows (upstream 有資料), "
                    f"data_empty 是合法結果。下游 count/verdict 可基於 0 計算。"
                ),
                "extracted": {"data_empty": True},
            }
        # Composite intermediate phase (block claims internal coverage but
        # its output port doesn't expose this kind) — no port to judge or
        # gate against. Trust the FF claim, advance without LLM-judge.
        elif internal_only:
            logger.info(
                "phase_verifier: phase %s (expected=%s) — composite internal-only "
                "by block %s; skipping rows-gate + judge",
                phase.get("id"), ph_expected, block_id,
            )
            judge = {
                "match": True,
                "reason": f"{ph_expected} phase covered internally by composite block {block_id}",
                "extracted": {},
            }
        # v30.17j: chart phases produce chart_spec (no rows).
        # v30.17l hotfix: verdict / alarm phases similarly produce
        # non-row-bearing output (Logic Node = {triggered: bool, evidence}).
        # Judge's row-count semantic rules don't fit either case; skip
        # entirely and trust the covers gate.
        is_chart_phase_chart_output = (
            ph_expected == "chart"
            and "chart" in covers_output
            and _has_chart_spec_output(preview_blob)
        )
        is_verdict_or_alarm_phase = (
            ph_expected in {"verdict", "alarm"}
            and ph_expected in covers_output
        )
        # v30.18 (2026-05-19) — skip-path STRUCTURAL guards BEFORE judge skip.
        # The skip path previously trusted covers tag alone, which let
        # validation_error / orphan nodes "advance" silently (alarm phase
        # then validator C14 catches orphan at finalize → failed_structural).
        # Guards (cheap, no LLM):
        #   (i)  snapshot.status indicates failure (validation_error / failed)
        #        → don't skip; treat as real reject so agent sees error_message
        #   (ii) non-source block has 0 inbound edges AND block isn't
        #        standalone_capable → reject with missing="connect upstream"
        skip_block_failed = False
        skip_block_orphan = False
        if (is_chart_phase_chart_output or is_verdict_or_alarm_phase) and cur == idx:
            snap_status = (snapshot or {}).get("status") or ""
            if snap_status in {"validation_error", "failed", "error"}:
                skip_block_failed = True
            else:
                # check 0 inbound edges + not standalone_capable
                _cat = (block_spec.get("category") or "").lower()
                _meta = (block_spec.get("meta") or {})
                if (
                    _cat != "source"
                    and not _meta.get("standalone_capable")
                ):
                    pipeline_now = state.get("pipeline_json") or {}
                    logical_to_real = state.get("logical_to_real") or {}
                    target_real = logical_to_real.get(last_lid, last_lid)
                    in_count = sum(
                        1 for e in (pipeline_now.get("edges") or [])
                        if (e.get("to") or {}).get("node") == target_real
                    )
                    if in_count == 0:
                        skip_block_orphan = True
        if data_empty_flag or internal_only:
            pass  # judge already set by data_empty / composite-intermediate branch above
        elif skip_block_failed:
            err_msg = ((snapshot or {}).get("error") or "")[:200]
            logger.info(
                "phase_verifier: phase %s (%s) skip-path BLOCKED — "
                "snapshot.status=%s (%s)",
                phase.get("id"), ph_expected, snap_status, err_msg[:80],
            )
            judge = {
                "match": False,
                "reason": (
                    f"block {block_id} execution failed ({snap_status}); "
                    f"error: {err_msg[:120]}"
                ),
                "extracted": {},
                "missing_for_phase": [
                    f"fix {block_id} params or replace block — {snap_status}: {err_msg[:80]}"
                ],
            }
            judge_reject_reason = judge["reason"]
            break
        elif skip_block_orphan:
            logger.info(
                "phase_verifier: phase %s (%s) skip-path BLOCKED — "
                "%s has 0 inbound edges (non-source, not standalone)",
                phase.get("id"), ph_expected, block_id,
            )
            judge = {
                "match": False,
                "reason": (
                    f"{block_id} added but has no upstream edge; "
                    f"non-source blocks need a connect() before advancing."
                ),
                "extracted": {},
                "missing_for_phase": [
                    f"connect upstream → {last_lid}.<input port> "
                    f"(block {block_id} needs data from upstream)"
                ],
            }
            judge_reject_reason = judge["reason"]
            break
        elif (is_chart_phase_chart_output or is_verdict_or_alarm_phase) and cur == idx:
            skip_reason = (
                "chart_spec output" if is_chart_phase_chart_output
                else "verdict/alarm phase (Logic Node output)"
            )
            logger.info(
                "phase_verifier: phase %s (expected=%s) — skipping LLM-judge "
                "(%s, rows=%s)",
                phase.get("id"), ph_expected, skip_reason, rows,
            )
            judge = {
                "match": True,
                "reason": f"{ph_expected} phase satisfied by {block_id} "
                          f"({skip_reason})",
                "extracted": {},
            }
        # v30.10 B2: LLM-judge semantic check (covers expected_output.value_desc)
        # Skip judge for the FAST-FORWARD downstream phases (only judge the
        # current phase being advanced); FF claim is enough for follow-ups
        # because their value_desc may not be matchable from same sample row.
        elif cur == idx and not deficit:
            logger.info(
                "phase_verifier: invoking LLM-judge for phase %s (block=%s rows=%s)",
                phase.get("id"), block_id, rows,
            )
            task_contract = state.get("v30_task_contract")
            try:
                if task_contract:
                    # v30.18: task-accomplishment judge — has full input pack
                    # (user instruction + contract + plan + upstream + ontology
                    # + glossary). Returns advance_phase + missing_for_phase.
                    upstream_brief = _build_upstream_brief(
                        last_lid=last_lid, state=state, registry=registry,
                    )
                    judge_raw = await _judge_task_progress(
                        phase=phase, all_phases=phases, current_idx=cur,
                        snapshot=snapshot, preview_blob=preview_blob,
                        block_id=block_id, rows=rows,
                        task_contract=task_contract,
                        ontology_context=state.get("v30_ontology_context") or "",
                        upstream_brief=upstream_brief,
                    )
                    # Normalize to {match, reason, extracted, missing_for_phase}
                    judge = {
                        "match": bool(judge_raw.get("advance_phase", True)),
                        "reason": str(judge_raw.get("reason") or "")[:300],
                        "extracted": judge_raw.get("extracted_outcomes") or {},
                        "missing_for_phase": judge_raw.get("missing_for_phase") or [],
                    }
                else:
                    judge = await _llm_judge_phase_outcome(
                        phase=phase, snapshot=snapshot,
                        preview_blob=preview_blob, block_id=block_id, rows=rows,
                    )
                logger.info(
                    "phase_verifier: LLM-judge for phase %s -> match=%s reason=%s",
                    phase.get("id"), judge.get("match"),
                    str(judge.get("reason") or "")[:80],
                )
            except Exception as ex:  # noqa: BLE001 — fail-safe: advance on judge error
                logger.info("phase_verifier: LLM-judge errored, defaulting to advance: %s", ex)
                judge = {"match": True, "reason": "(judge errored, defaulted advance)",
                         "extracted": {}}
            if not judge.get("match"):
                judge_reject_reason = str(judge.get("reason") or "no reason given")
                logger.info(
                    "phase_verifier: LLM-judge REJECTED phase %s — %s",
                    phase.get("id"), judge_reject_reason[:120],
                )
                break
        elif cur != idx:
            # FF downstream phase — accept the FF claim, skip judge.
            judge = {"match": True, "reason": "(FF downstream — judge skipped)", "extracted": {}}
        # else: cur == idx and deficit — `judge` was set inline by the
        # deficit-prior-decision branch above; keep it.

        outcome = _extract_outcome(phase, snapshot, preview_blob, extractors, block_id)
        advanced.append({
            "id": phase["id"],
            "expected": ph_expected,
            "goal": phase.get("goal"),
            "outcome": outcome["text"],
            "evidence": outcome["evidence"],
            "llm_summary": judge.get("reason"),
            "llm_extracted": judge.get("extracted") or {},
            "plan_target": phase.get("expected_output") or {},
        })
        # v30.17l: record this kind so the same block can't merge another
        # same-kind phase later in the chain.
        seen_kinds_in_chain.add(ph_expected)
        cur += 1

    tracer = get_current_tracer()

    if not advanced:
        # Block didn't satisfy current phase — let the loop continue rounds.
        # Don't emit phase_completed; stay on same idx, increment nothing.
        cur_phase = phases[idx]
        cur_expected = cur_phase.get("expected") or ""
        # v30.17l: compute would_pass + result up here (outside tracer block)
        # so they're available for state.v30_last_verifier_reject below.
        would_pass: list[str] = []
        result = "unknown"
        try:
            for (n, _v), s in (registry.catalog or {}).items():
                if str(s.get("status") or "").lower() == "deprecated":
                    continue
                s_covers = _resolve_covers(s, kind="output")
                if cur_expected in s_covers:
                    would_pass.append(n)
            rows_gate_applicable = cur_expected in {"raw_data", "transform", "table"}
            rows_gate_failed = rows_gate_applicable and (rows is None or rows < 1)
            if cur_expected not in covers_internal:
                result = "covers mismatch"
            elif rows_gate_failed:
                result = "rows quality gate failed"
            elif judge_reject_reason is not None:
                result = "llm_judge_rejected"
            else:
                result = "unknown (no rule gate hit but verifier rejected)"
        except Exception as ex:  # noqa: BLE001
            logger.info("phase_verifier: would_pass computation failed: %s", ex)

        if tracer is not None:
            tracer.record_step(
                "phase_verifier", status="no_match",
                phase_id=cur_phase.get("id"),
                expected=cur_expected,
                block_id=block_id, covers=covers_output, rows=rows,
                judge_reject_reason=judge_reject_reason,
            )
            try:
                rows_gate_applicable = cur_expected in {"raw_data", "transform", "table"}
                tracer.record_verifier_decision(
                    phase_id=cur_phase.get("id"),
                    phase_expected=cur_expected,
                    candidate_block=block_id or "(unknown)",
                    candidate_block_covers=covers_output,
                    comparison={
                        "expected_in_covers": cur_expected in covers_internal,
                        "rows_quality_gate": (
                            "applicable" if rows_gate_applicable else "n/a"
                        ),
                        "rows": rows,
                        "result": result,
                        "judge_reject_reason": judge_reject_reason,
                    },
                    verdict="no_match",
                    would_have_passed_with=would_pass,
                )
            except Exception as ex:  # noqa: BLE001
                logger.info("trace.record_verifier_decision failed (non-fatal): %s", ex)
        # v30.17l (2026-05-18) — surface verifier reject info for next
        # round prompt: which block was rejected, why, and which blocks
        # would have passed. Without this LLM kept retrying the same
        # rejected block (e.g. block_ewma_cusum for a verdict phase).
        # v30.18: actionable hint from new judge — list of concrete steps the
        # agent should take to satisfy this phase. Empty for legacy judge.
        missing_for_phase: list[str] = []
        try:
            missing_for_phase = list(judge.get("missing_for_phase") or [])  # type: ignore[name-defined]
        except (NameError, AttributeError):
            pass
        verifier_reject_info = {
            "block_id": block_id or "(unknown)",
            "expected": cur_expected,
            "covers": list(covers_output),
            "rows": rows,
            "result": result if 'result' in dir() else "no_match",
            "judge_reject_reason": judge_reject_reason,
            "would_have_passed_with": would_pass[:10] if 'would_pass' in dir() else [],
            "missing_for_phase": missing_for_phase,
        }
        return {
            # Clear handoff fields so next round can fill them again
            "v30_last_mutated_logical_id": None,
            "v30_last_preview": None,
            # v30.10 B2: surface LLM-judge reject reason for next round prompt
            "v30_last_judge_reject_reason": judge_reject_reason,
            # v30.17l: full verifier reject info for next round prompt
            "v30_last_verifier_reject": verifier_reject_info,
            "sse_events": [_event("phase_verifier_no_match", {
                "current_phase_id": phases[idx].get("id"),
                "expected": phases[idx].get("expected"),
                "block_id": block_id,
                "covers": covers_output,
                "rows": rows,
                "judge_reject_reason": judge_reject_reason,
                "missing_for_phase": missing_for_phase,
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
            # v30.10 B2: LLM-judge enriched outcome (propagates to next phase)
            "llm_summary": adv.get("llm_summary"),
            "llm_extracted": adv.get("llm_extracted") or {},
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
        # Clear judge reject reason now that phase advanced cleanly
        "v30_last_judge_reject_reason": None,
        # v30.17l hotfix: also clear verifier reject info so next phase
        # doesn't see stale reject from a previous phase (was causing
        # p6 prompt to show p3's reject info → LLM confused).
        "v30_last_verifier_reject": None,
    }

    # v30.18: build ontology context the first time a raw_data phase
    # advances. ~1-2 sentences describing the source data shape, carried
    # into every subsequent _judge_task_progress call.
    if not state.get("v30_ontology_context"):
        first_raw = next(
            (a for a in advanced if a.get("expected") == "raw_data"), None
        )
        if first_raw:
            ontology_hint = _collect_ontology_context(
                preview_blob=preview_blob, block_id=block_id, rows=rows,
            )
            if ontology_hint:
                update["v30_ontology_context"] = ontology_hint
                logger.info(
                    "phase_verifier: collected ontology_context = %s",
                    ontology_hint[:200],
                )

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
        # v30.1.1: structured verifier decision per advanced phase
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


def _resolve_covers(spec: dict, kind: str = "output") -> list[str]:
    """v30.5 (2026-05-16): resolve produces.covers per intent kind.

    Two semantically distinct concepts merged in the produces map:
      - `covers_output`: what the block's OUTPUT PORT can satisfy. Used by
        verifier (rows quality gate is on output, not internal capability).
        For spc_panel this is ['chart'] — output port is chart_spec only.
      - `covers_internal`: what work the block does INTERNALLY. Used by
        section / promotion (LLM-facing hint). For spc_panel this is
        ['raw_data', 'transform', 'verdict', 'chart'] — it internally
        fetches + filters + draws.

    Backward compat: if produces only has `covers` (old single field),
    treat it as both. If only one of the two new fields is set:
      - kind='output' missing → fall back to inferred from category+output_schema
        (do NOT mirror from internal; internal may overstate output)
      - kind='internal' missing → fall back to covers_output (output is a
        valid subset of internal capability)
    """
    produces = spec.get("produces") or {}
    if kind == "output":
        v = produces.get("covers_output")
        if v is not None:
            return list(v)
        # Old single field treated as output
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
        # Last resort: same as output
        return _infer_covers_from_block_spec(spec)
    raise ValueError(f"unknown kind={kind!r} (expected 'output' or 'internal')")


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


async def _llm_judge_phase_outcome(
    phase: dict,
    snapshot: dict,
    preview_blob: dict,
    block_id: str | None,
    rows: int | None,
) -> dict[str, Any]:
    """v30.10 B2: ask LLM whether the terminal node's output actually
    satisfies phase.expected_output.value_desc (semantic check on top of
    rule-based covers/rows check).

    Returns: {"match": bool, "reason": str, "extracted": dict<outcome_key, value>}.
    On error, defaults to match=True (don't block phase on judge failure).
    """
    from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
    import re

    eo = phase.get("expected_output") or {}
    value_desc = eo.get("value_desc") or "(unspecified)"
    outcome_keys = eo.get("outcome_keys") or []
    criterion = eo.get("criterion") or ""

    # Extract one sample row from preview for the judge to inspect
    sample_row: Any = None
    for _port, blob in (preview_blob or {}).items():
        if not isinstance(blob, dict):
            continue
        if blob.get("type") == "dataframe":
            rs = (
                blob.get("sample_rows") or blob.get("rows_sample")
                or blob.get("rows") or []
            )
            if rs and isinstance(rs[0], dict):
                # Trim heavy nested dicts to keep judge prompt compact
                first = rs[0]
                sample_row = {}
                for k, v in list(first.items())[:20]:
                    if isinstance(v, dict) and len(v) > 5:
                        sample_row[k] = f"<dict {len(v)} keys: {list(v.keys())[:4]}...>"
                    elif isinstance(v, list) and len(v) > 3:
                        sample_row[k] = f"<list[{len(v)}] first: {v[0] if v else None}>"
                    else:
                        sample_row[k] = v
                break
        if blob.get("type") in ("dict", "chart_spec"):
            snap = blob.get("snapshot") or blob
            if isinstance(snap, dict):
                sample_row = {k: snap.get(k) for k in list(snap.keys())[:8]}
                break

    import json as _json
    sample_json = (_json.dumps(sample_row, ensure_ascii=False, default=str)[:600]
                   if sample_row else "(no sample available)")

    system_prompt = (
        "你是 pipeline phase outcome 判定者。輸出純 JSON 物件 (no markdown fence)，"
        "schema: {\"match\": bool, \"reason\": \"<100 字以內為何 match/not\", "
        "\"extracted\": {<outcome_key>: <value_or_null>}}。\n\n"
        "**量詞規則**：\n"
        "- value_desc 含「最後一次 / latest / last / first / 第一筆」(單例語意)：\n"
        "  → 必須 total rows == 1\n"
        "  → 多筆或零筆都 match=false（這是 single-row 語意，不能放寬）\n"
        "- value_desc 含「N 張 / N 個 / N 筆」(精確數量請求):\n"
        "  → rows >= N        → match=true\n"
        "  → rows >= N * 0.2  → match=true, reason 加 note『資料源僅 {rows} 筆，少於要求 {N}』\n"
        "  → rows <  N * 0.2  → match=false, reason『資料源嚴重不足 (僅 {rows} 筆 / 要求 {N})』\n"
        "  v30.17i 放寬理由：simulator / 真實資料源 row 數有上限，user 寫『100 筆』但實際只有"
        "7 筆時，build 不該因此整個失敗 — 只要在合理 ratio 內 (>=20%) 就讓 pipeline 繼續，\n"
        "  讓 user 自己看 chart 決定要不要重跑。低於 20% 才是『真的拿不到資料』。\n"
        "- value_desc 含「所有 / all / list / 清單」(集合語意，無明確數量):\n"
        "  → rows >= 2 → match=true (有 2 筆以上就算「集合」)\n"
        "  → rows == 1 → match=true with note『資料源僅 1 筆』(不擋)\n"
        "  → rows == 0 → match=false\n"
        "- value_desc 寫「一個數值 / 數量 / count」(scalar 語意):\n"
        "  → 必須是 1 row + 對應 outcome_key 欄位有非 null 值\n\n"
        "**rationale**：rule-based gate 已查 covers+rows>=1，你的職責是**抓 plan 語意 vs 實際"
        "結果**的精確 mismatch — 但要區分「pipeline 邏輯錯」(該拒) vs「資料源天生有限」(該放)。\n"
        "「最後一次」絕對不是「最新時刻的一批 N rows」，是「**只有 1 row** (the single latest)」。"
    )
    user_prompt = (
        f"Phase: {phase.get('id')}\n"
        f"Goal: {phase.get('goal')}\n"
        f"Expected output spec:\n"
        f"  value_desc: {value_desc}\n"
        f"  outcome_keys: {outcome_keys}\n"
        + (f"  criterion: {criterion}\n" if criterion else "")
        + f"\nTerminal node:\n"
        f"  block_id: {block_id}\n"
        f"  **total rows: {rows}**  ← 嚴格對照 value_desc 的量詞\n"
        f"  sample row: {sample_json}\n\n"
        f"問: 這 output (含 total rows 數量) 是否**嚴格**滿足 expected_output.value_desc?\n"
        f"若 value_desc 暗示單一結果 (最後/first/latest) 而 rows != 1，必為 false。\n"
    )

    client = get_llm_client()
    resp = await client.create(
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=512,
    )
    raw = (resp.text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    try:
        parsed = _json.loads(text)
    except Exception:
        # Last resort: extract first json object
        m = re.search(r"\{.*\}", text, re.DOTALL)
        parsed = _json.loads(m.group(0)) if m else {}

    if not isinstance(parsed, dict):
        return {"match": True, "reason": "(judge returned non-dict, default advance)",
                "extracted": {}}
    return {
        "match": bool(parsed.get("match", True)),
        "reason": str(parsed.get("reason") or "")[:200],
        "extracted": parsed.get("extracted") or {},
    }


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


# ─────────────────────────────────────────────────────────────────────
# v30.18 — task-accomplishment verifier helpers
# ─────────────────────────────────────────────────────────────────────


def _collect_ontology_context(
    preview_blob: dict, block_id: str | None, rows: int | None,
) -> str:
    """One-shot hint about source data shape, captured from first raw_data
    block's preview. Examples:
      "process_history 6 rows; each event has nested spc_charts list (12 chart kinds)"
      "mcp_call returned 100 rows with columns [eventTime, toolID, lotID, step, spc_status]"
    """
    if not preview_blob or not block_id:
        return ""
    for _port, blob in (preview_blob or {}).items():
        if not isinstance(blob, dict) or blob.get("type") != "dataframe":
            continue
        cols = blob.get("columns") or []
        sample_rows = (
            blob.get("sample_rows") or blob.get("rows_sample")
            or blob.get("rows") or []
        )
        sample = sample_rows[0] if sample_rows else {}
        nested_hints: list[str] = []
        if isinstance(sample, dict):
            for k, v in sample.items():
                if isinstance(v, list) and v:
                    first = v[0]
                    if isinstance(first, dict):
                        keys = list(first.keys())[:6]
                        nested_hints.append(f"{k} is list[dict] keys={keys}")
                    else:
                        nested_hints.append(f"{k} is list len={len(v)}")
                elif isinstance(v, dict):
                    keys = list(v.keys())[:6]
                    nested_hints.append(f"{k} is dict keys={keys}")
        parts = [f"{block_id} returned {rows} rows"]
        if cols:
            parts.append(f"columns={cols[:12]}")
        if nested_hints:
            parts.append("nested: " + "; ".join(nested_hints[:3]))
        return ". ".join(parts)
    return ""


def _build_upstream_brief(
    last_lid: str, state: BuildGraphState, registry: Any,
) -> list[dict]:
    """Compact upstream chain for judge prompt — for each ancestor:
        {node, block_id, output_rows, key_columns}
    Skips sample row contents (already verified upstream); judge only
    needs to know structure not data values."""
    pipeline = (state.get("pipeline_json") or {})
    nodes = pipeline.get("nodes") or []
    edges = pipeline.get("edges") or []
    exec_trace = state.get("exec_trace") or {}
    logical_to_real = state.get("logical_to_real") or {}
    real_to_logical = {v: k for k, v in logical_to_real.items()}

    # last_lid is logical; map to real for canvas traversal
    target_real = logical_to_real.get(last_lid, last_lid)
    by_id = {n.get("id"): n for n in nodes if n.get("id")}
    target_node = by_id.get(target_real)
    if not target_node:
        return []
    ancestors: set[str] = set()
    frontier = {target_real}
    while frontier:
        nxt: set[str] = set()
        for e in edges:
            to_id = (e.get("to") or {}).get("node")
            from_id = (e.get("from") or {}).get("node")
            if to_id in frontier and from_id and from_id not in ancestors and from_id != target_real:
                ancestors.add(from_id)
                nxt.add(from_id)
        frontier = nxt

    brief: list[dict] = []
    for real_id in ancestors:
        logical_id = real_to_logical.get(real_id, real_id)
        snap = exec_trace.get(logical_id) or {}
        node = by_id.get(real_id, {})
        brief.append({
            "node": logical_id,
            "block_id": node.get("block_id", "?"),
            "output_rows": snap.get("rows"),
            "key_columns": (snap.get("cols") or [])[:8],
        })
    return brief


async def _judge_task_progress(
    *,
    phase: dict,
    all_phases: list[dict],
    current_idx: int,
    snapshot: dict,
    preview_blob: dict,
    block_id: str | None,
    rows: int | None,
    task_contract: dict,
    ontology_context: str,
    upstream_brief: list[dict],
) -> dict[str, Any]:
    """v30.18: task-accomplishment judge.

    Compares CURRENT block + upstream + canvas state against the extracted
    task contract (user-instruction-derived) to decide whether this phase
    is genuinely satisfied. Returns missing_for_phase hints so the agent's
    next round prompt can guide the right block pick.

    Returns: {advance_phase, task_progress_delta, missing_for_phase[],
              reason, extracted_outcomes}.
    On error/parse fail, defaults to advance_phase=True (don't block build).
    """
    from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
    from python_ai_sidecar.agent_builder.graph_build.prompts import (
        load_spc_apc_glossary,
    )
    import json as _json
    import re

    glossary = load_spc_apc_glossary()

    # Build plan snapshot with [DONE]/[CURRENT]/[PENDING] markers
    plan_lines: list[str] = []
    for i, ph in enumerate(all_phases):
        if i < current_idx:
            status = "DONE"
        elif i == current_idx:
            status = "CURRENT"
        else:
            status = "PENDING"
        plan_lines.append(
            f"  {ph.get('id')} [{status}] {ph.get('expected')}: {(ph.get('goal') or '')[:80]}"
        )

    # Extract sample rows (3-5 full rows when possible, not aggressively
    # truncated — judge needs to see actual values to detect mixed kinds)
    sample_rows: list[dict] = []
    cols: list[str] = []
    for _port, blob in (preview_blob or {}).items():
        if not isinstance(blob, dict):
            continue
        if blob.get("type") == "dataframe":
            cols = blob.get("columns") or []
            rs = (
                blob.get("sample_rows") or blob.get("rows_sample")
                or blob.get("rows") or []
            )
            for r in rs[:5]:
                if isinstance(r, dict):
                    trimmed: dict[str, Any] = {}
                    for k, v in list(r.items())[:14]:
                        if isinstance(v, dict) and len(v) > 4:
                            trimmed[k] = f"<dict {len(v)}k>"
                        elif isinstance(v, list) and len(v) > 4:
                            trimmed[k] = f"<list[{len(v)}]>"
                        else:
                            trimmed[k] = v
                    sample_rows.append(trimmed)
            break
        if blob.get("type") in ("dict", "chart_spec"):
            snap = blob.get("snapshot") or blob
            if isinstance(snap, dict):
                sample_rows.append({k: snap.get(k) for k in list(snap.keys())[:10]})
                break

    upstream_block = ""
    if upstream_brief:
        upstream_block = "\n".join(
            f"  {b['node']} [{b['block_id']}] rows={b['output_rows']} keys={b['key_columns']}"
            for b in upstream_brief
        )
    else:
        upstream_block = "  (none — this is the first block on this path)"

    system_prompt = (
        "你是 pipeline build verifier。判斷剛加的 block 是否讓 user 的任務更接近達成。\n\n"
        "輸出 JSON (no markdown fence):\n"
        "{\n"
        '  "advance_phase": bool,           # 這個 block 是否完成當前 phase\n'
        '  "task_progress_delta": str,      # 一句話：這 block 對任務的貢獻\n'
        '  "missing_for_phase": [str],      # **必填且非空** — 給 agent actionable 的下一步\n'
        '  "reason": str,                   # 100 字內判定原因\n'
        '  "extracted_outcomes": {}         # phase outcome key/value (給 ledger)\n'
        "}\n\n"
        "**missing_for_phase 規則（極重要）**:\n"
        "- 你有 task_contract + sample row + glossary 的『上帝視角』；agent 沒有。\n"
        "- 每次都必須給 1-2 條 **具體**指令，格式如 'add_node block_filter params={column=name,op==,value=xbar_chart}' 或 'connect n2.data -> n3.data'。\n"
        "- advance_phase=true 時，missing_for_phase 寫該 phase 的 follow-up confirmation（如 ['phase complete, proceed to next']）。\n"
        "- advance_phase=false 時，missing_for_phase 寫**最 blocking 的單一動作**（不要列 3 條，列最該做的 1 條）。\n"
        "- **禁止寫空 []** — 寫不出來就回顧 task_contract 找 gap。\n\n"
        "**硬性決策樹 (照這個順序判，不要自己加條件)**:\n\n"
        "STEP 1 — 結構檢查 (sample row 欄位值):\n"
        "  query: sample row 的 toolID / step / lotID 等欄位值\n"
        "         == contract.source_filters 的對應值?\n"
        "    NO  → advance_phase=FALSE, missing=['block 拉錯資料（toolID/step 不符），改 params 或換 block']\n"
        "    YES → 進 STEP 2\n\n"
        "STEP 2 — 資料聚焦檢查 (**只對 transform / chart / table** 階段套用):\n"
        "  query: 當前 phase 是 {transform, chart, table} 其中之一?\n"
        "    NO  → 跳過此 step (raw_data / scalar / verdict / alarm 不檢查 data_filters),\n"
        "          直接進 STEP 3\n"
        "    YES → contract.data_filters 有指定值?\n"
        "          NO  → 跳過, 進 STEP 3\n"
        "          YES → sample rows 的對應欄位 unique 值集合 == data_filters 的值?\n"
        "                NO  → advance_phase=FALSE,\n"
        "                      missing=['filter(<col>=<value>) 把資料聚焦到單一目標']\n"
        "                YES → 進 STEP 3\n\n"
        "  **raw_data phase 的任務是『拿原始資料』, sample 是否含 mixed status\n"
        "    不是 raw_data 的責任**; 套 STEP 2 會把 raw_data block 誤拒, 卡死\n"
        "    後續 phase。\n\n"
        "STEP 3 — 數量檢查 (只在 STEP 1+2 都過後)：\n"
        "  query: rows > 0?\n"
        "    NO  → advance_phase=FALSE\n"
        "    YES → **無論 rows 是否達 count_target, advance_phase=TRUE**\n"
        "          (count_target 不足只記在 reason 一行 note, **不影響 advance**)\n"
        "          理由: 資料源天生有限不是 block 的錯; user 看 chart 自己決定是否要重跑\n\n"
        "**禁止事項**:\n"
        "- 禁止以「count 不足」為主因 reject 一個結構正確的 raw_data block\n"
        "- 禁止在 STEP 1+2 都過的情況下加「但我覺得...」轉折去 reject\n"
        "- missing_for_phase 只列**最 blocking 的 1-2 條**，每條一句、actionable\n\n"
        + glossary
    )

    user_prompt = (
        f"USER INSTRUCTION:\n{task_contract.get('user_instruction','')}\n\n"
        f"TASK CONTRACT:\n{_json.dumps(task_contract, ensure_ascii=False, indent=2)[:1200]}\n\n"
        f"PLAN SNAPSHOT:\n" + "\n".join(plan_lines) + "\n\n"
        f"CURRENT PHASE: {phase.get('id')} {phase.get('expected')}\n"
        f"PHASE GOAL: {phase.get('goal')}\n"
        f"PHASE expected_output: {_json.dumps(phase.get('expected_output') or {}, ensure_ascii=False)[:300]}\n\n"
        f"UPSTREAM CHAIN (already accepted):\n{upstream_block}\n\n"
        f"JUST-ADDED BLOCK:\n"
        f"  block_id: {block_id}\n"
        f"  total_rows: {rows}\n"
        f"  columns: {cols[:15]}\n"
        f"  sample rows (up to 5):\n{_json.dumps(sample_rows, ensure_ascii=False, indent=2)[:1500]}\n\n"
        f"ONTOLOGY CONTEXT (build-cached):\n  {ontology_context or '(none yet)'}\n"
    )

    client = get_llm_client()
    resp = await client.create(
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=600,
    )
    raw = (resp.text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    try:
        parsed = _json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        parsed = _json.loads(m.group(0)) if m else {}
    if not isinstance(parsed, dict):
        return {
            "advance_phase": True,
            "task_progress_delta": "(judge returned non-dict, default advance)",
            "missing_for_phase": [],
            "reason": "judge non-dict",
            "extracted_outcomes": {},
        }
    return {
        "advance_phase": bool(parsed.get("advance_phase", True)),
        "task_progress_delta": str(parsed.get("task_progress_delta") or "")[:200],
        "missing_for_phase": [str(m)[:200] for m in (parsed.get("missing_for_phase") or [])][:3],
        "reason": str(parsed.get("reason") or "")[:300],
        "extracted_outcomes": parsed.get("extracted_outcomes") or {},
    }
