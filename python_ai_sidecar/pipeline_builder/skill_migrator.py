"""Skill → Pipeline JSON migrator (Phase 4-A).

Scans a legacy skill_definition (steps_mapping + input_schema + output_schema)
and attempts to emit an equivalent Pipeline JSON. Strategy:

- Pattern-match common MCP calls in each step's python_code.
- Derive pipeline.inputs from skill.input_schema.
- Rebuild the compute chain with the 23 built-in blocks.
- If a step can't be automatically translated, emit a skeleton with TODO notes
  so a PE can finish the migration manually.

This module never touches the DB directly; it returns a `MigrationResult`.
Callers (CLI / HTTP endpoint / test) decide whether to persist.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class MigrationResult:
    skill_id: int
    skill_name: str
    status: str  # "full" | "skeleton" | "manual"
    pipeline_json: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    detected_mcps: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

_MCP_CALL_RE = re.compile(
    r"execute_mcp\(\s*['\"](?P<name>\w+)['\"]\s*,\s*(?P<args>\{[^}]*\})",
    re.DOTALL,
)
_FINDINGS_RE = re.compile(r"_findings\s*=\s*(\{.*?\})(?=\n[a-zA-Z_#]|\n\s*$|\Z)", re.DOTALL)
_CONDITION_MET_RE = re.compile(r"condition_met['\"]?\s*[:=]\s*(?P<expr>[^,\n\)]+)")


def _extract_mcp_calls(python_code: str) -> list[tuple[str, str]]:
    """Return [(mcp_name, raw_args_src)] for every execute_mcp(...) call."""
    out: list[tuple[str, str]] = []
    for m in _MCP_CALL_RE.finditer(python_code):
        out.append((m.group("name"), m.group("args").strip()))
    return out


def _extract_condition_expr(python_code: str) -> Optional[str]:
    """Find the expression used as `condition_met` (approximate)."""
    m = _CONDITION_MET_RE.search(python_code)
    if not m:
        return None
    return m.group("expr").strip().rstrip(",")


def _mcp_to_source_block(mcp_name: str, args_src: str) -> tuple[str, dict[str, Any], list[str]]:
    """Map a known MCP call to (block_name, params, notes).

    block_process_history requires tool_id / lot_id / step (at least one). We
    detect which one the original skill used based on keys in the args dict.
    """
    notes: list[str] = []
    params: dict[str, Any] = {}

    # tool_id binding — toolID / equipment_id / targetID all map here
    if "toolID" in args_src or "equipment_id" in args_src or "targetID" in args_src:
        params["tool_id"] = "$tool_id"

    # lot_id binding — lotID key in args
    if re.search(r"['\"]lotID['\"]\s*:", args_src):
        params["lot_id"] = "$lotID"

    # step binding — `step` key in args (usually user-selected step code)
    if re.search(r"['\"]step['\"]\s*:", args_src):
        params["step"] = "$step"

    # object_name
    obj_match = re.search(r"['\"]objectName['\"]\s*:\s*['\"](\w+)['\"]", args_src)
    if obj_match:
        params["object_name"] = obj_match.group(1)

    # limit
    lim_match = re.search(r"['\"]limit['\"]\s*:\s*(\d+)", args_src)
    if lim_match:
        params["limit"] = int(lim_match.group(1))

    # Recognized MCPs → block_process_history
    if mcp_name in (
        "get_process_history",
        "get_process_info",
        "get_object_snapshot_history",
    ):
        return ("block_process_history", params, notes)

    # Unknown MCP → generic block_mcp_call
    notes.append(f"MCP '{mcp_name}' has no dedicated block; using block_mcp_call")
    return (
        "block_mcp_call",
        {"mcp_name": mcp_name, "args": {"tool_id": "$tool_id"}},
        notes,
    )


# ---------------------------------------------------------------------------
# Pattern recognizers (step-level)
# ---------------------------------------------------------------------------

def _detect_logic_pattern(combined_code: str) -> Optional[dict[str, Any]]:
    """Look for common OOC / trending condition patterns; return a logic block spec."""
    cc = combined_code

    # Pattern priority: SAME-GROUP check > rolling count.
    # Because skills doing `ooc_count >= K` while also checking `same_apc` /
    # `same_recipe` are semantically the latter — the count is auxiliary.
    if re.search(r"same_recipe|ooc_recipe_list|len\(ooc_recipe", cc) or re.search(r"same_apc|ooc_apc_ids", cc):
        field_guess = "recipeID" if "recipe" in cc.lower() else "apcID"
        return {
            "pattern": "same_group_check",
            "field": field_guess,
        }

    # Pattern 1: "last N processes have count > / >= K OOC".
    # Matches both `history[-5:]`, `records[-5:]`, AND `events[:5]` / `events[:N]`.
    m = re.search(r"\w+\[-(\d+):\]", cc) or re.search(r"\w+\[:(\d+)\]", cc)
    n_window = int(m.group(1)) if m else None
    m2 = re.search(r"ooc_count\s*(>=|>)\s*(\d+)", cc)
    if m2:
        op, val = m2.group(1), int(m2.group(2))
        k_threshold = val if op == ">=" else val + 1
    else:
        k_threshold = None
    if n_window and k_threshold:
        # rolling_window(sum of is_ooc, window=N) → threshold(count >= K)
        return {
            "pattern": "rolling_count_threshold",
            "window": n_window,
            "threshold": k_threshold,
            "flag_field": "spc_xbar_chart_is_ooc",  # best-effort default
        }

    # Pattern 3: simple trigger on count
    if re.search(r"condition_met\s*=\s*len\(", cc):
        return {"pattern": "count_threshold", "threshold": 0}

    return None


# ---------------------------------------------------------------------------
# Pipeline builder
# ---------------------------------------------------------------------------

def _build_inputs_from_schema(input_schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert skill.input_schema → pipeline.inputs, with sensible coercion."""
    pipeline_inputs: list[dict[str, Any]] = []
    for f in input_schema or []:
        key = f.get("key")
        if not key:
            continue
        # rename "equipment_id" → "tool_id" so it matches block_process_history
        name = "tool_id" if key == "equipment_id" else key
        t = f.get("type", "string")
        pipeline_inputs.append({
            "name": name,
            "type": t if t in {"string", "integer", "number", "boolean"} else "string",
            "required": bool(f.get("required", False)),
            "description": f.get("description"),
            "example": f.get("default") or ("EQP-01" if name == "tool_id" else None),
        })
    return pipeline_inputs


