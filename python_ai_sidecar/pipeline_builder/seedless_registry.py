"""DB-less BlockRegistry for sidecar runtime.

The sidecar doesn't own the DB, but it doesn't need to — block metadata is
static (seed.py is the SSOT for block specs) and executor classes are
imported directly via BUILTIN_EXECUTORS. This registry fills the same
interface as the DB-backed one but loads from seed.py synchronously at
startup.

Why this over the DB-backed one?
  - No async SQLAlchemy round-trip
  - No dependency on Java /internal/blocks endpoint shape
  - seed.py is already the SSOT — Java's block rows are just a mirror
  - Keeps sidecar strictly stateless + DB-free, matching its design
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from python_ai_sidecar.pipeline_builder.blocks import BUILTIN_EXECUTORS
from python_ai_sidecar.pipeline_builder.blocks.base import BlockExecutor
from python_ai_sidecar.pipeline_builder.seed import _blocks

logger = logging.getLogger(__name__)


class SeedlessBlockRegistry:
    """Drop-in for BlockRegistry with a constant catalog loaded from seed.py."""

    def __init__(self) -> None:
        self._catalog: dict[tuple[str, str], dict[str, Any]] = {}
        self._executors: dict[tuple[str, str], BlockExecutor] = {}

    def load(self) -> None:
        """Synchronous — load catalog from seed.py + attach executors."""
        specs = _blocks()
        catalog: dict[tuple[str, str], dict[str, Any]] = {}
        executors: dict[tuple[str, str], BlockExecutor] = {}

        for spec in specs:
            key = (spec["name"], spec["version"])
            # Enrich catalog with empty defaults missing from seed.py
            full_spec = {
                "id": None,  # no DB id in sidecar
                "name": spec["name"],
                "version": spec["version"],
                "category": spec.get("category", "transform"),
                "status": spec.get("status", "production"),
                "description": spec.get("description", ""),
                "input_schema": spec.get("input_schema", []),
                "output_schema": spec.get("output_schema", []),
                "param_schema": spec.get("param_schema", {}),
                "examples": spec.get("examples", []),
                "implementation": spec.get("implementation", {}),
                "is_custom": spec.get("is_custom", False),
                "output_columns_hint": spec.get("output_columns_hint", []),
                # v30: structured per-column doc consumed by goal_plan +
                # agentic_phase_loop prompt builders, and merged into
                # infer_runtime_schema's usage hint column.
                "column_docs": spec.get("column_docs", []),
            }
            catalog[key] = full_spec

            exec_cls = BUILTIN_EXECUTORS.get(spec["name"])
            if exec_cls is None:
                logger.warning(
                    "seedless registry: block %s@%s has no executor class — "
                    "validator will see it but execute() will skip",
                    spec["name"], spec["version"],
                )
                continue
            executors[key] = exec_cls()

        self._catalog = catalog
        self._executors = executors
        logger.info(
            "SeedlessBlockRegistry loaded %d blocks (%d with executors)",
            len(catalog), len(executors),
        )

    @property
    def catalog(self) -> dict[tuple[str, str], dict[str, Any]]:
        return self._catalog

    def get_spec(self, name: str, version: str) -> Optional[dict[str, Any]]:
        return self._catalog.get((name, version))

    def get_executor(self, name: str, version: str) -> Optional[BlockExecutor]:
        return self._executors.get((name, version))
