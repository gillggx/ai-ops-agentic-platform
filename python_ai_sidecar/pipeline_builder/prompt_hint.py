"""Compact block catalog formatter — used to inject pb block schemas into
the v2 orchestrator's system prompt so `build_pipeline` can emit valid DAGs.
"""

from __future__ import annotations

import json
from typing import Any


# Phase 5-UX-3b: mandatory flat-schema prelude. Without this the LLM tends to
# guess nested paths ("SPC.xbar_chart.value") because users describe data that
# way in conversation — but our blocks work on flat columns.
FLAT_SCHEMA_PRELUDE = """## IMPORTANT — Flat column naming rules

All Pipeline Builder blocks operate on **flat DataFrames**. Even when the user says
"SPC.xbar_chart.value" or "APC.parameters.etch_time_offset", the actual column
names after source blocks flatten the data are always flat snake_case:

| User says                           | Real flat column              |
|-------------------------------------|-------------------------------|
| SPC.xbar_chart.value                | spc_xbar_chart_value          |
| SPC.xbar_chart.ucl / lcl / is_ooc   | spc_xbar_chart_ucl / _lcl / _is_ooc |
| SPC.r_chart.value                   | spc_r_chart_value             |
| APC.parameters.etch_time_offset     | apc_etch_time_offset          |
| APC.parameters.rf_power_bias        | apc_rf_power_bias             |
| RECIPE.parameters.<name>            | recipe_<name>                 |
| DC.sensors.<name>                   | dc_<name>                     |
| event time / timestamp              | **eventTime** (camelCase)     |
| lot / batch                         | **lotID** (camelCase)         |
| tool / equipment                    | **toolID** (camelCase)        |

**Rules for you when building a pipeline:**
1. Never ask the user for column names — use this table and the per-block
   `output columns` listed below.
2. For time-based ordering use `eventTime` (NOT `event_time`, `time`, or `timestamp`).
3. Downstream blocks (sort, filter, regression, chart) reference the flat names
   directly — e.g. `block_sort(columns=[{column:"eventTime",order:"asc"}])`.
4. Overlay / secondary axis in block_chart: pass column names as string/list.
"""


