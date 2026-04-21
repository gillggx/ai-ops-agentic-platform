"""LLM client façade.

Phase 5b ships a **stub** that echoes back the prompt — good enough to verify
graph plumbing + SSE streaming without burning API credit. Production drops
in a real OpenAI / Bedrock / Anthropic client behind ``LLM_PROVIDER``.

Swap surface:
    await llm_stream(system, user_msg)   ->  AsyncIterator[str]  (tokens)
    await llm_complete(system, user_msg) ->  str                 (full reply)

Real implementations should honour the same signature.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncIterator

log = logging.getLogger("python_ai_sidecar.llm")


def _stub_reply(user_msg: str) -> str:
    head = user_msg.strip().replace("\n", " ")
    if len(head) > 200:
        head = head[:200] + "…"
    return f"(stub LLM reply) received: {head}"


async def llm_stream(system: str, user_msg: str) -> AsyncIterator[str]:
    """Yields tokens one at a time — shape-compatible with streaming LLM APIs."""
    provider = os.getenv("LLM_PROVIDER", "stub").lower()
    if provider != "stub":
        log.warning("LLM_PROVIDER=%s but only 'stub' is wired in phase 5b; falling back", provider)

    reply = _stub_reply(user_msg)
    for token in reply.split(" "):
        await asyncio.sleep(0.02)
        yield token + " "


async def llm_complete(system: str, user_msg: str) -> str:
    chunks = []
    async for tok in llm_stream(system, user_msg):
        chunks.append(tok)
    return "".join(chunks).strip()
