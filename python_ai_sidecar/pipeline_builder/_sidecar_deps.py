"""Shims for modules the ported pipeline_builder used to pull from
``fastapi_backend_service/app/*``.

Phase 8-B philosophy: keep the block files **identical** to the old backend so
``git blame`` and future diffs are clean. Instead of rewriting every block to
use sidecar-native DB / config calls, we expose this small compatibility
layer under the names the old code already imports.

Everything here is best-effort:
  - `get_settings()`: returns env-backed config (no DB lookup)
  - `_get_session_factory()`: raises — sidecar does not own the DB.
    Blocks that hit DB (mcp_call / mcp_foreach / block_registry) must be
    ported to route via `clients.java_client` before being activated in the
    sidecar REGISTRY. Until then they'll fall back to `:8001`.
  - Repositories: stub classes that raise on real calls.
"""

from __future__ import annotations

import os
from typing import Any


class _Settings:
    """Minimal drop-in for ``fastapi_backend_service.app.config.Settings``.

    Only the fields actually referenced by ported blocks are exposed.
    Extend on an as-needed basis when a new block needs a new field.
    """

    def __init__(self) -> None:
        self.ONTOLOGY_SIM_URL: str = os.environ.get(
            "ONTOLOGY_SIM_URL", "http://localhost:8012"
        )
        # Fallback proxy URL — used by blocks that need to reach the old
        # Python's `/api/v1/*` when the sidecar doesn't natively handle them.
        self.FALLBACK_PYTHON_URL: str = os.environ.get(
            "FALLBACK_PYTHON_URL", "http://localhost:8001"
        )
        # Phase 8-A: agent_builder + agent_orchestrator_v2 need direct
        # Anthropic access; key is on the sidecar's env.
        self.ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
        self.ANTHROPIC_MODEL: str = os.environ.get(
            "ANTHROPIC_MODEL", "claude-sonnet-4-20250514"
        )
        # Phase 8-A-1d: chat orchestrator native — its llm_client / embedding /
        # mem0 / data_distillation helpers all read these settings.
        self.LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "anthropic")
        self.LLM_MODEL: str = os.environ.get("LLM_MODEL", self.ANTHROPIC_MODEL)
        self.OLLAMA_BASE_URL: str = os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self.OLLAMA_API_KEY: str = os.environ.get("OLLAMA_API_KEY", "")
        self.OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        self.OLLAMA_EMBEDDING_MODEL: str = os.environ.get(
            "OLLAMA_EMBEDDING_MODEL", "bge-m3"
        )
        # mem0 (long-term semantic memory) — only used when key set
        self.MEM0_API_KEY: str = os.environ.get("MEM0_API_KEY", "")
        # Phase 5 (PIPELINE_ONLY_MODE): forces the chat orchestrator to route
        # data-analysis questions through build_pipeline_live + plan_pipeline
        # rather than the legacy direct-MCP path. Off by default so chat works
        # for ad-hoc queries; flip to "1" when the block catalog covers all
        # production analysis paths.
        self.PIPELINE_ONLY_MODE: bool = os.environ.get(
            "PIPELINE_ONLY_MODE", "0"
        ).strip() in ("1", "true", "True", "yes")


_settings_singleton: _Settings | None = None


def get_settings() -> _Settings:
    global _settings_singleton
    if _settings_singleton is None:
        _settings_singleton = _Settings()
    return _settings_singleton


def _get_session_factory() -> Any:  # noqa: ANN401
    """Sidecar does not own the DB. Blocks that need DB reads must be
    migrated to call the Java API via ``clients.java_client`` instead.
    """
    raise NotImplementedError(
        "Sidecar does not own the DB session. Port this block to call "
        "Java /internal/* endpoints instead, or keep it on the :8001 fallback."
    )


class MCPDefinitionRepository:  # noqa: N801 — mirror the old class name
    """Stub: the real repo was backed by SQLAlchemy. Blocks using it
    (``block_mcp_call``, ``block_mcp_foreach``) should be rewired to hit
    Java ``/internal/mcp/definitions`` via ``clients.java_client`` before
    being registered as sidecar-native.
    """

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def get_by_name(self, name: str) -> Any:  # noqa: ANN401
        raise NotImplementedError(
            f"MCPDefinitionRepository.get_by_name({name!r}) requires a DB. "
            "Migrate this call to the Java client before activating the block."
        )


class BlockRepository:  # noqa: N801
    """Stub: the real repo loaded blocks from DB at startup. Sidecar
    constructs its REGISTRY via explicit imports instead (see
    ``python_ai_sidecar/executor/block_runtime.py``).
    """

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass
