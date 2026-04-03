"""Generic Tools Router (v15.3).

Endpoints:
  GET  /generic-tools/catalog            — list all 50 tools with metadata
  POST /generic-tools/{tool_name}        — invoke a tool with data + params
  POST /generic-tools/promote-to-skill   — save JIT result as Agent Tool
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import StandardResponse
from app.api.dependencies import get_current_user, get_db
from app.generic_tools import TOOL_REGISTRY, call_tool

router = APIRouter(prefix="/api/v1/generic-tools", tags=["generic-tools"])


# ── Request / Response Models ─────────────────────────────────────────────────

class ToolInvokeRequest(BaseModel):
    data: List[Dict[str, Any]] = Field(default_factory=list, description="Row-of-dicts dataset")
    params: Dict[str, Any] = Field(default_factory=dict, description="Tool-specific parameters")


class PromoteToSkillRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    code: str = Field(..., min_length=1, description="Python code to promote as Agent Tool")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/catalog", response_model=StandardResponse)
async def get_catalog(
    category: Optional[str] = None,
) -> StandardResponse:
    """Return the full tool catalog (optionally filtered by category)."""
    items = [
        {
            "name": name,
            "category": meta["category"],
            "description": meta["description"],
            "params": meta["params"],
        }
        for name, meta in TOOL_REGISTRY.items()
        if (category is None or meta["category"] == category)
    ]
    return StandardResponse.success(
        data={"tools": items, "total": len(items)},
        message=f"Generic tools catalog: {len(items)} tools",
    )


@router.post("/promote-to-skill", response_model=StandardResponse, status_code=status.HTTP_201_CREATED)
async def promote_to_skill(
    body: PromoteToSkillRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> StandardResponse:
    """Save a JIT analysis result as a reusable Agent Tool in the user's tool chest."""
    from app.services.agent_tool_service import AgentToolService

    svc = AgentToolService(db)
    tool = await svc.create(
        user_id=current_user.id,
        name=body.name,
        code=body.code,
        description=body.description,
    )
    return StandardResponse.success(
        data=AgentToolService.to_dict(tool),
        message=f"Promoted '{body.name}' to Agent Tool (id={tool.id})",
    )


@router.post("/{tool_name}", response_model=StandardResponse)
async def invoke_tool(
    tool_name: str,
    body: ToolInvokeRequest,
    current_user=Depends(get_current_user),
) -> StandardResponse:
    """Invoke a generic tool by name with provided data and params."""
    if tool_name not in TOOL_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{tool_name}' not found. GET /generic-tools/catalog to see all tools.",
        )
    result = call_tool(tool_name, data=body.data, **body.params)
    if result.get("status") == "error":
        return StandardResponse.error(message=result.get("summary", "Tool execution failed"))
    return StandardResponse.success(
        data=result,
        message=result.get("summary", f"Tool '{tool_name}' executed"),
    )
