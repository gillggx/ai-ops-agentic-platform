"""Agentic Skill Router — bi-directional OpenClaw Markdown read/write API.

Implements PRD v12 Section 4.5.2:
  GET  /agentic/skills/{skill_id}/raw  → return skill as OpenClaw Markdown
  PUT  /agentic/skills/{skill_id}/raw  → parse Markdown and update DB fields
"""

import json
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.api.dependencies import get_db
from app.api.dependencies import get_current_user
from app.ontology.models.user import User
from app.ontology.repositories.mcp_definition_repository import MCPDefinitionRepository
from app.ontology.repositories.skill_definition_repository import SkillDefinitionRepository
from app.ontology.schemas.skill_definition import SkillDefinitionUpdate

router = APIRouter(prefix="/api/v1/agentic", tags=["agentic"])


def _j(s: Optional[str]) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _build_raw_markdown(skill, mcp=None) -> str:
    """Generate OpenClaw-compatible Markdown from a SkillDefinitionModel.

    Identical format to agent_router._build_tool_markdown() so that
    GET /raw output can be directly PUT back without data loss.
    """
    skill_id = skill.id
    skill_name = skill.name or ""
    skill_desc = skill.description or ""
    diagnostic_prompt = skill.diagnostic_prompt or ""
    problem_subject = skill.problem_subject or ""
    human_recommendation = skill.human_recommendation or ""

    # Build required params schema from MCP input_definition (if available)
    required_params: List[Dict] = []
    if mcp:
        input_def = _j(mcp.input_definition)
        if input_def:
            for p in input_def.get("params", []):
                if p.get("required", True) and p.get("source") != "data_subject":
                    required_params.append({
                        "name": p.get("name"),
                        "type": p.get("type", "string"),
                        "description": p.get("description", ""),
                    })

    params_schema = json.dumps(
        {
            "type": "object",
            "properties": {
                p["name"]: {"type": p["type"], "description": p["description"]}
                for p in required_params
            },
            "required": [p["name"] for p in required_params],
        },
        ensure_ascii=False,
        indent=2,
    )

    return (
        f"---\n"
        f"name: {skill_name}\n"
        f"description: 本技能是一套完整的自動化診斷管線。{skill_desc}\n"
        f"---\n"
        f"## 1. 執行規劃與優先級 (Planning Guidance)\n"
        f"- **優先使用**：當意圖符合時，直接呼叫本技能。絕對不要要求使用者先提供 raw_data。\n"
        f"\n"
        f"## 2. 依賴參數與介面 (Interface)\n"
        f"- API: `POST /api/v1/execute/skill/{skill_id}`\n"
        f"- **必須傳遞參數**:\n"
        f"```json\n{params_schema}\n```\n"
        f"- ⚠️ **邊界鐵律**: 呼叫 API 後，僅允許讀取 `llm_readable_data`。絕對禁止解析 `ui_render_payload`。\n"
        f"\n"
        f"## 3. 判斷邏輯與防呆處置 (Reasoning Rules)\n"
        f"請嚴格遵循以下 `<rules>` 標籤內的指示撰寫最終報告：\n"
        f"<rules>\n"
        f"  <condition>{diagnostic_prompt}</condition>\n"
        f"  <target_extraction>{problem_subject}</target_extraction>\n"
        f"  <expert_action>\n"
        f"    ⚠️ 若狀態為 ABNORMAL，必須強制在報告結尾附加處置建議：\n"
        f"    Action: {human_recommendation}\n"
        f"  </expert_action>\n"
        f"</rules>"
    )


def _parse_raw_markdown(md: str) -> Dict[str, Optional[str]]:
    """Extract Skill fields from OpenClaw Markdown using regex.

    Returns a dict with keys: name, description, diagnostic_prompt,
    problem_subject, human_recommendation.  Values are None if not found.
    """
    def _first(pattern, flags=0) -> Optional[str]:
        m = re.search(pattern, md, flags)
        return m.group(1).strip() if m else None

    # YAML header fields
    name = _first(r"^name:\s*(.+)$", re.MULTILINE)
    # description may be prefixed with the standard boilerplate
    desc = (
        _first(r"^description:\s*本技能是一套完整的自動化診斷管線。(.*)$", re.MULTILINE)
        or _first(r"^description:\s*(.+)$", re.MULTILINE)
    )

    # XML-tagged fields inside <rules>
    cond = _first(r"<condition>([\s\S]*?)</condition>")
    subj = _first(r"<target_extraction>([\s\S]*?)</target_extraction>")

    # expert_action: extract the text after "Action:" inside the block
    act_block = _first(r"<expert_action>([\s\S]*?)</expert_action>")
    action: Optional[str] = None
    if act_block:
        act_m = re.search(r"Action:\s*([\s\S]*?)$", act_block, re.MULTILINE)
        action = act_m.group(1).strip() if act_m else act_block.strip()

    return {
        "name": name,
        "description": desc,
        "diagnostic_prompt": cond,
        "problem_subject": subj,
        "human_recommendation": action,
    }


