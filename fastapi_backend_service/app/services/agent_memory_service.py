"""Agent Memory Service v2 — Mem0-backed semantic long-term memory.

Architecture:
  Mem0 (cloud)  — general memories, preferences, success patterns, schema lessons
                  Benefits: semantic search, entity extraction, conflict detection
  Local DB      — structured logs that need ref_id / FK linkage:
                    • write_trap       (tool error patterns)
                    • write_diagnosis  (skill diagnosis records)

All callers use the same public API — migration is transparent.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_memory import AgentMemoryModel

logger = logging.getLogger(__name__)

_MAX_MEMORIES_PER_USER = 200  # local DB soft cap (trap/diagnosis only)
_MEM0_TIMEOUT = 5.0           # seconds — Mem0 calls are non-blocking on timeout


# ── Lightweight result type (mirrors AgentMemoryModel interface) ───────────────

@dataclass
class _MemResult:
    """Minimal stand-in for AgentMemoryModel returned from Mem0 results."""
    id: Any                              # Mem0 UUID string or local int
    content: str
    source: str = "mem0"
    ref_id: Optional[str] = None
    task_type: Optional[str] = None
    data_subject: Optional[str] = None
    tool_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    user_id: int = 0
    # Conflict resolution flag (used by orchestrator SSE)
    _conflict_resolved: bool = field(default=False, repr=False)


# ── Main Service ───────────────────────────────────────────────────────────────

class AgentMemoryService:
    """Unified memory service: Mem0 for semantic search, local DB for structured logs."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._mem0 = None
        self._init_mem0()

    def _init_mem0(self) -> None:
        try:
            from app.config import get_settings
            api_key = get_settings().MEM0_API_KEY
            if not api_key:
                logger.info("MEM0_API_KEY not set — memory service using local keyword fallback")
                return
            from mem0 import AsyncMemoryClient
            self._mem0 = AsyncMemoryClient(api_key=api_key)
            logger.info("Mem0 AsyncMemoryClient initialised")
        except Exception as exc:
            logger.warning("Mem0 init failed (%s) — falling back to local keyword search", exc)

    def _has_mem0(self) -> bool:
        return self._mem0 is not None

    # ── Read ──────────────────────────────────────────────────────────────────

    async def list(self, user_id: int, limit: int = 50) -> List[Any]:
        """List recent memories. Returns Mem0 results when available, else local DB."""
        if self._has_mem0():
            try:
                results = await asyncio.wait_for(
                    self._mem0.get_all(user_id=str(user_id)),
                    timeout=_MEM0_TIMEOUT,
                )
                items = results if isinstance(results, list) else results.get("results", [])
                return [_mem0_to_result(r) for r in items[:limit]]
            except Exception as exc:
                logger.warning("Mem0 list failed: %s", exc)

        # Fallback: local DB
        try:
            result = await self._db.execute(
                select(AgentMemoryModel)
                .where(AgentMemoryModel.user_id.in_([user_id, 0]))
                .order_by(AgentMemoryModel.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())
        except Exception as exc:
            logger.warning("Local memory list failed: %s", exc)
            return []

    async def get(self, memory_id: int) -> Optional[AgentMemoryModel]:
        """Get a local DB memory by ID (trap/diagnosis records)."""
        result = await self._db.execute(
            select(AgentMemoryModel).where(AgentMemoryModel.id == memory_id)
        )
        return result.scalar_one_or_none()

    async def search(
        self, user_id: int, query: str, top_k: int = 5
    ) -> List[Any]:
        """Semantic search via Mem0, keyword fallback on local DB."""
        if self._has_mem0():
            try:
                results = await asyncio.wait_for(
                    self._mem0.search(query, user_id=str(user_id), limit=top_k),
                    timeout=_MEM0_TIMEOUT,
                )
                items = results if isinstance(results, list) else results.get("results", [])
                return [_mem0_to_result(r) for r in items]
            except Exception as exc:
                logger.warning("Mem0 search failed: %s — falling back to keyword", exc)

        return await self._keyword_search(user_id, query, top_k)

    async def search_with_metadata(
        self,
        user_id: int,
        query: str,
        top_k: int = 5,
        task_type: Optional[str] = None,
        data_subject: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> tuple[List[Any], Dict[str, Any]]:
        """Semantic search with metadata context hint for Mem0."""
        filter_meta: Dict[str, Any] = {
            "task_type": task_type,
            "data_subject": data_subject,
            "tool_name": tool_name,
            "strategy": "mem0_semantic",
        }

        if self._has_mem0():
            try:
                # Enrich query with metadata context for better semantic matching
                enriched_query = _enrich_query(query, task_type, data_subject, tool_name)
                results = await asyncio.wait_for(
                    self._mem0.search(enriched_query, user_id=str(user_id), limit=top_k),
                    timeout=_MEM0_TIMEOUT,
                )
                items = results if isinstance(results, list) else results.get("results", [])
                memories = [_mem0_to_result(r) for r in items]
                filter_meta["strategy"] = "mem0_semantic"
                filter_meta["results_count"] = len(memories)
                return memories, filter_meta
            except Exception as exc:
                logger.warning("Mem0 search_with_metadata failed: %s — keyword fallback", exc)
                filter_meta["strategy"] = "keyword_fallback"

        # Fallback: local keyword search
        memories = await self._keyword_search(user_id, query, top_k)
        filter_meta["strategy"] = "keyword_local"
        return memories, filter_meta

    # ── Write (Mem0) ──────────────────────────────────────────────────────────

    async def write(
        self,
        user_id: int,
        content: str,
        source: str = "manual",
        ref_id: Optional[str] = None,
        task_type: Optional[str] = None,
        data_subject: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> Any:
        """Write a general memory to Mem0 (or local DB as fallback)."""
        if self._has_mem0():
            try:
                metadata = _build_metadata(source, ref_id, task_type, data_subject, tool_name)
                result = await asyncio.wait_for(
                    self._mem0.add(
                        [{"role": "user", "content": content}],
                        user_id=str(user_id),
                        metadata=metadata,
                    ),
                    timeout=_MEM0_TIMEOUT,
                )
                # Mem0 returns {"results": [{"id": ..., "memory": ..., "event": "ADD"|"UPDATE"}]}
                items = result if isinstance(result, list) else result.get("results", [])
                mem_id = items[0].get("id", "mem0") if items else "mem0"
                logger.info("Memory written to Mem0: user=%d source=%s id=%s", user_id, source, mem_id)
                return _MemResult(
                    id=mem_id,
                    content=content,
                    source=source,
                    ref_id=ref_id,
                    task_type=task_type,
                    data_subject=data_subject,
                    tool_name=tool_name,
                    created_at=datetime.now(tz=timezone.utc),
                )
            except Exception as exc:
                logger.warning("Mem0 write failed: %s — writing to local DB", exc)

        # Fallback: local DB
        return await self._write_local(
            user_id=user_id, content=content, source=source,
            ref_id=ref_id, task_type=task_type,
            data_subject=data_subject, tool_name=tool_name,
        )

    async def write_preference(
        self,
        user_id: int,
        canvas_overrides: Dict[str, Any],
        task_type: Optional[str] = None,
        data_subject: Optional[str] = None,
    ) -> Any:
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        overrides_text = "; ".join(f"{k}={v}" for k, v in canvas_overrides.items())
        content = (
            f"[使用者偏好] {ts} | "
            f"任務類型: {task_type or '未知'} | "
            f"資料對象: {data_subject or '未知'} | "
            f"調整: {overrides_text}"
        )
        return await self.write(
            user_id=user_id, content=content,
            source="hitl_preference",
            task_type=task_type, data_subject=data_subject,
        )

    async def write_ds_schema_lesson(
        self,
        user_id: int,
        ds_name: str,
        correct_fields: List[str],
        wrong_guess: Optional[str] = None,
    ) -> Any:
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        fields_str = ", ".join(correct_fields) if correct_fields else "（未知）"
        wrong_str = f" | LLM 錯誤猜測: {wrong_guess}" if wrong_guess else ""
        content = (
            f"[DS_Schema] {ts} | DS={ds_name} | "
            f"正確欄位: {fields_str}{wrong_str}"
        )
        return await self.write(
            user_id=user_id, content=content,
            source="ds_schema_lesson",
            task_type="mcp_draft", data_subject=ds_name,
        )

    # ── Write (Local DB — structured logs) ───────────────────────────────────

    async def write_diagnosis(
        self,
        user_id: int,
        skill_name: str,
        targets: List[str],
        diagnosis_message: str,
        skill_id: Optional[int] = None,
    ) -> Optional[Any]:
        """Diagnosis record → local DB (needs ref_id FK linkage)."""
        if not targets and not diagnosis_message:
            return None
        target_str = "、".join(targets) if targets else "未知目標"
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        content = (
            f"[診斷記錄] {ts} | Skill「{skill_name}」判定 ABNORMAL | "
            f"問題目標: {target_str} | 訊息: {diagnosis_message}"
        )
        return await self._write_local(
            user_id=user_id, content=content, source="diagnosis",
            ref_id=f"skill:{skill_id}" if skill_id else None,
        )

    async def write_diagnosis_with_conflict_check(
        self,
        user_id: int,
        skill_name: str,
        targets: List[str],
        diagnosis_message: str,
        skill_id: Optional[int] = None,
    ) -> Optional[Any]:
        """Conflict-aware diagnosis write.
        Uses Mem0 semantic search to detect contradictions when available,
        otherwise falls back to keyword matching on local DB.
        """
        if not targets and not diagnosis_message:
            return None

        target_str = "、".join(targets) if targets else "未知目標"
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        new_content = (
            f"[診斷記錄] {ts} | Skill「{skill_name}」判定 ABNORMAL | "
            f"問題目標: {target_str} | 訊息: {diagnosis_message}"
        )

        # Search for conflicting memories (same skill + target)
        query = f"{skill_name} {target_str}"
        similar = await self.search(user_id, query, top_k=5)

        for mem in similar:
            content_val = mem.content if hasattr(mem, "content") else str(mem.get("memory", ""))
            if not _is_same_skill_target(content_val, skill_name, targets):
                continue
            if _is_contradictory(content_val, new_content):
                logger.info(
                    "Memory conflict detected for Skill '%s' target '%s' — updating",
                    skill_name, target_str,
                )
                mem_id = mem.id if hasattr(mem, "id") else None
                # Update via Mem0 if available
                if self._has_mem0() and isinstance(mem_id, str):
                    try:
                        await asyncio.wait_for(
                            self._mem0.update(mem_id, new_content),
                            timeout=_MEM0_TIMEOUT,
                        )
                        result = _MemResult(
                            id=mem_id, content=new_content, source="diagnosis",
                            ref_id=f"skill:{skill_id}" if skill_id else None,
                        )
                        result._conflict_resolved = True
                        return result
                    except Exception as exc:
                        logger.warning("Mem0 update failed: %s", exc)
                # Fallback: update local DB record
                elif isinstance(mem, AgentMemoryModel):
                    mem.content = new_content
                    mem.updated_at = datetime.now(tz=timezone.utc)
                    mem._conflict_resolved = True
                    await self._db.commit()
                    await self._db.refresh(mem)
                    return mem

        # No conflict — write new
        result = await self.write_diagnosis(
            user_id=user_id, skill_name=skill_name,
            targets=targets, diagnosis_message=diagnosis_message,
            skill_id=skill_id,
        )
        if result:
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
    ) -> Any:
        """Trap / Negative Index → always local DB for fast structured access."""
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        content = (
            f"[Trap] {ts} | 工具「{tool_name_failed}」發生錯誤 | "
            f"錯誤訊息: {error_message[:200]} | "
            f"修正規則: {fix_applied}"
        )
        return await self._write_local(
            user_id=user_id, content=content, source="trap",
            task_type=task_type, data_subject=data_subject,
            tool_name=tool_name_failed,
        )

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete(self, memory_id: Any, user_id: int) -> bool:
        """Delete memory. Tries Mem0 first (UUID string), then local DB (int)."""
        if self._has_mem0() and isinstance(memory_id, str):
            try:
                await asyncio.wait_for(
                    self._mem0.delete(memory_id),
                    timeout=_MEM0_TIMEOUT,
                )
                return True
            except Exception as exc:
                logger.warning("Mem0 delete failed: %s", exc)

        # Local DB — allow admin (user_id=1) to delete any memory (incl. system user_id=0)
        if isinstance(memory_id, int):
            where_clause = [AgentMemoryModel.id == memory_id]
            if user_id != 1:
                where_clause.append(AgentMemoryModel.user_id == user_id)
            result = await self._db.execute(
                select(AgentMemoryModel).where(*where_clause)
            )
            memory = result.scalar_one_or_none()
            if not memory:
                return False
            await self._db.delete(memory)
            await self._db.commit()
            return True
        return False

    async def delete_by_source(self, user_id: int, source: str) -> int:
        """Delete all memories of a specific source type for a user."""
        result = await self._db.execute(
            select(AgentMemoryModel).where(
                AgentMemoryModel.user_id == user_id,
                AgentMemoryModel.source == source,
            )
        )
        memories = list(result.scalars().all())
        for m in memories:
            await self._db.delete(m)
        await self._db.commit()
        return len(memories)

    async def delete_all(self, user_id: int) -> int:
        """Delete all memories for a user from both Mem0 and local DB."""
        count = 0
        if self._has_mem0():
            try:
                await asyncio.wait_for(
                    self._mem0.delete_all(user_id=str(user_id)),
                    timeout=10.0,
                )
                count += 1  # Mem0 bulk delete — exact count not returned
            except Exception as exc:
                logger.warning("Mem0 delete_all failed: %s", exc)

        # Also clear local DB
        result = await self._db.execute(
            select(AgentMemoryModel).where(AgentMemoryModel.user_id == user_id)
        )
        memories = list(result.scalars().all())
        for m in memories:
            await self._db.delete(m)
        await self._db.commit()
        return count + len(memories)

    # ── Serialisation helper ──────────────────────────────────────────────────

    @staticmethod
    def to_dict(m: Any) -> Dict[str, Any]:
        if isinstance(m, AgentMemoryModel):
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
        # _MemResult or raw Mem0 dict
        return {
            "id": getattr(m, "id", None) or m.get("id"),
            "user_id": getattr(m, "user_id", 0),
            "content": getattr(m, "content", None) or m.get("memory", ""),
            "source": getattr(m, "source", "mem0"),
            "ref_id": getattr(m, "ref_id", None),
            "task_type": getattr(m, "task_type", None),
            "data_subject": getattr(m, "data_subject", None),
            "tool_name": getattr(m, "tool_name", None),
            "created_at": (
                m.created_at.isoformat()
                if hasattr(m, "created_at") and m.created_at
                else None
            ),
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _write_local(
        self,
        user_id: int,
        content: str,
        source: str,
        ref_id: Optional[str] = None,
        task_type: Optional[str] = None,
        data_subject: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> AgentMemoryModel:
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
        logger.info("Memory written to local DB: user=%d source=%s id=%d", user_id, source, memory.id)
        return memory

    async def _keyword_search(
        self, user_id: int, query: str, top_k: int
    ) -> List[AgentMemoryModel]:
        """SQLite-compatible keyword search on local DB (fallback)."""
        try:
            result = await self._db.execute(
                select(AgentMemoryModel)
                .where(AgentMemoryModel.user_id.in_([user_id, 0]))
                .order_by(AgentMemoryModel.created_at.desc())
                .limit(_MAX_MEMORIES_PER_USER)
            )
            all_memories = list(result.scalars().all())
        except OperationalError:
            await self._db.rollback()
            return []

        if not all_memories:
            return []

        tokens = [t.lower() for t in query.split() if len(t) > 1]
        if not tokens:
            return all_memories[:top_k]

        scored = []
        for m in all_memories:
            score = sum(1 for t in tokens if t in m.content.lower())
            if score > 0:
                scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:top_k]]


# ── Mem0 result adapter ────────────────────────────────────────────────────────

def _mem0_to_result(r: Any) -> _MemResult:
    """Convert a Mem0 search/list result dict to _MemResult."""
    if isinstance(r, dict):
        return _MemResult(
            id=r.get("id", ""),
            content=r.get("memory", r.get("content", "")),
            source=r.get("metadata", {}).get("source", "mem0") if isinstance(r.get("metadata"), dict) else "mem0",
            task_type=r.get("metadata", {}).get("task_type") if isinstance(r.get("metadata"), dict) else None,
            data_subject=r.get("metadata", {}).get("data_subject") if isinstance(r.get("metadata"), dict) else None,
            tool_name=r.get("metadata", {}).get("tool_name") if isinstance(r.get("metadata"), dict) else None,
            created_at=datetime.now(tz=timezone.utc),
        )
    return _MemResult(id=str(r), content=str(r))


def _build_metadata(
    source: str,
    ref_id: Optional[str],
    task_type: Optional[str],
    data_subject: Optional[str],
    tool_name: Optional[str],
) -> Dict[str, Any]:
    m: Dict[str, Any] = {"source": source}
    if ref_id:
        m["ref_id"] = ref_id
    if task_type:
        m["task_type"] = task_type
    if data_subject:
        m["data_subject"] = data_subject
    if tool_name:
        m["tool_name"] = tool_name
    return m


def _enrich_query(
    query: str,
    task_type: Optional[str],
    data_subject: Optional[str],
    tool_name: Optional[str],
) -> str:
    """Prepend metadata context to query for better Mem0 semantic matching."""
    parts = [query]
    if task_type:
        parts.append(f"task_type:{task_type}")
    if data_subject:
        parts.append(f"data_subject:{data_subject}")
    if tool_name:
        parts.append(f"tool:{tool_name}")
    return " ".join(parts)


# ── Conflict Detection Helpers ─────────────────────────────────────────────────

def _is_same_skill_target(
    memory_content: str,
    skill_name: str,
    targets: List[str],
) -> bool:
    content_lower = memory_content.lower()
    if skill_name.lower() not in content_lower:
        return False
    return any(t.lower() in content_lower for t in targets if t)


def _is_contradictory(old_content: str, new_content: str) -> bool:
    """Detect logical contradiction between two diagnosis entries.
    Both must be [診斷記錄]; one NORMAL and one ABNORMAL for the same subject.
    """
    if "[診斷記錄]" not in old_content or "[診斷記錄]" not in new_content:
        return False
    old_lower = old_content.lower()
    new_lower = new_content.lower()
    old_abnormal = "abnormal" in old_lower
    new_abnormal = "abnormal" in new_lower
    return old_abnormal != new_abnormal
