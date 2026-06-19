"""resolve_presentation_contracts_node (2026-06-17, ENABLE_PRESENTATION_LOOKAHEAD).

Root problem: a handling/transform phase (p2) runs BEFORE the presentation
phase (p3), so the agent shaping data in p2 has no concrete target — it only
discovers what the chart/verdict block needs when it `inspect_block_doc`s in
p3, too late. Result: vague "transform" → spin.

This node runs ONCE after plan-confirm. For each presentation phase it resolves
the likely presentation block, reads that block's `## Inputs` contract (already
authored in block_docs.markdown), and stamps it onto the upstream handling
phase (and the present phase itself) so the agent aims at a concrete output
shape — the same "work backward from the target's contract" move a strong agent
makes implicitly, made explicit for a weaker model.

The contract is a HINT injected into the observation, never a hard constraint
and never a mutation of the (intent-only) plan goal — so a wrong resolution
degrades to today's behaviour, no worse.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
from python_ai_sidecar.feature_flags import is_presentation_lookahead_enabled

logger = logging.getLogger(__name__)

# Phase kinds that present/judge a result (need a shaped input). raw_data is the
# source; transform is the handling we want to aim. alarm/verdict/table/scalar/
# chart all consume a shaped dataframe.
PRESENT_KINDS = frozenset({"chart", "table", "scalar", "verdict", "alarm"})
_HANDLING_KIND = "transform"
_MAX_INPUTS_CHARS = 1200
_MAX_CANDIDATES = 15


# ── pure helpers (unit-tested) ──────────────────────────────────────────────


def _present_phase_indices(phases: list[dict]) -> list[int]:
    return [
        i for i, p in enumerate(phases)
        if (p.get("expected") or "").strip() in PRESENT_KINDS
    ]


def _contract_target_phase_ids(phases: list[dict], present_idx: int) -> list[str]:
    """Where to surface the present block's contract:
      - the nearest preceding transform phase (the real handling target), and
      - the present phase itself (it often builds filter→chart in one phase).
    Returns ids in upstream-first order, deduped."""
    out: list[str] = []
    for j in range(present_idx - 1, -1, -1):
        if (phases[j].get("expected") or "").strip() == _HANDLING_KIND:
            out.append(phases[j].get("id"))
            break  # nearest only
    pid = phases[present_idx].get("id")
    if pid and pid not in out:
        out.append(pid)
    return [p for p in out if p]


def _extract_inputs_section(markdown: str) -> str:
    """Pull the `## Input(s)` section (up to the next `## ` header) from a
    block-doc markdown. Returns '' if no such section."""
    if not markdown:
        return ""
    lines = markdown.splitlines()
    start = None
    for i, ln in enumerate(lines):
        s = ln.strip().lower()
        if s.startswith("## input"):
            start = i
            break
    if start is None:
        return ""
    body = [lines[start]]
    for ln in lines[start + 1:]:
        if ln.strip().startswith("## "):
            break
        body.append(ln)
    return "\n".join(body).strip()


def _render_contract(block_name: str, inputs_md: str, present_goal: str) -> str:
    inputs = inputs_md.strip()
    if len(inputs) > _MAX_INPUTS_CHARS:
        inputs = inputs[:_MAX_INPUTS_CHARS] + "\n…(完整見 inspect_block_doc)"
    return (
        "== DOWNSTREAM CONTRACT (此 phase 要產出「下游呈現步驟吃得下」的形狀) ==\n"
        f"下游呈現步驟（{present_goal[:60]}）預計使用 **{block_name}**，"
        "它需要的輸入契約如下：\n\n"
        f"{inputs}\n\n"
        "→ 你這個 phase 的目標：把資料轉成上面這個形狀（必要欄位齊、格式對），"
        "下游 block 才接得上。**這是 hint 不是硬限制**；若你判斷下游會用別的 block，"
        "以實際需求為準。"
    )


# ── I/O helpers ─────────────────────────────────────────────────────────────


def _candidate_present_blocks(expected: str) -> list[tuple[str, str]]:
    """[(block_name, one-line desc)] for blocks whose covers_output includes
    `expected`. Mirrors _build_matching_blocks_section's selection."""
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
    from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import (
        _resolve_covers,
    )
    import re

    registry = SeedlessBlockRegistry()
    registry.load()
    out: list[tuple[str, str]] = []
    for (name, _v), spec in registry.catalog.items():
        if str(spec.get("status") or "").lower() == "deprecated":
            continue
        if expected not in _resolve_covers(spec, kind="output"):
            continue
        desc = (spec.get("description") or "").strip()
        m = re.search(r"== What ==\s*\n+(.+?)(?:\n\n|\n==)", desc, re.DOTALL)
        first = (m.group(1).strip().split("\n")[0] if m
                 else desc.split("\n", 1)[0])[:90]
        out.append((name, first))
    out.sort(key=lambda t: t[0])
    return out[:_MAX_CANDIDATES]


_RESOLVE_SYSTEM = (
    "你是 pipeline 的 present-block 選擇器。根據 phase 目標，從候選 present block "
    "清單裡選**一個**最適合產出該目標的 block。只回 JSON：{\"block\": \"block_xxx\"}，"
    "block 必須是清單裡的名稱，不要解釋。"
)


async def _resolve_present_block(goal: str, candidates: list[tuple[str, str]]) -> str:
    """LLM-pick the single best present block for this phase goal. Single
    candidate → no LLM call. Falls back to the first candidate on any failure."""
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0][0]
    names = {c[0] for c in candidates}
    listing = "\n".join(f"  {n}  -- {d}" for n, d in candidates)
    try:
        client = get_llm_client()
        resp = await client.create(
            system=_RESOLVE_SYSTEM,
            messages=[{"role": "user",
                       "content": f"Phase 目標: {goal}\n\n候選 present blocks:\n{listing}"}],
            max_tokens=80,
        )
        raw = (resp.text or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[raw.find("{"):]
        block = (json.loads(raw) or {}).get("block", "")
        if block in names:
            return block
        logger.info("present-block resolver: LLM returned %r not in candidates — fallback", block)
    except Exception as ex:  # noqa: BLE001 — never break the build
        logger.info("present-block resolver failed (%s) — fallback to first candidate", ex)
    return candidates[0][0]


async def resolve_presentation_contracts_node(state: BuildGraphState) -> dict[str, Any]:
    """Resolve each presentation phase's input contract and stamp it on the
    upstream handling phase. No-op unless ENABLE_PRESENTATION_LOOKAHEAD."""
    if not is_presentation_lookahead_enabled():
        return {}
    from python_ai_sidecar.agent_builder.tools import _fetch_block_doc_markdown

    phases = state.get("v30_phases") or []
    contracts: dict[str, str] = {}
    for i in _present_phase_indices(phases):
        ph = phases[i]
        expected = (ph.get("expected") or "").strip()
        goal = ph.get("goal") or ""
        candidates = _candidate_present_blocks(expected)
        if not candidates:
            continue
        block = await _resolve_present_block(goal, candidates)
        if not block:
            continue
        try:
            md = await _fetch_block_doc_markdown(block)
        except Exception as ex:  # noqa: BLE001
            logger.info("contract: doc fetch failed for %s (%s)", block, ex)
            continue
        inputs = _extract_inputs_section(md)
        if not inputs:
            continue
        contract_md = _render_contract(block, inputs, goal)
        for pid in _contract_target_phase_ids(phases, i):
            contracts.setdefault(pid, contract_md)

    if not contracts:
        return {}
    logger.info("presentation_lookahead: resolved contracts for phases %s",
                list(contracts.keys()))
    return {"v30_phase_contracts": contracts}
