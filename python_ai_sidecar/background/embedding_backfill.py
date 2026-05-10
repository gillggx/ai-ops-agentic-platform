"""Background task: backfill embeddings on agent_knowledge + agent_examples.

User creates a knowledge fact via UI → POST /api/v1/agent-knowledge → row
inserted with embedding=NULL. This task wakes periodically, fetches missing
rows from Java, embeds via Ollama, PUTs the vector back. Best-effort —
failures logged + retried next cycle.

Disabled by default; enable via env AGENT_KB_BACKFILL_ENABLED=1.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


_BACKFILL_INTERVAL_SEC = 30.0
_BATCH_LIMIT = 20


def _vec_to_pg_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


class EmbeddingBackfill:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if os.getenv("AGENT_KB_BACKFILL_ENABLED", "1") not in ("1", "true", "True"):
            logger.info("agent-knowledge embedding backfill disabled (AGENT_KB_BACKFILL_ENABLED!=1)")
            return
        if self._task is not None:
            return
        self._task = asyncio.ensure_future(self._loop())
        logger.info("agent-knowledge embedding backfill started (interval=%.0fs)", _BACKFILL_INTERVAL_SEC)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _loop(self) -> None:
        # Lazy imports — avoid circular deps + don't pay if disabled
        from python_ai_sidecar.clients.java_client import JavaAPIClient
        from python_ai_sidecar.config import CONFIG
        from python_ai_sidecar.agent_helpers_native.embedding_client import get_embedding_client

        java = JavaAPIClient(
            CONFIG.java_api_url, CONFIG.java_internal_token,
            timeout_sec=CONFIG.java_timeout_sec,
        )
        embedder = get_embedding_client()

        while not self._stop.is_set():
            try:
                # Knowledge
                kn_rows = await java.list_knowledge_missing_embeddings(limit=_BATCH_LIMIT)
                for row in kn_rows or []:
                    text = self._compose_text_kn(row)
                    if not text:
                        continue
                    try:
                        vec = await embedder.embed(text)
                        await java.put_knowledge_embedding(int(row["id"]), _vec_to_pg_literal(vec))
                        logger.info("backfilled knowledge embedding id=%s len=%d", row.get("id"), len(text))
                    except Exception as e:  # noqa: BLE001
                        logger.warning("knowledge embed failed id=%s: %s", row.get("id"), e)

                # Examples
                ex_rows = await java.list_examples_missing_embeddings(limit=_BATCH_LIMIT)
                for row in ex_rows or []:
                    text = (row.get("input_text") or "").strip()
                    if not text:
                        continue
                    try:
                        vec = await embedder.embed(text)
                        await java.put_example_embedding(int(row["id"]), _vec_to_pg_literal(vec))
                        logger.info("backfilled example embedding id=%s", row.get("id"))
                    except Exception as e:  # noqa: BLE001
                        logger.warning("example embed failed id=%s: %s", row.get("id"), e)
            except Exception as e:  # noqa: BLE001
                logger.warning("backfill cycle failed (will retry): %s", e)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_BACKFILL_INTERVAL_SEC)
            except asyncio.TimeoutError:
                pass

    @staticmethod
    def _compose_text_kn(row: dict) -> str:
        title = (row.get("title") or "").strip()
        body = (row.get("body") or "").strip()
        if title and body:
            return f"{title}\n\n{body}"
        return title or body


_INSTANCE: Optional[EmbeddingBackfill] = None


def get_instance() -> EmbeddingBackfill:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = EmbeddingBackfill()
    return _INSTANCE
