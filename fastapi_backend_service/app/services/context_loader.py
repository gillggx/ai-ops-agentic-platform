"""Context Loader — assembles the three-layer System Prompt for the Agentic Loop.

Layers (highest to lowest priority):
  1. Soul        — global iron rules (SystemParameter: AGENT_SOUL_PROMPT)
  2. UserPref    — per-user preferences (user_preferences table)
  3. RAG         — top-k relevant memories retrieved by keyword search
  4. Overrides   — canvas_overrides (highest weight, injected per-request)

v14: Returns List[Dict] (Anthropic content blocks) for Prompt Caching support.
     Stable blocks (Soul + MCP registry) get cache_control: ephemeral.
     Dynamic block (RAG memories) is NOT cached.
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
   ③ 僅在使用者明確要求「建立新技能」時，才用 draft_skill（mcp_ids 從 list_mcps 取 Custom MCP ID）
   ④ 若需要「建立新 MCP」：先 list_system_mcps 取得 system_mcp_id，再 draft_mcp
   ⚠️ 嚴禁在使用者只想「查詢」或「診斷」時直接跳到建立草稿！
   ⚠️ draft_skill 的 mcp_ids 只能填 Custom MCP ID，不可填 System MCP ID！
3. 禁止解析 ui_render_payload：工具回傳中僅允許讀取 llm_readable_data，絕對禁止解析 ui_render_payload。
4. 草稿交握原則：若需要新增或修改 DB 資料，必須使用 draft_skill / draft_mcp 工具，禁止直接操作資料庫。
5. 記憶引用誠實：引用長期記憶時必須在句首標注「[記憶]」前綴，讓使用者知道這來自歷史記錄。
6. 最大迭代自律：若已執行超過 4 輪工具呼叫仍未完成，主動回報「超過預期步驟，請人工協助」。
7. 草稿填寫原則：使用 draft_skill 時：
   ① human_recommendation 除非用戶明確告知，否則留空。
   ② 用戶確認方向後（如說「可以」「好」「建立」），立刻呼叫 draft_skill，不再逐欄詢問確認。
   ③ 草稿建立後只說一句「草稿已備妥，請點右側連結審核」，不重複列出所有欄位。
8. [參數填寫原則] 能從對話推斷的參數直接填入，不要問。只有在「同一參數有多個合理候選值且無法判斷」時，才一次性列出選項請用戶選擇。
   ✅ 正確：用戶說「查 Depth 9800 站的狀況」→ 直接帶入 DCName=Depth, operationNumber=9800 執行。
   ✅ 正確：draft_skill 時，診斷條件、MCP 綁定從上下文推斷後直接填，不逐欄詢問。
   ❌ 禁止：已知參數還反覆確認；禁止把已明確說過的參數再問一遍。
   ⚠️ 真正不確定時（例如有 CD/Depth/Oxide 三種 chart_name 不知選哪個）：列出選項問一次，之後不再重複問。
9. [v14 規劃鐵律] Sequential Planning：在執行任何工具前，必須先輸出一個 <plan> 標籤描述行動路徑。
   格式：<plan>Step 1: [工具名稱] (原因) → Step 2: [工具名稱] (原因) → ...</plan>
   ✅ 正確：<plan>Step 1: list_skills (確認是否有 SPC 診斷 Skill) → Step 2: execute_skill (執行診斷)</plan>
   ⚠️ 規劃後才可呼叫工具，不可跳過 <plan> 直接行動。"""

_SOUL_PARAM_KEY = "AGENT_SOUL_PROMPT"

_OUTPUT_ROUTING = """\
⚠️ 輸出格式鐵律（不可違反，優先級最高）：
1. Chat Bubble（對話框）：只能有一句簡短的狀態報告 + UI 引導語。
   ✅ 正確範例：「✅ 常態分佈分析完成，發現異常。👉 請檢視右側 AI 分析報告。」
   ❌ 禁止在標籤外出現 Markdown 表格、多行統計數據、詳細列表。
2. 詳細分析（數據表格、統計量、Sigma 計算、專家建議）：必須全部包入 <ai_analysis>...</ai_analysis> 標籤。
3. 若沒有詳細分析需要輸出，則不使用標籤，僅一句對話回覆即可。"""


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
        canvas_overrides: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Build system prompt blocks and return (content_blocks, context_meta).

        Returns Anthropic content block list (List[Dict]) so callers can set
        cache_control on stable blocks to enable Prompt Caching.

        Stable (cached): soul + output_routing
        Dynamic (not cached): user_preference + RAG memories + canvas_overrides
        """
        soul = await self._load_soul(user_id)
        pref = await self._load_preference(user_id)
        memories = await self._memory_svc.search(user_id, query or "", top_k=top_k_memories) if query else []

        rag_lines = [f"- {m.content}" for m in memories]
        rag_block = "\n".join(rag_lines) if rag_lines else "(無相關歷史記憶)"

        # ── Block 1: Soul + output rules (stable → cache) ─────────────────────
        stable_text = f"""<soul>
{soul}
  ⚠️ 強制約束：若 <dynamic_memory> 與 <soul> 衝突，一律以 <soul> 鐵律為準。
</soul>
<output_routing_rules>
{_OUTPUT_ROUTING}
</output_routing_rules>"""

        # ── Block 2: Dynamic context (changes each turn → no cache) ───────────
        dynamic_parts = [
            f"<user_preference>\n{pref or '(使用者尚未設定個人偏好)'}\n</user_preference>",
            f"<dynamic_memory>\n{rag_block}\n</dynamic_memory>",
        ]
        if canvas_overrides:
            overrides_text = "\n".join(f"- {k}: {v}" for k, v in canvas_overrides.items())
            dynamic_parts.append(
                f"<canvas_overrides priority=\"highest\">\n"
                f"以下為使用者手動修正，具最高優先權，必須覆蓋 AI 推理結果：\n"
                f"{overrides_text}\n</canvas_overrides>"
            )
        dynamic_text = "\n".join(dynamic_parts)

        # Build Anthropic content block list with cache_control on stable block
        system_blocks: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": stable_text,
                "cache_control": {"type": "ephemeral"},  # v14: Prompt Caching
            },
            {
                "type": "text",
                "text": dynamic_text,
                # No cache_control — changes every turn
            },
        ]

        meta: Dict[str, Any] = {
            "soul_preview": soul[:120] + ("..." if len(soul) > 120 else ""),
            "pref_summary": (pref[:80] + "...") if pref and len(pref) > 80 else (pref or "(無)"),
            "rag_hits": [AgentMemoryService.to_dict(m) for m in memories],
            "rag_count": len(memories),
            "cache_blocks": 1,  # number of cached blocks
            "has_canvas_overrides": bool(canvas_overrides),
        }

        return system_blocks, meta

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
