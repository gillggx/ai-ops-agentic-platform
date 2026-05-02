"""Builder Mode Block Advisor — answers block-related questions inside the
Pipeline Builder Glass Box without entering the build flow.

Architecture (SPEC v2 — flow in graph, LLM only thinks):

    user_message
        ↓
    [Node 1] classify_intent → BUILD | EXPLAIN | COMPARE | RECOMMEND | AMBIGUOUS
        ↓
        ├─ BUILD       → caller falls back to stream_agent_build (no advisor)
        ├─ EXPLAIN     → extract_block_target → java.get_block_by_name → synthesize_explain
        ├─ COMPARE     → extract_block_targets → java.list_blocks (filter) → synthesize_compare
        ├─ RECOMMEND   → extract_use_case_keywords → registry.search → synthesize_recommend
        └─ AMBIGUOUS   → emit clarification message (no LLM call)

Each node is a pure function. The LLM only does (a) classification,
(b) parameter extraction, (c) answer synthesis — never decides which
node to run next. That's the graph's job.

Source-of-truth: every block fact comes from Java /internal/blocks at
call time (NOT the boot-time BlockRegistry snapshot, NOT hard-coded in
prompts). See CLAUDE.md "MCP / Skill 的 Description 是唯一的文件來源".
"""

from python_ai_sidecar.agent_builder.advisor.graph import (
    AdvisorIntent,
    classify_advisor_intent,
    stream_block_advisor,
)

__all__ = [
    "AdvisorIntent",
    "classify_advisor_intent",
    "stream_block_advisor",
]
