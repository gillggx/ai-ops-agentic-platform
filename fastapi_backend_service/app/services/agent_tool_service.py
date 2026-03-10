"""AgentToolService — v15.0 JIT Analyst.

Manages the per-user Agent Tool Chest:
  - CRUD for agent_tools table
  - LLM-based reusability evaluation after a successful JIT execution
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import anthropic
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agent_tool import AgentToolModel

logger = logging.getLogger(__name__)

_settings = get_settings()
_MODEL = _settings.LLM_MODEL


def _get_text(content: list) -> str:
    for block in content:
        if hasattr(block, "text"):
            return block.text
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")
    return ""


def _extract_json(text: str) -> Dict[str, Any]:
    """Extract the first JSON object from a text string."""
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}


class AgentToolService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._client = anthropic.AsyncAnthropic(api_key=_settings.ANTHROPIC_API_KEY)

    # ── CRUD ────────────────────────────────────────────────────────────────

    async def get_all(self, user_id: int) -> List[AgentToolModel]:
        result = await self._db.execute(
            select(AgentToolModel)
            .where(AgentToolModel.user_id == user_id)
            .order_by(AgentToolModel.usage_count.desc(), AgentToolModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, tool_id: int) -> Optional[AgentToolModel]:
        result = await self._db.execute(
            select(AgentToolModel).where(AgentToolModel.id == tool_id)
        )
        return result.scalar_one_or_none()

    async def search_by_name(self, user_id: int, name: str) -> List[AgentToolModel]:
        result = await self._db.execute(
            select(AgentToolModel).where(
                AgentToolModel.user_id == user_id,
                AgentToolModel.name.ilike(f"%{name}%"),
            )
        )
        return list(result.scalars().all())

    async def create(
        self,
        user_id: int,
        name: str,
        code: str,
        description: str = "",
    ) -> AgentToolModel:
        tool = AgentToolModel(
            user_id=user_id,
            name=name,
            code=code,
            description=description,
            usage_count=0,
        )
        self._db.add(tool)
        await self._db.commit()
        await self._db.refresh(tool)
        logger.info("AgentTool created: id=%s name=%s user_id=%s", tool.id, tool.name, user_id)
        return tool

    async def increment_usage(self, tool_id: int) -> None:
        await self._db.execute(
            update(AgentToolModel)
            .where(AgentToolModel.id == tool_id)
            .values(usage_count=AgentToolModel.usage_count + 1)
        )
        await self._db.commit()

    # ── LLM reusability evaluation ───────────────────────────────────────────

    async def evaluate_reusability(
        self, code: str, context: str = ""
    ) -> Dict[str, Any]:
        """Ask LLM whether a JIT script is worth saving as a reusable Agent Tool.

        Returns::
            {"reusable": bool, "name": str, "description": str}
        """
        prompt = f"""以下是一段 JIT 執行成功的 Python 腳本片段：

```python
{code[:1500]}
```

執行上下文：{context[:300]}

請判斷此腳本是否值得保存為可重用工具（Agent Tool）。
判斷標準（需全部符合才算 true）：
1. 邏輯通用性：不硬編碼特定批號、機台 ID 或日期範圍
2. 功能獨立性：完整的分析單元，輸入 df 輸出結果
3. 可重用性：未來類似查詢可直接套用

只回傳 JSON，不加任何說明文字：
{{"reusable": true|false, "name": "簡短工具名稱（英文，不超過30字）", "description": "一句話功能說明（中文）"}}"""

        try:
            response = await self._client.messages.create(
                model=_MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            text = _get_text(response.content)
            result = _extract_json(text)
            if "reusable" not in result:
                return {"reusable": False, "name": "", "description": ""}
            return result
        except Exception as exc:
            logger.warning("evaluate_reusability failed: %s", exc)
            return {"reusable": False, "name": "", "description": ""}

    @staticmethod
    def to_dict(tool: AgentToolModel) -> Dict[str, Any]:
        return {
            "id": tool.id,
            "user_id": tool.user_id,
            "name": tool.name,
            "description": tool.description,
            "usage_count": tool.usage_count,
            "created_at": tool.created_at.isoformat() if tool.created_at else None,
        }
