"""Session-scoped source-block result cache (成本結構修正 波1, 2026-07-07).

Problem: every build round's auto-preview re-executes the whole upstream
subgraph — a 7-round phase fetches the SAME process_history from the MCP
7 times; a repair retry fetches everything again. Source data does not
change second-to-second, so this is pure waste (wall-clock + API load),
and it is what made "small repairs" as expensive as full rebuilds.

Design:
  - Scope: ONE build session (LangGraph thread session_id). Created lazily,
    dropped at build finalize; pause/resume within the same session reuses it.
    NO cross-conversation persistence (per spec 不做的事).
  - Key: (block_id, block_version, canonical-JSON of resolved params).
    A param change produces a new key — invalidation is automatic.
  - What qualifies: nodes with NO inbound edges (pure sources — their output
    is a deterministic function of params within a session). The executor
    enforces this rule; this module just stores.
  - Values are returned as shallow copies with DataFrame.copy() so a
    downstream block mutating its input can never poison the cache.
  - Registry is process-local with TTL + cap eviction (a crashed build that
    never finalizes must not leak DataFrames forever).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger("python_ai_sidecar.source_cache")

_TTL_SEC = 30 * 60          # a build session should never outlive this
_MAX_SESSIONS = 16          # hard cap — oldest evicted first
_MAX_ENTRIES_PER_SESSION = 32


def _params_key(block_id: str, version: str, params: dict[str, Any]) -> str:
    try:
        blob = json.dumps(params or {}, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        blob = repr(sorted((params or {}).items(), key=lambda kv: kv[0]))
    h = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]
    return f"{block_id}@{version}:{h}"


def _copy_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for port, val in outputs.items():
        out[port] = val.copy() if isinstance(val, pd.DataFrame) else val
    return out


class SessionSourceCache:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.created_at = time.monotonic()
        self._entries: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, block_id: str, version: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        key = _params_key(block_id, version, params)
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        self.hits += 1
        return _copy_outputs(entry)

    def put(self, block_id: str, version: str, params: dict[str, Any], outputs: dict[str, Any]) -> None:
        if len(self._entries) >= _MAX_ENTRIES_PER_SESSION:
            return  # cap — never grow unbounded; extra sources just refetch
        key = _params_key(block_id, version, params)
        self._entries[key] = _copy_outputs(outputs)

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "fetches": self.misses, "entries": len(self._entries)}


_registry: dict[str, SessionSourceCache] = {}
_lock = threading.Lock()


def get_session_cache(session_id: str) -> SessionSourceCache:
    """Fetch-or-create the cache for a build session (thread-safe)."""
    now = time.monotonic()
    with _lock:
        # lazy TTL sweep
        stale = [sid for sid, c in _registry.items() if now - c.created_at > _TTL_SEC]
        for sid in stale:
            _registry.pop(sid, None)
        if session_id not in _registry:
            if len(_registry) >= _MAX_SESSIONS:
                oldest = min(_registry.values(), key=lambda c: c.created_at)
                _registry.pop(oldest.session_id, None)
            _registry[session_id] = SessionSourceCache(session_id)
        return _registry[session_id]


def drop_session_cache(session_id: str) -> Optional[dict[str, int]]:
    """Drop at build finalize; returns final stats (for the timeline event)."""
    with _lock:
        cache = _registry.pop(session_id, None)
    if cache is None:
        return None
    stats = cache.stats()
    logger.info("source_cache[%s]: %d hits, %d fetches, %d entries",
                session_id[:8], stats["hits"], stats["fetches"], stats["entries"])
    return stats
