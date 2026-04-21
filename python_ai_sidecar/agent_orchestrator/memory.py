"""Agent memory — reads + writes go through ``JavaAPIClient``.

Phase 5b: text-only recall (newest N items). Phase 7 will add pgvector
similarity query via a dedicated Java endpoint.
"""

from __future__ import annotations

from ..clients.java_client import JavaAPIClient


async def recall(java: JavaAPIClient, user_id: int, task_type: str | None = None, limit: int = 5) -> list[dict]:
    rows = await java.list_agent_memories(user_id=user_id, task_type=task_type)
    return (rows or [])[:limit]


async def remember(
    java: JavaAPIClient,
    user_id: int,
    content: str,
    *,
    source: str = "agent_request",
    task_type: str | None = None,
    ref_id: str | None = None,
) -> dict:
    body = {
        "userId": user_id,
        "content": content,
        "source": source,
        "taskType": task_type,
        "refId": ref_id,
    }
    return await java.save_agent_memory({k: v for k, v in body.items() if v is not None})
