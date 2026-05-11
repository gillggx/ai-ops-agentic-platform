"""Embedding client — multi-provider abstraction returning 1024-dim vectors.

Providers (selected via env EMBEDDING_PROVIDER, default 'ollama'):
  - ollama  : self-hosted bge-m3 via Ollama HTTP /api/embeddings (1024-dim).
              Needs Ollama running locally + bge-m3 pulled.
  - cohere  : Cohere embed-multilingual-v3.0 (1024-dim, matches schema).
              Needs COHERE_API_KEY env. ~$0.10/1M tokens; free tier 1000 RPM.

Both return EMBEDDING_DIM (1024) so pgvector schema stays unchanged.

2026-05-11: Added Cohere fallback because the production EC2 box (4GB RAM)
can't host Ollama bge-m3 alongside Java + sidecar + Postgres + simulator
without OOM. Cohere does the embedding remotely — zero RAM cost.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Both ollama bge-m3 and cohere embed-multilingual-v3.0 emit 1024 dims.
EMBEDDING_DIM = 1024


class EmbeddingError(RuntimeError):
    """Raised when embedding generation fails."""
    pass


# ── Cohere remote provider ─────────────────────────────────────────────


class CohereEmbeddingClient:
    """Cohere /v1/embed — model embed-multilingual-v3.0 returns 1024-dim.

    Requires COHERE_API_KEY env. Picks input_type='search_document' for
    backfill writes + 'search_query' for query-time retrieval — Cohere's
    asymmetric model gives better recall when document/query are tagged
    differently. We use search_document by default since both backfill
    and chat-query callers go through the same .embed() interface;
    asymmetry is a future optimization (small lift).
    """

    _ENDPOINT = "https://api.cohere.ai/v1/embed"

    def __init__(
        self,
        api_key: str,
        model: str = "embed-multilingual-v3.0",
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise EmbeddingError("CohereEmbeddingClient requires non-empty api_key")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    async def embed(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingError("embed() requires non-empty text")
        body = {
            "texts": [text],
            "model": self._model,
            "input_type": "search_document",
            "embedding_types": ["float"],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._ENDPOINT, json=body, headers=headers)
                if resp.status_code >= 400:
                    raise EmbeddingError(
                        f"Cohere HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                data = resp.json()
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Cohere HTTP error: {exc}") from exc
        # New API shape: {"embeddings":{"float":[[..1024..]]}, ...}
        # Old API shape: {"embeddings":[[..1024..]]}
        embs = data.get("embeddings")
        vec = None
        if isinstance(embs, dict):
            float_list = embs.get("float") or []
            vec = float_list[0] if float_list else None
        elif isinstance(embs, list):
            vec = embs[0] if embs else None
        if not isinstance(vec, list) or len(vec) != EMBEDDING_DIM:
            raise EmbeddingError(
                f"Cohere returned unexpected shape: keys={list(data.keys())} "
                f"first_item_len={len(vec) if isinstance(vec,list) else 'N/A'}"
            )
        return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for t in texts:
            results.append(await self.embed(t))
        return results


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


# ── Module-level singleton + provider dispatch ─────────────────────────

_client_instance: Optional[object] = None


def get_embedding_client():
    """Cached singleton. Provider selected via EMBEDDING_PROVIDER env:
       - 'ollama' (default) → self-hosted bge-m3, free, needs RAM
       - 'cohere'           → remote, ~$0.10/1M tokens, zero local RAM
    """
    global _client_instance
    if _client_instance is not None:
        return _client_instance
    provider = (os.getenv("EMBEDDING_PROVIDER") or "ollama").lower().strip()
    if provider == "cohere":
        api_key = os.getenv("COHERE_API_KEY") or ""
        model = os.getenv("COHERE_EMBED_MODEL", "embed-multilingual-v3.0")
        if not api_key:
            raise EmbeddingError(
                "EMBEDDING_PROVIDER=cohere but COHERE_API_KEY env not set"
            )
        _client_instance = CohereEmbeddingClient(api_key=api_key, model=model)
        logger.info("Embedding provider: Cohere (model=%s)", model)
        return _client_instance
    # Default: Ollama
    from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings
    settings = get_settings()
    base_url = getattr(settings, "OLLAMA_BASE_URL", None) or "http://localhost:11434"
    model = getattr(settings, "OLLAMA_EMBEDDING_MODEL", "bge-m3")
    _client_instance = OllamaEmbeddingClient(base_url=base_url, model=model)
    logger.info("Embedding provider: Ollama (base=%s, model=%s)", base_url, model)
    return _client_instance


def reset_embedding_client_for_test() -> None:
    """Test hook: reset cached singleton so env changes pick up."""
    global _client_instance
    _client_instance = None