def build_block_catalog_hint(catalog: dict[tuple[str, str], dict[str, Any]]) -> str:
    """Compact LLM-readable summary of all blocks.

    We deliberately keep the description short per block and only surface
    input/output ports + param schema + flat output columns so the LLM can
    emit correct node specs without overwhelming the context. Full examples
    + long-form descriptions live on individual blocks and surface to the
    Pipeline Builder's own Agent (see app/services/agent_builder/prompt.py).
    """
    lines: list[str] = []
    lines.append(FLAT_SCHEMA_PRELUDE)
    lines.append("")
    lines.append(f"## Available Blocks ({len(catalog)})")
    lines.append("")

    by_cat: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for (name, version), spec in catalog.items():
        by_cat.setdefault(spec.get("category") or "other", []).append((name, version, spec))

    order = ["source", "transform", "logic", "output", "custom", "other"]
    for cat in order:
        items = by_cat.get(cat) or []
        if not items:
            continue
        lines.append(f"### {cat.upper()}")
        for name, version, spec in sorted(items, key=lambda x: x[0]):
            desc_first_line = (spec.get("description") or "").strip().splitlines()[0][:100]
            lines.append(f"- **`{name}`** — {desc_first_line}")
            in_ports = [p.get("port") for p in (spec.get("input_schema") or [])]
            out_ports = [p.get("port") for p in (spec.get("output_schema") or [])]
            ports_line = ""
            if in_ports:
                ports_line += f"in: {in_ports}"
            if out_ports:
                ports_line += (" | " if ports_line else "") + f"out: {out_ports}"
            if ports_line:
                lines.append(f"  - ports: {ports_line}")
            param_schema = spec.get("param_schema") or {}
            props = param_schema.get("properties") or {}
            if props:
                # Show just the param names + type + required-marker
                required = set(param_schema.get("required") or [])
                params_brief = ", ".join(
                    f"{k}{'*' if k in required else ''}:{(v.get('type') if isinstance(v, dict) else '?')}"
                    for k, v in list(props.items())[:8]
                )
                lines.append(f"  - params: {params_brief}")
            # Phase 5-UX-3b: show flat output columns if provided
            out_cols = spec.get("output_columns_hint") or []
            if out_cols:
                # Pack terse: name:type (when_present)
                col_lines: list[str] = []
                for c in out_cols[:20]:  # cap to keep prompt compact
                    nm = c.get("name", "?")
                    tp = c.get("type", "?")
                    wp = c.get("when_present")
                    if wp:
                        col_lines.append(f"`{nm}`:{tp} ({wp})")
                    else:
                        col_lines.append(f"`{nm}`:{tp}")
                lines.append(f"  - output columns: {', '.join(col_lines)}")
                if len(out_cols) > 20:
                    lines.append(f"    …and {len(out_cols) - 20} more")
        lines.append("")

    # Mini-example so LLM has an anchor
    lines.append("### Example build_pipeline payload")
    lines.append("```json")
    example = {
        "pipeline_json": {
            "version": "1.0",
            "name": "EQP-01 xbar trend",
            "inputs": [],
            "nodes": [
                {"id": "n1", "block_id": "block_process_history", "block_version": "1.0.0",
                 "position": {"x": 30, "y": 80},
                 "params": {"tool_id": "EQP-01", "object_name": "SPC", "limit": 50}},
                {"id": "n2", "block_id": "block_sort", "block_version": "1.0.0",
                 "position": {"x": 300, "y": 80},
                 "params": {"columns": [{"column": "eventTime", "order": "asc"}]}},
                {"id": "n3", "block_id": "block_chart", "block_version": "1.0.0",
                 "position": {"x": 580, "y": 80},
                 "params": {"chart_type": "line", "x": "eventTime",
                            "y": "spc_xbar_chart_value",
                            "ucl_column": "spc_xbar_chart_ucl",
                            "lcl_column": "spc_xbar_chart_lcl",
                            "highlight_column": "spc_xbar_chart_is_ooc",
                            "title": "EQP-01 xbar trend"}},
            ],
            "edges": [
                {"id": "e1", "from": {"node": "n1", "port": "data"},
                 "to": {"node": "n2", "port": "data"}},
                {"id": "e2", "from": {"node": "n2", "port": "data"},
                 "to": {"node": "n3", "port": "data"}},
            ],
        },
        "inputs": {},
    }
    lines.append(json.dumps(example, ensure_ascii=False, indent=2))
    lines.append("```")

    # Second example — linear regression SPC vs APC (covers EQP-07 bug scenario)
    lines.append("")
    lines.append("### Example 2 — SPC vs APC linear regression")
    lines.append("```json")
    example2 = {
        "pipeline_json": {
            "version": "1.0",
            "name": "xbar vs etch_time_offset regression",
            "inputs": [],
            "nodes": [
                {"id": "n1", "block_id": "block_process_history", "block_version": "1.0.0",
                 "position": {"x": 30, "y": 80},
                 "params": {"tool_id": "EQP-07", "limit": 100}},
                {"id": "n2", "block_id": "block_sort", "block_version": "1.0.0",
                 "position": {"x": 300, "y": 80},
                 "params": {"columns": [{"column": "eventTime", "order": "asc"}], "limit": 100}},
                {"id": "n3", "block_id": "block_linear_regression", "block_version": "1.0.0",
                 "position": {"x": 580, "y": 80},
                 "params": {"x_column": "apc_etch_time_offset", "y_column": "spc_xbar_chart_value"}},
                {"id": "n4", "block_id": "block_chart", "block_version": "1.0.0",
                 "position": {"x": 860, "y": 80},
                 "params": {"chart_type": "scatter", "x": "apc_etch_time_offset",
                            "y": "spc_xbar_chart_value",
                            "title": "xbar vs etch_time_offset"}},
            ],
            "edges": [
                {"id": "e1", "from": {"node": "n1", "port": "data"}, "to": {"node": "n2", "port": "data"}},
                {"id": "e2", "from": {"node": "n2", "port": "data"}, "to": {"node": "n3", "port": "data"}},
                {"id": "e3", "from": {"node": "n3", "port": "data"}, "to": {"node": "n4", "port": "data"}},
            ],
        },
        "inputs": {},
    }
    lines.append(json.dumps(example2, ensure_ascii=False, indent=2))
    lines.append("```")

    return "\n".join(lines)
