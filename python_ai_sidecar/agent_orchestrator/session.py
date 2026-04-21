"""LangGraph checkpointer — stores conversation + workspace state in Java.

Every chat turn ends with ``save()`` so a fresh process can resume mid-session.
The message list is kept as a JSON string in ``agent_sessions.messages``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from ..clients.java_client import JavaAPIClient, JavaAPIError


@dataclass
class SessionState:
    session_id: str
    user_id: int
    messages: list[dict] = field(default_factory=list)
    workspace_state: str | None = None
    title: str | None = None

    def append(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def to_upsert_body(self) -> dict:
        body: dict = {
            "userId": self.user_id,
            "messages": json.dumps(self.messages, ensure_ascii=False),
        }
        if self.workspace_state is not None:
            body["workspaceState"] = self.workspace_state
        if self.title is not None:
            body["title"] = self.title
        return body


async def load_or_new(java: JavaAPIClient, session_id: str | None, user_id: int) -> SessionState:
    if session_id:
        try:
            raw = await java.get_agent_session(session_id)
        except JavaAPIError as ex:
            if ex.status != 404:
                raise
            raw = None
        if raw:
            messages_raw = raw.get("messages") or "[]"
            try:
                messages = json.loads(messages_raw)
            except ValueError:
                messages = []
            return SessionState(
                session_id=session_id,
                user_id=raw.get("userId") or user_id,
                messages=messages,
                workspace_state=raw.get("workspaceState"),
                title=raw.get("title"),
            )
    return SessionState(session_id=session_id or _new_id(), user_id=user_id)


async def save(java: JavaAPIClient, state: SessionState) -> dict:
    return await java.upsert_agent_session(state.session_id, state.to_upsert_body())


def _new_id() -> str:
    return str(uuid.uuid4())
