"""compile_chunk_node — v16 Phase 2 of macro+chunk architecture.

Takes 1 macro step at a time and translates it to 1-3 concrete ops
(add_node / connect / set_param). Append to state.plan; the existing
dispatch_op + call_tool loop walks them. After all ops for THIS step
have executed, routing brings us back here for the NEXT macro step.

Why this scales better than 1-shot plan_node:
- LLM sees ONLY 1 step at a time → input scope ~10x smaller
- Block catalog filtered to just the candidate + neighbors (~5 blocks)
  rather than all 52 (~5k tokens vs ~55k)
- Errors localized: if step 3's compile fails, we retry step 3, don't
  touch steps 1-2 (which already ran successfully)
- Upstream state (real cols + sample) feeds in, so the LLM doesn't
  have to "guess" what upstream produces

Output: appends 1-3 ops to state.plan. validate_chunk runs after to
catch structural errors. On failure, compile_attempts[step] increments;
max 2 retries before falling back to reflect_plan / failing the build.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)


MAX_COMPILE_ATTEMPTS = 2
# How many "neighbor" blocks to include in the LLM prompt context
# alongside the candidate block_id. Picks blocks in the same category.
N_NEIGHBOR_BLOCKS = 4


_SYSTEM = """你是 pipeline op-compiler。給你 1 個 macro step 的描述，你產出 1-3 個 ops 來實作它。

每個 op 是下面 5 種之一:
  - add_node     (帶 block_id, block_version="1.0.0", node_id, params)
  - set_param    (改 existing node 的 1 個 param)
  - connect      (接 2 個 node 的 port: src_id, src_port, dst_id, dst_port)
  - run_preview  (debug 用，通常不必)
  - remove_node  (刪 existing node)

你會看到:
  1. 這個 macro step 的描述 + expected_kind + candidate_block hint
  2. 上游已建好的 nodes (含 block_id + 真實 output cols)
  3. 候選 blocks (含完整 description + param_schema)
  4. 整個 macro plan 的脈絡 (前後 steps 都做什麼)

嚴格規則 (違反 → op 會被擋下):

1. **不重複 add_node**
   - UPSTREAM TRACE 列出的 logical id (n1, n2, ...) 都已經在 canvas 上，**不要再 add 第二次**
   - 如果某 macro step 看起來需要的 block 已經在 canvas (block_id 一樣)，**不 add，改用 set_param 改它的參數** 或直接 connect
   - 新加 node 的 logical id 必須是接續編號 (canvas 最大 + 1)

2. **column ref 嚴格從 UPSTREAM TRACE 取**
   - 如果 op 的 param 是 column 名 (filter.column, sort.columns, select.fields...)，**這個名字必須出現在 UPSTREAM TRACE 任一個 upstream node 的 cols 裡**
   - 不要憑想像填欄位 (例: 上游沒列 'spc_xbar_chart_value'，就不要寫這個 column ref)
   - 不確定欄位該叫什麼 → 看 block_process_history description，或上游真實列出的欄位名

3. **不要 remove 上游 node** — 上游已穩，這 step 只負責接續

4. **每 step 通常 1 add_node + 1 connect** (有的 step 只是 set_param 不加新 node)

5. **如果 candidate_block 看起來不對**，從 RELEVANT BLOCKS 區段挑一個對的；**絕對不要寫不在 RELEVANT BLOCKS 區段的 block_id** (e.g. 自己合成 "block_sort_limit" → 系統會 reject)

