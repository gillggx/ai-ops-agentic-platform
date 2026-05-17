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

        # v30.10 B2: LLM-judge semantic check (covers expected_output.value_desc)
        # Skip judge for the FAST-FORWARD downstream phases (only judge the
        # current phase being advanced); FF claim is enough for follow-ups
        # because their value_desc may not be matchable from same sample row.
        if cur == idx:
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
        else:
            judge = {"match": True, "reason": "(FF downstream — judge skipped)", "extracted": {}}

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
        "你是 pipeline phase outcome 嚴格判定者。輸出純 JSON 物件 (no markdown fence)，"
        "schema: {\"match\": bool, \"reason\": \"<100 字以內為何 match/not\", "
        "\"extracted\": {<outcome_key>: <value_or_null>}}。\n\n"
        "**嚴格量詞規則（違反一律 match=false）**：\n"
        "- value_desc 含「最後一次 / latest / last / first / 第一筆」→ 必須 total rows == 1\n"
        "- value_desc 含「N 張 / N 個 / N 筆」→ 必須 rows >= N (應為 scalar/精確數字)\n"
        "- value_desc 含「所有 / all / list / 清單」→ 必須 rows >= 2 (集合語意)\n"
        "- value_desc 寫「一個數值 / 數量 / count」→ 必須是 scalar (1 row + 對應欄位)\n\n"
        "**rationale**：rule-based gate 已查 covers+rows>=1, 你的職責是**抓 plan 語意 vs 實際結果**的精確 mismatch。\n"
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
