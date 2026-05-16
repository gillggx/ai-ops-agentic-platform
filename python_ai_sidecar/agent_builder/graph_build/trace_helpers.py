"""v30.1.1 trace helpers — feed decision_records with empathetic-debug
information that's NOT visible from raw LLM I/O alone.

These functions compute server-side what blocks WOULD have satisfied a
phase, what text the LLM emitted alongside its tool call, and how to
present the observation as structured sections (rather than one big
opaque string). Used by agentic_phase_loop, phase_verifier, goal_plan.
"""
from __future__ import annotations

import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


def compute_phase_candidates(
    phase: dict,
    remaining_phases: list[dict],
    registry: Any,
) -> dict[str, Any]:
    """Server-side enumeration: which blocks COULD have satisfied this phase,
    and which of those would also fast-forward through the next N phases.

    Returns:
      {
        "phase_id": str,
        "phase_expected": str,
        "candidates": [
          {"block": "block_spc_panel", "covers": ["raw_data","verdict","chart"],
           "matches_phase_expected": True,
           "would_fast_forward_through": ["p4","p5"]},
          ...
        ],
        "fast_forward_capable": ["block_spc_panel"]   # subset that does FF
      }

    A block is a candidate if:
      - it's not deprecated
      - its `produces.covers` (or inferred fallback) includes phase.expected

    `would_fast_forward_through` lists phase ids beyond the current phase
    whose `expected` is ALSO in this block's covers. Empty list = block
    only satisfies current phase. Non-empty = picking this block triggers
    multi-phase advancement.
    """
    from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import (
        _resolve_covers,
    )

    expected = (phase.get("expected") or "").strip()
    if not expected:
        return {"phase_id": phase.get("id"), "phase_expected": expected,
                "candidates": [], "fast_forward_capable": []}

    candidates: list[dict[str, Any]] = []
    fast_fwd_blocks: list[str] = []

    catalog = getattr(registry, "catalog", {}) or {}
    for (name, _version), spec in catalog.items():
        if str(spec.get("status") or "").lower() == "deprecated":
            continue
        # v30.5: use covers_output (aligned with verifier + section)
        covers = _resolve_covers(spec, kind="output")
        if expected not in covers:
            continue

        # Walk remaining phases; record which can ALSO be covered
        ff_through: list[str] = []
        for nxt in remaining_phases:
            nxt_exp = (nxt.get("expected") or "").strip()
            if nxt_exp and nxt_exp in covers:
                ff_through.append(nxt.get("id"))
            else:
                break  # contiguous-only fast-forward (matches verifier logic)

        candidates.append({
            "block": name,
            "covers": covers,
            "matches_phase_expected": True,
            "would_fast_forward_through": ff_through,
        })
        if ff_through:
            fast_fwd_blocks.append(name)

    # Sort: fast-forward capable first (more coverage = more useful), then
    # by block name for stable diffs.
    candidates.sort(
        key=lambda c: (-len(c["would_fast_forward_through"]), c["block"])
    )

    return {
        "phase_id": phase.get("id"),
        "phase_expected": expected,
        "candidates": candidates,
        "fast_forward_capable": fast_fwd_blocks,
    }


def extract_llm_text_blocks(resp: Any) -> list[str]:
    """Pull text-content blocks from an Anthropic response (which can mix
    text + tool_use). Returns the reasoning text the LLM wrote BEFORE its
    tool_use, if any. Empty list when LLM emitted tool_use only.

    Key for debug: shows the LLM's stated reason for its action choice,
    not just the action itself.
    """
    out: list[str] = []
    content = getattr(resp, "content", None) or []
    if not isinstance(content, list):
        return out
    for blk in content:
        btype = getattr(blk, "type", None) or (
            blk.get("type") if isinstance(blk, dict) else None
        )
        if btype == "text":
            text = getattr(blk, "text", None) or (
                blk.get("text") if isinstance(blk, dict) else None
            )
            if text:
                out.append(str(text))
    return out