只輸出 JSON:
{
  "ops": [
    {"type": "add_node", "block_id": "...", "block_version": "1.0.0",
     "node_id": "n3", "params": {...}},
    {"type": "connect", "src_id": "n2", "src_port": "data",
     "dst_id": "n3", "dst_port": "data"}
  ],
  "reason": "<1 句話為什麼這樣編>"
}
"""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


# Param names that carry column references — per block. If the LLM emits
# a value for any of these and it's a single string (or a list of strings
# for the *_list variants), we check against upstream cols.
_COLUMN_REF_PARAMS = {
    "block_filter": ["column"],
    "block_sort": ["columns"],            # list[str]
    "block_select": ["fields"],           # list[str]
    "block_groupby_agg": ["group_by", "agg_column"],
    "block_line_chart": ["x", "y"],
    "block_bar_chart": ["x", "y"],
    "block_scatter": ["x", "y"],
    "block_area_chart": ["x", "y"],
    "block_pie_chart": ["category", "value"],
    "block_data_view": ["columns"],
    "block_threshold": ["column"],
    "block_consecutive_rule": ["column"],
    "block_linear_regression": ["x_column", "y_column"],
    "block_unnest": ["column"],
    "block_pluck": ["column"],
    "block_step_check": ["column"],
}


def _collect_upstream_cols(plan: list[dict], exec_trace: dict) -> set[str]:
    """Union of cols observed in exec_trace for any logical id in plan.

    Used by _validate_column_refs as the "allowed columns" set. Each
    block's preview adds a snapshot keyed by logical id; we union them
    so a column emitted by ANY upstream node is considered valid.
    """
    cols: set[str] = set()
    for op in plan:
        if op.get("type") != "add_node":
            continue
        lid = op.get("node_id")
        snap = exec_trace.get(lid) or {}
        for c in snap.get("cols") or []:
            cols.add(c)
            # nested path syntax: 'spc_summary.ooc_count' — also accept
            # the prefix 'spc_summary' so users can reference the parent.
            if "." in c:
                cols.add(c.split(".", 1)[0])
            if "[]" in c:
                cols.add(c.split("[]", 1)[0])
    return cols


def _validate_column_refs(
    new_ops: list[dict[str, Any]],
    upstream_cols: set[str],
) -> list[str]:
    """Check every new add_node's column-ref params against upstream_cols.
    Returns list of human-readable issues; empty if all refs are valid.

    Skips validation if upstream_cols is empty (first compile step has
    no upstream snapshots yet — source block's params are user-given).
    Also passes any string value starting with '$' (declared input ref)
    and any value not in our column-ref param map (free-form params).
    """
    if not upstream_cols:
        return []
    issues: list[str] = []
    for op in new_ops:
        if op.get("type") != "add_node":
            continue
        block_id = op.get("block_id") or ""
        ref_params = _COLUMN_REF_PARAMS.get(block_id)
        if not ref_params:
            continue
        params = op.get("params") or {}
        for pname in ref_params:
            val = params.get(pname)
            candidates = val if isinstance(val, list) else [val]
            for cand in candidates:
                if not isinstance(cand, str) or not cand:
                    continue
                if cand.startswith("$"):
                    continue
                # Allow dotted paths whose ROOT is a known col
                root = cand.split(".", 1)[0].split("[", 1)[0]
                if cand in upstream_cols or root in upstream_cols:
                    continue
                issues.append(
                    f"{block_id}.{pname}='{cand}' not in upstream cols "
                    f"({sorted(upstream_cols)[:8]}…)"
                )
    return issues


def _dedup_against_plan(
    new_ops: list[dict[str, Any]],
    existing_plan: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop add_node ops whose logical id already exists in plan, and
    drop connect ops that exactly duplicate an existing edge.

    Returns (kept_ops, dropped_reasons).
    """
    existing_logical_ids: set[str] = set()
    existing_edges: set[tuple] = set()
    for op in existing_plan:
        t = op.get("type")
        if t == "add_node":
            lid = op.get("node_id")
            if lid:
                existing_logical_ids.add(lid)
        elif t == "connect":
            existing_edges.add((
                op.get("src_id"), op.get("src_port"),
                op.get("dst_id"), op.get("dst_port"),
            ))

    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for op in new_ops:
        t = op.get("type")
        if t == "add_node":
            lid = op.get("node_id")
            if lid and lid in existing_logical_ids:
                dropped.append(f"add_node {lid} (logical id already on canvas)")
                continue
            if lid:
                existing_logical_ids.add(lid)
        elif t == "connect":
            edge = (
                op.get("src_id"), op.get("src_port"),
                op.get("dst_id"), op.get("dst_port"),
            )
            if edge in existing_edges:
                dropped.append(f"connect {edge[0]}->{edge[2]} (duplicate edge)")
                continue
            existing_edges.add(edge)
        kept.append(op)
    return kept, dropped


def _existing_nodes_summary(plan: list[dict], exec_trace: dict) -> str:
    """One-line per existing logical node with its block_id + observed cols
    (from exec_trace if available)."""
    lines: list[str] = []
    for op in plan:
        if op.get("type") != "add_node":
            continue
        lid = op.get("node_id") or "?"
        block = op.get("block_id") or "?"
        snap = exec_trace.get(lid) or {}
        cols = snap.get("cols") or []
        if cols:
            cols_str = ", ".join(cols[:8])
            if len(cols) > 8:
                cols_str += f"...+{len(cols)-8}"
            lines.append(f"  {lid} [{block}] cols=[{cols_str}]")
        else:
            lines.append(f"  {lid} [{block}] (no preview yet)")
    return "\n".join(lines) if lines else "  (no upstream nodes — this is the first step)"


def _format_relevant_blocks(catalog: dict, candidate_id: str) -> str:
    """Format the candidate block + a few neighbors (same category) with
    full description + param_schema."""
    if not candidate_id:
        # No candidate — show high-traffic blocks
        keys = [k for k in catalog if "process_history" in k[0] or "filter" in k[0]
                or "step_check" in k[0]]
        relevant = [(k, catalog[k]) for k in keys[:N_NEIGHBOR_BLOCKS]]
    else:
        candidate_spec = None
        category = None
        for (name, _ver), spec in catalog.items():
            if name == candidate_id:
                candidate_spec = spec
                category = spec.get("category")
                break
        relevant: list[tuple[tuple, dict]] = []
        if candidate_spec:
            relevant.append(((candidate_id, "1.0.0"), candidate_spec))
        # add same-category neighbors
        for (name, ver), spec in catalog.items():
            if name == candidate_id:
                continue
            if spec.get("category") == category:
                relevant.append(((name, ver), spec))
                if len(relevant) >= N_NEIGHBOR_BLOCKS + 1:
                    break

    out_lines: list[str] = []
    for (name, _ver), spec in relevant:
        out_lines.append(f"=== {name} (category={spec.get('category', '?')}) ===")
        desc = (spec.get("description") or "").strip()
        out_lines.append(desc[:1200])  # cap description
        try:
            schema_str = json.dumps(
                spec.get("param_schema") or {}, ensure_ascii=False, indent=2,
            )[:1500]
        except (TypeError, ValueError):
            schema_str = "(schema serialization failed)"
        out_lines.append(f"param_schema:\n{schema_str}")
        out_lines.append("")
    return "\n".join(out_lines)


async def compile_chunk_node(state: BuildGraphState) -> dict[str, Any]:
    """Compile the current macro step into ops + append to state.plan."""
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
    from python_ai_sidecar.agent_builder.graph_build.nodes.plan import (
        _extract_first_json_object,
    )

    macro_plan = state.get("macro_plan") or []
    idx = state.get("current_macro_step", 0)

    if idx >= len(macro_plan):
        logger.info("compile_chunk_node: idx %d >= macro_plan len %d, nothing to compile",
                    idx, len(macro_plan))
        return {}

    step = macro_plan[idx]
    step_key = f"step_{step.get('step_idx', idx + 1)}"
    attempts_map = dict(state.get("compile_attempts") or {})
    attempts = attempts_map.get(step_key, 0) + 1
    attempts_map[step_key] = attempts

    if attempts > MAX_COMPILE_ATTEMPTS:
        logger.warning(
            "compile_chunk_node: step %s exceeded %d attempts — failing build",
            step_key, MAX_COMPILE_ATTEMPTS,
        )
        return {
            "compile_attempts": attempts_map,
            "status": "failed",
            "summary": f"Macro step {step_key} failed to compile after {MAX_COMPILE_ATTEMPTS} attempts.",
            "sse_events": [_event("compile_chunk_failed", {
                "step_idx": step.get("step_idx"),
                "attempts": attempts,
            })],
        }

    registry = SeedlessBlockRegistry()
    registry.load()

    candidate = step.get("candidate_block", "")
    relevant_blocks = _format_relevant_blocks(registry.catalog, candidate)
    existing_nodes = _existing_nodes_summary(state.get("plan") or [], state.get("exec_trace") or {})

    # Pull macro context: this step + neighbors (prev + next 1 each)
    context_lines: list[str] = []
    for i, s in enumerate(macro_plan):
        marker = " ← (你現在要編這個)" if i == idx else ""
        context_lines.append(f"  Step {s['step_idx']}: {s['text']}{marker}")

    declared_inputs = (state.get("base_pipeline") or {}).get("inputs") or []
    inputs_section = ""
    if declared_inputs:
        names = [inp.get("name") for inp in declared_inputs if isinstance(inp, dict)]
        if names:
            inputs_section = (
                f"\nPipeline 已宣告 inputs (用 $name 引用): "
                f"{', '.join('$' + n for n in names if n)}"
            )
    clarifications = state.get("clarifications") or {}
    clarify_section = ""
    if clarifications:
        clarify_section = (
            "\nUser 澄清: " + ", ".join(f"{k}={v}" for k, v in clarifications.items())
        )

    # On retry: surface the last attempt's validator errors so the LLM
    # knows which col-ref / dedup rule it violated. Without this the
    # retry has no signal that anything changed and the LLM emits the
    # same broken ops.
    prev_errors = state.get("plan_validation_errors") or []
    retry_section = ""
    if attempts > 1 and prev_errors:
        retry_section = (
            f"\n\n⚠ 你上次 compile 這 step 的 ops 被 validator 擋下，原因：\n"
            + "\n".join(f"  - {e[:300]}" for e in prev_errors[:4])
            + "\n這次請對照 UPSTREAM TRACE 的實際 cols 重寫，不要再用不在 cols 裡的欄位名。"
        )

    user_msg = (
        f"USER NEED:\n{(state.get('instruction') or '')[:600]}"
        f"{inputs_section}"
        f"{clarify_section}"
        f"{retry_section}"
        f"\n\nMACRO PLAN (context):\n" + "\n".join(context_lines) +
        f"\n\nCURRENT STEP:\n  step_idx={step.get('step_idx')}\n  text={step.get('text')}"
        f"\n  expected_kind={step.get('expected_kind')}"
        f"\n  expected_cols={step.get('expected_cols')}"
        f"\n  candidate_block={candidate or '(none)'}"
        f"\n\nUPSTREAM nodes already on canvas:\n{existing_nodes}"
        f"\n\nRELEVANT BLOCKS:\n{relevant_blocks}"
    )

    client = get_llm_client()
    from python_ai_sidecar.agent_builder.graph_build.trace import (
        get_current_tracer, trace_event_to_sse,
    )
    tracer = get_current_tracer()
    extra_sse: list[dict[str, Any]] = []

    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=2048,
        )
        text = _strip_fence(resp.text or "")
        try:
            decision = json.loads(text)
        except json.JSONDecodeError:
            decision = _extract_first_json_object(text or "")
    except Exception as ex:  # noqa: BLE001
        logger.warning("compile_chunk_node: LLM/parse failed (%s) — retry %d/%d",
                       ex, attempts, MAX_COMPILE_ATTEMPTS)
        return {
            "compile_attempts": attempts_map,
            "plan_validation_errors": [f"compile step {step_key} failed: {ex}"],
            "sse_events": [_event("compile_chunk_error", {
                "step_idx": step.get("step_idx"),
                "error": str(ex)[:200],
                "attempts": attempts,
            })],
        }

    new_ops_raw = (decision or {}).get("ops") or []
    new_ops: list[dict[str, Any]] = []
    if isinstance(new_ops_raw, list):
        for op in new_ops_raw[:5]:
            if isinstance(op, dict) and op.get("type"):
                new_ops.append(op)

    # Deterministic dedup against existing plan — even if the LLM
    # violated Rule 1, drop colliding add_node + duplicate connect ops
    # so we don't end up with two real nodes sharing the same logical id
    # (which silently rebinds logical_to_real and breaks downstream refs).
    new_ops, dropped = _dedup_against_plan(new_ops, state.get("plan") or [])
    if dropped:
        logger.info(
            "compile_chunk_node: step %s dedup dropped %d op(s): %s",
            step_key, len(dropped), dropped[:4],
        )

    # Deterministic column-ref check — if the LLM emitted a filter /
    # sort / chart / select op referencing a column not in any upstream
    # node's exec_trace snapshot, retry compile_chunk with the issue in
    # plan_validation_errors instead of letting a doomed op enter the
    # plan and cascade through reflect_op. This is the main brake on
    # "filter column='chart_name'" / "sort by 'eventTime' after groupby"
    # style hallucinations.
    upstream_cols = _collect_upstream_cols(
        state.get("plan") or [], state.get("exec_trace") or {},
    )
    col_issues = _validate_column_refs(new_ops, upstream_cols)
    if col_issues:
        logger.warning(
            "compile_chunk_node: step %s attempt %d col-ref issues: %s — retry",
            step_key, attempts, col_issues[:3],
        )
        return {
            "compile_attempts": attempts_map,
            "plan_validation_errors": [
                f"step {step_key} column refs invalid: " + "; ".join(col_issues[:3])
            ],
            "sse_events": [_event("compile_chunk_error", {
                "step_idx": step.get("step_idx"),
                "error": "column_ref_invalid: " + "; ".join(col_issues[:2]),
                "attempts": attempts,
            })],
        }

    if not new_ops:
        logger.warning("compile_chunk_node: step %s produced 0 ops", step_key)
        return {
            "compile_attempts": attempts_map,
            "plan_validation_errors": [f"step {step_key} produced no valid ops"],
            "sse_events": [_event("compile_chunk_error", {
                "step_idx": step.get("step_idx"),
                "error": "no ops",
                "attempts": attempts,
            })],
        }

    # Append to plan; mark this macro step as completed (advanced after
    # ops actually execute via cursor reaching plan end).
    plan = list(state.get("plan") or [])
    plan.extend(new_ops)

    # Mark step as compiled (executor will mark completed via cursor)
    updated_macro = list(macro_plan)
    updated_macro[idx] = {
        **step,
        "ops_appended": (step.get("ops_appended", 0)) + len(new_ops),
        "compile_reason": (decision or {}).get("reason", "")[:200],
    }

    logger.info(
        "compile_chunk_node: step %s attempt %d → %d ops appended (plan now %d ops)",
        step_key, attempts, len(new_ops), len(plan),
    )

    if tracer is not None:
        llm_entry = tracer.record_llm(
            node="compile_chunk_node",
            system=_SYSTEM[:200] + "…",
            user_msg=user_msg[:2000],
            raw_response=resp.text or "",
            parsed=decision,
            step_idx=step.get("step_idx"),
            attempt=attempts,
        )
        sse = trace_event_to_sse(llm_entry, kind="llm_call")
        if sse: extra_sse.append(sse)
        step_entry = tracer.record_step(
            "compile_chunk_node", status="ok",
            step_idx=step.get("step_idx"),
            n_ops=len(new_ops), attempts=attempts,
        )
        sse2 = trace_event_to_sse(step_entry, kind="step")
        if sse2: extra_sse.append(sse2)

    return {
        "plan": plan,
        "macro_plan": updated_macro,
        "compile_attempts": attempts_map,
        "plan_validation_errors": [],
        "sse_events": [
            _event("chunk_compiled", {
                "step_idx": step.get("step_idx"),
                "step_text": step.get("text"),
                "n_ops": len(new_ops),
                "attempts": attempts,
                "reason": (decision or {}).get("reason", "")[:200],
            }),
            *extra_sse,
        ],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
