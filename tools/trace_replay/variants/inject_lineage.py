"""inject_pipeline_lineage — add lineage schema view to user_msg.

Hypothesis: LLM picks wrong port names (e.g. connect default port='data' when
block_step_check outputs 'check') because the CANVAS NOW section in user_msg
shows params + edges but NOT each node's output port names / cols.

This variant:
  1. Locates the `== CANVAS NOW (...)` section in user_msg.
  2. For each `nN [block_id]` line, queries SeedlessBlockRegistry for the
     block's output_schema (port name + type) and input_schema, and
     appends them inline.
  3. Inserts a separator + brief "== HOW TO READ ==" hint before PHASE GOAL.

No data sampling — just schema. Cheap (~50 tokens / node).
"""
from __future__ import annotations

import re

from ..types import LLMInput


_CANVAS_HEADER_PAT = re.compile(r"== CANVAS NOW \([^)]*\) ==\n")
_NODE_LINE_PAT = re.compile(r"^(\s*)(n\d+)\s+\[([^\]]+)\]\s*(params=.*)?$")
_PHASE_GOAL_PAT = re.compile(r"\nPHASE GOAL:", re.DOTALL)


def inject_pipeline_lineage(inp: LLMInput) -> LLMInput:
    canvas_match = _CANVAS_HEADER_PAT.search(inp.user_msg)
    if not canvas_match:
        return LLMInput(
            system=inp.system, user_msg=inp.user_msg,
            tool_specs=inp.tool_specs, messages=list(inp.messages),
            meta={**inp.meta, "variant_applied": "inject_pipeline_lineage",
                  "skipped_reason": "no CANVAS NOW section in user_msg"},
        )

    # Find canvas section boundaries
    canvas_start = canvas_match.start()
    canvas_body_start = canvas_match.end()
    # Canvas ends at blank line or PHASE GOAL marker
    pg_match = _PHASE_GOAL_PAT.search(inp.user_msg, canvas_body_start)
    canvas_end = pg_match.start() if pg_match else len(inp.user_msg)

    canvas_body = inp.user_msg[canvas_body_start:canvas_end]

    # Load registry lazily
    from python_ai_sidecar.pipeline_builder.seedless_registry import (
        SeedlessBlockRegistry,
    )
    reg = SeedlessBlockRegistry()
    reg.load()

    def _spec(block_id: str) -> dict:
        return reg.get_spec(block_id, "1.0.0") or {}

    def _fmt_ports(port_list: list[dict]) -> str:
        if not port_list:
            return "-"
        return ", ".join(f"{p.get('port')}:{p.get('type')}" for p in port_list)

    augmented_lines: list[str] = []
    for line in canvas_body.split("\n"):
        m = _NODE_LINE_PAT.match(line)
        if not m:
            augmented_lines.append(line)
            continue
        indent, nid, block_id, _params = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        spec = _spec(block_id)
        out_ports = _fmt_ports(spec.get("output_schema") or [])
        in_ports = _fmt_ports(spec.get("input_schema") or [])
        # Keep original line, append a continuation line with ports
        augmented_lines.append(line)
        augmented_lines.append(
            f"{indent}    └─ in_ports=[{in_ports}]  out_ports=[{out_ports}]"
        )

    new_canvas = "\n".join(augmented_lines)

    hint = (
        "\n== HOW TO READ in_ports / out_ports ==\n"
        "在 `connect` 時，from_port 必須是 source node 的 out_ports 之一；\n"
        "to_port 必須是 dest node 的 in_ports 之一。預設 'data' 對許多 block 不存在。\n"
        "若需要某張 df 當 evidence/input 又不在直線 lineage 上，可以從上游 fan-out\n"
        "(同一上游 node 可有多條 outgoing edges)。\n"
    )

    new_user_msg = (
        inp.user_msg[:canvas_body_start]
        + new_canvas
        + hint
        + inp.user_msg[canvas_end:]
    )

    new_messages = list(inp.messages)
    if new_messages and new_messages[-1].get("role") == "user":
        new_messages[-1] = {"role": "user", "content": new_user_msg}

    return LLMInput(
        system=inp.system, user_msg=new_user_msg,
        tool_specs=inp.tool_specs, messages=new_messages,
        meta={**inp.meta, "variant_applied": "inject_pipeline_lineage"},
    )
