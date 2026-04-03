"""
Agent Draft Router - API v1

Manages agent draft responses and proposed actions.
Provides endpoints for saving, reviewing, and approving/rejecting agent drafts.

代理草案路由器 - API v1
管理代理草案回應和建議的操作。
提供保存、審查和批准/拒絕代理草案的端點。
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
from app.ontology.schemas.agent_session import AgentSessionRead
from app.ontology.schemas.common import ListResponse

# Draft status enum
class DraftStatus(str, Enum):
    """Status of an agent draft."""
    PROPOSED = "proposed"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


# Initialize router
router = APIRouter(
    prefix="/api/v1/agent-drafts",
    tags=["Agent Draft"],
)

# Initialize repository
agent_session_repo = AgentSessionRepository()

# In-memory draft storage (in production, use database)
# Format: {draft_id: {agent_id, status, content, timestamp, ...}}
drafts_store: dict = {}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create Agent Draft",
    description="Save a draft response from an agent for review.",
)
async def create_draft(
    agent_id: int,
    content: str,
    reasoning: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Create a draft response from agent.
    
    **Path:** `POST /api/v1/agent-drafts`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    - `content` (str): Draft content/response
    - `reasoning` (str, optional): Agent's reasoning
    
    **Returns:** { draft_id: str, agent_id: int, status: str, created_at: str }
    
    **Errors:**
    - 400: Invalid parameters
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error
    
    創建代理草案回應。
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
            detail="You do not have permission to create drafts for this agent",
        )
    
    # Generate draft ID
    import uuid
    draft_id = str(uuid.uuid4())
    
    # Store draft
    drafts_store[draft_id] = {
        "agent_id": agent_id,
        "user_id": current_user.id,
        "status": DraftStatus.PROPOSED,
        "content": content,
        "reasoning": reasoning,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "approved_by": None,
        "rejection_reason": None,
    }
    
    return {
        "draft_id": draft_id,
        "agent_id": agent_id,
        "status": DraftStatus.PROPOSED,
        "created_at": drafts_store[draft_id]["created_at"],
    }


@router.get(
    "",
    response_model=ListResponse[dict],
    status_code=status.HTTP_200_OK,
    summary="List Agent Drafts",
    description="List drafts with optional filtering by status.",
)
async def list_drafts(
    agent_id: Optional[int] = Query(None, description="Filter by agent ID"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[dict]:
    """
    List drafts for current user's agents.
    
    **Path:** `GET /api/v1/agent-drafts`
    
    **Query Parameters:**
    - `agent_id` (int, optional): Filter by specific agent
    - `status_filter` (str, optional): Filter by status
    - `skip` (int, default=0): Records to skip
    - `limit` (int, default=100): Max records to return
    
    **Returns:** ListResponse with array of drafts
    
    **Errors:**
    - 401: Unauthorized
    - 500: Server error
    
    列出代理草案。
    """
    # Get all drafts for user's agents
    user_drafts = []
    for draft_id, draft in drafts_store.items():
        # Skip if filtered by agent_id and doesn't match
        if agent_id and draft["agent_id"] != agent_id:
            continue
        
        # Skip if filtered by status and doesn't match
        if status_filter and draft["status"] != status_filter:
            continue
        
        # Only show drafts for user's agents (unless admin)
        if not current_user.is_admin:
            if draft["user_id"] != current_user.id:
                continue
        
        user_drafts.append({
            "draft_id": draft_id,
            **draft,
        })
    
    # Apply pagination
    total = len(user_drafts)
    paginated = user_drafts[skip:skip + limit]
    
    return ListResponse[dict](
        items=paginated,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{draft_id}",
    status_code=status.HTTP_200_OK,
    summary="Get Draft Details",
    description="Retrieve a specific draft by ID.",
)
async def get_draft(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Get a specific draft by ID.
    
    **Path:** `GET /api/v1/agent-drafts/{draft_id}`
    
    **Parameters:**
    - `draft_id` (str): Draft UUID
    
    **Returns:** Complete draft details
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied
    - 404: Draft not found
    - 500: Server error
    
    獲取草案詳情。
    """
    if draft_id not in drafts_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft with ID {draft_id} not found",
        )
    
    draft = drafts_store[draft_id]
    
    # Verify access
    if draft["user_id"] != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this draft",
        )
    
    return {
        "draft_id": draft_id,
        **draft,
    }


