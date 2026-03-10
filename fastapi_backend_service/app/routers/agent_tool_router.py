"""Agent Tool Router — v15.0 JIT Analyst.

Endpoints for the per-user Agent Tool Chest:
  GET  /agent-tools          — list all tools for current user
  POST /agent-tools          — manually save a tool
  GET  /agent-tools/{id}     — get a single tool (with full code)
  DELETE /agent-tools/{id}   — delete a tool
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.dependencies import get_current_user, get_db
from app.services.agent_tool_service import AgentToolService

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
