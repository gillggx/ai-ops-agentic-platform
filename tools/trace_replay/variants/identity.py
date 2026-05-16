"""identity variant — control. Returns input unchanged."""
from __future__ import annotations

from ..types import LLMInput


def identity(inp: LLMInput) -> LLMInput:
    """Pass-through. Used as the control variant for A/B comparisons."""
    return LLMInput(
        system=inp.system, user_msg=inp.user_msg,
        tool_specs=inp.tool_specs,
        messages=list(inp.messages),
        meta=dict(inp.meta),
    )
