"""v6.2 (2026-05-20) — tool-using doc Q&A agent.

Replaces the graph-based advisor (classifier → extractor → fetcher →
synthesize) for EXPLAIN / COMPARE / RECOMMEND intents with a single
Anthropic tool-use loop. LLM decides which doc to fetch instead of
pre-fetching the entire catalog.

Why: see project_rag_for_llm_lookups.md — "棄死板 push 全清單, 改 LLM
主動 query". Also lets admin-edited block_docs.markdown surface in
answers automatically (inspect_block_doc tool reads DB markdown).

KNOWLEDGE intent stays on the old fast path (pure LLM, no fetch).
AMBIGUOUS stays on the old "ask user to clarify" path.
"""
from python_ai_sidecar.agent_builder.advisor_v2.loop import (
    stream_doc_qa_agent,
)

__all__ = ["stream_doc_qa_agent"]
