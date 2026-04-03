"""
Agent Tool Router - API v1

Manages agent tools and tool access permissions.
Provides endpoints for registering, configuring, and executing tools.

代理工具路由器 - API v1
管理代理工具和工具訪問權限。
提供註冊、配置和執行工具的端點。
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
    prefix="/api/v1/agent-tools",
    tags=["Agent Tool"],
)

# Initialize repository
agent_session_repo = AgentSessionRepository()

# In-memory tool registry
# Format: {tool_id: {name, description, category, agent_ids, enabled, ...}}
tools_store: dict = {}

# Tool access tracking
# Format: {access_id: {agent_id, tool_id, access_granted, created_at, ...}}
access_store: dict = {}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Register Tool",
    description="Register a new tool in the system.",
)
async def register_tool(
    name: str,
    description: str,
    category: str,
    params: Optional[dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Register a new tool.
    
    **Path:** `POST /api/v1/agent-tools`
    
    **Parameters:**
    - `name` (str): Tool name
    - `description` (str): Tool description
    - `category` (str): Tool category (analytics, data, control, etc.)
    - `params` (dict, optional): Tool parameters schema
    
    **Returns:** {
        tool_id: str,
        name: str,
        category: str,
        enabled: bool,
        created_at: str
    }
    
    **Errors:**
    - 400: Invalid parameters
    - 401: Unauthorized (admin only)
    - 500: Server error
    
    註冊新工具。
    """
    # Verify admin
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can register tools",
        )
    
    # Check for duplicate tool name
    for tool in tools_store.values():
        if tool["name"] == name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tool '{name}' already exists",
            )
    
    # Generate tool ID
    import uuid
    tool_id = str(uuid.uuid4())
    
    # Store tool
    tools_store[tool_id] = {
        "name": name,
        "description": description,
        "category": category,
        "params": params or {},
        "enabled": True,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "usage_count": 0,
    }
    
    return {
        "tool_id": tool_id,
        "name": name,
        "category": category,
        "enabled": True,
        "created_at": tools_store[tool_id]["created_at"],
    }


@router.get(
    "",
    response_model=ListResponse[dict],
    status_code=status.HTTP_200_OK,
    summary="List Tools",
    description="List available tools with optional filtering.",
)
async def list_tools(
    category: Optional[str] = Query(None, description="Filter by category"),
    enabled_only: bool = Query(True, description="Only return enabled tools"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[dict]:
    """
    List available tools.
    
    **Path:** `GET /api/v1/agent-tools`
    
    **Query Parameters:**
    - `category` (str, optional): Filter by category
    - `enabled_only` (bool, default=True): Only return enabled tools
    - `skip` (int, default=0): Records to skip
    - `limit` (int, default=100): Max records to return
    
    **Returns:** ListResponse with array of tools
    
    **Errors:**
    - 401: Unauthorized
    - 500: Server error
    
    列出可用工具。
    """
    # Get all tools
    all_tools = []
    for tool_id, tool in tools_store.items():
        # Filter by enabled status if requested
        if enabled_only and not tool["enabled"]:
            continue
        
        # Filter by category if specified
        if category and tool["category"] != category:
            continue
        
        all_tools.append({
            "tool_id": tool_id,
            **tool,
        })
    
    # Sort by name
    all_tools.sort(key=lambda x: x["name"])
    
    # Apply pagination
    total = len(all_tools)
    paginated = all_tools[skip:skip + limit]
    
    return ListResponse[dict](
        items=paginated,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/{tool_id}/grant/{agent_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Grant Tool Access",
    description="Grant an agent access to a tool.",
)
async def grant_tool_access(
    tool_id: str,
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Grant tool access to an agent.
    
    **Path:** `POST /api/v1/agent-tools/{tool_id}/grant/{agent_id}`
    
    **Parameters:**
    - `tool_id` (str): Tool ID
    - `agent_id` (int): Agent ID
    
    **Returns:** { access_id, tool_id, agent_id, access_granted, created_at }
    
    **Errors:**
    - 400: Tool not found or access already granted
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error
    
    向代理授予工具訪問權限。
    """
    # Verify admin
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can grant tool access",
        )
    
    # Verify tool exists
    if tool_id not in tools_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool with ID {tool_id} not found",
        )
    
    # Verify agent exists
    agent = await agent_session_repo.get_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found",
        )
    
    # Check for duplicate access
    for access in access_store.values():
        if access["tool_id"] == tool_id and access["agent_id"] == agent_id and access["access_granted"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent already has access to this tool",
            )
    
    # Generate access ID
    import uuid
    access_id = str(uuid.uuid4())
    
    # Store access
    access_store[access_id] = {
        "tool_id": tool_id,
        "agent_id": agent_id,
        "access_granted": True,
        "created_at": datetime.utcnow().isoformat(),
    }
    
    return {
        "access_id": access_id,
        "tool_id": tool_id,
        "agent_id": agent_id,
        "access_granted": True,
        "created_at": access_store[access_id]["created_at"],
    }


@router.delete(
    "/{tool_id}/revoke/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke Tool Access",
    description="Revoke an agent's access to a tool.",
)
async def revoke_tool_access(
    tool_id: str,
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Revoke tool access from an agent.
    
    **Path:** `DELETE /api/v1/agent-tools/{tool_id}/revoke/{agent_id}`
    
    **Parameters:**
    - `tool_id` (str): Tool ID
    - `agent_id` (int): Agent ID
    
    **Returns:** 204 No Content
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied (admin only)
    - 404: Access not found
    - 500: Server error
    
    撤銷代理對工具的訪問權限。
    """
    # Verify admin
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can revoke tool access",
        )
    
    # Find and delete access
    for access_id, access in list(access_store.items()):
        if access["tool_id"] == tool_id and access["agent_id"] == agent_id:
            del access_store[access_id]
            return
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No access found for agent {agent_id} to tool {tool_id}",
    )


@router.get(
    "/{agent_id}/available",
    response_model=ListResponse[dict],
    status_code=status.HTTP_200_OK,
    summary="Get Agent's Available Tools",
    description="Get list of tools available to an agent.",
)
async def get_agent_available_tools(
    agent_id: int,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[dict]:
    """
    Get tools available to an agent.
    
    **Path:** `GET /api/v1/agent-tools/{agent_id}/available`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    
    **Query Parameters:**
    - `skip` (int, default=0): Records to skip
    - `limit` (int, default=100): Max records to return
    
    **Returns:** ListResponse with array of available tools
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied (not owner or admin)
    - 404: Agent not found
    - 500: Server error
    
    獲取代理可用的工具。
    """
    # Verify agent exists and user owns it or is admin
    agent = await agent_session_repo.get_by_id(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found",
        )
    
    if agent.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this agent's tools",
        )
    
    # Get tools granted to agent
    agent_tool_ids = set()
    for access in access_store.values():
        if access["agent_id"] == agent_id and access["access_granted"]:
            agent_tool_ids.add(access["tool_id"])
    
    # Get tool details
    available_tools = []
    for tool_id in agent_tool_ids:
        if tool_id in tools_store and tools_store[tool_id]["enabled"]:
            available_tools.append({
                "tool_id": tool_id,
                **tools_store[tool_id],
            })
    
    # Sort by category then name
    available_tools.sort(key=lambda x: (x["category"], x["name"]))
    
    # Apply pagination
    total = len(available_tools)
    paginated = available_tools[skip:skip + limit]
    
    return ListResponse[dict](
        items=paginated,
        total=total,
        skip=skip,
        limit=limit,
    )
