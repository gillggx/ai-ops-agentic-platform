"""In-memory registry mapping chat session → pending build clarify state.

When chat tool_execute hits an intent_confirm_required event during a
build, it stores the build's session_id + bullets here and returns a
clarify_pending tool result. Frontend posts /chat/intent-respond, which
looks up the pending state, resumes the build, and re-invokes the chat
agent loop with the build result.

Per Task 2 Q3 choice: in-memory map (volatile, lost on restart).
Production K8s deployment will need Redis-backed equivalent.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional


logger = logging.getLogger(__name__)


@dataclass
class PendingClarify:
    chat_session_id: str
    build_session_id: str
    bullets: list[dict]
    instruction: str           # original user prompt
    base_pipeline: Optional[dict]
    skill_step_mode: bool
    user_id: Optional[int]
    created_at: float = field(default_factory=time.time)
    # ── State for the chat agent's tool-use loop ──────────────────────
    # The LLM's tool_use id when the build was originally called.
    # Needed when we synthesize the resumed tool_result.
    tool_use_id: Optional[str] = None
    # The chat session history at the moment we paused — needed to
    # continue the LLM loop after resume.
    pre_pause_messages: list[Any] = field(default_factory=list)


# session_id → pending state. Per Task 2 Q2, only ONE pending per chat
# session — new build attempt auto-cancels the previous one.
_PENDING: dict[str, PendingClarify] = {}
_MAX_AGE_SEC = 30 * 60  # 30 min before stale entries get GC'd


def register(p: PendingClarify) -> None:
    """Store pending state, auto-cancelling any prior pending for the
    same chat session (Q2)."""
    prior = _PENDING.get(p.chat_session_id)
    if prior is not None:
        logger.info(
            "pending_clarify: replacing prior pending for chat_session=%s "
            "(prior build_session=%s)", p.chat_session_id, prior.build_session_id,
        )
    _PENDING[p.chat_session_id] = p
    logger.info(
        "pending_clarify: registered chat_session=%s build_session=%s n_bullets=%d",
        p.chat_session_id, p.build_session_id, len(p.bullets),
    )
    # Opportunistic GC
    _gc_stale()


def get(chat_session_id: str) -> Optional[PendingClarify]:
    return _PENDING.get(chat_session_id)


def consume(chat_session_id: str) -> Optional[PendingClarify]:
    """Pop the pending state (consume on resume)."""
    p = _PENDING.pop(chat_session_id, None)
    if p is not None:
        logger.info(
            "pending_clarify: consumed chat_session=%s build_session=%s",
            chat_session_id, p.build_session_id,
        )
    return p


def cancel(chat_session_id: str) -> bool:
    """Cancel pending for a chat session (used when user starts a new
    build without confirming the previous)."""
    return _PENDING.pop(chat_session_id, None) is not None


def _gc_stale() -> None:
    now = time.time()
    stale = [k for k, v in _PENDING.items() if now - v.created_at > _MAX_AGE_SEC]
    for k in stale:
        logger.info("pending_clarify: gc stale chat_session=%s", k)
        _PENDING.pop(k, None)
