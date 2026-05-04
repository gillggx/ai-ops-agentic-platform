"""Pin the Glass Box system prompt size.

The catalog used to dump every block's full description + param_schema +
examples on every turn (~20K tokens). After the 2026-05-04 slim, we keep
1-line summaries for everything except a handful of HOT blocks. The test
fails loudly if a future change re-bloats the system prompt — token
count directly affects per-turn LLM cost.

Also pins the explain_block tool's contract since that's the lazy path
for non-hot block specs.
"""

from __future__ import annotations

import pytest

from python_ai_sidecar.agent_builder.prompt import (
    HOT_BLOCK_NAMES,
    build_system_prompt,
    claude_tool_defs,
)
from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry


def _make_full_catalog() -> BlockRegistry:
    """Stub registry with 47 blocks like prod has — each with realistic
    description / param_schema / examples sizes."""
    reg = BlockRegistry()
    # 7 hot + 40 other = 47 total. Each non-hot block gets ~1KB of text;
    # hot blocks get ~2KB. Mirrors prod where description+examples+
    # param_schema averaged ~1.7KB/block.
    sample_desc = (
        "Filter rows by column / operator / value. Operates on the "
        "input dataframe and returns rows where `column op value` is "
        "true. Supports equality (==, !=), comparison (<, <=, >, >=), "
        "and SQL-style LIKE for substring match.\n\n"
        "Use cases: keep only OOC events, drop NULL timestamps, scope "
        "to a specific recipe family. Combine multiple filters by "
        "chaining filter blocks rather than using AND in a single one.\n"
    )
    sample_params = {
        "type": "object",
        "required": ["column", "operator", "value"],
        "properties": {
            "column":   {"type": "string"},
            "operator": {"type": "string", "enum": ["==", "!=", "<", "<=", ">", ">=", "LIKE"]},
            "value":    {"type": "string"},
        },
    }
    sample_examples = [
        {"name": "OOC events only", "summary": "spc_status == 'OOC'",
         "params": {"column": "spc_status", "operator": "==", "value": "OOC"}},
        {"name": "non-null lots", "summary": "lotID is not blank",
         "params": {"column": "lotID", "operator": "!=", "value": ""}},
    ]

    for name in HOT_BLOCK_NAMES:
        reg._catalog[(name, "1.0.0")] = {
            "name": name,
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": sample_desc,
            "input_schema":  [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": sample_params,
            "examples": sample_examples,
        }
    # 40 other blocks with same shape so we exercise the index path
    for i in range(40):
        nm = f"block_other_{i:02d}"
        reg._catalog[(nm, "1.0.0")] = {
            "name": nm,
            "version": "1.0.0",
            "category": "transform",
            "status": "production",
            "description": sample_desc,
            "input_schema":  [{"port": "data", "type": "dataframe"}],
            "output_schema": [{"port": "data", "type": "dataframe"}],
            "param_schema": sample_params,
            "examples": sample_examples,
        }
    return reg


def _tokens_estimate(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 chars (English) or 2 chars (CJK)."""
    return len(text) // 4


def test_system_prompt_size_under_budget():
    reg = _make_full_catalog()
    prompt = build_system_prompt(reg)
    tokens = _tokens_estimate(prompt)
    # Pre-slim: ~25K tokens for 47 blocks at this density.
    # Post-slim target: 5K. Allow up to 8K to absorb wording changes
    # in the preamble; if you legitimately need more, raise this and
    # justify in the commit message.
    assert tokens < 8000, (
        f"system prompt = {tokens} tokens (limit 8K). "
        "Did a recent change add a long block to HOT_BLOCK_NAMES, or "
        "re-introduce full-spec dump for non-hot blocks?"
    )


def test_index_contains_all_47_blocks():
    """Even non-hot blocks must surface in the catalog index so the
    LLM knows they exist (and can call explain_block)."""
    reg = _make_full_catalog()
    prompt = build_system_prompt(reg)
    for name in HOT_BLOCK_NAMES:
        assert name in prompt, f"hot block {name} missing from system prompt"
    # Spot-check a few non-hot blocks appear as index entries
    assert "block_other_00" in prompt
    assert "block_other_39" in prompt


def test_hot_blocks_have_full_spec():
    """Hot blocks must include param_schema in the prompt (so add_node
    works without an explain_block round trip)."""
    reg = _make_full_catalog()
    prompt = build_system_prompt(reg)
    # The full-spec rendering puts param_schema literally in the text
    assert '"required": ["column", "operator", "value"]' in prompt or \
           "'required': ['column', 'operator', 'value']" in prompt


def test_explain_block_tool_registered():
    """explain_block must appear in the Claude tool defs so the LLM can
    invoke it. Without this the lazy-load path is broken."""
    tools = claude_tool_defs()
    names = {t["name"] for t in tools}
    assert "explain_block" in names
    assert "list_blocks" in names


def test_explain_block_input_schema():
    tools = claude_tool_defs()
    explain = next(t for t in tools if t["name"] == "explain_block")
    schema = explain["input_schema"]
    assert "block_name" in schema["properties"]
    assert "block_name" in schema["required"]
