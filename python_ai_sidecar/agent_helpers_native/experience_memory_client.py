"""ExperienceMemoryClient — Phase 8-A-1d Java-backed replacement.

Mirrors the public interface of
``fastapi_backend_service.app.services.experience_memory_service.ExperienceMemoryService``
so callers (memory_lifecycle node + context_loader) can swap the import
without touching their call sites.

Key differences from the old service:
- No SQLAlchemy session — every method calls Java ``/internal/agent-experience-memories/*``
- Embedding is computed locally via the ported ``embedding_client``
- Dedup happens server-side (Java ``WriteRequest.dedupThreshold``)
- ``record_feedback`` only handles ``success | fail``; ``env_error`` no-ops
  (Java endpoint design — symmetric with the old "no score change" case)

Returns dict shapes that match ``ExperienceMemoryService.to_dict(mem)`` so
``context_loader`` 's existing ``hit = ExpSvc.to_dict(mem)`` call site continues
to work — we expose ``to_dict`` as a static passthrough.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from python_ai_sidecar.agent_helpers_native.embedding_client import (
    EmbeddingError,
    get_embedding_client,
)
from python_ai_sidecar.clients.java_client import JavaAPIClient

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
MIN_COSINE_SIMILARITY = 0.6
MIN_RETRIEVE_CONFIDENCE = 1
DEDUP_COSINE_THRESHOLD = 0.92


class _MemRow:
    """Lightweight stand-in for AgentExperienceMemoryModel.

    The old code accesses ``.id``, ``.user_id``, ``.intent_summary``, ...
    directly on the ORM row, so we expose the Java JSON via attribute access.
    """

    __slots__ = ("_data",)

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        # Java DTO uses camelCase — accept both forms
        if name in self._data:
            return self._data[name]
        camel = _snake_to_camel(name)
        return self._data.get(camel)

    @property
    def id(self) -> Optional[int]:
        return self._data.get("id")


def _snake_to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class ExperienceMemoryClient:
    """Drop-in replacement for ExperienceMemoryService — Java-backed."""

    def __init__(self, java_client: JavaAPIClient) -> None:
        self._java = java_client

    async def write(
        self,
        user_id: int,
        intent_summary: str,
        abstract_action: str,
        source: str = "auto",
        source_session_id: Optional[str] = None,
    ) -> _MemRow:
        if not intent_summary.strip() or not abstract_action.strip():
            raise ValueError("intent_summary and abstract_action must be non-empty")

        embed_text = f"{intent_summary}\n{abstract_action}"
        try:
            client = get_embedding_client()
            embedding = await client.embed(embed_text)
        except EmbeddingError as exc:
            logger.warning("write: embedding failed (%s) — storing without vector", exc)
            embedding = None

        result = await self._java.write_experience_memory(
            user_id=user_id,
            intent_summary=intent_summary[:500],
            abstract_action=abstract_action,
            embedding=embedding,
            source=source,
            source_session_id=source_session_id,
            dedup_threshold=DEDUP_COSINE_THRESHOLD if embedding else None,
        )
        mem = result.get("memory") if isinstance(result, dict) else None
        if mem is None:
            raise RuntimeError(f"write_experience_memory returned unexpected shape: {result!r}")
        if result.get("dedupHit"):
            logger.info(
                "memory dedup: bumped existing id=%s sim=%.3f",
                mem.get("id"), result.get("similarity", 0.0),
            )
        return _MemRow(mem)

    async def retrieve(
        self,
        user_id: int,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        min_similarity: float = MIN_COSINE_SIMILARITY,
        min_confidence: int = MIN_RETRIEVE_CONFIDENCE,
    ) -> List[Tuple[_MemRow, float]]:
        if not query.strip():
            return []
        try:
            client = get_embedding_client()
            query_vec = await client.embed(query)
        except EmbeddingError as exc:
            logger.warning("retrieve: embedding failed — %s", exc)
            return []

        hits = await self._java.search_experience_memory(
            user_id=user_id,
            query_embedding=query_vec,
            top_k=top_k,
            min_similarity=min_similarity,
            min_confidence=min_confidence,
        )
        return [(_MemRow(h["memory"]), float(h["similarity"])) for h in hits]

    async def record_feedback(
        self,
        memory_id: int,
        outcome: str,  # 'success' | 'failure' | 'env_error'
        reason: Optional[str] = None,  # noqa: ARG002 — interface compat
    ) -> Optional[_MemRow]:
        # Map old vocabulary to new endpoint — env_error is a no-op
        if outcome == "env_error":
            return None
        java_outcome = "fail" if outcome == "failure" else "success"
        try:
            data = await self._java.feedback_experience_memory(memory_id, java_outcome)
        except Exception as exc:  # noqa: BLE001
            logger.warning("feedback failed for id=%s outcome=%s: %s", memory_id, outcome, exc)
            return None
        return _MemRow(data) if data else None

    async def list_for_user(
        self,
        user_id: int,
        status_filter: Optional[str] = None,
        limit: int = 100,  # noqa: ARG002 — Java endpoint returns full list
    ) -> List[_MemRow]:
        rows = await self._java.list_experience_memories(
            user_id=user_id, status=status_filter or "ACTIVE",
        )
        return [_MemRow(r) for r in rows]

    @staticmethod
    def to_dict(mem: Any) -> Dict[str, Any]:
        """Serialise for API responses — accepts both _MemRow and raw dict.

        Mirrors the old service's static method so context_loader's
        ``hit = ExpSvc.to_dict(mem)`` continues to work unchanged.
        """
        if isinstance(mem, dict):
            d = mem
        elif isinstance(mem, _MemRow):
            d = mem._data  # noqa: SLF001
        else:
            # Best-effort: assume attribute access on a model-like object
            d = {
                "id": getattr(mem, "id", None),
                "user_id": getattr(mem, "user_id", None),
                "intent_summary": getattr(mem, "intent_summary", None),
                "abstract_action": getattr(mem, "abstract_action", None),
                "confidence_score": getattr(mem, "confidence_score", None),
                "use_count": getattr(mem, "use_count", None),
                "success_count": getattr(mem, "success_count", None),
                "fail_count": getattr(mem, "fail_count", None),
                "status": getattr(mem, "status", None),
                "source": getattr(mem, "source", None),
                "source_session_id": getattr(mem, "source_session_id", None),
                "last_used_at": getattr(mem, "last_used_at", None),
                "created_at": getattr(mem, "created_at", None),
                "updated_at": getattr(mem, "updated_at", None),
            }

        # Normalize Java camelCase → snake_case for API compat
        out = {
            "id": d.get("id"),
            "user_id": d.get("user_id") or d.get("userId"),
            "intent_summary": d.get("intent_summary") or d.get("intentSummary"),
            "abstract_action": d.get("abstract_action") or d.get("abstractAction"),
            "confidence_score": d.get("confidence_score") or d.get("confidenceScore"),
            "use_count": d.get("use_count") or d.get("useCount"),
            "success_count": d.get("success_count") or d.get("successCount"),
            "fail_count": d.get("fail_count") or d.get("failCount"),
            "status": d.get("status"),
            "source": d.get("source"),
            "source_session_id": d.get("source_session_id") or d.get("sourceSessionId"),
            "last_used_at": _iso(d.get("last_used_at") or d.get("lastUsedAt")),
            "created_at": _iso(d.get("created_at") or d.get("createdAt")),
            "updated_at": _iso(d.get("updated_at") or d.get("updatedAt")),
        }
        return out


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)
