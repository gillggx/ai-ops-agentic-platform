"""plan_node — LLM call #1: turn instruction into a list[Op] plan.

LLM uses logical ids n1, n2, ... — call_tool_node maps to real ids at
execution time. The plan is one-shot: no mid-flight extension (E8).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)


_SYSTEM = """你是 pipeline planner，把使用者需求拆成一個 plan = list[Op]。

Op type 共 5 種:
  add_node     — 加 1 個 block (帶 block_id, block_version="1.0.0", params)
  set_param    — 改某 node 的某個 param (params={"key":..., "value":...})
  connect      — 接 2 個 node (src_id, src_port, dst_id, dst_port)
  run_preview  — 預覽某 node 輸出 (node_id) — 通常不必加，僅 debug
  remove_node  — 移除某 node (node_id)

規則:
  1. 用邏輯 id n1, n2, n3, ... 編號（不要編真實 id）
  2. **op 順序硬性規則**（違反就會被擋）:
     a) add_node — 加入這個 block，可帶 initial params (純值，不要帶 column-ref)
     b) connect  — 把上游接進來
     c) set_param — 寫 column-ref 參數（value_column / x / y / column / agg_column 等）
     ⚠ column-ref 的 set_param 必須在 connect 之後，否則沒有 upstream 可查
  3. connect 的 src_id / dst_id 都用邏輯 id
  4. 一次出完整 plan — 後面不能再補 op
  5. block 必須來自下面的目錄；不要編造 block_id
  6. 如需 preview/debug 輸出，可在中間或末尾加 run_preview op
  7. **block_id 不要帶 @version 後綴**。block_id 跟 block_version 是兩個分開的欄位：
     ✅ 對：{"block_id":"block_xbar_r", "block_version":"1.0.0"}
     ❌ 錯：{"block_id":"block_xbar_r@1.0.0", "block_version":"1.0.0"}（會找不到 block）
  8. **column-ref 一定要用上游真實的 column 名**。每個 block 在 catalog 都標了 out_cols=[...]，
     下游 set_param value_column / x / y 等就從 upstream 的 out_cols 挑。例如：
        block_process_history out_cols=[eventTime, toolID, ..., spc_xbar_chart_value, ...]
     → 接 block_ewma_cusum 時 value_column='spc_xbar_chart_value'（不是 'xbar' 不是 'value'）

✅ 正確 op 順序範例:
  Op#0 add_node block_process_history → n1, params={tool_id:'EQP-01', step:'STEP_001'}
  Op#1 add_node block_ewma_cusum → n2
  Op#2 connect n1.data → n2.data
  Op#3 set_param n2 value_column='spc_xbar_chart_value'   ← connect 之後才寫

❌ 錯誤示範（會被擋下來）:
  add_node n2 → set_param n2 value_column=...  ← 沒有 upstream 可參考

Block 目錄:
{BLOCK_CATALOG}

只輸出 JSON，不要 markdown fence:
{
  "plan_summary": "<一句話描述要建什麼>",
  "expected_outputs": [
    "<跑完 user 會看到的 artifact，每行一個 — 用 user-facing 語言>",
    "..."
  ],
  "plan": [
    {"type":"add_node", "block_id":"...", "block_version":"1.0.0", "node_id":"n1", "params":{...}},
    {"type":"set_param", "node_id":"n1", "params":{"key":"...", "value":...}},
    {"type":"connect", "src_id":"n1", "src_port":"out", "dst_id":"n2", "dst_port":"in"},
    ...
  ]
}

expected_outputs 範例（描述 user 會看到的東西，不是 ops 列表）:
  ✅ ["📈 EWMA-CUSUM drift trend", "📦 各 lot 的 box-plot", "📉 Q-Q 常態檢定圖"]
  ✅ ["📋 OOC 機台清單表", "📊 各站點 OOC 比例 bar chart"]
  ❌ ["add block_xbar_r", "set_param value_column", ...]   ← 這是 ops 不是 outputs
  ❌ ["build pipeline"]                                     ← 太籠統
