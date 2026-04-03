"""Agent compat router — /api/v1/agent/* routes matching the original v13 frontend contract.

Provides:
  GET/PUT  /api/v1/agent/soul
  GET/POST /api/v1/agent/preference
  GET/POST/DELETE /api/v1/agent/memory
  GET      /api/v1/agent/tools_manifest
  GET      /api/v1/agent/analyze-data/templates
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user, get_db
from app.ontology.models.agent_session import AgentPreference, AgentTool
from app.ontology.models.system_parameter import SystemParameter
from app.ontology.models.user import User
from app.services.agent_memory_service import AgentMemoryService

router = APIRouter(prefix="/api/v1/agent", tags=["agent-compat"])

_SOUL_KEY = "AGENT_SOUL_PROMPT"


# ── Soul ──────────────────────────────────────────────────────────────────────

@router.get("/soul")
async def get_soul(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    from app.services.context_loader import _DEFAULT_SOUL
    result = await db.execute(select(SystemParameter).where(SystemParameter.key == _SOUL_KEY))
    sp = result.scalar_one_or_none()
    return {
        "status": "success",
        "key": _SOUL_KEY,
        "soul_prompt": sp.value if sp else _DEFAULT_SOUL,
        "is_default": sp is None,
    }


class SoulUpdateRequest(BaseModel):
    soul_prompt: str


@router.put("/soul")
async def update_soul(
    body: SoulUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    result = await db.execute(select(SystemParameter).where(SystemParameter.key == _SOUL_KEY))
    sp = result.scalar_one_or_none()
    if sp:
        sp.value = body.soul_prompt
    else:
        sp = SystemParameter(key=_SOUL_KEY, value=body.soul_prompt, description="Agent Soul Prompt")
        db.add(sp)
    await db.commit()
    return {"status": "success", "key": _SOUL_KEY, "message": "Soul Prompt 已更新"}


# ── Preference ────────────────────────────────────────────────────────────────

@router.get("/preference")
async def get_preference(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    result = await db.execute(select(AgentPreference).where(AgentPreference.user_id == current_user.id))
    pref = result.scalar_one_or_none()
    return {
        "status": "success",
        "user_id": current_user.id,
        "preferences": pref.preferences if pref else None,
        "has_soul_override": bool(pref and pref.soul_override),
    }


class PreferenceRequest(BaseModel):
    text: str


@router.post("/preference")
async def update_preference(
    body: PreferenceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    result = await db.execute(select(AgentPreference).where(AgentPreference.user_id == current_user.id))
    pref = result.scalar_one_or_none()
    if pref:
        pref.preferences = body.text
    else:
        pref = AgentPreference(user_id=current_user.id, preferences=body.text)
        db.add(pref)
    await db.commit()
    await db.refresh(pref)
    return {"status": "success", "user_id": current_user.id, "preferences": pref.preferences, "blocked": False}


# ── Memory ────────────────────────────────────────────────────────────────────

@router.get("/memory/search")
async def search_memory(
    q: str = Query(...),
    top_k: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    svc = AgentMemoryService(db)
    memories = await svc.search(current_user.id, query=q, top_k=top_k)
    return {"status": "success", "query": q, "count": len(memories),
            "memories": [AgentMemoryService.to_dict(m) for m in memories]}


@router.get("/memory")
async def list_memory(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    svc = AgentMemoryService(db)
    memories = await svc.list(current_user.id, limit=limit)
    return {"status": "success", "count": len(memories),
            "memories": [AgentMemoryService.to_dict(m) for m in memories]}


class MemoryWriteRequest(BaseModel):
    content: str
    source: Optional[str] = "manual"
    ref_id: Optional[str] = None


@router.post("/memory")
async def save_memory(
    body: MemoryWriteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    svc = AgentMemoryService(db)
    m = await svc.write(user_id=current_user.id, content=body.content,
                        source=body.source or "manual", ref_id=body.ref_id)
    return {"status": "success", "memory": AgentMemoryService.to_dict(m)}


@router.delete("/memory/{memory_id}")
async def delete_memory(
    memory_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    svc = AgentMemoryService(db)
    deleted = await svc.delete(memory_id, user_id=current_user.id)
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Memory id={memory_id} not found")
    return {"status": "success", "deleted_id": memory_id}


@router.delete("/memory")
async def delete_all_memory(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    svc = AgentMemoryService(db)
    count = await svc.delete_all(current_user.id)
    return {"status": "success", "deleted_count": count}


# ── Tools manifest ────────────────────────────────────────────────────────────

@router.get("/tools_manifest")
async def get_tools_manifest(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    from app.ontology.models.skill import SkillDefinition
    from app.ontology.models.mcp import MCPDefinition

    result = await db.execute(select(SkillDefinition))
    all_skills = result.scalars().all()
    public_skills = [s for s in all_skills if getattr(s, "visibility", "private") == "public"]

    tools = [{"skill_id": s.id, "name": s.name, "description": s.description or ""} for s in public_skills]

    meta_tools = [{
        "tool_name": "patch_skill_markdown",
        "description": "讀取或更新指定 Skill 的原生 OpenClaw Markdown。",
        "endpoints": {"read": "GET /api/v1/agentic/skills/{skill_id}/raw",
                      "write": "PUT /api/v1/agentic/skills/{skill_id}/raw"},
    }]

    result2 = await db.execute(select(AgentTool).where(AgentTool.user_id == current_user.id))
    agent_tools = result2.scalars().all()
    agent_tools_manifest = [
        {"tool_id": t.id, "name": t.name, "description": t.description, "usage_count": t.usage_count}
        for t in agent_tools
    ]

    return {"tools": tools, "total": len(tools), "meta_tools": meta_tools,
            "agent_tools": agent_tools_manifest, "agent_tools_total": len(agent_tools_manifest)}


# ── Analyze-data templates ─────────────────────────────────────────────────────

_TEMPLATES = {
    "spc_chart": {"label": "SPC 管制圖", "description": "Statistical Process Control chart analysis"},
    "correlation": {"label": "相關性分析", "description": "Pearson correlation between parameters"},
    "trend": {"label": "趨勢分析", "description": "Time-series trend and anomaly detection"},
    "distribution": {"label": "分佈分析", "description": "Distribution and outlier analysis"},
}


@router.get("/analyze-data/templates")
async def get_analyze_templates(
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    return {"status": "success", "data": {"templates": _TEMPLATES}}
