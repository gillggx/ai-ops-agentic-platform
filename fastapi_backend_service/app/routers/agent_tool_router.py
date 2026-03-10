"""Agent Tool Router — v15.0 JIT Analyst.

Endpoints for the per-user Agent Tool Chest:
  GET    /agent-tools            — list all tools for current user
  POST   /agent-tools            — manually save a tool
  GET    /agent-tools/{id}       — get a single tool (with full code)
  DELETE /agent-tools/{id}       — delete a tool
  POST   /agent-tools/{id}/execute — run tool code in sandbox with provided data
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.dependencies import get_current_user, get_db
from app.services.agent_tool_service import AgentToolService
from app.services import sandbox_service

router = APIRouter(prefix="/agent-tools", tags=["agent-tools"])


class AgentToolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=1)
    description: str = Field(default="")


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=Dict[str, Any])
async def list_agent_tools(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    svc = AgentToolService(db)
    tools = await svc.get_all(user_id=current_user.id)
    return StandardResponse.success(
        data={"items": [AgentToolService.to_dict(t) for t in tools], "total": len(tools)},
        message=f"Found {len(tools)} agent tools",
    )


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_agent_tool(
    body: AgentToolCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    svc = AgentToolService(db)
    tool = await svc.create(
        user_id=current_user.id,
        name=body.name,
        code=body.code,
        description=body.description,
    )
    return StandardResponse.success(
        data=AgentToolService.to_dict(tool),
        message="Agent tool saved",
    )


@router.get("/{tool_id}", response_model=Dict[str, Any])
async def get_agent_tool(
    tool_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    svc = AgentToolService(db)
    tool = await svc.get_by_id(tool_id)
    if not tool or tool.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Agent tool not found")
    data = AgentToolService.to_dict(tool)
    data["code"] = tool.code  # include full code in single-item view
    return StandardResponse.success(data=data)


@router.delete("/{tool_id}", response_model=Dict[str, Any])
async def delete_agent_tool(
    tool_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    svc = AgentToolService(db)
    tool = await svc.get_by_id(tool_id)
    if not tool or tool.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Agent tool not found")
    await db.delete(tool)
    await db.commit()
    return StandardResponse.success(message="Agent tool deleted")


class AgentToolExecuteRequest(BaseModel):
    raw_data: Any = Field(..., description="Dataset to operate on (list-of-dicts or dict)")


@router.post("/{tool_id}/execute", response_model=Dict[str, Any])
async def execute_agent_tool(
    tool_id: int,
    body: AgentToolExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Execute an Agent Tool's code in sandbox with the provided raw_data (df injected)."""
    svc = AgentToolService(db)
    tool = await svc.get_by_id(tool_id)
    if not tool or tool.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Agent tool not found")

    try:
        result = await sandbox_service.execute_script(
            script=tool.code,
            raw_data=body.raw_data,
        )
        await svc.increment_usage(tool_id)
        return StandardResponse.success(
            data={
                "tool_id": tool_id,
                "tool_name": tool.name,
                "output": result,
            }
        )
    except Exception as exc:
        return StandardResponse.error(message=f"Agent tool execution failed: {exc}")
