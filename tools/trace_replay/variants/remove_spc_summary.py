"""remove_spc_summary_expand_spc_charts — test user's hypothesis (2026-05-16):
spc_summary is redundant cache that misleads LLM; if we (a) remove it from
schema entirely and (b) document spc_charts inner fields properly, LLM
should naturally find the unnest+filter+count path.

Hypothesis: with spc_summary gone + spc_charts inner schema clear, LLM
will pick: sort+limit=1 (last OOC) -> unnest(spc_charts) -> filter(is_ooc) -> count_rows.
"""
from __future__ import annotations

import re

from ..types import LLMInput


def remove_spc_summary_expand_spc_charts(inp: LLMInput) -> LLMInput:
    """Rewrite spc_charts row to detail inner fields + drop spc_summary row."""
    new_um = inp.user_msg

    # 1. Replace the spc_charts row with one that documents inner fields
    spc_charts_pat = re.compile(
        r"\| spc_charts \| [^|]+ \| [^|]+ \|",
        re.MULTILINE,
    )
    new_spc_charts_row = (
        "| spc_charts | list[dict] x ~12 charts per event. "
        "**Each chart dict**: {`name`: str (chart 名 e.g. 'xbar_chart','r_chart'), "
        "`value`: float (該 chart 當下測量值), `ucl`: float (上管制限), "
        "`lcl`: float (下管制限), **`is_ooc`: bool (此 chart 是否超管制 — TRUE = OOC)**, "
        "`status`: enum<'PASS'\\|'OOC'> (per-chart 結果)} | "
        "[best] 「OOC 數量」-> unnest -> filter(is_ooc==true) -> count_rows ; "
        "[best] 「OOC 名單」-> unnest -> filter(is_ooc==true) -> pluck(name) ; "
        "[best] 「畫單一 chart trend」-> unnest -> filter(name='xbar_chart') -> line_chart ; "
        "[best] 「跨 chart value 分佈」-> unnest -> box_plot ; "
        "[best] 「直接出 SPC panel」-> block_spc_panel composite (1-block 內部 unnest) ; "
        "[warn] unnest 後 leaf 名是 'name'/'value'，不是 'spc_name'/'spc_value' |"
    )
    if spc_charts_pat.search(new_um):
        new_um = spc_charts_pat.sub(new_spc_charts_row, new_um, count=1)

    # 2. Drop the spc_summary row entirely
    spc_summary_pat = re.compile(
        r"\n\| spc_summary \| [^|]+ \| [^|]+ \|",
        re.MULTILINE,
    )
    new_um = spc_summary_pat.sub("", new_um)

    # 3. Trim spc_summary mention from sample row JSON (cosmetic — LLM
    #    still sees the data but schema doesn't suggest using it)
    new_um = re.sub(
        r', "spc_summary": \{[^}]+\}',
        ', "spc_summary": <removed in variant>',
        new_um,
    )

    new_messages = list(inp.messages)
    if new_messages and new_messages[-1].get("role") == "user":
        new_messages[-1] = {"role": "user", "content": new_um}
    return LLMInput(
        system=inp.system,
        user_msg=new_um,
        tool_specs=inp.tool_specs,
        messages=new_messages,
        meta={**inp.meta, "variant_applied": "remove_spc_summary_expand_spc_charts"},
    )
