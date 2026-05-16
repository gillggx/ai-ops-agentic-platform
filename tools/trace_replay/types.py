"""Shared dataclasses for trace_replay."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class LLMInput:
    """Snapshot of an LLM call extracted from a trace OR transformed by a
    variant. All fields are independently mutable. `meta` carries trace
    context (node, phase_id, round) so variants can be context-aware
    (e.g. find current phase in observation_md).
    """
    system: str
    user_msg: str
    # Tool schemas the original call used. For phase loop calls these are
    # the agentic toolset (inspect_node_output / add_node / etc.). Variants
    # usually leave this alone.
    tool_specs: list[dict] | None = None
    # The full Anthropic `messages` history (for round>=2 in phase loop the
    # original call replayed tool_result history). For round 1 / goal_plan
    # this is just [{"role":"user","content": user_msg}].
    messages: list[dict] = field(default_factory=list)
    # Original trace context — variants read but should not write
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayResult:
    """One LLM round-trip outcome."""
    variant: str
    rep: int
    tool: str | None
    picked: str | None              # block_name / inspect:block_id / None
    tool_input: dict | None
    text_blocks: list[str]
    duration_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None


# Variant signature: take an LLMInput and return a (possibly) modified one.
# Pure function — must NOT mutate the input.
Variant = Callable[[LLMInput], LLMInput]
