"""catalog_brief variants — modify the AVAILABLE BLOCKS section.

`enrich_catalog_brief` adds a `[1-BLOCK covers N: kind1+kind2+...]` prefix
to every block whose `produces.covers` length >= 2 (composite blocks like
spc_panel / apc_panel / step_check). This was the first hypothesis tested
on 2026-05-16; 3-rep A/B showed it did NOT change LLM behaviour because
the phase goal text dominates. Kept in the registry as a reference variant.
"""
from __future__ import annotations

import re

from ..types import LLMInput


_CATALOG_PAT = re.compile(
    r"(== AVAILABLE BLOCKS [^\n]*\n)(.*?)(\nWhen you call add_node)",
    re.DOTALL,
)


def enrich_catalog_brief(inp: LLMInput) -> LLMInput:
    new_brief = _build_enriched_brief()
    new_user_msg = _CATALOG_PAT.sub(
        lambda m: m.group(1) + new_brief + m.group(3),
        inp.user_msg,
        count=1,
    )
    new_messages = [
        m if m.get("role") != "user" else {**m, "content": new_user_msg}
        for m in inp.messages
    ]
    # Only rewrite the LAST user message (most recent observation)
    if inp.messages and new_messages[-1].get("role") == "user":
        new_messages[-1] = {"role": "user", "content": new_user_msg}
    return LLMInput(
        system=inp.system, user_msg=new_user_msg,
        tool_specs=inp.tool_specs, messages=new_messages,
        meta={**inp.meta, "variant_applied": "enrich_catalog_brief"},
    )


def _build_enriched_brief() -> str:
    """Rebuild catalog brief with composite-block prefix."""
    from python_ai_sidecar.pipeline_builder.seedless_registry import (
        SeedlessBlockRegistry,
    )
    from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import (
        _infer_covers_from_block_spec,
    )

    registry = SeedlessBlockRegistry()
    registry.load()

    by_cat: dict[str, list[str]] = {}
    for (name, _v), spec in registry.catalog.items():
        if str(spec.get("status") or "").lower() == "deprecated":
            continue
        cat = spec.get("category") or "transform"
        desc = spec.get("description") or ""
        m = re.search(r"== What ==\s*\n+(.+?)(?:\n\n|\n==)", desc, re.DOTALL)
        what_line = (
            m.group(1).strip().split("\n")[0][:90] if m
            else desc.split("\n", 1)[0][:90]
        )
        produces = spec.get("produces") or {}
        covers = list(produces.get("covers") or [])
        if not covers:
            covers = _infer_covers_from_block_spec(spec)
        prefix = (
            f"[1-BLOCK covers {len(covers)}: {'+'.join(covers)}] "
            if len(covers) >= 2 else ""
        )
        by_cat.setdefault(cat, []).append(f"  {name}  -- {prefix}{what_line}")

    lines: list[str] = []
    for cat in sorted(by_cat.keys()):
        lines.append(f"[{cat}]")
        for entry in sorted(by_cat[cat]):
            lines.append(entry)
        lines.append("")
    return "\n".join(lines)
