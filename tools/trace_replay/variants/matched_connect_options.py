"""matched_connect_options — show LLM only TYPE-COMPATIBLE source ports
for each un-connected input port. Forces graph-side type matching;
LLM only picks semantically.

Hypothesis: stronger than raw lineage view — LLM literally cannot pick
type-mismatched ports because they aren't shown. Also surfaces "no
compatible source" as an explicit signal that LLM needs to add an
intermediate block.
"""
from __future__ import annotations

import re
from typing import Any

from ..types import LLMInput


_CANVAS_HEADER_PAT = re.compile(r"== CANVAS NOW \([^)]*\) ==\n")
_NODE_LINE_PAT = re.compile(r"^\s*(n\d+)\s+\[([^\]]+)\]\s*(params=.*)?$")
_EDGE_LINE_PAT = re.compile(r"^\s*edge\s+(n\d+)\s*->\s*(n\d+)")
_PHASE_GOAL_PAT = re.compile(r"\nPHASE GOAL:", re.DOTALL)


def _types_compatible(src_type: str, dst_type: str) -> bool:
    """Return True if a source port of src_type can feed a dest port of dst_type."""
    if not src_type or not dst_type:
        return True  # unknown — be permissive
    if src_type == dst_type:
        return True
    # treat 'any' as wildcard either side
    if "any" in (src_type, dst_type):
        return True
    return False


def inject_matched_connect_options(inp: LLMInput) -> LLMInput:
    canvas_match = _CANVAS_HEADER_PAT.search(inp.user_msg)
    if not canvas_match:
        return LLMInput(
            system=inp.system, user_msg=inp.user_msg,
            tool_specs=inp.tool_specs, messages=list(inp.messages),
            meta={**inp.meta, "variant_applied": "inject_matched_connect_options",
                  "skipped_reason": "no CANVAS NOW section"},
        )

    canvas_body_start = canvas_match.end()
    pg_match = _PHASE_GOAL_PAT.search(inp.user_msg, canvas_body_start)
    canvas_end = pg_match.start() if pg_match else len(inp.user_msg)

    canvas_body = inp.user_msg[canvas_body_start:canvas_end]

    from python_ai_sidecar.pipeline_builder.seedless_registry import (
        SeedlessBlockRegistry,
    )
    reg = SeedlessBlockRegistry()
    reg.load()

    def _spec(block_id: str) -> dict:
        return reg.get_spec(block_id, "1.0.0") or {}

    # Parse nodes + edges
    nodes: list[dict[str, Any]] = []
    incoming_count: dict[str, int] = {}
    for raw in canvas_body.split("\n"):
        m = _NODE_LINE_PAT.match(raw)
        if m:
            nid, bid = m.group(1), m.group(2)
            spec = _spec(bid)
            nodes.append({
                "id": nid,
                "block_id": bid,
                "in_ports": list(spec.get("input_schema") or []),
                "out_ports": list(spec.get("output_schema") or []),
            })
            incoming_count.setdefault(nid, 0)
            continue
        e = _EDGE_LINE_PAT.match(raw)
        if e:
            incoming_count[e.group(2)] = incoming_count.get(e.group(2), 0) + 1

    nodes_by_id = {n["id"]: n for n in nodes}

    # For nodes whose incoming_count < len(in_ports), emit CONNECT OPTIONS section
    options_sections: list[str] = []
    for n in nodes:
        n_in = len(n["in_ports"])
        if n_in == 0:
            continue
        if incoming_count.get(n["id"], 0) >= n_in:
            continue  # all inputs already filled

        section_lines = [f"== CONNECT OPTIONS for {n['id']} ({n['block_id']}) =="]
        for in_port in n["in_ports"]:
            iname, itype = in_port.get("port"), in_port.get("type")
            section_lines.append(f"{n['id']}.{iname} ({itype}):")

            # Find type-compatible source ports across ALL other nodes
            compats: list[tuple[str, str, str, str]] = []  # (src_nid, src_block, src_port, src_type)
            for src in nodes:
                if src["id"] == n["id"]:
                    continue  # self
                for op in src["out_ports"]:
                    oname, otype = op.get("port"), op.get("type")
                    if _types_compatible(otype, itype):
                        compats.append((src["id"], src["block_id"], oname, otype))

            if compats:
                section_lines.append(f"  Compatible sources (pick semantically; fan-out OK):")
                for sid, sblock, sport, stype in compats:
                    section_lines.append(f"    {sid}.{sport}   [{sblock}]  ({stype})")
            else:
                # No compatible source — list blocks that DO produce this type
                producers = _find_blocks_producing_type(reg, itype)
                section_lines.append(f"  [NO COMPATIBLE SOURCE in current pipeline]")
                if producers:
                    ps = ", ".join(producers[:8])
                    section_lines.append(
                        f"  ⚠ Need to add an intermediate block first. Blocks that "
                        f"output type={itype}: {ps}"
                    )
                else:
                    section_lines.append(
                        f"  ⚠ No registered block outputs type={itype}."
                    )

        options_sections.append("\n".join(section_lines))

    if not options_sections:
        return LLMInput(
            system=inp.system, user_msg=inp.user_msg,
            tool_specs=inp.tool_specs, messages=list(inp.messages),
            meta={**inp.meta, "variant_applied": "inject_matched_connect_options",
                  "skipped_reason": "all nodes have all inputs filled"},
        )

    injection = "\n\n" + "\n\n".join(options_sections) + "\n"

    new_user_msg = (
        inp.user_msg[:canvas_end]
        + injection
        + inp.user_msg[canvas_end:]
    )
    new_messages = list(inp.messages)
    if new_messages and new_messages[-1].get("role") == "user":
        new_messages[-1] = {"role": "user", "content": new_user_msg}

    return LLMInput(
        system=inp.system, user_msg=new_user_msg,
        tool_specs=inp.tool_specs, messages=new_messages,
        meta={**inp.meta, "variant_applied": "inject_matched_connect_options"},
    )


def _find_blocks_producing_type(reg, target_type: str) -> list[str]:
    """Scan registry for blocks whose output_schema includes target_type."""
    if not target_type:
        return []
    out: list[str] = []
    for (name, _v), spec in reg.catalog.items():
        if str(spec.get("status") or "").lower() == "deprecated":
            continue
        for op in spec.get("output_schema") or []:
            if _types_compatible(op.get("type"), target_type):
                out.append(name)
                break
    return sorted(out)
