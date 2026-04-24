"""BlockRegistry — load blocks from DB into an in-memory catalog.

Responsibilities:
  - Load all active (pi_run / production) blocks from DB at runtime
  - Provide catalog map {(name, version): spec_dict} for the Validator
  - Resolve (block_id, version) → BlockExecutor instance for the Executor
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from python_ai_sidecar.pipeline_builder._sidecar_deps import BlockRepository
from python_ai_sidecar.pipeline_builder.blocks import BUILTIN_EXECUTORS
from python_ai_sidecar.pipeline_builder.blocks.base import BlockExecutor

logger = logging.getLogger(__name__)


class BlockRegistry:
    def __init__(self) -> None:
        self._catalog: dict[tuple[str, str], dict[str, Any]] = {}
        self._executors: dict[tuple[str, str], BlockExecutor] = {}

    async def load_from_db(self, db: AsyncSession, *, include_draft: bool = False) -> None:
        """Reload catalog from DB. Includes all rows (draft/pi_run/production)
        when `include_draft=True`, otherwise only active ones."""
        repo = BlockRepository(db)
        blocks = await repo.list_all() if include_draft else await repo.list_active()

        catalog: dict[tuple[str, str], dict[str, Any]] = {}
        executors: dict[tuple[str, str], BlockExecutor] = {}

        for b in blocks:
            key = (b.name, b.version)
            try:
                spec = {
                    "id": b.id,
                    "name": b.name,
                    "version": b.version,
                    "category": b.category,
                    "status": b.status,
                    "description": b.description,
                    "input_schema": json.loads(b.input_schema or "[]"),
                    "output_schema": json.loads(b.output_schema or "[]"),
                    "param_schema": json.loads(b.param_schema or "{}"),
                    "examples": json.loads(b.examples or "[]"),
                    "implementation": json.loads(b.implementation or "{}"),
                    "is_custom": b.is_custom,
                    "output_columns_hint": json.loads(
                        getattr(b, "output_columns_hint", None) or "[]"
                    ),
                }
            except json.JSONDecodeError as e:
                logger.warning("Block %s@%s has invalid JSON: %s — skipping", b.name, b.version, e)
                continue

            catalog[key] = spec

            # Resolve executor — Phase 1 only supports builtin python executors by name
            exec_cls = BUILTIN_EXECUTORS.get(b.name)
            if exec_cls is None:
                logger.warning(
                    "Block %s@%s has no registered executor (skipping execution registration)",
                    b.name, b.version,
                )
                continue
            executors[key] = exec_cls()

        self._catalog = catalog
        self._executors = executors
        logger.info("BlockRegistry loaded %d blocks (%d with executors)", len(catalog), len(executors))

    @property
    def catalog(self) -> dict[tuple[str, str], dict[str, Any]]:
        return self._catalog

    def get_spec(self, name: str, version: str) -> Optional[dict[str, Any]]:
        return self._catalog.get((name, version))

    def get_executor(self, name: str, version: str) -> Optional[BlockExecutor]:
        return self._executors.get((name, version))
