"""Shared agent_knowledge injection for planner nodes.

Two layers (per CLAUDE.md: knowledge lives in DB agent_knowledge, retrieved
via pgvector cosine — never hardcoded into prompts):

  Layer 1 (always-on): every priority='high' global entry. First-principle
    rules ("SPC is station-level", "參數分佈 chart 用 flat-mode 別 unnest")
    that must reach the planner regardless of RAG recall — Cohere multilingual
    recall on long Chinese queries is patchy.
  Layer 2 (RAG bonus): cosine-similar entries for the specific instruction.

Originally lived inline in plan_node (v27 path). Extracted 2026-06-12 so the
v30 builder's goal_plan_node can reuse it — agent_knowledge was previously
dead weight for the v30 path (goal_plan_node never injected it). Gated by
ENABLE_PLAN_KNOWLEDGE so the wiring can be A/B'd.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def build_knowledge_hint(
    instruction: str, *, user_id: int = 1, source: str = "plan",
    layer: Optional[str] = None, always_only: bool = False,
    include_always_on: bool = True, rag_limit: int = 3,
) -> str:
    """Return a prompt-appendable knowledge block ("" on any failure).

    Best-effort: when Java / embedding is unreachable the result is empty and
    the caller proceeds exactly as before. Never raises.

    V58 — layer-aware retrieval (each agent layer gets its own slice):
      layer            : 'plan' | 'execute' | None — filter by applies_to.
      always_only      : Layer-1 fetch narrows to always_on=true (the core).
                         Plan path uses this (gated) to shrink the always-on
                         dump from "all high bodies" to "core + RAG".
      include_always_on: when False, SKIP Layer-1 entirely and return RAG only.
                         The execute path uses this — a source-block pick prompt
                         must stay lean (top-rag_limit RAG, no always-on dump).
      rag_limit        : Layer-2 top-K (execute uses a small K, e.g. 2).
    """
    try:
        from python_ai_sidecar.agent_orchestrator_v2.nodes.load_context import (
            _build_knowledge_block,
        )
        from python_ai_sidecar.clients.java_client import JavaAPIClient
        from python_ai_sidecar.config import CONFIG

        java = JavaAPIClient(
            CONFIG.java_api_url, CONFIG.java_internal_token,
            timeout_sec=CONFIG.java_timeout_sec,
        )
        sections: list[str] = []

        # Layer 1: always-on high-priority first-principle rules (layer-filtered).
        if include_always_on:
            try:
                hp_rows = await java.list_high_priority_knowledge(
                    user_id=user_id, limit=20, layer=layer, always_only=always_only,
                )
            except Exception as ex:  # noqa: BLE001
                logger.info("%s_node: high-priority knowledge fetch failed (%s)", source, ex)
                hp_rows = []
            if hp_rows:
                lines = ["## Domain first principles (always-on)"]
                for r in hp_rows:
                    lines.append(f"  ### {r.get('title','')}")
                    body = (r.get("body") or "").strip()
                    if body:
                        lines.append("\n".join(f"    {ln}" for ln in body.split("\n")))
                sections.append("\n".join(lines))

        # Layer 2: RAG-retrieved (cosine-matched) additional knowledge.
        try:
            rag_block = await _build_knowledge_block(
                java, user_id=user_id, query_text=instruction,
                skill_slug=None, tool_id=None, recipe_id=None,
                layer=layer, limit=rag_limit,
            )
            if rag_block:
                sections.append(rag_block)
        except Exception as ex:  # noqa: BLE001
            logger.info("%s_node: RAG knowledge fetch failed (%s)", source, ex)

        if sections:
            return "\n\n" + "\n\n".join(sections)
    except Exception as ex:  # noqa: BLE001
        logger.info("%s_node: knowledge retrieval skipped (%s)", source, ex)
    return ""
