"""phase_goal variants — rewrite the CURRENT PHASE section of user_msg.

Hypothesis (2026-05-16): goal_plan_node sometimes emits phase goals that
include block-specific tokens (e.g. "process_history", "spc_chart"). LLM
in agentic_phase_loop then locks onto these tokens and picks the
correspondingly-named block, ignoring catalog hints about better composite
alternatives.

`rewrite_phase_goal_generic` replaces the most common leaky tokens with
neutral synonyms in the CURRENT PHASE goal text. If the hypothesis holds,
B variant should let spc_panel / step_check be picked at non-trivial rates.
"""
from __future__ import annotations

import re

from ..types import LLMInput


# Leaky tokens → neutral synonyms. Keep small + conservative so we don't
# strip legitimate user vocabulary.
_LEAKY_REPLACEMENTS = [
    (r"\bprocess_history\b", "處理歷史資料"),
    (r"\bspc_summary\b", "SPC 統計結果"),
    (r"\bspc_charts?\b", "SPC 資料"),
    (r"\bspc_status\b", "SPC 狀態"),
    (r"\bstep_check\b", "判定"),
    (r"\bblock_\w+\b", ""),   # any explicit block_xxx token
]


_CURRENT_PHASE_PAT = re.compile(
    r"(== CURRENT PHASE [^\n]*\n)(.*?)(\n== ALL PHASES CONTEXT)",
    re.DOTALL,
)


def rewrite_phase_goal_generic(inp: LLMInput) -> LLMInput:
    """Strip block-name tokens from the CURRENT PHASE block.

    Only touches the `goal:` and `why:` lines inside the CURRENT PHASE
    section. Leaves the rest of user_msg intact.
    """

    def _strip(section_body: str) -> str:
        new = section_body
        for pat, repl in _LEAKY_REPLACEMENTS:
            new = re.sub(pat, repl, new, flags=re.IGNORECASE)
        # Collapse multiple spaces left by removed block_xxx tokens
        new = re.sub(r"  +", " ", new)
        return new

    new_user_msg = _CURRENT_PHASE_PAT.sub(
        lambda m: m.group(1) + _strip(m.group(2)) + m.group(3),
        inp.user_msg,
        count=1,
    )
    new_messages = list(inp.messages)
    if new_messages and new_messages[-1].get("role") == "user":
        new_messages[-1] = {"role": "user", "content": new_user_msg}
    return LLMInput(
        system=inp.system, user_msg=new_user_msg,
        tool_specs=inp.tool_specs, messages=new_messages,
        meta={**inp.meta, "variant_applied": "rewrite_phase_goal_generic"},
    )
