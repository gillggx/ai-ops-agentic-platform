"""
Agent Execute Router - API v1

Manages agent action execution and execution history.
Provides endpoints for executing pending actions and retrieving execution logs.

代理執行路由器 - API v1
管理代理操作執行和執行歷史。
提供執行待執行操作和檢索執行日誌的端點。
"""

from typing import Any, Dict, Optional
import json
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_active_user
from app.ontology.models import AgentSession, User
from app.ontology.repositories import AgentSessionRepository
from app.ontology.repositories.data_subject import DataSubjectRepository
from app.ontology.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.ontology.schemas.common import ListResponse
from app.services.mcp_builder_service import MCPBuilderService
from app.services.mcp_definition_service import MCPDefinitionService

# Execution status enum
class ExecutionStatus(str, Enum):
    """Status of an execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Initialize router
router = APIRouter(
    prefix="/api/v1/agent-execute",
    tags=["Agent Execute"],
)

# Initialize repository
agent_session_repo = AgentSessionRepository()

# In-memory execution logs storage
# Format: {execution_id: {agent_id, status, command, output, ...}}
executions_store: dict = {}


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    summary="Execute Agent Action",
    description="Execute a pending action from an agent.",
)
async def execute_action(
    agent_id: int,
    action: str,
    parameters: Optional[dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Execute an agent action.
    
    **Path:** `POST /api/v1/agent-execute`
    
    **Parameters:**
    - `agent_id` (int): Agent ID
    - `action` (str): Action to execute
    - `parameters` (dict, optional): Action parameters
    
    **Returns:** { 
        execution_id: str,
        status: str,
        agent_id: int,
        started_at: str (ISO timestamp),
        result: any (optional)
    }
    
    **Errors:**
    - 400: Invalid action
    - 401: Unauthorized
    - 403: Access denied
    - 404: Agent not found
    - 500: Server error / execution error
    
    執行代理操作。
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
            detail="You do not have permission to execute actions for this agent",
        )
    
    # Generate execution ID
    import uuid
    execution_id = str(uuid.uuid4())
    
    try:
        # Simulate action execution
        result = {
            "action": action,
            "parameters": parameters or {},
            "output": f"Executed action '{action}' successfully",
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Store execution
        executions_store[execution_id] = {
            "agent_id": agent_id,
            "user_id": current_user.id,
            "action": action,
            "parameters": parameters or {},
            "status": ExecutionStatus.COMPLETED,
            "result": result,
            "started_at": datetime.utcnow().isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
            "error": None,
        }
        
        return {
            "execution_id": execution_id,
            "status": ExecutionStatus.COMPLETED,
            "agent_id": agent_id,
            "started_at": executions_store[execution_id]["started_at"],
            "result": result,
        }
    except Exception as e:
        # Store failed execution
        executions_store[execution_id] = {
            "agent_id": agent_id,
            "user_id": current_user.id,
            "action": action,
            "parameters": parameters or {},
            "status": ExecutionStatus.FAILED,
            "started_at": datetime.utcnow().isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
            "error": str(e),
        }
        
        return {
            "execution_id": execution_id,
            "status": ExecutionStatus.FAILED,
            "agent_id": agent_id,
            "started_at": executions_store[execution_id]["started_at"],
            "error": str(e),
        }


@router.get(
    "/history",
    response_model=ListResponse[dict],
    status_code=status.HTTP_200_OK,
    summary="Get Execution History",
    description="Get execution history for an agent or user.",
)
async def get_execution_history(
    agent_id: Optional[int] = Query(None, description="Filter by agent ID"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[dict]:
    """
    Get execution history.
    
    **Path:** `GET /api/v1/agent-execute/history`
    
    **Query Parameters:**
    - `agent_id` (int, optional): Filter by agent ID
    - `status_filter` (str, optional): Filter by status
    - `skip` (int, default=0): Records to skip
    - `limit` (int, default=100): Max records to return
    
    **Returns:** ListResponse with array of executions
    
    **Errors:**
    - 401: Unauthorized
    - 500: Server error
    
    獲取執行歷史。
    """
    # Get user's executions
    user_executions = []
    for execution_id, execution in executions_store.items():
        # Skip if filtered by agent_id and doesn't match
        if agent_id and execution["agent_id"] != agent_id:
            continue
        
        # Skip if filtered by status and doesn't match
        if status_filter and execution["status"] != status_filter:
            continue
        
        # Only show executions for user's agents (unless admin)
        if not current_user.is_admin:
            if execution["user_id"] != current_user.id:
                continue
        
        user_executions.append({
            "execution_id": execution_id,
            **execution,
        })
    
    # Sort by started_at (most recent first)
    user_executions.sort(
        key=lambda x: x["started_at"],
        reverse=True
    )
    
    # Apply pagination
    total = len(user_executions)
    paginated = user_executions[skip:skip + limit]
    
    return ListResponse[dict](
        items=paginated,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/mcp/{mcp_id}",
    summary="Execute MCP",
    response_model=Dict[str, Any],
)
async def execute_mcp(
    mcp_id: int,
    body: Dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Execute a System or Custom MCP and return the Standard Payload.

    For mcp_type='system': proxies to the raw API endpoint (e.g. OntologySimulator).
    For mcp_type='custom': runs the stored processing_script against live data.
    """
    base_url = f"{request.url.scheme}://{request.url.netloc}"

    mcp_repo = MCPDefinitionRepository(db)
    svc = MCPDefinitionService(
        repo=mcp_repo,
        ds_repo=DataSubjectRepository(db),
        llm=MCPBuilderService(),
    )

    mcp_obj = await mcp_repo.get_by_id(mcp_id)
    if not mcp_obj:
        raise HTTPException(status_code=404, detail=f"MCP #{mcp_id} 不存在")
    mcp_name = mcp_obj.name

    result = await svc.run_with_data(mcp_id=mcp_id, raw_data=body, base_url=base_url)

    if not result.success or result.error:
        return {
            "status": "error",
            "mcp_id": mcp_id,
            "mcp_name": mcp_name,
            "error": result.error or "MCP 執行失敗（未知錯誤）",
            "llm_readable_data": {},
        }

    od = result.output_data if hasattr(result, "output_data") else {}
    dataset = od.get("dataset") or [] if isinstance(od, dict) else []
    preview = dataset[:10] if isinstance(dataset, list) else []
    return {
        "status": "success",
        "mcp_id": mcp_id,
        "mcp_name": mcp_name,
        "row_count": len(dataset) if isinstance(dataset, list) else 0,
        "output_data": od,
        "llm_readable_data": json.dumps(preview, ensure_ascii=False)[:3000],
    }
