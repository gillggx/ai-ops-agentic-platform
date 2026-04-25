"""In-memory session registry with TTL cleanup.

Sessions are ephemeral — they exist only for the duration of one Agent run.
After TTL seconds of inactivity (no subscriber, no cancel), they are purged.

Thread/async safety: we guard with an asyncio.Lock for mutations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from python_ai_sidecar.agent_builder.session import AgentBuilderSession

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 5 * 60  # 5 minutes
_CLEANUP_INTERVAL_SECONDS = 60


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, AgentBuilderSession] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task[None]] = None

    async def register(self, session: AgentBuilderSession) -> None:
        async with self._lock:
            self._sessions[session.session_id] = session

    async def get(self, session_id: str) -> Optional[AgentBuilderSession]:
        async with self._lock:
            return self._sessions.get(session_id)

    async def drop(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def cancel(self, session_id: str) -> bool:
        s = await self.get(session_id)
        if s is None:
            return False
        s.request_cancel()
        return True

    def start_cleanup(self) -> None:
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        self._cleanup_task = asyncio.ensure_future(self._cleanup_loop())

    def stop_cleanup(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
                await self._purge_expired()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                logger.exception("Session cleanup loop error (continuing)")

    async def _purge_expired(self) -> None:
        now = time.time()
        async with self._lock:
            expired = [
                sid for sid, s in self._sessions.items()
                if (s.finished_at is not None and now - s.finished_at > SESSION_TTL_SECONDS)
                or (s.finished_at is None and now - s.started_at > SESSION_TTL_SECONDS * 2)
            ]
            for sid in expired:
                self._sessions.pop(sid, None)
        if expired:
            logger.info("Agent session registry purged %d expired sessions", len(expired))


_global_registry = SessionRegistry()


def get_session_registry() -> SessionRegistry:
    return _global_registry
