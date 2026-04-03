"""
Agent Preference Router - API v1

Manages agent preferences, configuration, and personalization.
Provides endpoints for setting and retrieving agent preferences.

代理偏好路由器 - API v1
管理代理偏好、配置和個性化。
提供設置和檢索代理偏好的端點。
"""

from typing import Optional
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_active_user
from app.ontology.models import AgentSession, User
from app.ontology.repositories import AgentSessionRepository
from app.ontology.schemas.common import ListResponse

# Initialize router
router = APIRouter(
    prefix="/api/v1/agent-preferences",
    tags=["Agent Preference"],
)

# Initialize repository
agent_session_repo = AgentSessionRepository()

# In-memory preferences storage
# Format: {preference_id: {agent_id, key, value, category, ...}}
preferences_store: dict = {}


@router.post(
    "/{agent_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Set Agent Preference",
    description="Set a preference for an agent.",
)
async def set_preference(
    agent_id: int,
    key: str,
    value: str,
    category: str = "general",
    description: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Set an agent preference.
    
    **Path:** `POST /api/v1/agent-preferences/{agent_id}`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    - `key` (str): Preference key
    - `value` (str): Preference value
    - `category` (str, default="general"): Preference category
    - `description` (str, optional): Preference description
    
    **Returns:** {
        preference_id: str,
        agent_id: int,
        key: str,
        value: str,
        category: str,
        created_at: str
    }
    
    **Errors:**
    - 400: Invalid parameters
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error
    
    設置代理偏好。
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
            detail="You do not have permission to set preferences for this agent",
        )
    
    # Generate preference ID
    import uuid
    preference_id = str(uuid.uuid4())
    
    # Store preference
    preferences_store[preference_id] = {
        "agent_id": agent_id,
        "user_id": current_user.id,
        "key": key,
        "value": value,
        "category": category,
        "description": description,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    
    return {
        "preference_id": preference_id,
        "agent_id": agent_id,
        "key": key,
        "value": value,
        "category": category,
        "created_at": preferences_store[preference_id]["created_at"],
    }


@router.get(
    "/{agent_id}",
    response_model=ListResponse[dict],
    status_code=status.HTTP_200_OK,
    summary="List Agent Preferences",
    description="List preferences for an agent.",
)
async def list_preferences(
    agent_id: int,
    category: Optional[str] = Query(None, description="Filter by category"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[dict]:
    """
    List agent preferences.
    
    **Path:** `GET /api/v1/agent-preferences/{agent_id}`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    
    **Query Parameters:**
    - `category` (str, optional): Filter by category
    - `skip` (int, default=0): Records to skip
    - `limit` (int, default=100): Max records to return
    
    **Returns:** ListResponse with array of preferences
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error
    
    列出代理偏好。
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
            detail="You do not have permission to access this agent's preferences",
        )
    
    # Get agent's preferences
    agent_prefs = []
    for preference_id, pref in preferences_store.items():
        if pref["agent_id"] != agent_id:
            continue
        
        # Filter by category if specified
        if category and pref["category"] != category:
            continue
        
        agent_prefs.append({
            "preference_id": preference_id,
            **pref,
        })
    
    # Sort by category then key
    agent_prefs.sort(key=lambda x: (x["category"], x["key"]))
    
    # Apply pagination
    total = len(agent_prefs)
    paginated = agent_prefs[skip:skip + limit]
    
    return ListResponse[dict](
        items=paginated,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{agent_id}/{key}",
    status_code=status.HTTP_200_OK,
    summary="Get Preference Value",
    description="Get a specific preference value for an agent.",
)
async def get_preference(
    agent_id: int,
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Get a specific preference value.
    
    **Path:** `GET /api/v1/agent-preferences/{agent_id}/{key}`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    - `key` (str): Preference key
    
    **Returns:** { key, value, category, description }
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent or preference not found
    - 500: Server error
    
    獲取特定偏好值。
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
            detail="You do not have permission to access this agent's preferences",
        )
    
    # Find preference
    for preference_id, pref in preferences_store.items():
        if pref["agent_id"] == agent_id and pref["key"] == key:
            return {
                "preference_id": preference_id,
                **pref,
            }
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Preference '{key}' not found for agent {agent_id}",
    )


@router.put(
    "/{agent_id}/{key}",
    status_code=status.HTTP_200_OK,
    summary="Update Preference",
    description="Update a preference value.",
)
async def update_preference(
    agent_id: int,
    key: str,
    value: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Update a preference value.
    
    **Path:** `PUT /api/v1/agent-preferences/{agent_id}/{key}`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    - `key` (str): Preference key
    - `value` (str): New value
    
    **Returns:** Updated preference
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent or preference not found
    - 500: Server error
    
    更新偏好值。
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
            detail="You do not have permission to modify this agent's preferences",
        )
    
    # Find and update preference
    for preference_id, pref in preferences_store.items():
        if pref["agent_id"] == agent_id and pref["key"] == key:
            pref["value"] = value
            pref["updated_at"] = datetime.utcnow().isoformat()
            return {
                "preference_id": preference_id,
                **pref,
            }
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Preference '{key}' not found for agent {agent_id}",
    )


@router.delete(
    "/{agent_id}/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Preference",
    description="Delete a preference.",
)
async def delete_preference(
    agent_id: int,
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete a preference.
    
    **Path:** `DELETE /api/v1/agent-preferences/{agent_id}/{key}`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    - `key` (str): Preference key
    
    **Returns:** 204 No Content
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent or preference not found
    - 500: Server error
    
    刪除偏好。
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
            detail="You do not have permission to modify this agent's preferences",
        )
    
    # Find and delete preference
    for preference_id, pref in preferences_store.items():
        if pref["agent_id"] == agent_id and pref["key"] == key:
            del preferences_store[preference_id]
            return
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Preference '{key}' not found for agent {agent_id}",
    )
