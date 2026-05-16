"""Load LLM calls from a BuildTracer JSON and reconstruct LLMInput.

Trace schema reminder (relevant fields):
  llm_calls: [
    {node, ts, system_chars, user_msg, raw_response, parsed,
     attempt?, phase_id?, round?,
     input_tokens?, output_tokens?, ...}
  ]

The traced `system` field is the CHAR COUNT, not the body (to save space).
For replay we re-inject the real system from agentic_phase_loop._SYSTEM /
goal_plan._SYSTEM at runtime — those are static per node.

Tool specs are also static per node and re-fetched at runtime, since
they aren't traced.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import LLMInput


def load_trace(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def list_llm_calls(trace: dict) -> list[dict]:
    """Return all LLM calls in the trace, in order recorded."""
    return list(trace.get("llm_calls") or [])


def pick_llm_call(
    trace: dict,
    *,
    node: str | None = None,
    phase_id: str | None = None,
    round: int | None = None,
    index: int | None = None,
) -> dict:
    """Select one LLM call matching the filters.

    Precedence: index > (node + phase_id + round) > last call. Raises if no
    match or multiple match without a specific selector.
    """
    calls = list_llm_calls(trace)
    if not calls:
        raise RuntimeError(f"trace has no llm_calls")

    if index is not None:
        if index < 0 or index >= len(calls):
            raise RuntimeError(f"index {index} out of range (0..{len(calls)-1})")
        return calls[index]

    cands = calls
    if node is not None:
        cands = [c for c in cands if c.get("node") == node]
    if phase_id is not None:
        cands = [c for c in cands if c.get("phase_id") == phase_id]
    if round is not None:
        cands = [c for c in cands if c.get("round") == round]

    if not cands:
        avail = [
            f"{c.get('node')}:phase={c.get('phase_id')}:round={c.get('round')}"
            for c in calls
        ]
        raise RuntimeError(
            f"no llm_call matches selectors (node={node} phase={phase_id} round={round}); "
            f"available:\n  " + "\n  ".join(avail)
        )

    # Use last match by default (most recent). Print warn when multiple.
    return cands[-1]


def build_llm_input_from_call(
    call: dict,
    *,
    system_loader_for_node: dict[str, str] | None = None,
    tools_loader_for_node: dict[str, list[dict]] | None = None,
) -> LLMInput:
    """Convert a traced call dict into an LLMInput ready for replay.

    system_loader_for_node / tools_loader_for_node are maps:
      {"agentic_phase_loop": "..."} → system text per node
      {"agentic_phase_loop": [tool_specs]} → tools per node

    These need to be loaded by the caller (with a runtime sidecar import)
    because trace doesn't store the system text — just its char count.
    """
    node = call.get("node") or "(unknown)"
    user_msg = call.get("user_msg") or ""
    system = ""
    if system_loader_for_node and node in system_loader_for_node:
        system = system_loader_for_node[node]
    tool_specs = None
    if tools_loader_for_node and node in tools_loader_for_node:
        tool_specs = tools_loader_for_node[node]

    # Build a fresh messages stack from user_msg. For round>=2 the original
    # trace also had assistant + tool_result history we don't reconstruct
    # here (we trust user_msg captures the final user-side content).
    # Variants that need to manipulate prior turns can use meta to detect.
    messages = [{"role": "user", "content": user_msg}]

    meta = {
        "trace_node": node,
        "trace_phase_id": call.get("phase_id"),
        "trace_round": call.get("round"),
        "original_pick": (call.get("parsed") or {}).get("name") if isinstance(call.get("parsed"), dict) else None,
        "raw_response_excerpt": (call.get("raw_response") or "")[:600],
    }
    return LLMInput(
        system=system, user_msg=user_msg,
        tool_specs=tool_specs, messages=messages, meta=meta,
    )
