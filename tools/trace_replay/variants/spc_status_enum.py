"""clarify_spc_status_enum — patch runtime_schema_md so spc_status row
explicitly shows enum<"PASS"|"OOC"> instead of the sample-inferred
`enum['PASS'=5]`.

Hypothesis (2026-05-16, EQP-08 case): at p2, LLM saw `spc_status |
enum['PASS'=5] | [best] 直接讀此欄是最快路徑` but skipped the [best] path
because the inferred enum only listed 'PASS' — LLM didn't know what value
to filter for OOC events. It took the longer pluck+filter+sort path via
spc_summary.ooc_count instead.

This variant rewrites that one row to make the binary clear. If LLM
switches to spc_status filter, the hypothesis is confirmed.
"""
from __future__ import annotations

import re

from ..types import LLMInput


def clarify_spc_status_enum(inp: LLMInput) -> LLMInput:
    """Rewrite the spc_status row in runtime_schema_md."""
    new_um = inp.user_msg

    # Match the spc_status table row and replace its `inferred type` cell
    # Pattern: | spc_status | <anything> | [best] ...
    pat = re.compile(
        r"(\| spc_status \| )([^|]+?)( \|)",
        re.MULTILINE,
    )
    if pat.search(new_um):
        new_um = pat.sub(
            r"\1enum<'PASS'|'OOC'> (explicit; sample only shows PASS but OOC is the OOC-event value)\3",
            new_um,
            count=1,
        )

    new_messages = list(inp.messages)
    if new_messages and new_messages[-1].get("role") == "user":
        new_messages[-1] = {"role": "user", "content": new_um}
    return LLMInput(
        system=inp.system,
        user_msg=new_um,
        tool_specs=inp.tool_specs,
        messages=new_messages,
        meta={**inp.meta, "variant_applied": "clarify_spc_status_enum"},
    )
