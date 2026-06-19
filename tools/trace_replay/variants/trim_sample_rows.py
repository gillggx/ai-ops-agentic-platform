"""trim_sample_rows — simulate optimization A (2026-06-16).

Hypothesis: the "Sample (N rows)" block in each canvas node's runtime
schema dumps the FULL nested object (DC/EC/RECIPE/APC/FDC ~30 sensors each,
spc_charts ~12 charts) — tens of KB of noise. The agent picks blocks / fills
params from the **Schema table** (col | type | description) above it, NOT
from the raw sensor values. So collapsing nested dict/list values in the
sample rows should cut ~10K tokens off the observation with NO loss of the
decision-relevant info.

This variant collapses every nested dict/list VALUE in each sample row to a
compact placeholder (`{…N keys…}` / `[…N items…]`) while leaving scalar
columns (eventTime, toolID, spc_status, …) fully intact. The Schema table is
untouched. It mirrors exactly what the prod change to
`schema_doc.infer_runtime_schema` would do, so the replayed pick is a
faithful proxy for "would proposal A change the LLM's decision?".
"""
from __future__ import annotations

import json
import re

from ..types import LLMInput

_DECODER = json.JSONDecoder()
# Matches the start of a sample row line: `row 0: {` / `row 12: {`
_ROW_RE = re.compile(r"(row\s+\d+:\s*)(\{)")


def _summarize_row(d: dict) -> dict:
    """Keep scalar columns; collapse nested dict/list values to a placeholder."""
    out: dict = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = f"<{{…{len(v)} keys…}}>"
        elif isinstance(v, list):
            out[k] = f"<[…{len(v)} items…]>"
        else:
            out[k] = v
    return out


def _trim_block(text: str) -> str:
    """Find every `row N: {…}` and collapse its nested values in place.

    Uses raw_decode so a single big JSON object followed by trailing text
    (or a truncated final row) is handled: parse from the `{`, summarize,
    re-dump compactly, splice back. On parse failure (truncated row) leave
    that row untouched."""
    out_parts: list[str] = []
    pos = 0
    for m in _ROW_RE.finditer(text):
        brace_idx = m.start(2)
        out_parts.append(text[pos:brace_idx])
        try:
            obj, end = _DECODER.raw_decode(text, brace_idx)
        except (json.JSONDecodeError, ValueError):
            # truncated / non-JSON — leave the rest of this row as-is
            out_parts.append(text[brace_idx:m.end(2)])
            pos = m.end(2)
            continue
        if isinstance(obj, dict):
            compact = json.dumps(_summarize_row(obj), ensure_ascii=False,
                                 separators=(", ", ": "))
            out_parts.append(compact)
        else:
            out_parts.append(text[brace_idx:end])
        pos = end
    out_parts.append(text[pos:])
    return "".join(out_parts)


def trim_sample_rows(inp: LLMInput) -> LLMInput:
    new_um = _trim_block(inp.user_msg)
    new_messages = list(inp.messages)
    if new_messages and new_messages[-1].get("role") == "user":
        last = new_messages[-1]
        if isinstance(last.get("content"), str):
            new_messages[-1] = {"role": "user", "content": new_um}
    return LLMInput(
        system=inp.system,
        user_msg=new_um,
        tool_specs=inp.tool_specs,
        messages=new_messages,
        meta={**inp.meta, "variant_applied": "trim_sample_rows"},
    )
