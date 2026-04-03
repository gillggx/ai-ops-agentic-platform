"""
Agent Router - API v1

Manages agent lifecycle, configuration, and core operations.
Provides endpoints for creating agents, managing preferences, and querying status.

代理路由器 - API v1
管理代理生命週期、配置和核心操作。
提供創建代理、管理偏好和查詢狀態的端點。
"""

from typing import Optional
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_active_user
from app.ontology.models import AgentSession, User
from app.ontology.repositories import AgentSessionRepository
from app.ontology.schemas.agent_session import (
    AgentSessionCreate,
    AgentSessionRead,
    AgentSessionUpdate,
)
from app.ontology.schemas.common import ListResponse

# Initialize router
router = APIRouter(
    prefix="/api/v1/agents",
    tags=["Agent"],
)

# Initialize repository
agent_session_repo = AgentSessionRepository()


@router.post(
    "",
    response_model=AgentSessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Agent",
    description="Create a new agent session with system prompt and configuration.",
)
async def create_agent(
    schema: AgentSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> AgentSessionRead:
    """
    Create a new agent session.
    
    **Path:** `POST /api/v1/agents`
    
    **Parameters:**
    - `user_id` (int): User ID for the agent
    - `title` (str): Agent/session title
    - `system_prompt` (str): System prompt for the agent
    - `context_summary` (str, optional): Initial context
    
    **Returns:** AgentSessionRead with created agent details
    
    **Errors:**
    - 400: Invalid data
    - 401: Unauthorized
    - 500: Server error
    
    創建新的代理會話。
    """
    # Ensure user owns the session (non-admin users can only create for themselves)
    if not current_user.is_admin and schema.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only create agents for yourself",
        )
    
    # Create new agent session
    agent = AgentSession(
        user_id=schema.user_id,
        title=schema.title,
        system_prompt=schema.system_prompt,
        context_summary=schema.context_summary,
        message_count=0,
        is_active=True,
    )
    
    return await agent_session_repo.create(db, agent)


@router.get(
    "",
    response_model=ListResponse[AgentSessionRead],
    status_code=status.HTTP_200_OK,
    summary="List Agents",
    description="List user's agents with pagination.",
)
async def list_agents(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    active_only: bool = Query(True, description="Only return active agents"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[AgentSessionRead]:
    """
    List agents for current user.
    
    **Path:** `GET /api/v1/agents`
    
    **Query Parameters:**
    - `skip` (int, default=0): Records to skip for pagination
    - `limit` (int, default=100): Max records to return (1-1000)
    - `active_only` (bool, default=True): Only return active agents
    
    **Returns:** ListResponse with array of AgentSessionRead
    
    **Errors:**
    - 401: Unauthorized
    - 500: Server error
    
    列出用戶的代理。
    """
    # Get user's agents
    if current_user.is_admin:
        agents = await agent_session_repo.get_all(db, skip=skip, limit=limit)
        total = await agent_session_repo.count_all(db)
    else:
        agents = await agent_session_repo.get_by_filter(
            db,
            user_id=current_user.id,
            skip=skip,
            limit=limit,
        )
        all_agents = await agent_session_repo.get_by_filter(db, user_id=current_user.id)
        total = len(all_agents)
    
    # Filter by active status if requested
    if active_only:
        agents = [a for a in agents if a.is_active]
    
    return ListResponse[AgentSessionRead](
        items=agents,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{agent_id}",
    response_model=AgentSessionRead,
    status_code=status.HTTP_200_OK,
    summary="Get Agent",
    description="Retrieve a specific agent by ID.",
)
async def get_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> AgentSessionRead:
    """
    Get a specific agent by ID.
    
    **Path:** `GET /api/v1/agents/{agent_id}`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    
    **Returns:** AgentSessionRead
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied (not owner)
    - 404: Agent not found
    - 500: Server error
    
    獲取特定的代理。
    """
    agent = await agent_session_repo.get_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found",
        )
    
    # Verify ownership or admin
    if agent.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this agent",
        )
    
    return agent