def build_decision_metadata(
    phase: dict,
    remaining_phases: list[dict],
    registry: Any,
    actual_pick_block: Optional[str],
) -> dict[str, Any]:
    """Convenience: combine phase_candidates with actual LLM pick to produce
    the full decision_metadata block. Returns dict ready for
    tracer.record_decision(decision_metadata=...).

    actual_pick_block: the block_name LLM picked via add_node, or None
                       (inspect_*, phase_complete, connect, etc.).
    """
    pc = compute_phase_candidates(phase, remaining_phases, registry)
    candidates = pc["candidates"]
    candidate_names = {c["block"] for c in candidates}
    in_candidates = (
        actual_pick_block is not None and actual_pick_block in candidate_names
    )

    # If LLM picked something, find which fast-forward chain (if any) it
    # missed by NOT picking a fast-forward-capable block.
    missed: list[str] = []
    if actual_pick_block is not None and not in_candidates:
        # LLM picked off-list — every FF-capable candidate's chain is missed
        for c in candidates:
            if c["would_fast_forward_through"]:
                missed = c["would_fast_forward_through"]
                break  # report the top one (already sorted by FF length)
    elif actual_pick_block is not None and in_candidates:
        # LLM picked a candidate. Did they pick a non-FF one when FF was available?
        picked = next((c for c in candidates if c["block"] == actual_pick_block), None)
        if picked and not picked["would_fast_forward_through"]:
            for c in candidates:
                if c["would_fast_forward_through"]:
                    missed = c["would_fast_forward_through"]
                    break

    return {
        "phase_id": pc["phase_id"],
        "phase_expected": pc["phase_expected"],
        "candidates_could_have_picked": candidates,
        "fast_forward_capable_blocks": pc["fast_forward_capable"],
        "actual_pick": actual_pick_block,
        "actual_pick_in_candidates": in_candidates,
        "potential_fast_forward_missed": missed,
    }


def structure_user_msg_sections(
    *,
    current_phase: dict,
    all_phases: list[dict],
    current_idx: int,
    declared_inputs: list[dict],
    exec_trace: dict[str, dict],
    recent_actions: list[dict],
    catalog_brief_text: str,
    instruction: str,
) -> dict[str, Any]:
    """Same content that _build_observation_md renders into a string, but
    as structured dict for trace. Mirrors the prompt builder.

    Why a separate function and not refactor _build_observation_md to return
    dict? Because the LLM still needs the string. We dual-emit: prompt sees
    the rendered string; trace stores the dict. Drift risk is acceptable
    given trace is a debug aide, not a contract.
    """
    return {
        "current_phase": {
            "id": current_phase.get("id"),
            "goal": current_phase.get("goal"),
            "expected": current_phase.get("expected"),
            "expected_output": current_phase.get("expected_output"),
            "why": current_phase.get("why"),
        },
        "all_phases_context": [
            {
                "id": p.get("id"),
                "goal": p.get("goal"),
                "expected": p.get("expected"),
                "is_current": i == current_idx,
            }
            for i, p in enumerate(all_phases)
        ],
        "available_inputs": {
            "declared_inputs": list(declared_inputs or []),
            "canvas_nodes": [
                {
                    "logical_id": lid,
                    "block_id": (snap or {}).get("block_id"),
                    "rows": (snap or {}).get("rows"),
                    "cols_count": len((snap or {}).get("cols") or []),
                }
                for lid, snap in (exec_trace or {}).items()
                if isinstance(snap, dict)
            ],
        },
        "actions_this_phase": [
            {
                "tool": a.get("tool"),
                "args_summary": a.get("args_summary"),
                "result_digest_preview": (a.get("result_digest") or "")[:200],
            }
            for a in (recent_actions or [])[-8:]
        ],
        "catalog_brief_chars": len(catalog_brief_text or ""),
        "instruction_preview": (instruction or "")[:600],
    }
