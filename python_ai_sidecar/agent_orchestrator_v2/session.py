"""Session management — load/save agent session history from Postgres.

Reuses the existing agent_sessions + agent_chat_messages tables.
In a future iteration this will be replaced by LangGraph's PostgresSaver
checkpointer, but for Phase 2-B we keep backward compat with v1.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from python_ai_sidecar.agent_helpers._model_stubs import AgentSessionModel

logger = logging.getLogger(__name__)


async def load_session(
    db: AsyncSession,
    session_id: Optional[str],
    user_id: int,
) -> Tuple[str, List[Any], int]:
    """Load or create a session. Returns (session_id, history_messages, cumulative_tokens).

    history_messages is a list of LangChain message objects (HumanMessage / AIMessage).

    Phase 8-A-1d: when ``db`` is None we route via Java
    ``/internal/agent-sessions/*``. SQLAlchemy path is retained for
    in-process tests that want to skip the network.
    """
    if db is None:
        return await _load_session_java(session_id, user_id)

    if session_id:
        result = await db.execute(
            select(AgentSessionModel).where(
                AgentSessionModel.session_id == session_id,
                AgentSessionModel.user_id == user_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            history = _parse_history(row.messages)
            tokens = row.cumulative_tokens or 0
            return session_id, history, tokens

    # Create new session
    new_sid = str(uuid.uuid4())
    new_session = AgentSessionModel(
        session_id=new_sid,
        user_id=user_id,
        messages="[]",
        cumulative_tokens=0,
    )
    db.add(new_session)
    await db.commit()
    return new_sid, [], 0


async def save_session(
    db: AsyncSession,
    session_id: str,
    user_id: int,
    messages: List[Any],
    cumulative_tokens: int,
) -> None:
    """Persist the latest conversation messages to the session."""
    if db is None:
        await _save_session_java(session_id, user_id, messages, cumulative_tokens)
        return

    result = await db.execute(
        select(AgentSessionModel).where(
            AgentSessionModel.session_id == session_id,
            AgentSessionModel.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return

    # Convert LangChain messages → v1-compatible JSON list
    history_json = json.dumps(
        _messages_to_dicts(messages),
        ensure_ascii=False,
    )
    row.messages = history_json
    row.cumulative_tokens = cumulative_tokens
    row.updated_at = datetime.now(tz=timezone.utc)
    # Phase 5-UX-3b: backfill session title from first user message (for listing)
    if not getattr(row, "title", None):
        first_user = next(
            (m for m in messages if isinstance(m, HumanMessage)),
            None,
        )
        if first_user and isinstance(first_user.content, str):
            row.title = first_user.content[:200]
    await db.commit()


# ── Java-backed paths (Phase 8-A-1d) ─────────────────────────────────


async def _load_session_java(
    session_id: Optional[str], user_id: int,
) -> Tuple[str, List[Any], int]:
    from python_ai_sidecar.clients.java_client import JavaAPIClient
    from python_ai_sidecar.config import CONFIG
    java = JavaAPIClient(
        CONFIG.java_api_url, CONFIG.java_internal_token,
        timeout_sec=CONFIG.java_timeout_sec,
    )
    if session_id:
        try:
            row = await java.get_agent_session(session_id)
            if row and (row.get("userId") == user_id or row.get("user_id") == user_id):
                history = _parse_history(row.get("messages"))
                tokens = row.get("cumulativeTokens") or row.get("cumulative_tokens") or 0
                return session_id, history, tokens
        except Exception as exc:
            logger.warning("load_session via java failed (%s) — creating new", exc)

    new_sid = str(uuid.uuid4())
    try:
        await java.upsert_agent_session(new_sid, {
            "userId": user_id, "messages": "[]", "cumulativeTokens": 0,
        })
    except Exception as exc:
        logger.warning("upsert_agent_session (init) failed: %s", exc)
    return new_sid, [], 0


async def _save_session_java(
    session_id: str, user_id: int, messages: List[Any], cumulative_tokens: int,
) -> None:
    from python_ai_sidecar.clients.java_client import JavaAPIClient
    from python_ai_sidecar.config import CONFIG
    java = JavaAPIClient(
        CONFIG.java_api_url, CONFIG.java_internal_token,
        timeout_sec=CONFIG.java_timeout_sec,
    )
    history_json = json.dumps(_messages_to_dicts(messages), ensure_ascii=False)
    body: Dict[str, Any] = {
        "userId": user_id,
        "messages": history_json,
        "cumulativeTokens": cumulative_tokens,
    }
    first_user = next((m for m in messages if isinstance(m, HumanMessage)), None)
    if first_user and isinstance(first_user.content, str):
        body["title"] = first_user.content[:200]
    try:
        await java.upsert_agent_session(session_id, body)
    except Exception as exc:
        logger.warning("save_session via java failed: %s", exc)


def _parse_history(raw: Optional[str]) -> List[Any]:
    """Parse v1-format JSON history into LangChain message objects."""
    if not raw:
        return []
    try:
        entries = json.loads(raw)
    except Exception:
        return []
    messages = []
    for entry in entries:
        role = entry.get("role", "user")
        content = entry.get("content", "")
        if isinstance(content, list):
            # v1 stores Anthropic content blocks as list
            text_parts = [
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            content = "\n".join(text_parts)
        if role == "user":
            messages.append(HumanMessage(content=content or ""))
        elif role == "assistant":
            messages.append(AIMessage(content=content or ""))
    return messages


def _messages_to_dicts(messages: List[Any]) -> List[Dict[str, str]]:
    """Convert LangChain messages back to v1-compatible dicts for storage."""
    result = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            result.append({"role": "assistant", "content": msg.content})
    return result