@router.put(
    "/{agent_id}",
    response_model=AgentSessionRead,
    status_code=status.HTTP_200_OK,
    summary="Update Agent",
    description="Update an existing agent configuration.",
)
async def update_agent(
    agent_id: int,
    schema: AgentSessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> AgentSessionRead:
    """
    Update an existing agent.
    
    **Path:** `PUT /api/v1/agents/{agent_id}`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    - Request body: AgentSessionUpdate fields to update
    
    **Returns:** Updated AgentSessionRead
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error
    
    更新現有的代理。
    """
    agent = await agent_session_repo.get_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found",
        )
    
    # Verify ownership or admin
    if agent.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this agent",
        )
    
    # Update fields
    if schema.title is not None:
        agent.title = schema.title
    if schema.system_prompt is not None:
        agent.system_prompt = schema.system_prompt
    if schema.is_active is not None:
        agent.is_active = schema.is_active
    if schema.context_summary is not None:
        agent.context_summary = schema.context_summary
    
    return await agent_session_repo.update(db, agent)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Agent",
    description="Delete an agent and all its data.",
)
async def delete_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete an agent.
    
    **Path:** `DELETE /api/v1/agents/{agent_id}`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    
    **Returns:** 204 No Content
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error
    
    刪除代理及其所有數據。
    """
    agent = await agent_session_repo.get_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found",
        )
    
    # Verify ownership or admin
    if agent.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this agent",
        )
    
    await agent_session_repo.delete(db, agent)


@router.post(
    "/{agent_id}/activate",
    response_model=AgentSessionRead,
    status_code=status.HTTP_200_OK,
    summary="Activate Agent",
    description="Activate a deactivated agent.",
)
async def activate_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> AgentSessionRead:
    """
    Activate an agent.
    
    **Path:** `POST /api/v1/agents/{agent_id}/activate`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    
    **Returns:** Updated AgentSessionRead
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error
    
    激活代理。
    """
    agent = await agent_session_repo.get_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found",
        )
    
    # Verify ownership
    if agent.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this agent",
        )
    
    agent.is_active = True
    return await agent_session_repo.update(db, agent)


@router.post(
    "/{agent_id}/deactivate",
    response_model=AgentSessionRead,
    status_code=status.HTTP_200_OK,
    summary="Deactivate Agent",
    description="Deactivate an active agent.",
)
async def deactivate_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> AgentSessionRead:
    """
    Deactivate an agent.
    
    **Path:** `POST /api/v1/agents/{agent_id}/deactivate`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    
    **Returns:** Updated AgentSessionRead
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error
    
    停用代理。
    """
    agent = await agent_session_repo.get_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found",
        )
    
    # Verify ownership
    if agent.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this agent",
        )
    
    agent.is_active = False
    return await agent_session_repo.update(db, agent)


@router.get(
    "/{agent_id}/status",
    status_code=status.HTTP_200_OK,
    summary="Get Agent Status",
    description="Get detailed status of an agent including message count and last activity.",
)
async def get_agent_status(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Get agent status.
    
    **Path:** `GET /api/v1/agents/{agent_id}/status`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    
    **Returns:** { 
        agent_id: int,
        is_active: bool,
        message_count: int,
        title: str,
        last_activity_at: str (ISO timestamp)
    }
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error
    
    獲取代理狀態。
    """
    agent = await agent_session_repo.get_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found",
        )
    
    # Verify ownership
    if agent.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this agent",
        )
    
    return {
        "agent_id": agent.id,
        "is_active": agent.is_active,
        "message_count": agent.message_count,
        "title": agent.title,
        "last_activity_at": agent.last_activity_at.isoformat() if agent.last_activity_at else None,
    }


@router.post(
    "/{agent_id}/reset-context",
    response_model=AgentSessionRead,
    status_code=status.HTTP_200_OK,
    summary="Reset Agent Context",
    description="Reset the agent's context and message history.",
)
async def reset_agent_context(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> AgentSessionRead:
    """
    Reset agent context and message history.
    
    **Path:** `POST /api/v1/agents/{agent_id}/reset-context`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    
    **Returns:** Updated AgentSessionRead
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error
    
    重置代理上下文和消息歷史。
    """
    agent = await agent_session_repo.get_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found",
        )
    
    # Verify ownership
    if agent.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this agent",
        )
    
    # Reset context
    agent.context_summary = None
    agent.message_count = 0
    
    return await agent_session_repo.update(db, agent)
