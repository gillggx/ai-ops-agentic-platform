"""v30.17j pending_judge — keyed-by-chat-session storage of judge clarify
pause records. Parallel to pending_clarify.py.

When phase_verifier detects a data-source deficit (rows >> below user
quantifier), the graph pauses via judge_clarify_pause_node and emits
pb_judge_clarify. Frontend renders JudgeClarifyCard; user picks an
action; frontend POSTs /chat/intent-respond with a judge_decision body.
That endpoint consumes the pending record + resumes the graph.

TTL: 10 minutes (same as pending_clarify). Past that, considered expired
and consume() returns None (treated as cancel).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_TTL_SECONDS = 600  # 10 minutes


@dataclass
class PendingJudge:
    chat_session_id: str
    build_session_id: str
    phase_id: str
    requested_n: int
    actual_rows: int
    value_desc: str
    block_id: str
    instruction: str  # original user prompt — needed if replan
    base_pipeline: dict | None = None
    skill_step_mode: bool = False
    user_id: Optional[str] = None
    expires_at: float = field(default_factory=lambda: time.time() + _TTL_SECONDS)


_lock = threading.RLock()
_store: dict[str, PendingJudge] = {}


def register(p: PendingJudge) -> None:
    """Store/replace a pending judge record keyed by chat_session_id."""
    with _lock:
        prior = _store.get(p.chat_session_id)
        if prior is not None:
            logger.info(
                "pending_judge: replacing prior pending for chat_session=%s "
                "(was phase=%s, now phase=%s)",
                p.chat_session_id, prior.phase_id, p.phase_id,
            )
        _store[p.chat_session_id] = p
        logger.info(
            "pending_judge: registered chat_session=%s build_session=%s "
            "phase=%s (deficit %d/%d)",
            p.chat_session_id, p.build_session_id,
            p.phase_id, p.actual_rows, p.requested_n,
        )


def consume(chat_session_id: str) -> Optional[PendingJudge]:
    """Pop the pending record for this chat session.

    Returns None if not found OR expired (TTL exceeded). Caller treats
    None as "no pending judge clarification".
    """
    with _lock:
        p = _store.pop(chat_session_id, None)
        if p is None:
            return None
        if time.time() >= p.expires_at:
            logger.info(
                "pending_judge: expired chat_session=%s (TTL %ds elapsed)",
                chat_session_id, _TTL_SECONDS,
            )
            return None
        logger.info(
            "pending_judge: consumed chat_session=%s build_session=%s phase=%s",
            chat_session_id, p.build_session_id, p.phase_id,
        )
        return p


def gc_stale(max_age_seconds: int = _TTL_SECONDS) -> int:
    """Remove expired entries. Returns count removed."""
    now = time.time()
    n = 0
    with _lock:
        for k in list(_store.keys()):
            if now >= _store[k].expires_at:
                _store.pop(k, None)
                n += 1
                logger.info("pending_judge: gc stale chat_session=%s", k)
    return n
