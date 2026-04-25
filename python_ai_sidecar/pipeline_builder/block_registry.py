"""BlockRegistry — load blocks from DB / Java into an in-memory catalog.

Responsibilities:
  - Load all active (pi_run / production) blocks at runtime
  - Provide catalog map {(name, version): spec_dict} for the Validator
  - Resolve (block_id, version) → BlockExecutor instance for the Executor

Phase 8-A-1d: ``load_from_db`` is retained as a backward-compat shim
that now silently routes to ``load_from_java``. The new canonical path
is ``await registry.load_from_java(java_client)``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from python_ai_sidecar.pipeline_builder.blocks import BUILTIN_EXECUTORS
from python_ai_sidecar.pipeline_builder.blocks.base import BlockExecutor

logger = logging.getLogger(__name__)


class BlockRegistry:
    def __init__(self) -> None:
        self._catalog: dict[tuple[str, str], dict[str, Any]] = {}
        self._executors: dict[tuple[str, str], BlockExecutor] = {}

    async def load_from_java(self, java: Any) -> None:
        """Reload catalog via Java /internal/blocks. Java DTO is camelCase."""
        rows = await java.list_blocks()
        catalog: dict[tuple[str, str], dict[str, Any]] = {}
        executors: dict[tuple[str, str], BlockExecutor] = {}

        for r in (rows or []):
            name = r.get("name")
            version = r.get("version")
            if not name or not version:
                continue
            key = (name, version)
            try:
                spec = {
                    "id": r.get("id"),
                    "name": name,
                    "version": version,
                    "category": r.get("category"),
                    "status": r.get("status"),
                    "description": r.get("description"),
                    "input_schema": _maybe_json(r.get("inputSchema") or r.get("input_schema") or "[]"),
                    "output_schema": _maybe_json(r.get("outputSchema") or r.get("output_schema") or "[]"),
                    "param_schema": _maybe_json(r.get("paramSchema") or r.get("param_schema") or "{}"),
                    "examples": _maybe_json(r.get("examples") or "[]"),
                    "implementation": _maybe_json(r.get("implementation") or "{}"),
                    "is_custom": r.get("isCustom") or r.get("is_custom"),
                    "output_columns_hint": _maybe_json(
                        r.get("outputColumnsHint") or r.get("output_columns_hint") or "[]"
                    ),
                }
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Block %s@%s has invalid JSON: %s — skipping", name, version, e)
                continue

            catalog[key] = spec

            exec_cls = BUILTIN_EXECUTORS.get(name)
            if exec_cls is None:
                logger.warning(
                    "Block %s@%s has no registered executor (skipping execution registration)",
                    name, version,
                )
                continue
            executors[key] = exec_cls()

        self._catalog = catalog
        self._executors = executors
        logger.info("BlockRegistry loaded %d blocks (%d with executors) via Java", len(catalog), len(executors))

    async def load_from_db(self, db: Any, *, include_draft: bool = False) -> None:  # noqa: ARG002
        """Back-compat shim — Phase 8-A-1d routes via Java instead of opening
        a local DB session. The ``db`` argument is ignored; a fresh
        ``JavaAPIClient`` is constructed from sidecar config.
        """
        from python_ai_sidecar.clients.java_client import JavaAPIClient
        from python_ai_sidecar.config import CONFIG
        java = JavaAPIClient(
            CONFIG.java_api_url, CONFIG.java_internal_token,
            timeout_sec=CONFIG.java_timeout_sec,
        )
        await self.load_from_java(java)

    @property
    def catalog(self) -> dict[tuple[str, str], dict[str, Any]]:
        return self._catalog

    def get_spec(self, name: str, version: str) -> Optional[dict[str, Any]]:
        return self._catalog.get((name, version))

    def get_executor(self, name: str, version: str) -> Optional[BlockExecutor]:
        return self._executors.get((name, version))


def _maybe_json(v: Any) -> Any:  # noqa: ANN401
    """Java DTO ships JSON-as-string for opaque columns; decode if needed."""
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    return v
