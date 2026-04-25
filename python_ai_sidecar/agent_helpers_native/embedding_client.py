"""Embedding client — wraps Ollama's /api/embeddings for bge-m3.

Returns 1024-dim vectors for semantic search on agent experience memory.
Provider-agnostic interface so we can swap in OpenAI text-embedding-3
later without touching the memory service.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# bge-m3 dimension (matches EMBEDDING_DIM in the ORM model)
EMBEDDING_DIM = 1024


class EmbeddingError(RuntimeError):
    """Raised when embedding generation fails."""
    pass


class OllamaEmbeddingClient:
    """Calls Ollama's native /api/embeddings endpoint.

    Different from the chat client — Ollama's embedding endpoint takes
    {model, prompt} and returns {embedding: [...]}, no OpenAI-style
    translation needed.

    Usage:
        client = OllamaEmbeddingClient(base_url="http://localhost:11434",
                                        model="bge-m3")
        vec = await client.embed("SPC OOC 分析需求")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "bge-m3",
        timeout: float = 30.0,
    ) -> None:
        # Strip /v1 suffix if accidentally supplied (Ollama's native API is /api/*)
        self._base_url = base_url.rstrip("/").removesuffix("/v1")
        self._model = model
        self._timeout = timeout

    async def embed(self, text: str) -> list[float]:
        """Generate a single embedding vector for `text`.

        Raises EmbeddingError on network / parsing failure.
        """
        if not isinstance(text, str):
            raise EmbeddingError(f"embed() requires str, got {type(text).__name__}")
        text = text.strip()
        if not text:
            raise EmbeddingError("embed() requires non-empty text")

        url = f"{self._base_url}/api/embeddings"
        payload = {"model": self._model, "prompt": text}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Ollama embedding HTTP error: {exc}") from exc
        except Exception as exc:
            raise EmbeddingError(f"Ollama embedding call failed: {exc}") from exc

        vec = data.get("embedding")
        if not isinstance(vec, list) or not vec:
            raise EmbeddingError(f"Ollama returned invalid embedding: {data!r}")
        if len(vec) != EMBEDDING_DIM:
            logger.warning(
                "Embedding dim mismatch: expected %d, got %d (model=%s)",
                EMBEDDING_DIM, len(vec), self._model,
            )
        return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts sequentially.

        Ollama doesn't have a native batch endpoint yet; this is
        fire-and-await sequentially. Fine for memory writes (low
        throughput), don't use in tight loops.
        """
        results = []
        for t in texts:
            results.append(await self.embed(t))
        return results


# ── Module-level singleton ─────────────────────────────────────────────

_client_instance: Optional[OllamaEmbeddingClient] = None


def get_embedding_client() -> OllamaEmbeddingClient:
    """Cached singleton configured from app settings."""
    global _client_instance
    if _client_instance is None:
        from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings
        settings = get_settings()
        base_url = getattr(settings, "OLLAMA_BASE_URL", None) or "http://localhost:11434"
        model = getattr(settings, "OLLAMA_EMBEDDING_MODEL", "bge-m3")
        _client_instance = OllamaEmbeddingClient(base_url=base_url, model=model)
    return _client_instance