@router.post(
    "/{draft_id}/approve",
    status_code=status.HTTP_200_OK,
    summary="Approve Draft",
    description="Approve a draft and mark it for execution.",
)
async def approve_draft(
    draft_id: str,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Approve a draft.
    
    **Path:** `POST /api/v1/agent-drafts/{draft_id}/approve`
    
    **Parameters:**
    - `draft_id` (str): Draft UUID
    - `notes` (str, optional): Approval notes
    
    **Returns:** Updated draft with status = APPROVED
    
    **Errors:**
    - 400: Invalid state (already approved/rejected)
    - 401: Unauthorized
    - 403: Access denied
    - 404: Draft not found
    - 500: Server error
    
    批准草案。
    """
    if draft_id not in drafts_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft with ID {draft_id} not found",
        )
    
    draft = drafts_store[draft_id]
    
    # Verify access
    if draft["user_id"] != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to approve this draft",
        )
    
    # Verify state
    if draft["status"] in [DraftStatus.APPROVED, DraftStatus.REJECTED, DraftStatus.EXECUTED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve a draft with status {draft['status']}",
        )
    
    # Approve
    draft["status"] = DraftStatus.APPROVED
    draft["approved_by"] = current_user.id
    draft["approval_notes"] = notes
    draft["updated_at"] = datetime.utcnow().isoformat()
    
    return {
        "draft_id": draft_id,
        **draft,
    }


@router.post(
    "/{draft_id}/reject",
    status_code=status.HTTP_200_OK,
    summary="Reject Draft",
    description="Reject a draft with explanation.",
)
async def reject_draft(
    draft_id: str,
    reason: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Reject a draft.
    
    **Path:** `POST /api/v1/agent-drafts/{draft_id}/reject`
    
    **Parameters:**
    - `draft_id` (str): Draft UUID
    - `reason` (str, optional): Rejection reason
    
    **Returns:** Updated draft with status = REJECTED
    
    **Errors:**
    - 400: Invalid state
    - 401: Unauthorized
    - 403: Access denied
    - 404: Draft not found
    - 500: Server error
    
    拒絕草案。
    """
    if draft_id not in drafts_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft with ID {draft_id} not found",
        )
    
    draft = drafts_store[draft_id]
    
    # Verify access
    if draft["user_id"] != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to reject this draft",
        )
    
    # Verify state
    if draft["status"] in [DraftStatus.APPROVED, DraftStatus.REJECTED, DraftStatus.EXECUTED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject a draft with status {draft['status']}",
        )
    
    # Reject
    draft["status"] = DraftStatus.REJECTED
    draft["rejection_reason"] = reason
    draft["updated_at"] = datetime.utcnow().isoformat()
    
    return {
        "draft_id": draft_id,
        **draft,
    }


@router.post(
    "/{draft_id}/execute",
    status_code=status.HTTP_200_OK,
    summary="Execute Approved Draft",
    description="Execute an approved draft.",
)
async def execute_draft(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Execute an approved draft.
    
    **Path:** `POST /api/v1/agent-drafts/{draft_id}/execute`
    
    **Parameters:**
    - `draft_id` (str): Draft UUID (must be approved)
    
    **Returns:** { draft_id, status: EXECUTED, execution_result }
    
    **Errors:**
    - 400: Draft not approved
    - 401: Unauthorized
    - 403: Access denied
    - 404: Draft not found
    - 500: Server error / execution error
    
    執行已批准的草案。
    """
    if draft_id not in drafts_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft with ID {draft_id} not found",
        )
    
    draft = drafts_store[draft_id]
    
    # Verify access
    if draft["user_id"] != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to execute this draft",
        )
    
    # Verify status
    if draft["status"] != DraftStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Can only execute approved drafts (current status: {draft['status']})",
        )
    
    # Execute
    try:
        # In production, this would execute the draft content
        execution_result = {
            "success": True,
            "output": f"Executed draft: {draft['content'][:100]}...",
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        draft["status"] = DraftStatus.EXECUTED
        draft["execution_result"] = execution_result
        draft["updated_at"] = datetime.utcnow().isoformat()
        
        return {
            "draft_id": draft_id,
            **draft,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute draft: {str(e)}",
        )


@router.delete(
    "/{draft_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Draft",
    description="Delete a draft.",
)
async def delete_draft(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete a draft.
    
    **Path:** `DELETE /api/v1/agent-drafts/{draft_id}`
    
    **Parameters:**
    - `draft_id` (str): Draft UUID
    
    **Returns:** 204 No Content
    
    **Errors:**
    - 401: Unauthorized
    - 403: Access denied (not owner)
    - 404: Draft not found
    - 500: Server error
    
    刪除草案。
    """
    if draft_id not in drafts_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft with ID {draft_id} not found",
        )
    
    draft = drafts_store[draft_id]
    
    # Verify access (only owner or admin can delete)
    if draft["user_id"] != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this draft",
        )
    
    # Delete
    del drafts_store[draft_id]
