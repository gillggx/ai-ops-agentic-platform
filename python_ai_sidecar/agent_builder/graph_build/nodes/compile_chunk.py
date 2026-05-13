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

規則:
  - 通常 1 add_node + 1 connect (接上一步的 terminal)
  - 如果 macro step 已含參數線索 (e.g. "過濾 spc_status='OOC'") 直接寫進 params
  - logical node id 用 n1, n2, ... 接續編號
  - column ref 必須在上游 output_cols 裡 (不確定就用上游真實列出的欄位)
  - 不要新增不在這 macro step 範圍內的 node — 那是下一個 step 的工作
  - 不要 remove 上游 node (上游已穩，這 step 只負責接續)

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

    user_msg = (
        f"USER NEED:\n{(state.get('instruction') or '')[:600]}"
        f"{inputs_section}"
        f"{clarify_section}"
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
