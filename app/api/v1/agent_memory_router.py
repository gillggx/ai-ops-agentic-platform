"""
Agent Memory Router - API v1

Manages agent memory (facts, insights, learned patterns).
Provides endpoints for storing, retrieving, and searching agent memories.

代理記憶路由器 - API v1
管理代理記憶（事實、見解、學習的模式）。
提供存儲、檢索和搜索代理記憶的端點。
"""

from typing import Optional
import json
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_active_user
from app.ontology.models import AgentSession, User
from app.ontology.repositories import AgentSessionRepository
from app.ontology.schemas.common import ListResponse

# Memory type enum
class MemoryType(str, Enum):
    """Type of memory."""
    FACT = "fact"
    INSIGHT = "insight"
    CONTEXT = "context"
    LEARNED_PATTERN = "learned_pattern"


# Initialize router
router = APIRouter(
    prefix="/api/v1/agent-memory",
    tags=["Agent Memory"],
)

# Initialize repository
agent_session_repo = AgentSessionRepository()

# In-memory memory storage
# Format: {memory_id: {agent_id, memory_type, content, importance, ...}}
memory_store: dict = {}


@router.post(
    "/{agent_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Create Memory",
    description="Store a new memory for an agent.",
)
async def create_memory(
    agent_id: int,
    memory_type: str,
    content: str,
    importance: float = 0.5,
    tags: Optional[list[str]] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Create a new memory for an agent.
    
    **Path:** `POST /api/v1/agent-memory/{agent_id}`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    - `memory_type` (str): Type of memory (fact, insight, context, learned_pattern)
    - `content` (str): Memory content
    - `importance` (float, 0-1): Importance score
    - `tags` (list[str], optional): Tags for searching
    
    **Returns:** {
        memory_id: str,
        agent_id: int,
        memory_type: str,
        content: str,
        importance: float,
        created_at: str
    }
    
    **Errors:**
    - 400: Invalid memory type or parameters
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error
    
    為代理創建新的記憶。
    """
    # Verify agent exists and user owns it
    agent = await agent_session_repo.get_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found",
        )
    
    if agent.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to create memories for this agent",
        )
    
    # Validate memory type
    try:
        MemoryType(memory_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid memory type. Must be one of: {', '.join([t.value for t in MemoryType])}",
        )
    
    # Validate importance
    if not (0.0 <= importance <= 1.0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Importance must be between 0.0 and 1.0",
        )
    
    # Generate memory ID
    import uuid
    memory_id = str(uuid.uuid4())
    
    # Store memory
    memory_store[memory_id] = {
        "agent_id": agent_id,
        "user_id": current_user.id,
        "memory_type": memory_type,
        "content": content,
        "importance": importance,
        "tags": tags or [],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "access_count": 0,
    }
    
    return {
        "memory_id": memory_id,
        "agent_id": agent_id,
        "memory_type": memory_type,
        "content": content,
        "importance": importance,
        "created_at": memory_store[memory_id]["created_at"],
    }


@router.get(
    "/{agent_id}",
    response_model=ListResponse[dict],
    status_code=status.HTTP_200_OK,
    summary="List Agent Memories",
    description="List memories for an agent with filtering.",
)
async def list_memories(
    agent_id: int,
    memory_type: Optional[str] = Query(None, description="Filter by memory type"),
    min_importance: float = Query(0.0, ge=0.0, le=1.0, description="Minimum importance"),
    tags: Optional[list[str]] = Query(None, description="Filter by tags"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[dict]:
    """
    List agent memories with filtering.
    
    **Path:** `GET /api/v1/agent-memory/{agent_id}`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    
    **Query Parameters:**
    - `memory_type` (str, optional): Filter by type
    - `min_importance` (float, 0-1): Minimum importance threshold
    - `tags` (list[str], optional): Filter by tags
    - `skip` (int, default=0): Records to skip
    - `limit` (int, default=100): Max records to return
    
    **Returns:** ListResponse with array of memories
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error
    
    列出代理記憶。
    """
    # Verify agent exists and user owns it
    agent = await agent_session_repo.get_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found",
        )
    
    if agent.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this agent's memories",
        )
    
    # Get agent's memories
    agent_memories = []
    for memory_id, memory in memory_store.items():
        if memory["agent_id"] != agent_id:
            continue
        
        # Filter by type if specified
        if memory_type and memory["memory_type"] != memory_type:
            continue
        
        # Filter by importance
        if memory["importance"] < min_importance:
            continue
        
        # Filter by tags if specified
        if tags:
            if not any(tag in memory["tags"] for tag in tags):
                continue
        
        agent_memories.append({
            "memory_id": memory_id,
            **memory,
        })
    
    # Sort by importance (descending) then by recency
    agent_memories.sort(
        key=lambda x: (-x["importance"], x["updated_at"]),
        reverse=True
    )
    
    # Apply pagination
    total = len(agent_memories)
    paginated = agent_memories[skip:skip + limit]
    
    return ListResponse[dict](
        items=paginated,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.put(
    "/{memory_id}",
    status_code=status.HTTP_200_OK,
    summary="Update Memory",
    description="Update an existing memory.",
)
async def update_memory(
    memory_id: str,
    content: Optional[str] = None,
    importance: Optional[float] = None,
    tags: Optional[list[str]] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Update an existing memory.
    
    **Path:** `PUT /api/v1/agent-memory/{memory_id}`
    
    **Parameters:**
    - `memory_id` (str): Memory ID
    - `content` (str, optional): New content
    - `importance` (float, optional): New importance score
    - `tags` (list[str], optional): New tags
    
    **Returns:** Updated memory
    
    **Errors:**
    - 400: Invalid parameters
    - 401: Unauthorized
    - 403: Access denied
    - 404: Memory not found
    - 500: Server error
    
    更新現有的記憶。
    """
    if memory_id not in memory_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory with ID {memory_id} not found",
        )
    
    memory = memory_store[memory_id]
    
    # Verify access
    if memory["user_id"] != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this memory",
        )
    
    # Update fields
    if content is not None:
        memory["content"] = content
    if importance is not None:
        if not (0.0 <= importance <= 1.0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Importance must be between 0.0 and 1.0",
            )
        memory["importance"] = importance
    if tags is not None:
        memory["tags"] = tags
    
    memory["updated_at"] = datetime.utcnow().isoformat()
    
    return {
        "memory_id": memory_id,
        **memory,
    }


@router.delete(
    "/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Memory",
    description="Delete a memory.",
)
async def delete_memory(
    memory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete a memory.
    
    **Path:** `DELETE /api/v1/agent-memory/{memory_id}`
    
    **Parameters:**
    - `memory_id` (str): Memory ID
    
    **Returns:** 204 No Content
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Memory not found
    - 500: Server error
    
    刪除記憶。
    """
    if memory_id not in memory_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory with ID {memory_id} not found",
        )
    
    memory = memory_store[memory_id]
    
    # Verify access
    if memory["user_id"] != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this memory",
        )
    
    del memory_store[memory_id]
