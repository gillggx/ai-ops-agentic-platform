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


def _detect_deficit(value_desc: str | None, rows: int | None) -> Optional[dict]:
    """v30.17j — return deficit info dict when actual rows are significantly
    below the requested count quantifier in value_desc; else None.

    Returns: {"requested_n": int, "actual_rows": int, "ratio": float} or None.

    Triggers ONLY when ALL of:
      - value_desc parseable for an explicit count (≥ 2 digits + unit)
      - rows > 0 (zero handled separately — likely filter bug, not data ceiling)
      - rows < requested
      - ratio = rows / requested < DEFICIT_AUTO_ABOVE (i.e. < 80% — not close enough)

    Used by phase_verifier_node to decide whether to pause + ask user vs
    continue the existing rule-based + LLM-judge gate.
    """
    if not value_desc or not isinstance(rows, int) or rows <= 0:
        return None
    m = _COUNT_QUANTIFIER_PATTERN.search(value_desc)
    if not m:
        return None
    requested = int(m.group("n"))
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
    # v30.5 (2026-05-16): use covers_output (strict — what the block's
    # output port can actually satisfy). See _resolve_covers docstring.
    covers = _resolve_covers(block_spec, kind="output")
    extractors = (block_spec.get("produces") or {}).get("outcome_extractors") or []

    # Walk phases starting at current; advance while block covers AND
    # LLM-judge confirms the output really satisfies phase.expected_output
    # (v30.10 B2: semantic check on top of rule-based).
    advanced: list[dict[str, Any]] = []
    judge_reject_reason: str | None = None
    cur = idx
    while cur < len(phases) and len(advanced) < MAX_FAST_FORWARD_CHAIN:
        phase = phases[cur]
        ph_expected = (phase.get("expected") or "").strip()
        if ph_expected not in covers:
            break
        # Rule-based quality gate: data-bearing phases must have rows>=1.
        if ph_expected in {"raw_data", "transform", "table"} and (rows is None or rows < 1):
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
        deficit = _detect_deficit(eo_value_desc, rows) if cur == idx else None
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

        # v30.17j hotfix: chart phases produce chart_spec, not row-based
        # output — rows=None is by design. Judge prompt's row-count rules
        # ("1 張 / N 筆") incorrectly reject these. Skip judge entirely
        # for chart-phase + chart_spec output; trust the covers gate.
        is_chart_phase_chart_output = (
            ph_expected == "chart"
            and "chart" in covers
            and _has_chart_spec_output(preview_blob)
        )
        if is_chart_phase_chart_output and cur == idx:
            logger.info(
                "phase_verifier: chart phase %s with chart_spec output — "
                "skipping LLM-judge (rows=%s by design)",
                phase.get("id"), rows,
            )
            judge = {
                "match": True,
                "reason": f"chart phase satisfied by chart_spec from {block_id}",
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
            try:
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
        cur += 1

    tracer = get_current_tracer()

    if not advanced:
        # Block didn't satisfy current phase — let the loop continue rounds.
        # Don't emit phase_completed; stay on same idx, increment nothing.
        cur_phase = phases[idx]
        cur_expected = cur_phase.get("expected") or ""
        if tracer is not None:
            tracer.record_step(
                "phase_verifier", status="no_match",
                phase_id=cur_phase.get("id"),
                expected=cur_expected,
                block_id=block_id, covers=covers, rows=rows,
                judge_reject_reason=judge_reject_reason,
            )
            # v30.1.1: empathetic-debug — what blocks WOULD have passed?
            # v30.5: use covers_output (consistent with verifier's actual check)
            try:
                would_pass: list[str] = []
                for (n, _v), s in (registry.catalog or {}).items():
                    if str(s.get("status") or "").lower() == "deprecated":
                        continue
                    s_covers = _resolve_covers(s, kind="output")
                    if cur_expected in s_covers:
                        would_pass.append(n)
                # v30.17g (2026-05-17) — distinguish the three failure modes
                # so debugging tools (.claude/skills/verify-build) can show
                # the actual reason instead of always saying "rows gate":
                #   covers mismatch — block can't produce this kind
                #   rows quality gate — covers OK but data-bearing phase had 0 rows
                #   llm_judge_rejected — both rule gates OK but semantic check failed
                rows_gate_applicable = cur_expected in {"raw_data", "transform", "table"}
                rows_gate_failed = rows_gate_applicable and (rows is None or rows < 1)
                if cur_expected not in covers:
                    result = "covers mismatch"
                elif rows_gate_failed:
                    result = "rows quality gate failed"
                elif judge_reject_reason is not None:
                    result = "llm_judge_rejected"
                else:
                    # Shouldn't reach here — would_pass should be empty, log so we know
                    result = "unknown (no rule gate hit but verifier rejected)"
                tracer.record_verifier_decision(
                    phase_id=cur_phase.get("id"),
                    phase_expected=cur_expected,
                    candidate_block=block_id or "(unknown)",
                    candidate_block_covers=covers,
                    comparison={
                        "expected_in_covers": cur_expected in covers,
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
        return {
            # Clear handoff fields so next round can fill them again
            "v30_last_mutated_logical_id": None,
            "v30_last_preview": None,
            # v30.10 B2: surface LLM-judge reject reason for next round prompt
            "v30_last_judge_reject_reason": judge_reject_reason,
            "sse_events": [_event("phase_verifier_no_match", {
                "current_phase_id": phases[idx].get("id"),
                "expected": phases[idx].get("expected"),
                "block_id": block_id,
                "covers": covers,
                "rows": rows,
                "judge_reject_reason": judge_reject_reason,
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
        # v30.1.1: structured verifier decision per advanced phase
        try:
            for adv in advanced:
                tracer.record_verifier_decision(
                    phase_id=adv["id"],
                    phase_expected=adv["expected"],
                    candidate_block=block_id or "(unknown)",
                    candidate_block_covers=covers,
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
