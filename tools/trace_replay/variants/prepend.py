"""prepend variants — add a section at the TOP of user_msg.

`prepend_oneblock_solutions` injects a server-detected list of composite
blocks that could fast-forward through the current + upcoming phases.
Pulls from the actual catalog at replay time (NOT trace), so it always
reflects current produces.covers maps.
"""
from __future__ import annotations

import re

from ..types import LLMInput


_CURRENT_PHASE_PAT = re.compile(
    r"== CURRENT PHASE [^\n]*\nid: (\S+)\ngoal: (.+?)\nexpected: (\S+)",
    re.DOTALL,
)
_ALL_PHASES_PAT = re.compile(
    r"== ALL PHASES CONTEXT ==\n(.+?)\n\n",
    re.DOTALL,
)


def prepend_oneblock_solutions(inp: LLMInput) -> LLMInput:
    """Compute 1-block solutions for current+remaining phases and prepend
    a SOLUTIONS section before the existing user_msg.
    """
    cur_match = _CURRENT_PHASE_PAT.search(inp.user_msg)
    all_match = _ALL_PHASES_PAT.search(inp.user_msg)
    if not cur_match or not all_match:
        # Can't locate phase structure — return unchanged with a note
        return LLMInput(
            system=inp.system, user_msg=inp.user_msg,
            tool_specs=inp.tool_specs, messages=list(inp.messages),
            meta={**inp.meta, "variant_applied": "prepend_oneblock_solutions",
                  "skipped_reason": "phase pattern not found in user_msg"},
        )

    cur_id = cur_match.group(1).strip()
    cur_expected = cur_match.group(3).strip()
    all_lines = all_match.group(1).split("\n")
    phases: list[dict] = []
    for line in all_lines:
        m = re.match(r"\s*(\S+):\s*(.+?)\s*\(expected:\s*(\S+)\)", line)
        if m:
            phases.append({"id": m.group(1), "expected": m.group(3).strip()})

    # Find current idx, derive remaining
    try:
        cur_idx = next(i for i, p in enumerate(phases) if p["id"] == cur_id)
    except StopIteration:
        cur_idx = 0
    remaining = phases[cur_idx + 1:]

    section = _build_solutions_section(
        cur_expected=cur_expected,
        remaining_expecteds=[p["expected"] for p in remaining],
        remaining_ids=[p["id"] for p in remaining],
        cur_id=cur_id,
    )
    if not section:
        # No 1-block solution — keep unchanged but mark
        return LLMInput(
            system=inp.system, user_msg=inp.user_msg,
            tool_specs=inp.tool_specs, messages=list(inp.messages),
            meta={**inp.meta, "variant_applied": "prepend_oneblock_solutions",
                  "skipped_reason": "no composite block covers current phase"},
        )

    new_user_msg = section + "\n" + inp.user_msg
    new_messages = list(inp.messages)
    if new_messages and new_messages[-1].get("role") == "user":
        new_messages[-1] = {"role": "user", "content": new_user_msg}
    return LLMInput(
        system=inp.system, user_msg=new_user_msg,
        tool_specs=inp.tool_specs, messages=new_messages,
        meta={**inp.meta, "variant_applied": "prepend_oneblock_solutions"},
    )


def _build_solutions_section(
    *, cur_expected: str, remaining_expecteds: list[str],
    remaining_ids: list[str], cur_id: str,
) -> str:
    from python_ai_sidecar.pipeline_builder.seedless_registry import (
        SeedlessBlockRegistry,
    )
    from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import (
        _infer_covers_from_block_spec,
    )

    registry = SeedlessBlockRegistry()
    registry.load()
    solutions: list[tuple[str, list[str], list[str]]] = []  # (block, ff_through, covers)
    for (name, _v), spec in registry.catalog.items():
        if str(spec.get("status") or "").lower() == "deprecated":
            continue
        covers = list((spec.get("produces") or {}).get("covers") or [])
        if not covers:
            covers = _infer_covers_from_block_spec(spec)
        if cur_expected not in covers:
            continue
        ff: list[str] = []
        for i, exp in enumerate(remaining_expecteds):
            if exp in covers:
                ff.append(remaining_ids[i])
            else:
                break
        if ff:  # only list blocks that actually fast-forward
            solutions.append((name, ff, covers))

    if not solutions:
        return ""

    solutions.sort(key=lambda x: (-len(x[1]), x[0]))
    lines = [
        "== 1-BLOCK SOLUTIONS (server-detected) ==",
        "下列 block 一次 add_node 可同時完成當前 phase + 後續多 phase",
        "(由 server 比對 phase.expected 與 block.produces.covers 算出，不是建議是事實):",
    ]
    for name, ff, covers in solutions[:3]:
        chain = f"{cur_id}+{'+'.join(ff)}"
        lines.append(
            f"  {name}  → 同時涵蓋 {chain} ({len(ff) + 1} phases)"
            f"  [block covers: {'+'.join(covers)}]"
        )
    lines.append(
        "考慮優先選上面任一 candidate；server verifier 會自動 fast-forward "
        "通過後續 phase。"
    )
    lines.append("")
    return "\n".join(lines)
