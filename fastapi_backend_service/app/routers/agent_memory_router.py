"""Agent Memory Router — CRUD + search for long-term RAG memories.

GET    /agent/memory              — list user's memories
POST   /agent/memory              — manually save a memory
DELETE /agent/memory/{id}         — delete a specific memory
DELETE /agent/memory              — delete ALL memories for user (reset)
GET    /agent/memory/search?q=    — keyword search
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.services.agent_memory_service import AgentMemoryService

router = APIRouter(prefix="/agent", tags=["agent-v13"])


class MemoryWriteRequest(BaseModel):
    content: str
    source: Optional[str] = "manual"
    ref_id: Optional[str] = None


@router.get("/memory/search", summary="語意搜尋長期記憶")
async def search_memory(
    q: str = Query(..., description="搜尋關鍵字"),
    top_k: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    svc = AgentMemoryService(db)
    memories = await svc.search(current_user.id, query=q, top_k=top_k)
    return {
        "status": "success",
        "query": q,
        "count": len(memories),
        "memories": [AgentMemoryService.to_dict(m) for m in memories],
    }


@router.get("/memory", summary="列出長期記憶")
async def list_memory(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    svc = AgentMemoryService(db)
    memories = await svc.list(current_user.id, limit=limit)
    return {
        "status": "success",
        "count": len(memories),
        "memories": [AgentMemoryService.to_dict(m) for m in memories],
    }


@router.post("/memory", summary="手動儲存記憶")
async def save_memory(
    body: MemoryWriteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    svc = AgentMemoryService(db)
    m = await svc.write(
        user_id=current_user.id,
        content=body.content,
        source=body.source or "manual",
        ref_id=body.ref_id,
    )
    return {"status": "success", "memory": AgentMemoryService.to_dict(m)}


@router.delete("/memory/{memory_id}", summary="刪除指定記憶")
async def delete_memory(
    memory_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    svc = AgentMemoryService(db)
    deleted = await svc.delete(memory_id, user_id=current_user.id)
    if not deleted:
        raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Memory id={memory_id} 不存在或無權限")
    return {"status": "success", "deleted_id": memory_id}


@router.delete("/memory", summary="清除所有記憶 (重置)")
async def delete_all_memory(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    svc = AgentMemoryService(db)
    count = await svc.delete_all(current_user.id)
    return {"status": "success", "deleted_count": count}
