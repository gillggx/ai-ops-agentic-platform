"""Agent Router — tools manifest and execution endpoints for AI agents."""

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository

router = APIRouter(prefix="/agent", tags=["agent"])


def _j(s: Optional[str]) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _build_tool_markdown(skill, mcp_map: Dict[int, Any]) -> str:
    """Build XML-tagged Markdown tool description for a public skill.

    Strictly follows PRD v12 Section 3.2 format to prevent agent hallucination.
    """
    skill_id = skill.id
    skill_name = skill.name or ""
    skill_desc = skill.description or ""
    diagnostic_prompt = skill.diagnostic_prompt or ""
    problem_subject = skill.problem_subject or ""
    human_recommendation = skill.human_recommendation or ""

    # Collect required parameters from bound MCPs
    mcp_ids: List[int] = _j(skill.mcp_ids) or []
    required_params: List[Dict] = []
    for mid in mcp_ids:
        mcp = mcp_map.get(mid)
        if not mcp:
            continue
        input_def = _j(mcp.input_definition)
        if not input_def:
            continue
        for p in input_def.get("params", []):
            if p.get("required", True) and p.get("source") != "data_subject":
                required_params.append({
                    "name": p.get("name"),
                    "type": p.get("type", "string"),
                    "description": p.get("description", ""),
                    "required": True,
                })

    params_schema = json.dumps(
        {"type": "object", "properties": {
            p["name"]: {"type": p["type"], "description": p["description"]}
            for p in required_params
        }, "required": [p["name"] for p in required_params]},
        ensure_ascii=False, indent=2
    )

    return f"""---
name: {skill_name}
description: 本技能是一套完整的自動化診斷管線。{skill_desc}
---
## 1. 執行規劃與優先級 (Planning Guidance)
- **優先使用**：當意圖符合時，直接呼叫本技能。絕對不要要求使用者先提供 raw_data 或去呼叫底層 MCP，系統會自動撈取。

## 2. 依賴參數與介面 (Interface)
- API: `POST /api/v1/execute/skill/{skill_id}`
- **必須傳遞參數**:
```json
{params_schema}
```
- ⚠️ **邊界鐵律**: 呼叫 API 後，僅允許讀取 `llm_readable_data` 進行判斷。絕對禁止解析 `ui_render_payload`。

## 3. 判斷邏輯與防呆處置 (Reasoning Rules)
請嚴格遵循以下 `<rules>` 標籤內的指示撰寫最終報告：
<rules>
  <condition>{diagnostic_prompt}</condition>
  <target_extraction>{problem_subject}</target_extraction>
  <expert_action>
    ⚠️ 若狀態為 ABNORMAL，必須強制在報告結尾附加處置建議：
    Action: {human_recommendation}
  </expert_action>
</rules>"""


@router.get(
    "/tools_manifest",
    summary="取得 Agent 工具清單 (公開技能)",
    response_model=Dict[str, Any],
)
async def get_tools_manifest(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return all public skills as XML-tagged Markdown tool descriptions.

    Used by the AI agent to discover available diagnostic tools.
    Only 'public' skills appear here. Private skills belong to their owners only.
    """
    skill_repo = SkillDefinitionRepository(db)
    mcp_repo = MCPDefinitionRepository(db)

    all_skills = await skill_repo.get_all()
    public_skills = [s for s in all_skills if s.visibility == "public"]

    # Collect all referenced MCP ids to batch-load
    all_mcp_ids: List[int] = []
    for skill in public_skills:
        ids = _j(skill.mcp_ids) or []
        all_mcp_ids.extend(ids)
    all_mcp_ids = list(set(all_mcp_ids))

    all_mcps = await mcp_repo.get_all()
    mcp_map = {m.id: m for m in all_mcps}

    tools = []
    for skill in public_skills:
        md = _build_tool_markdown(skill, mcp_map)
        tools.append({
            "skill_id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "markdown": md,
        })

    # ── Meta-tool: patch_skill_markdown (PRD v12 §4.5.3) ──────────────────
    meta_tools = [
        {
            "tool_name": "patch_skill_markdown",
            "description": (
                "讀取或更新指定 Skill 的原生 OpenClaw Markdown。"
                "當使用者要求修改某個 Skill 的判斷條件、目標物件或處置建議時使用此工具。"
            ),
            "endpoints": {
                "read": "GET /api/v1/agentic/skills/{skill_id}/raw",
                "write": "PUT /api/v1/agentic/skills/{skill_id}/raw",
            },
            "write_body": {"raw_markdown": "<完整的 OpenClaw Markdown 字串>"},
            "workflow": (
                "1. GET /agentic/skills/{skill_id}/raw 取得原始 Markdown\n"
                "2. 在 <condition> 區塊修改判斷條件\n"
                "3. PUT /agentic/skills/{skill_id}/raw 覆蓋更新\n"
                "4. 從回傳的 deep_link 引導使用者進入 ⌨️ Raw 模式進行最終 Code Review"
            ),
            "constraints": (
                "⚠️ 只能修改 <condition>、<target_extraction>、<expert_action> 及 YAML header 的 name/description。"
                "禁止修改 API 端點或參數 Schema。"
            ),
        }
    ]

    return {"tools": tools, "total": len(tools), "meta_tools": meta_tools}