"""


_OUT_COL_PREVIEW_CAP = 12

# Phase 10-C Fix 1b: transform-block output column rules. Hard-coded because
# transforms compute their output columns dynamically from upstream — no static
# `output_columns_hint` can capture this. Keep in sync with each block's
# implementation; CI invariant test catches drift.
_TRANSFORM_OUT_RULES: dict[str, str] = {
    "block_filter": "preserves upstream",
    "block_sort": "preserves upstream",
    "block_select": "subset of upstream (whichever 'columns' param picks)",
    "block_rename": "upstream renamed",
    "block_drop_duplicates": "preserves upstream",
    "block_pivot": "depends on pivot params",
    "block_groupby_agg": "[<group_by> cols] + <agg_column>_<agg_func>",
    "block_linear_regression": "stats port: [slope, intercept, r_squared, p_value, n, stderr, group]; "
                               "data port: upstream + <y_column>_pred + <y_column>_residual + group; "
                               "ci port: [<x_column>, pred, ci_lower, ci_upper, group]",
    "block_xbar_r": "preserves upstream + xbar/r/sigma derived columns",
    "block_ewma_cusum": "preserves upstream + ewma/cusum/signal columns",
    "block_cpk": "[group, cpk, cp, mean, std]",
    "block_hypothesis_test": "[group, statistic, p_value, reject_null]",
    "block_spc_long_form": "[eventTime, toolID, lotID, step, spc_status, fdc_classification, chart_name, value, ucl, lcl, is_ooc]",
    # 2026-05-11: was wrong on two counts — said 'parameter' instead of
    # 'param_name', and missed the passthrough cols (spc_status etc). LLM
    # then couldn't reference spc_status as the OOC marker for APC and
    # synthesised wrong logic like `value != null`. APC has NO is_ooc;
    # OOC is process-level via spc_status.
    "block_apc_long_form": "[eventTime, toolID, lotID, step, spc_status, fdc_classification, apc_id, param_name, value]",
    "block_data_view": "preserves upstream (display only)",
    "block_box_plot": "preserves upstream (chart only)",
    "block_probability_plot": "preserves upstream (chart only)",
    "block_alert": "preserves upstream + alert_id, alert_severity",
}


def _format_catalog(catalog: dict[tuple[str, str], dict[str, Any]]) -> str:
    """Single source of truth for block info — DB description (CLAUDE.md §1).

    Each line carries:
      name@version  in=[...]  out=[...]  params={key:type-or-enum-or-range,...}
      out_cols=[...] (or transform rule)  — short description

    Surfacing param enum + range + output column names is critical. Without
    them the LLM blindly passes user phrases ('spc_xbar_chart_value') to enum
    params, picks out-of-range numbers (limit=1000 vs max 200), or references
    column names that don't exist in upstream output.

    Phase 11 v13 — when a block has any free-form `object` param (e.g.
    block_compute.expression, block_mcp_call.args), the one-line summary
    can't possibly convey the schema, and the LLM blindly invents shapes.
    For those blocks we emit the FULL DB description + DB examples after
    the summary line. Whitelist is computed dynamically from param_schema
    (no hardcoded block-name list).
    """
    lines = []
    for (name, version), spec in sorted(catalog.items()):
        full_desc = (spec.get("description") or "").strip()
        first_line = full_desc.split("\n", 1)[0]
        if len(first_line) > 120:
            first_line = first_line[:120].rsplit(" ", 1)[0] + "…"
        in_ports = [p.get("port") for p in (spec.get("input_schema") or [])]
        out_ports = [p.get("port") for p in (spec.get("output_schema") or [])]
        param_schema = spec.get("param_schema") or {}
        param_props = (param_schema.get("properties") or {})
        param_hints = []
        has_freeform_object = False
        # 2026-05-10: chart (category=output) blocks always get full description
        # treatment. Param choice for chart blocks is intent-driven (facet vs
        # series_field vs y_secondary vs single y; chart_type variants etc.) —
        # cannot be conveyed in a one-line summary, so the description's
        # `== When to use ==` / `== Params ==` sections must reach the LLM.
        # Without this, the carefully-authored "facet='chart_name' splits SPC
        # long-form into one chart per chart_name" example was invisible and
        # LLM produced one big chart with series_field instead.
        is_chart_block = (spec.get("category") == "output")
        # 2026-05-11: also surface full description when the author marked
        # critical anti-pattern warnings (`== ⚠`) — those are the cases
        # where LLM gets the block "wrong by default" without explicit
        # guidance. apc_long_form's "APC 沒有 is_ooc, OOC 看 spc_status"
        # warning was invisible without this. Just `== When to use ==` is
        # too broad (every block has it; would 2× the catalog token cost).
        has_critical_warning = "== ⚠" in full_desc
        for k, v in param_props.items():
            if not isinstance(v, dict):
                continue
            t = v.get("type") or "?"
            enum = v.get("enum")
            if enum is not None:
                preview = enum[:6]
                more = "" if len(enum) <= 6 else f"…+{len(enum)-6}"
                param_hints.append(f"{k}∈{preview}{more}")
                continue
            mn = v.get("minimum")
            mx = v.get("maximum")
            if mn is not None or mx is not None:
                rng = f"[{mn if mn is not None else '?'}..{mx if mx is not None else '?'}]"
                param_hints.append(f"{k}:{t}{rng}")
            else:
                param_hints.append(f"{k}:{t}")
            # Phase 11 v15: schema-heavy detection. The LLM cannot guess any
            # of these from a one-line summary:
            #   (a) free-form object (no nested properties)
            #   (b) array of objects (items.type=='object' or items.properties exists)
            #   (c) free-form array (items missing entirely)
            # All three need the full DB description + examples to be reliably
            # generated. Detection is dynamic — no block-name allow-list.
            if t == "object" and not v.get("properties"):
                has_freeform_object = True
            elif t == "array":
                items = v.get("items") or {}
                items_t = items.get("type") if isinstance(items, dict) else None
                if items_t == "object" or (isinstance(items, dict) and items.get("properties")):
                    has_freeform_object = True
                elif not items:
                    has_freeform_object = True
        params_str = ", ".join(param_hints) if param_hints else "(none)"
        out_cols_str = _format_out_cols(name, spec)
        lines.append(
            f"- {name}@{version}  in={in_ports}  out={out_ports}  "
            f"params={{{params_str}}}\n"
            f"    out_cols={out_cols_str}\n"
            f"    — {first_line}"
        )
        if has_freeform_object or is_chart_block or has_critical_warning:
            # Inject the full description (already authored in DB) so the LLM
            # sees the embedded grammar / examples instead of inventing.
            indented = "      " + full_desc.replace("\n", "\n      ")
            label = (
                "Full schema" if has_freeform_object
                else "Full description"
            )
            lines.append(f"    [{label} for {name}]\n{indented}")
            examples = spec.get("examples") or []
            if examples:
                # examples is a list of {title?, params}. Include first 2.
                import json as _json
                for i, ex in enumerate(examples[:2]):
                    if not isinstance(ex, dict):
                        continue
                    ex_params = ex.get("params") or ex
                    try:
                        ex_str = _json.dumps(ex_params, ensure_ascii=False, indent=2)
                    except (TypeError, ValueError):
                        continue
                    ex_indented = "      " + ex_str.replace("\n", "\n      ")
                    lines.append(f"    [Example {i+1} for {name}]\n{ex_indented}")
    return "\n".join(lines)


def _format_out_cols(block_name: str, spec: dict[str, Any]) -> str:
    """Fix 1: surface block's output columns to LLM.

    Priority order:
      1. transform rule (hardcoded; preserves/derives from upstream)
      2. output_columns_hint from spec (static columns, e.g. source blocks)
      3. fallback "?" — LLM should treat as unknown
    """
    rule = _TRANSFORM_OUT_RULES.get(block_name)
    if rule is not None:
        return rule
    hint = spec.get("output_columns_hint") or []
    if not hint:
        return "?"
    names = []
    for col in hint:
        if isinstance(col, dict):
            n = col.get("name")
            if n:
                names.append(n)
        elif isinstance(col, str):
            names.append(col)
    if not names:
        return "?"
    preview = names[:_OUT_COL_PREVIEW_CAP]
    more = "" if len(names) <= _OUT_COL_PREVIEW_CAP else f"…+{len(names)-_OUT_COL_PREVIEW_CAP}"
    return f"[{', '.join(preview)}{more}]"


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    text = text.strip()
    text = _FENCE_RE.sub("", text)
    return text.strip()


def _extract_first_json_object(text: str) -> dict[str, Any]:
    """Parse the first balanced JSON object from text. Tolerates trailing
    explanation text (a Haiku habit when the prompt asks for JSON only)."""
    text = _strip_fence(text)
    # Fast path — pure JSON.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Slow path — find the outermost {...} block by brace counting.
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object found in LLM output")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unbalanced JSON object in LLM output")


async def plan_node(state: BuildGraphState) -> dict[str, Any]:
    """LLM produces a structured plan. Errors here downgrade gracefully —
    validate_plan_node will catch them and route to repair_plan."""
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry

    registry = SeedlessBlockRegistry()
    registry.load()
    catalog_text = _format_catalog(registry.catalog)
    system = _SYSTEM.replace("{BLOCK_CATALOG}", catalog_text)

    base_pipeline = state.get("base_pipeline") or {}
    has_existing = bool(base_pipeline.get("nodes"))
    canvas_hint = (
        f"\n\n目前 canvas 已有 {len(base_pipeline.get('nodes', []))} 個 node、"
        f"{len(base_pipeline.get('edges', []))} 條 edge — incremental modification."
        if has_existing else "\n\n目前 canvas 是空的 — from-scratch build."
    )

    # Phase 11 v16: surface pipeline-level declared inputs so the LLM uses
    # `$name` references in node params instead of hardcoding example values.
    # User reported: had `$tool_id` declared in Pipeline Inputs UI but agent
    # still hardcoded EQP-03/EQP-09 + union — plan_node simply wasn't told
    # about declared inputs. Source: state.base_pipeline.inputs (set by
    # canvas snapshot upload).
    declared_inputs = base_pipeline.get("inputs") or []
    if declared_inputs:
        lines = []
        for inp in declared_inputs:
            if not isinstance(inp, dict):
                continue
            nm = inp.get("name")
            if not nm:
                continue
            t = inp.get("type", "string")
            req = "required" if inp.get("required") else "optional"
            ex = inp.get("example")
            ex_str = f", example={ex!r}" if ex is not None else ""
            desc = inp.get("description") or ""
            desc_str = f" — {desc}" if desc else ""
            lines.append(f"  ${nm} ({t}, {req}{ex_str}){desc_str}")
        inputs_hint = (
            "\n\n⚡ Pipeline-level inputs ALREADY declared (use $name refs in node params, "
            "DO NOT hardcode literal values — that defeats parametric reuse):\n"
            + "\n".join(lines)
        )
    else:
        inputs_hint = ""

    skill_step_mode = bool(state.get("skill_step_mode"))
    # 2026-05-10: hint 只說「方向」(每個 skill step 都需要 pass/fail gate)，
    # 不說「chart 不適用」— 那是錯的、且越權干涉 block 用法。
    # 真實情境：skill 觸發後常需要附帶圖表佐證（e.g. 連續 OOC 觸發時，告警附
    # 各 SPC chart 的 trend 給 user 看）。chart 可作為 side branch 與
    # step_check 並存。block 怎麼用、param 怎麼帶請看上方 catalog 的 block 描述。
    skill_hint = (
        "\n\n⚠ SKILL STEP MODE — 此 pipeline 是 Skill 的一個 step，必須含一個"
        " `block_step_check` 作為 pass/fail 觸發 gate（決定要不要觸發後續動作）。"
        "其他 block（含視覺化 chart）可作為 side branches 與 step_check 並存"
        "— 圖表不影響觸發判定，但會附在告警 payload 給 user 看。"
        if skill_step_mode else ""
    )
    user_msg = state["instruction"] + canvas_hint + inputs_hint + skill_hint
    client = get_llm_client()
    # Phase 11 v17 — opt-in BuildTracer captures full LLM exchange.
    from python_ai_sidecar.agent_builder.graph_build.trace import (
        get_current_tracer, trace_event_to_sse,
    )
    tracer = get_current_tracer()
    extra_sse: list[dict[str, Any]] = []
    try:
        resp = await client.create(
            system=system,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=8192,  # Haiku 4.5 max; large plans (10+ ops) can overflow 4096
        )
        decision = _extract_first_json_object(resp.text or "")
        if tracer is not None:
            entry = tracer.record_llm(
                node="plan_node",
                system=system,
                user_msg=user_msg,
                raw_response=resp.text or "",
                parsed=decision,
            )
            sse = trace_event_to_sse(entry, kind="llm_call")
            if sse: extra_sse.append(sse)
    except Exception as ex:  # noqa: BLE001
        logger.warning("plan_node: LLM/parse failed (%s) — empty plan returned", ex)
        if tracer is not None:
            tracer.record_step("plan_node", status="failed", error=str(ex))
        return {
            "plan": [],
            "plan_validation_errors": [f"plan_node failed: {ex}"],
            "sse_events": [_event("plan_proposed", {
                "plan": [], "summary": "(plan generation failed)",
                "error": str(ex),
            })],
        }

    plan_list = decision.get("plan") or []
    summary = (decision.get("plan_summary") or "").strip() or "(no summary)"
    expected_outputs_raw = decision.get("expected_outputs") or []
    expected_outputs = [
        s.strip() for s in expected_outputs_raw
        if isinstance(s, str) and s.strip()
    ][:8]

    # Determine FROM_SCRATCH heuristic: empty canvas + plan ≥ 3 ops
    is_from_scratch = (not has_existing) and (len(plan_list) >= 3)

    logger.info(
        "plan_node: produced %d ops, %d outputs, from_scratch=%s, summary=%r",
        len(plan_list), len(expected_outputs), is_from_scratch, summary[:80],
    )
    if tracer is not None:
        step_entry = tracer.record_step(
            "plan_node",
            status="ok",
            n_ops=len(plan_list),
            n_outputs=len(expected_outputs),
            is_from_scratch=is_from_scratch,
            summary=summary[:200],
        )
        sse = trace_event_to_sse(step_entry, kind="step")
        if sse: extra_sse.append(sse)

    sse_events_list = [
        _event("plan_proposed", {
            "plan": plan_list,
            "summary": summary,
            "expected_outputs": expected_outputs,
            "from_scratch": is_from_scratch,
        }),
        *extra_sse,
    ]
    return {
        "plan": plan_list,
        "is_from_scratch": is_from_scratch,
        "plan_validation_errors": [],
        "summary": summary,
        "expected_outputs": expected_outputs,
        "sse_events": sse_events_list,
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
