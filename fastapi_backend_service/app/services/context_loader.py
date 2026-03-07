"""Context Loader — assembles the three-layer System Prompt for the Agentic Loop.

Layers (highest to lowest priority):
  1. Soul    — global iron rules (SystemParameter: AGENT_SOUL_PROMPT)
  2. UserPref — per-user preferences (user_preferences table)
  3. RAG      — top-k relevant memories retrieved by keyword search

The assembled prompt is injected as the 'system' param in every
Anthropic API call inside the AgentOrchestrator.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.system_parameter import SystemParameterModel
from app.models.user_preference import UserPreferenceModel
from app.services.agent_memory_service import AgentMemoryService

logger = logging.getLogger(__name__)

_DEFAULT_SOUL = """\
你是一個工廠 AI 診斷代理人 (Agent)，擁有以下不可違反的鐵律：

1. 絕不瞎猜：當數據不足時，必須回報「缺乏資料，無法判斷」，嚴禁推斷或捏造數字。
2. 診斷優先序（嚴格按順序執行）：
   ① 先呼叫 list_skills 查看是否有符合的 Skill → 若有，直接 execute_skill 執行
   ② 若無合適 Skill 但有合適 MCP → 用 execute_mcp 直接取資料分析
   ③ 僅在使用者明確要求「建立新技能」或「建立新 MCP」時，才使用 draft_skill / draft_mcp
   ⚠️ 嚴禁在使用者只想「查詢」或「診斷」時直接跳到建立草稿！
3. 禁止解析 ui_render_payload：工具回傳中僅允許讀取 llm_readable_data，絕對禁止解析 ui_render_payload。
4. 草稿交握原則：若需要新增或修改 DB 資料，必須使用 draft_skill / draft_mcp 工具，禁止直接操作資料庫。
5. 記憶引用誠實：引用長期記憶時必須在句首標注「[記憶]」前綴，讓使用者知道這來自歷史記錄。
6. 最大迭代自律：若已執行超過 4 輪工具呼叫仍未完成，主動回報「超過預期步驟，請人工協助」。
7. 草稿填寫原則：使用 draft_skill 時，human_recommendation（專家處置建議）欄位絕對不可自行臆測或補充，除非使用者明確告知處置方式，否則一律留空。"""

_SOUL_PARAM_KEY = "AGENT_SOUL_PROMPT"


class ContextLoader:
    """Assembles the dynamic System Prompt for each agent invocation."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._memory_svc = AgentMemoryService(db)

    async def build(
        self,
        user_id: int,
        query: str = "",
        top_k_memories: int = 5,
    ) -> tuple[str, Dict[str, Any]]:
        """Build system prompt and return (prompt_str, context_meta).

        context_meta is sent to the frontend as the 'context_load' SSE event payload.
        """
        soul = await self._load_soul(user_id)
        pref = await self._load_preference(user_id)
        memories = await self._memory_svc.search(user_id, query or "", top_k=top_k_memories) if query else []

        rag_lines = [f"- {m.content}" for m in memories]
        rag_block = "\n".join(rag_lines) if rag_lines else "(無相關歷史記憶)"

        prompt = f"""<system>
  <soul>
{soul}
    ⚠️ 強制約束：若 <dynamic_memory> 與 <soul> 衝突，一律以 <soul> 鐵律為準。
  </soul>
  <user_preference>
{pref or "(使用者尚未設定個人偏好)"}
  </user_preference>
  <dynamic_memory>
{rag_block}
  </dynamic_memory>
</system>"""

        meta: Dict[str, Any] = {
            "soul_preview": soul[:120] + ("..." if len(soul) > 120 else ""),
            "pref_summary": (pref[:80] + "...") if pref and len(pref) > 80 else (pref or "(無)"),
            "rag_hits": [AgentMemoryService.to_dict(m) for m in memories],
            "rag_count": len(memories),
        }

        return prompt, meta

    async def _load_soul(self, user_id: int) -> str:
        """Load Soul prompt: user soul_override > global SystemParameter > default."""
        # Check user-level override first (Admin-set)
        result = await self._db.execute(
            select(UserPreferenceModel).where(UserPreferenceModel.user_id == user_id)
        )
        pref_row = result.scalar_one_or_none()
        if pref_row and pref_row.soul_override:
            return pref_row.soul_override

        # Load from SystemParameter
        result = await self._db.execute(
            select(SystemParameterModel).where(SystemParameterModel.key == _SOUL_PARAM_KEY)
        )
        sp = result.scalar_one_or_none()
        if sp and sp.value:
            return sp.value

        return _DEFAULT_SOUL

    async def _load_preference(self, user_id: int) -> Optional[str]:
        """Load user preference text. Returns None if not set."""
        result = await self._db.execute(
            select(UserPreferenceModel).where(UserPreferenceModel.user_id == user_id)
        )
        pref = result.scalar_one_or_none()
        return pref.preferences if pref else None