# ── Request / Response schemas ─────────────────────────────────────────────

class RawMarkdownBody(BaseModel):
    raw_markdown: str


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get(
    "/skills/{skill_id}/raw",
    summary="取得 Skill 的原生 OpenClaw Markdown (Agentic Read)",
    response_model=Dict[str, Any],
)
async def get_skill_raw(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return the Skill as an OpenClaw-compatible Markdown string.

    Agents can read this to understand or modify the skill definition.
    The format is identical to what tools_manifest generates.
    """
    skill_repo = SkillDefinitionRepository(db)
    mcp_repo = MCPDefinitionRepository(db)

    skill = await skill_repo.get_by_id(skill_id)
    if not skill:
        raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Skill id={skill_id} 不存在")

    mcp = None
    mcp_ids = _j(skill.mcp_ids) or []
    if mcp_ids:
        mcp = await mcp_repo.get_by_id(mcp_ids[0])

    raw_md = _build_raw_markdown(skill, mcp)

    return {
        "skill_id": skill_id,
        "skill_name": skill.name,
        "visibility": skill.visibility if hasattr(skill, "visibility") and skill.visibility else "private",
        "raw_markdown": raw_md,
        "deep_link": {
            "view": "skill-builder",
            "skill_id": skill_id,
            "note": "開啟 Skill Editor 的 ⌨️ Raw 模式即可直接編輯此 Markdown",
        },
    }


@router.put(
    "/skills/{skill_id}/raw",
    summary="以原生 Markdown 更新 Skill (Agentic Write / patch_skill_markdown)",
    response_model=Dict[str, Any],
)
async def update_skill_raw(
    skill_id: int,
    body: RawMarkdownBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Parse an OpenClaw Markdown string and update the Skill in the DB.

    This is the backend implementation of the ``patch_skill_markdown``
    meta-skill described in PRD v12 Section 4.5.3.

    Fields extracted:
      - YAML header ``name`` / ``description``
      - ``<condition>`` → diagnostic_prompt
      - ``<target_extraction>`` → problem_subject
      - ``<expert_action>`` → human_recommendation (text after ``Action:``)
    """
    skill_repo = SkillDefinitionRepository(db)
    mcp_repo = MCPDefinitionRepository(db)

    skill = await skill_repo.get_by_id(skill_id)
    if not skill:
        raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Skill id={skill_id} 不存在")

    parsed = _parse_raw_markdown(body.raw_markdown)

    # Build update payload — only include fields that were found in the Markdown
    update_data: Dict[str, Any] = {}
    if parsed["name"] is not None:
        update_data["name"] = parsed["name"]
    if parsed["description"] is not None:
        update_data["description"] = parsed["description"]
    if parsed["diagnostic_prompt"] is not None:
        update_data["diagnostic_prompt"] = parsed["diagnostic_prompt"]
    if parsed["problem_subject"] is not None:
        update_data["problem_subject"] = parsed["problem_subject"]
    if parsed["human_recommendation"] is not None:
        update_data["human_recommendation"] = parsed["human_recommendation"]

    updated = await skill_repo.update(skill, **update_data)

    # Build response with updated raw Markdown + deep link for Code Review
    mcp = None
    mcp_ids = _j(updated.mcp_ids) or []
    if mcp_ids:
        mcp = await mcp_repo.get_by_id(mcp_ids[0])

    return {
        "skill_id": skill_id,
        "skill_name": updated.name,
        "updated_fields": list(update_data.keys()),
        "raw_markdown": _build_raw_markdown(updated, mcp),
        "deep_link": {
            "view": "skill-builder",
            "skill_id": skill_id,
            "mode": "raw",
            "note": "⚠️ Agent 已更新完畢，請進入 ⌨️ Raw 模式進行最終 Code Review 與 Try Run",
        },
    }
