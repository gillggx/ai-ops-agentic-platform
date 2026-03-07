"""Agent Memory Service — long-term RAG memory for the v13 Agentic Platform.

Dev strategy: keyword-based search (SQLite has no vector extension).
Prod path: swap search() for pgvector cosine similarity query.

Auto-write triggers:
  - Skill execution with status=ABNORMAL → write diagnosis memory
  - Agent explicitly calls save_memory tool → write with source='agent_request'
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_memory import AgentMemoryModel

logger = logging.getLogger(__name__)

_MAX_MEMORIES_PER_USER = 200  # soft cap — oldest pruned on exceed


class AgentMemoryService:
    """CRUD + search for agent_memories table."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Read ──────────────────────────────────────────────────────────────────

    async def list(self, user_id: int, limit: int = 50) -> List[AgentMemoryModel]:
        result = await self._db.execute(
            select(AgentMemoryModel)
            .where(AgentMemoryModel.user_id == user_id)
            .order_by(AgentMemoryModel.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get(self, memory_id: int) -> Optional[AgentMemoryModel]:
        result = await self._db.execute(
            select(AgentMemoryModel).where(AgentMemoryModel.id == memory_id)
        )
        return result.scalar_one_or_none()

    async def search(
        self, user_id: int, query: str, top_k: int = 5
    ) -> List[AgentMemoryModel]:
        """Keyword-based search (SQLite-compatible).

        Splits query into tokens and scores each memory by token hit count.
        Returns top_k by score, then recency.
        """
        all_memories = await self.list(user_id, limit=_MAX_MEMORIES_PER_USER)
        if not all_memories:
            return []

        tokens = [t.lower() for t in query.split() if len(t) > 1]
        if not tokens:
            return all_memories[:top_k]

        scored: List[tuple[int, AgentMemoryModel]] = []
        for m in all_memories:
            text = m.content.lower()
            score = sum(1 for t in tokens if t in text)
            if score > 0:
                scored.append((score, m))

        scored.sort(key=lambda x: (-x[0], x[1].created_at), reverse=False)
        # re-sort: higher score first, then newer first
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:top_k]]

    # ── Write ─────────────────────────────────────────────────────────────────

    async def write(
        self,
        user_id: int,
        content: str,
        source: str = "manual",
        ref_id: Optional[str] = None,
    ) -> AgentMemoryModel:
        """Persist a new memory entry."""
        memory = AgentMemoryModel(
            user_id=user_id,
            content=content,
            source=source,
            ref_id=ref_id,
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(memory)
        await self._db.commit()
        await self._db.refresh(memory)
        logger.info("Memory written: user=%d source=%s id=%d", user_id, source, memory.id)
        return memory

    async def write_diagnosis(
        self,
        user_id: int,
        skill_name: str,
        targets: List[str],
        diagnosis_message: str,
        skill_id: Optional[int] = None,
    ) -> Optional[AgentMemoryModel]:
        """Auto-write triggered after an ABNORMAL skill diagnosis."""
        if not targets and not diagnosis_message:
            return None
        target_str = "、".join(targets) if targets else "未知目標"
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        content = (
            f"[診斷記錄] {ts} | Skill「{skill_name}」判定 ABNORMAL | "
            f"問題目標: {target_str} | 訊息: {diagnosis_message}"
        )
        return await self.write(
            user_id=user_id,
            content=content,
            source="diagnosis",
            ref_id=f"skill:{skill_id}" if skill_id else None,
        )

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete(self, memory_id: int, user_id: int) -> bool:
        """Delete a memory. Returns True if deleted, False if not found/not owned."""
        result = await self._db.execute(
            select(AgentMemoryModel).where(
                AgentMemoryModel.id == memory_id,
                AgentMemoryModel.user_id == user_id,
            )
        )
        memory = result.scalar_one_or_none()
        if not memory:
            return False
        await self._db.delete(memory)
        await self._db.commit()
        logger.info("Memory deleted: id=%d user=%d", memory_id, user_id)
        return True

    async def delete_all(self, user_id: int) -> int:
        """Delete all memories for a user. Returns count deleted."""
        result = await self._db.execute(
            select(AgentMemoryModel).where(AgentMemoryModel.user_id == user_id)
        )
        memories = list(result.scalars().all())
        for m in memories:
            await self._db.delete(m)
        await self._db.commit()
        return len(memories)

    # ── Serialisation helper ──────────────────────────────────────────────────

    @staticmethod
    def to_dict(m: AgentMemoryModel) -> Dict[str, Any]:
        return {
            "id": m.id,
            "user_id": m.user_id,
            "content": m.content,
            "source": m.source,
            "ref_id": m.ref_id,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
