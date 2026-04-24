"""In-memory run-scoped cache for node outputs.

Phase 1 scope: single-worker process, no Redis.
Each pipeline run gets its own cache keyed by run_id.
Caller is responsible for disposing the cache after the run finishes.
"""

from __future__ import annotations

import threading
from typing import Any, Optional


class RunCache:
    """Per-run cache: node_id → outputs dict."""

    def __init__(self, run_id: Optional[int] = None) -> None:
        self.run_id = run_id
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, node_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._store.get(node_id)

    def set(self, node_id: str, outputs: dict[str, Any]) -> None:
        with self._lock:
            self._store[node_id] = outputs

    def has(self, node_id: str) -> bool:
        with self._lock:
            return node_id in self._store

    def dispose(self) -> None:
        with self._lock:
            self._store.clear()

    def snapshot_keys(self) -> list[str]:
        with self._lock:
            return list(self._store.keys())
