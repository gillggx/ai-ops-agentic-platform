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

from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError
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
        try:
            result = await self._db.execute(
                select(AgentMemoryModel)
                .where(AgentMemoryModel.user_id == user_id)
                .order_by(AgentMemoryModel.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())
        except OperationalError:
            # Metadata columns not yet migrated — query only stable columns
            await self._db.rollback()
            rows = await self._db.execute(
                text(
                    "SELECT id, user_id, content, embedding, source, ref_id, "
                    "created_at, updated_at "
                    "FROM agent_memories WHERE user_id = :uid "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                {"uid": user_id, "lim": limit},
            )
            objs: List[AgentMemoryModel] = []
            for row in rows.mappings():
                m = AgentMemoryModel()
                for k, v in row.items():
                    # SQLite returns datetime columns as strings — parse them back
                    if k in ("created_at", "updated_at") and isinstance(v, str):
                        try:
                            v = datetime.fromisoformat(v)
                        except (ValueError, TypeError):
                            pass
                    setattr(m, k, v)
                objs.append(m)
            return objs

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
        # Include user's own memories AND system shared memories (user_id=0)
        result_own = await self._db.execute(
            select(AgentMemoryModel)
            .where(AgentMemoryModel.user_id.in_([user_id, 0]))
            .order_by(AgentMemoryModel.created_at.desc())
            .limit(_MAX_MEMORIES_PER_USER)
        )
        all_memories = list(result_own.scalars().all())
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

    async def search_with_metadata(
        self,
        user_id: int,
        query: str,
        top_k: int = 5,
        task_type: Optional[str] = None,
        data_subject: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> tuple[List[AgentMemoryModel], Dict[str, Any]]:
        """v14.1: Pre-filtered keyword search — Metadata Indexing.

        Stage 1 filter strategy:
        1. If metadata filters provided → fetch matching memories (primary pool)
           + supplement with legacy memories (no metadata) if pool too small
        2. Score candidates with keyword tokens, return top_k

        Returns (memories, filter_meta) where filter_meta documents applied filters
        for the context_load SSE event.
        """
        filter_meta: Dict[str, Any] = {
            "task_type": task_type,
            "data_subject": data_subject,
            "tool_name": tool_name,
            "strategy": "none",
        }

        has_filters = bool(task_type or data_subject or tool_name)

        if has_filters:
            try:
                filter_meta["strategy"] = "metadata_prefilter"
                meta_conditions = [AgentMemoryModel.user_id.in_([user_id, 0])]
                if task_type:
                    meta_conditions.append(AgentMemoryModel.task_type == task_type)
                if data_subject:
                    meta_conditions.append(AgentMemoryModel.data_subject == data_subject)
                if tool_name:
                    meta_conditions.append(AgentMemoryModel.tool_name == tool_name)

                result = await self._db.execute(
                    select(AgentMemoryModel)
                    .where(*meta_conditions)
                    .order_by(AgentMemoryModel.created_at.desc())
                    .limit(_MAX_MEMORIES_PER_USER)
                )
                primary_pool = list(result.scalars().all())
                filter_meta["primary_pool_size"] = len(primary_pool)

                # Backward-compat: supplement with legacy (no metadata) if needed
                if len(primary_pool) < top_k:
                    result2 = await self._db.execute(
                        select(AgentMemoryModel)
                        .where(
                            AgentMemoryModel.user_id.in_([user_id, 0]),
                            AgentMemoryModel.task_type.is_(None),
                            AgentMemoryModel.data_subject.is_(None),
                        )
                        .order_by(AgentMemoryModel.created_at.desc())
                        .limit(_MAX_MEMORIES_PER_USER)
                    )
                    legacy_pool = list(result2.scalars().all())
                    filter_meta["legacy_supplement"] = len(legacy_pool)
                    candidate_pool = primary_pool + legacy_pool
                else:
                    candidate_pool = primary_pool
            except OperationalError as exc:
                # Migration not yet applied on this DB — fall back gracefully
                logger.warning(
                    "agent_memory metadata columns missing (migration pending): %s — "
                    "falling back to unfiltered search", exc
                )
                filter_meta["strategy"] = "no_filter_fallback"
                filter_meta["fallback_reason"] = "migration_pending"
                await self._db.rollback()
                # fallback: include system memories too
                result_fb = await self._db.execute(
                    select(AgentMemoryModel)
                    .where(AgentMemoryModel.user_id.in_([user_id, 0]))
                    .order_by(AgentMemoryModel.created_at.desc())
                    .limit(_MAX_MEMORIES_PER_USER)
                )
                candidate_pool = list(result_fb.scalars().all())
        else:
            filter_meta["strategy"] = "no_filter_fallback"
            result_nf = await self._db.execute(
                select(AgentMemoryModel)
                .where(AgentMemoryModel.user_id.in_([user_id, 0]))
                .order_by(AgentMemoryModel.created_at.desc())
                .limit(_MAX_MEMORIES_PER_USER)
            )
            candidate_pool = list(result_nf.scalars().all())

        if not candidate_pool:
            return [], filter_meta

        tokens = [t.lower() for t in query.split() if len(t) > 1]
        if not tokens:
            return candidate_pool[:top_k], filter_meta

        scored: List[tuple[int, AgentMemoryModel]] = []
        seen_ids: set = set()
        for m in candidate_pool:
            if m.id in seen_ids:
                continue
            seen_ids.add(m.id)
            text = m.content.lower()
            score = sum(1 for t in tokens if t in text)
            if score > 0:
                scored.append((score, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:top_k]], filter_meta

    # ── Write ─────────────────────────────────────────────────────────────────

    async def write(
        self,
        user_id: int,
        content: str,
        source: str = "manual",
        ref_id: Optional[str] = None,
        task_type: Optional[str] = None,       # v14.1: Metadata Indexing
        data_subject: Optional[str] = None,    # v14.1
        tool_name: Optional[str] = None,       # v14.1
    ) -> AgentMemoryModel:
        """Persist a new memory entry."""
        memory = AgentMemoryModel(
            user_id=user_id,
            content=content,
            source=source,
            ref_id=ref_id,
            task_type=task_type,
            data_subject=data_subject,
            tool_name=tool_name,
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
        """Auto-write triggered after an ABNORMAL skill diagnosis (no conflict check)."""
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

    async def write_diagnosis_with_conflict_check(
        self,
        user_id: int,
        skill_name: str,
        targets: List[str],
        diagnosis_message: str,
        skill_id: Optional[int] = None,
    ) -> Optional[AgentMemoryModel]:
        """v14: Conflict-aware diagnosis memory write.

        Before writing, searches existing memories for the same Skill + target
        combination. If a contradicting memory is found (same target, different
        NORMAL/ABNORMAL conclusion), performs UPDATE instead of ADD to maintain
        consistency (Conflict Resolution).
        """
        if not targets and not diagnosis_message:
            return None

        target_str = "、".join(targets) if targets else "未知目標"
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        new_content = (
            f"[診斷記錄] {ts} | Skill「{skill_name}」判定 ABNORMAL | "
            f"問題目標: {target_str} | 訊息: {diagnosis_message}"
        )

        # Search for conflicting memories about the same skill + target
        query = f"{skill_name} {target_str}"
        similar = await self.search(user_id, query, top_k=5)

        for mem in similar:
            if not _is_same_skill_target(mem.content, skill_name, targets):
                continue
            if _is_contradictory(mem.content, new_content):
                # UPDATE: replace old contradicting memory
                logger.info(
                    "Memory conflict detected for Skill '%s' target '%s' — updating mem.id=%d",
                    skill_name, target_str, mem.id,
                )
                mem.content = new_content
                mem.updated_at = datetime.now(tz=timezone.utc)
                mem._conflict_resolved = True  # flag for SSE event
                await self._db.commit()
                await self._db.refresh(mem)
                return mem

        # No conflict — ADD new memory
        result = await self.write(
            user_id=user_id,
            content=new_content,
            source="diagnosis",
            ref_id=f"skill:{skill_id}" if skill_id else None,
        )
        result._conflict_resolved = False
        return result

    async def write_trap(
        self,
        user_id: int,
        tool_name_failed: str,
        error_message: str,
        fix_applied: str,
        task_type: Optional[str] = None,
        data_subject: Optional[str] = None,
    ) -> AgentMemoryModel:
        """v14.1: Negative Index / Trap — auto-write when tool returns error.

        Format: [Trap] tool=X | Error: ... | Rule: 下次遇到此情況應 ...
        Bound to tool_name metadata for precise pre-filtering.
        """
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        content = (
            f"[Trap] {ts} | 工具「{tool_name_failed}」發生錯誤 | "
            f"錯誤訊息: {error_message[:200]} | "
            f"修正規則: {fix_applied}"
        )
        return await self.write(
            user_id=user_id,
            content=content,
            source="trap",
            ref_id=None,
            task_type=task_type,
            data_subject=data_subject,
            tool_name=tool_name_failed,
        )

    async def write_ds_schema_lesson(
        self,
        user_id: int,
        ds_name: str,
        correct_fields: List[str],
        wrong_guess: Optional[str] = None,
    ) -> AgentMemoryModel:
        """v14.2 Lesson Learnt — DS Naming Convention.

        Called after a successful MCP Try-Run to persist the correct field
        names for a DataSubject.  On the next Try-Run for the same DS,
        Stage 1 pre-filter (data_subject=ds_name, task_type=mcp_draft)
        retrieves this lesson so the LLM uses correct column names on the
        first attempt — skipping the retry entirely.

        Args:
            ds_name: Name of the DataSubject / System MCP.
            correct_fields: List of verified column names from actual sample data.
            wrong_guess: Optional — what LLM guessed before (for richer lesson text).
        """
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        fields_str = ", ".join(correct_fields) if correct_fields else "（未知）"
        wrong_str = f" | LLM 錯誤猜測: {wrong_guess}" if wrong_guess else ""
        content = (
            f"[DS_Schema] {ts} | DS={ds_name} | "
            f"正確欄位: {fields_str}{wrong_str}"
        )
        return await self.write(
            user_id=user_id,
            content=content,
            source="ds_schema_lesson",
            task_type="mcp_draft",
            data_subject=ds_name,
        )

    async def write_preference(
        self,
        user_id: int,
        canvas_overrides: Dict[str, Any],
        task_type: Optional[str] = None,
        data_subject: Optional[str] = None,
    ) -> AgentMemoryModel:
        """v14.1: HITL Preference Write — persist canvas_overrides as user preference memory."""
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        overrides_text = "; ".join(f"{k}={v}" for k, v in canvas_overrides.items())
        content = (
            f"[使用者偏好] {ts} | "
            f"任務類型: {task_type or '未知'} | "
            f"資料對象: {data_subject or '未知'} | "
            f"調整: {overrides_text}"
        )
        return await self.write(
            user_id=user_id,
            content=content,
            source="hitl_preference",
            task_type=task_type,
            data_subject=data_subject,
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
            "task_type": getattr(m, "task_type", None),
            "data_subject": getattr(m, "data_subject", None),
            "tool_name": getattr(m, "tool_name", None),
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }


# ── Conflict Detection Helpers (module-level) ─────────────────────────────────

def _is_same_skill_target(
    memory_content: str,
    skill_name: str,
    targets: List[str],
) -> bool:
    """Check if a memory entry is about the same Skill + at least one target."""
    content_lower = memory_content.lower()
    if skill_name.lower() not in content_lower:
        return False
    return any(t.lower() in content_lower for t in targets if t)


def _is_contradictory(old_content: str, new_content: str) -> bool:
    """Detect logical contradiction between two diagnosis memory entries.

    v14 heuristic (SQLite-compatible, no embeddings):
    - Both must be [診斷記錄] entries
    - Old says NORMAL, new says ABNORMAL (or vice-versa) for the same object
    - OR old says ABNORMAL and new says NORMAL

    Semantic similarity > 0.9 threshold is approximated by shared token overlap.
    """
    if "[診斷記錄]" not in old_content or "[診斷記錄]" not in new_content:
        return False

    old_lower = old_content.lower()
    new_lower = new_content.lower()

    # Token overlap (similarity proxy)
    old_tokens = set(old_lower.split())
    new_tokens = set(new_lower.split())
    if not old_tokens or not new_tokens:
        return False
    overlap = len(old_tokens & new_tokens) / min(len(old_tokens), len(new_tokens))
    if overlap < 0.4:
        return False  # Too different — not about the same thing

    # Contradiction: one says NORMAL, other says ABNORMAL
    old_is_abnormal = "abnormal" in old_lower
    new_is_abnormal = "abnormal" in new_lower
    return old_is_abnormal != new_is_abnormal
