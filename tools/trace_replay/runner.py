"""Replay runner — execute LLMInput against the live LLM provider and
extract a normalized ReplayResult.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .types import LLMInput, ReplayResult


def get_system_and_tools_for_node(node: str) -> tuple[str, list[dict] | None]:
    """Per-node sidecar resources. Trace doesn't store these (system text
    is large + static; tool specs are static). Loaded at replay time so
    the variant runs against whatever sidecar code is currently checked
    out — useful for "would my proposed prompt change actually help?"
    """
    if node == "agentic_phase_loop":
        from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
            _SYSTEM, _build_tool_specs,
        )
        return _SYSTEM, _build_tool_specs()
    if node == "goal_plan_node":
        from python_ai_sidecar.agent_builder.graph_build.nodes.goal_plan import _SYSTEM
        return _SYSTEM, None
    if node == "phase_revise_node":
        # phase_revise uses its own prompt; tools=None (pure JSON response)
        try:
            from python_ai_sidecar.agent_builder.graph_build.nodes.phase_revise import _SYSTEM
            return _SYSTEM, None
        except (ImportError, AttributeError):
            return "", None
    # Unknown — return empty system. Variant runner will warn.
    return "", None


async def run_replay(inp: LLMInput) -> ReplayResult:
    """Execute one LLM call and normalize the result."""
    from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

    client = get_llm_client()
    variant_name = inp.meta.get("variant_applied") or "identity"
    rep = inp.meta.get("rep", 0)
    t0 = time.perf_counter()

    try:
        kwargs: dict[str, Any] = {
            "system": inp.system,
            "messages": inp.messages or [{"role": "user", "content": inp.user_msg}],
            "max_tokens": 2048,
        }
        if inp.tool_specs:
            kwargs["tools"] = inp.tool_specs
        resp = await client.create(**kwargs)
    except Exception as ex:  # noqa: BLE001
        return ReplayResult(
            variant=variant_name, rep=rep,
            tool=None, picked=None, tool_input=None, text_blocks=[],
            duration_ms=int((time.perf_counter() - t0) * 1000),
            error=f"{type(ex).__name__}: {ex}",
        )

    content = getattr(resp, "content", None) or []
    text_blocks: list[str] = []
    tool_name = None
    tool_input = None
    for blk in content:
        btype = getattr(blk, "type", None) or (
            blk.get("type") if isinstance(blk, dict) else None
        )
        if btype == "text":
            t = getattr(blk, "text", None) or (
                blk.get("text") if isinstance(blk, dict) else None
            )
            if t:
                text_blocks.append(str(t))
        elif btype == "tool_use":
            tool_name = getattr(blk, "name", None) or (
                blk.get("name") if isinstance(blk, dict) else None
            )
            tool_input = getattr(blk, "input", None) or (
                blk.get("input") if isinstance(blk, dict) else None
            )

    picked = _normalize_picked(tool_name, tool_input)
    return ReplayResult(
        variant=variant_name, rep=rep,
        tool=tool_name, picked=picked, tool_input=tool_input,
        text_blocks=text_blocks,
        duration_ms=int((time.perf_counter() - t0) * 1000),
        input_tokens=getattr(resp, "input_tokens", None),
        output_tokens=getattr(resp, "output_tokens", None),
    )


def _normalize_picked(tool_name: str | None, tool_input: dict | None) -> str | None:
    """Convert tool_use into a comparable string. add_node -> block_name;
    inspect_block_doc -> "inspect:block_id"; etc.
    """
    if tool_name is None:
        return None
    if not isinstance(tool_input, dict):
        return tool_name
    if tool_name == "add_node":
        return tool_input.get("block_name") or tool_input.get("block")
    if tool_name == "inspect_block_doc":
        return f"inspect:{tool_input.get('block_id')}"
    if tool_name == "inspect_node_output":
        return f"inspect_node:{tool_input.get('node_id')}"
    if tool_name == "connect":
        return f"connect:{tool_input.get('from_node')}->{tool_input.get('to_node')}"
    if tool_name == "phase_complete":
        return "phase_complete"
    return tool_name


async def run_experiment(
    base_input: LLMInput,
    variants: list[tuple[str, Any]],
    reps: int,
) -> list[ReplayResult]:
    """Run each variant × reps. Sequential (Anthropic rate limits + clean
    log order). variants is [(name, callable_variant), ...].
    """
    results: list[ReplayResult] = []
    for rep in range(1, reps + 1):
        for name, variant_fn in variants:
            variant_input = variant_fn(base_input)
            variant_input.meta["variant_applied"] = name
            variant_input.meta["rep"] = rep
            print(f"  [{name} rep{rep}] calling LLM...", flush=True)
            r = await run_replay(variant_input)
            picked_str = r.picked or "(none)"
            err = f" ERROR={r.error}" if r.error else ""
            print(
                f"  [{name} rep{rep}] tool={r.tool} picked={picked_str} "
                f"dur={r.duration_ms}ms in={r.input_tokens} out={r.output_tokens}{err}",
                flush=True,
            )
            results.append(r)
    return results