def _gen_id(existing: set[str], prefix: str) -> str:
    i = 1
    while f"{prefix}{i}" in existing:
        i += 1
    nid = f"{prefix}{i}"
    existing.add(nid)
    return nid


def migrate_skill(skill: dict[str, Any]) -> MigrationResult:
    """Attempt to migrate a single skill record to a pipeline.

    `skill` is the DB row as a dict — needs keys: id, name, description, steps_mapping (JSON-str),
    input_schema (JSON-str), output_schema (JSON-str).
    """
    skill_id = int(skill.get("id", 0))
    skill_name = skill.get("name", "unnamed")
    notes: list[str] = []

    steps = json.loads(skill.get("steps_mapping") or "[]")
    input_schema = json.loads(skill.get("input_schema") or "[]")
    output_schema = json.loads(skill.get("output_schema") or "[]")

    pipeline_inputs = _build_inputs_from_schema(input_schema)
    if not any(inp["name"] == "tool_id" for inp in pipeline_inputs):
        # Most skills assume equipment_id → tool_id
        pipeline_inputs.insert(0, {
            "name": "tool_id", "type": "string", "required": True,
            "example": "EQP-01", "description": "機台 ID（migration 自動補宣告）",
        })
        notes.append("Auto-injected tool_id input (not in original input_schema).")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    edge_ids: set[str] = set()

    # -- Step 1: collect all MCP calls from all steps
    all_mcps: list[tuple[str, str, int]] = []  # (mcp_name, args_src, step_idx)
    for idx, step in enumerate(steps):
        calls = _extract_mcp_calls(step.get("python_code", ""))
        for name, args in calls:
            all_mcps.append((name, args, idx))

    detected_mcps = sorted({m[0] for m in all_mcps})
    if not all_mcps:
        return MigrationResult(
            skill_id=skill_id,
            skill_name=skill_name,
            status="manual",
            pipeline_json={},
            notes=["No execute_mcp(...) call detected — cannot determine data source."],
        )

    # Use the FIRST MCP call as primary source
    primary_mcp, primary_args, _ = all_mcps[0]
    src_block, src_params, src_notes = _mcp_to_source_block(primary_mcp, primary_args)
    notes.extend(src_notes)

    source_id = _gen_id(node_ids, "n")
    nodes.append({
        "id": source_id,
        "block_id": src_block,
        "block_version": "1.0.0",
        "position": {"x": 30, "y": 80},
        "params": src_params,
    })
    last_id = source_id
    x_cursor = 30
    status = "full"

    # Phase 4-A+: if there are MCP calls inside a for-loop → wire via block_mcp_foreach.
    # Heuristic: a 2nd MCP exists AND appears inside `for ... in ...:` block.
    loop_mcp: Optional[tuple[str, str]] = None
    if len(all_mcps) > 1:
        for name, args_src, step_idx in all_mcps[1:]:
            step_code = steps[step_idx].get("python_code", "")
            # crude "loop context" detector
            if re.search(r"for\s+\w+\s+in\s+.+:", step_code) and "execute_mcp" in step_code:
                loop_mcp = (name, args_src)
                break
        if loop_mcp:
            foreach_name, foreach_args = loop_mcp
            # Parse args_template — look for {"key": expr} mapping; replace expr with $col
            # best-effort: map common patterns
            tmpl: dict[str, Any] = {}
            for m in re.finditer(r"['\"](\w+)['\"]\s*:\s*([^,}]+)", foreach_args):
                key, expr = m.group(1), m.group(2).strip()
                # `lot_id` → `$lotID`; `step_name` → `$step`; `proc.get('xxx')` → `$xxx`
                if expr in {"lot_id", "lotID"}:
                    tmpl[key] = "$lotID"
                elif expr in {"step_name", "step"}:
                    tmpl[key] = "$step"
                elif expr.startswith(("'", '"')):
                    tmpl[key] = expr.strip("'\"")
                else:
                    tmpl[key] = f"${expr}"
            x_cursor += 260
            fe_id = _gen_id(node_ids, "n")
            nodes.append({
                "id": fe_id, "block_id": "block_mcp_foreach", "block_version": "1.0.0",
                "position": {"x": x_cursor, "y": 80},
                "params": {
                    "mcp_name": foreach_name,
                    "args_template": tmpl,
                    "result_prefix": f"{foreach_name.replace('get_', '').replace('_context', '')}_",
                    "max_concurrency": 5,
                },
            })
            edges.append({"id": _gen_id(edge_ids, "e"),
                          "from": {"node": last_id, "port": "data"},
                          "to": {"node": fe_id, "port": "data"}})
            last_id = fe_id
            notes.append(
                f"Wired row-level MCP loop via block_mcp_foreach ({foreach_name}). "
                f"Review args_template + result_prefix."
            )
        else:
            extras = sorted({f"{n} (step{i+1})" for n, _, i in all_mcps[1:]})
            notes.append(
                f"Skill calls {len(all_mcps)} MCPs; only the first ({primary_mcp}) was wired. "
                f"Extras not in a detectable for-loop: {', '.join(extras)}."
            )

    # -- Step 2: detect logic pattern from combined python
    combined_code = "\n".join(s.get("python_code", "") for s in steps)
    pattern = _detect_logic_pattern(combined_code)

    if pattern and pattern["pattern"] == "rolling_count_threshold":
        x_cursor += 260
        rw_id = _gen_id(node_ids, "n")
        nodes.append({
            "id": rw_id, "block_id": "block_rolling_window", "block_version": "1.0.0",
            "position": {"x": x_cursor, "y": 80},
            "params": {
                "column": pattern["flag_field"],
                "window": pattern["window"],
                "func": "sum",
                "sort_by": "eventTime",
            },
        })
        edges.append({"id": _gen_id(edge_ids, "e"),
                      "from": {"node": last_id, "port": "data"},
                      "to": {"node": rw_id, "port": "data"}})
        last_id = rw_id

        x_cursor += 260
        thr_id = _gen_id(node_ids, "n")
        nodes.append({
            "id": thr_id, "block_id": "block_threshold", "block_version": "1.0.0",
            "position": {"x": x_cursor, "y": 80},
            "params": {
                "column": f"{pattern['flag_field']}_rolling_sum",
                "bound_type": "upper",
                "upper_bound": pattern["threshold"] - 1,
            },
        })
        edges.append({"id": _gen_id(edge_ids, "e"),
                      "from": {"node": last_id, "port": "data"},
                      "to": {"node": thr_id, "port": "data"}})
        last_id = thr_id
        notes.append(
            f"Translated rolling_count pattern: "
            f"rolling_window(window={pattern['window']}, sum) + threshold(>={pattern['threshold']})."
        )

    elif pattern and pattern["pattern"] == "same_group_check":
        # PR-F runtime-QA: actual canonical column names differ.
        # recipeID → recipe_version (when source=RECIPE object).
        # apcID → APC.mode which is nested — can't auto-extract.
        # Use best-effort field name: if obj_prefix exists, try {prefix}version.
        field_mapping = {"recipeID": "recipe_version", "apcID": "apc_mode"}
        mapped_field = field_mapping.get(pattern["field"], pattern["field"])

        x_cursor += 260
        filter_id = _gen_id(node_ids, "n")
        nodes.append({
            "id": filter_id, "block_id": "block_filter", "block_version": "1.0.0",
            "position": {"x": x_cursor, "y": 80},
            "params": {"column": "spc_status", "operator": "==", "value": "OOC"},
        })
        edges.append({"id": _gen_id(edge_ids, "e"),
                      "from": {"node": last_id, "port": "data"},
                      "to": {"node": filter_id, "port": "data"}})
        last_id = filter_id

        # Count unique values in the target field via block_count_rows(group_by=field)
        x_cursor += 260
        cr_id = _gen_id(node_ids, "n")
        nodes.append({
            "id": cr_id, "block_id": "block_count_rows", "block_version": "1.0.0",
            "position": {"x": x_cursor, "y": 80},
            "params": {"group_by": mapped_field},
        })
        edges.append({"id": _gen_id(edge_ids, "e"),
                      "from": {"node": last_id, "port": "data"},
                      "to": {"node": cr_id, "port": "data"}})
        last_id = cr_id

        # Then another count_rows to get the row count of that result = "# unique groups"
        x_cursor += 260
        cr2_id = _gen_id(node_ids, "n")
        nodes.append({
            "id": cr2_id, "block_id": "block_count_rows", "block_version": "1.0.0",
            "position": {"x": x_cursor, "y": 80},
            "params": {},  # no group_by → total row count
        })
        edges.append({"id": _gen_id(edge_ids, "e"),
                      "from": {"node": last_id, "port": "data"},
                      "to": {"node": cr2_id, "port": "data"}})
        last_id = cr2_id

        # threshold(operator='>', target=1) → triggers when there are 2+ unique groups
        # (meaning NOT all from same recipe/APC → fire alert)
        x_cursor += 260
        thr_id = _gen_id(node_ids, "n")
        nodes.append({
            "id": thr_id, "block_id": "block_threshold", "block_version": "1.0.0",
            "position": {"x": x_cursor, "y": 80},
            "params": {"column": "count", "operator": ">", "target": 1},
        })
        edges.append({"id": _gen_id(edge_ids, "e"),
                      "from": {"node": last_id, "port": "data"},
                      "to": {"node": thr_id, "port": "data"}})
        last_id = thr_id

        notes.append(
            f"Translated same-{pattern['field']} check into filter(OOC) + count_rows(group_by={pattern['field']}) + "
            f"count_rows + threshold(count > 1). Triggers when OOC events span multiple {pattern['field']}s."
        )

    else:
        status = "skeleton"
        notes.append(
            "Logic pattern not recognized automatically. "
            "Pipeline has source + TODO downstream for manual completion."
        )

    # -- Step 3: output-schema-driven output emission.
    # Parse output_schema to decide what terminal outputs the pipeline needs:
    #   *_chart types           → block_chart with x/y/y_secondary from x_key/y_keys
    #   table types             → block_data_view with columns from columns[*].key
    #   condition_met scalars   → block_alert (if we have a logic node upstream)
    #   correlation_coef scalar → upstream block_correlation before chart
    #   slope/intercept/r_squared → upstream block_linear_regression
    last_node = nodes[-1]
    has_logic = last_node["block_id"] in {
        "block_threshold", "block_consecutive_rule", "block_weco_rules", "block_any_trigger"
    }
    chart_outputs = [o for o in (output_schema or []) if o.get("type", "").endswith("_chart")]
    table_outputs = [o for o in (output_schema or []) if o.get("type") == "table"]
    scalar_outputs = [o for o in (output_schema or []) if o.get("type") in {"scalar", "badge"}]
    scalar_keys = {o.get("key") for o in scalar_outputs}
    has_alarm_like = any(k in scalar_keys for k in {"condition_met", "ooc_count", "event_count"}) \
        or "condition_met" in combined_code

    # Canonical column aliases — delegated to column_aliases (single source of truth).
    from python_ai_sidecar.pipeline_builder.column_aliases import canonicalise_column
    source_object_name = (src_params or {}).get("object_name", "")

    def _canonical(col: str | None) -> str | None:
        return canonicalise_column(col, object_name=source_object_name)

    # ── 3a: pre-chart regression / correlation nodes
    skill_source = skill.get("source", "")
    is_auto_patrol = skill_source == "auto_patrol"
    data_source_id = source_id  # chart/view/regression default feeds from original source

    # linear_regression: add before chart if output has slope/intercept + predicted in y_keys
    wants_regression = any(
        o.get("key") in {"slope", "intercept", "r_squared"} for o in scalar_outputs
    ) or any("predicted" in (o.get("y_keys") or []) for o in chart_outputs)
    regression_out_id: Optional[str] = None
    if wants_regression and chart_outputs:
        primary_chart = chart_outputs[0]
        x_key = _canonical(primary_chart.get("x_key") or "eventTime")
        # The main y value for regression is the first non-predicted/ucl/lcl key
        y_keys = primary_chart.get("y_keys") or []
        y_key = next(
            (_canonical(k) for k in y_keys if k not in {"predicted", "ucl", "lcl"}),
            None,
        )
        if y_key:
            x_cursor += 260
            regression_out_id = _gen_id(node_ids, "n")
            nodes.append({
                "id": regression_out_id, "block_id": "block_linear_regression", "block_version": "1.0.0",
                "position": {"x": x_cursor, "y": 60},
                "params": {"x_column": x_key, "y_column": y_key},
            })
            edges.append({"id": _gen_id(edge_ids, "e"),
                          "from": {"node": data_source_id, "port": "data"},
                          "to": {"node": regression_out_id, "port": "data"}})
            data_source_id = regression_out_id  # chart reads regression output
            notes.append(f"Wired block_linear_regression ({x_key} → {y_key}) ahead of chart.")

    # correlation: if output has correlation_coef scalar → add block_correlation
    wants_correlation = any(
        o.get("key") in {"correlation_coef", "correlation"} for o in scalar_outputs
    )
    if wants_correlation and chart_outputs:
        primary_chart = chart_outputs[0]
        x_col = _canonical(primary_chart.get("x_key") or "x")
        y_col_list = [_canonical(k) for k in (primary_chart.get("y_keys") or ["y"])]
        x_cursor += 260
        corr_id = _gen_id(node_ids, "n")
        nodes.append({
            "id": corr_id, "block_id": "block_correlation", "block_version": "1.0.0",
            "position": {"x": x_cursor, "y": 60},
            "params": {"columns": [x_col] + y_col_list[:1]},
        })
        edges.append({"id": _gen_id(edge_ids, "e"),
                      "from": {"node": data_source_id, "port": "data"},
                      "to": {"node": corr_id, "port": "data"}})
        notes.append(
            f"Wired block_correlation ({x_col} vs {y_col_list[0]}) alongside chart — "
            "correlation_coef scalar will be read from its output."
        )

    # ── 3b: chart output (uses _canonical defined above)
    for idx, chart in enumerate(chart_outputs):
        x_key = _canonical(chart.get("x_key") or "eventTime")
        raw_y_keys = chart.get("y_keys") or []
        y_keys = [_canonical(k) for k in raw_y_keys]
        y_primary = y_keys[0] if y_keys else "spc_xbar_chart_value"
        y_secondary = y_keys[1:] if len(y_keys) > 1 else []
        chart_type_raw = chart.get("type", "line_chart")
        # scatter_chart → "scatter"; line_chart → "line"; bar_chart → "bar"; etc.
        chart_type_map = {
            "line_chart": "line",
            "scatter_chart": "scatter",
            "bar_chart": "bar",
            "area_chart": "area",
        }
        pb_chart_type = chart_type_map.get(chart_type_raw, "line")
        x_cursor += 260
        chart_id = _gen_id(node_ids, "n")
        chart_params: dict[str, Any] = {
            "chart_type": pb_chart_type,
            "x": x_key,
            "y": y_primary,
            "title": chart.get("label") or skill_name,
            "sequence": idx + 1,
        }
        if y_secondary:
            chart_params["y_secondary"] = y_secondary
        hk = chart.get("highlight_key")
        if hk:
            chart_params["highlight_column"] = _canonical(hk)
        nodes.append({
            "id": chart_id, "block_id": "block_chart", "block_version": "1.0.0",
            "position": {"x": x_cursor, "y": 60 if regression_out_id is None else 160},
            "params": chart_params,
        })
        edges.append({"id": _gen_id(edge_ids, "e"),
                      "from": {"node": data_source_id, "port": "data"},
                      "to": {"node": chart_id, "port": "data"}})

    # ── 3c: table output → block_data_view
    for idx, tbl in enumerate(table_outputs):
        cols = [c.get("key") for c in (tbl.get("columns") or []) if c.get("key")]
        x_cursor += 260
        dv_id = _gen_id(node_ids, "n")
        nodes.append({
            "id": dv_id, "block_id": "block_data_view", "block_version": "1.0.0",
            "position": {"x": x_cursor, "y": 240 if chart_outputs else 120},
            "params": {
                "title": tbl.get("label") or f"Data {idx + 1}",
                **({"columns": cols} if cols else {}),
                "sequence": idx + 1 + len(chart_outputs),
            },
        })
        edges.append({"id": _gen_id(edge_ids, "e"),
                      "from": {"node": source_id, "port": "data"},  # always fed from source
                      "to": {"node": dv_id, "port": "data"}})

    # ── 3d: alert (only if we have a logic chain + alarm-ish output)
    if has_logic and has_alarm_like:
        x_cursor += 260
        alert_id = _gen_id(node_ids, "n")
        nodes.append({
            "id": alert_id, "block_id": "block_alert", "block_version": "1.0.0",
            "position": {"x": x_cursor, "y": 80},
            "params": {"severity": "HIGH", "title_template": f"[{skill_name}] triggered"},
        })
        edges.append({"id": _gen_id(edge_ids, "e"),
                      "from": {"node": last_id, "port": "triggered"},
                      "to": {"node": alert_id, "port": "triggered"}})
        edges.append({"id": _gen_id(edge_ids, "e"),
                      "from": {"node": last_id, "port": "evidence"},
                      "to": {"node": alert_id, "port": "evidence"}})

    # ── Mark status: full if we emitted some output node; else skeleton
    output_emitted = bool(chart_outputs or table_outputs) or (has_logic and has_alarm_like)
    if output_emitted and status == "skeleton":
        # We had no logic pattern but did emit valid chart/view — count as full
        status = "full"
        notes.append(
            "Auto-wired from output_schema: "
            f"{len(chart_outputs)} chart(s), {len(table_outputs)} data_view(s)."
        )
    elif not output_emitted and status == "full":
        status = "skeleton"
        notes.append("No output node emitted; skeleton only.")

    # ── Fallback: ensure at least one output block so C7_ENDPOINTS passes.
    # Skeleton stubs (e.g. DC drift / Recipe consistency on prod) have source
    # only; attach a generic block_data_view so the pipeline is at least valid
    # structurally. Human can refine later.
    if not output_emitted:
        x_cursor += 260
        fallback_id = _gen_id(node_ids, "n")
        nodes.append({
            "id": fallback_id, "block_id": "block_data_view", "block_version": "1.0.0",
            "position": {"x": x_cursor, "y": 80},
            "params": {"title": f"{skill_name} — 原始資料", "max_rows": 200},
        })
        edges.append({"id": _gen_id(edge_ids, "e"),
                      "from": {"node": last_id, "port": "data"},
                      "to": {"node": fallback_id, "port": "data"}})
        notes.append(
            "Added fallback block_data_view so pipeline passes C7_ENDPOINTS; "
            "human should refine logic + output manually."
        )

    pipeline_json = {
        "version": "1.0",
        "name": f"[migrated] {skill_name}",
        "metadata": {
            "migrated_from_skill_id": skill_id,
            "original_source": skill.get("source"),
        },
        "inputs": pipeline_inputs,
        "nodes": nodes,
        "edges": edges,
    }

    return MigrationResult(
        skill_id=skill_id,
        skill_name=skill_name,
        status=status,
        pipeline_json=pipeline_json,
        notes=notes,
        detected_mcps=detected_mcps,
    )


def migrate_all_skills(skills_rows: list[dict[str, Any]]) -> list[MigrationResult]:
    """Migrate a batch. Each skill row must expose id / name / source / steps_mapping /
    input_schema / output_schema as JSON strings."""
    return [migrate_skill(s) for s in skills_rows]
