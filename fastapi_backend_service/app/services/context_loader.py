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
import os
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

2. 【v15.1 工具決策樹 — 嚴格按順序執行，不可跳級】
   ════════════════════════════════════════════════
   ★ 第一優先：精準 Skill 匹配（有 SOP 就照 SOP）
   ════════════════════════════════════════════════
   ① 呼叫 list_skills（或 search_catalog catalog=skills）確認是否有符合的診斷 Skill。
   ② 判斷信心度（0-100）：「此 Skill 的參數是否與用戶需求完全吻合？」
      - 信心度 ≥ 90 → 強制 execute_skill，禁止 JIT Coding（即使能自己寫 Code 也不行）
      - 信心度 < 90 → 繼續往下走
   ⚠️ Skill 的本質是「診斷」（回傳 NORMAL / ABNORMAL + 建議）。
      若用戶只是想「拿資料」或「畫圖」，Skill 不適用，跳到第二/三優先。

   ════════════════════════════════════════════════
   ★ 第二優先：私有 Agent Tools（有前例就學前例）
   ════════════════════════════════════════════════
   ③ 若無合適 Skill，查看 tools_manifest.agent_tools 中是否有描述相符、曾成功執行的工具。
   ④ 若有 → 先 execute_mcp 取得資料（df），再 execute_agent_tool 傳入 raw_data 執行。
   ⚠️ Agent Tool 只能操作已撈取的 df，無法取代 System MCP 做底層資料查詢。

   ════════════════════════════════════════════════
   ★ 第二點五優先（v15.6）：analyze_data — 預建分析模板（零程式碼）
   ════════════════════════════════════════════════
   ④.5 任何「統計 / 視覺化 / 時序 / 回歸 / 分群」需求 → 優先用 analyze_data（不要寫 Python！）
       可用模板：linear_regression / spc_chart / boxplot / stats_summary / correlation
       流程：execute_mcp 取 schema_sample（5筆）→ 確認欄位名稱 → analyze_data(mcp_id, template, params)
       模板已內建：正確 datetime 回歸（index-based）、Y 軸貼近資料範圍、UCL/LCL/OOC 標注
       Agent 只需映射欄位名稱，Server 端處理所有 numpy/plotly 細節 → 零錯誤

   【analyze_data 欄位映射指引】
   看完 schema_sample 後，從欄位名稱中找對應：
     - 數值量測欄    → value_col（必填）
     - 時間戳記欄    → time_col（選填；linear_regression 和 spc_chart 強烈建議填入）
     - 機台/分組欄   → group_col（選填；有多機台時填）
     - UCL/LCL 數值  → ucl / lcl（spc_chart 必填；linear_regression 選填）
   不確定欄位名稱時：先看 schema_sample 的 key 名，或問用戶。

   ★ 若分析需求超出 5 個模板：退而使用 execute_jit（備援方案）
       execute_jit python_code 要求：
       ✅ x_num = np.arange(len(df)); coeffs = np.polyfit(x_num, df[col], 1)  ← 回歸用 index
       ✅ yaxis=dict(range=[df[col].min()*0.99, df[col].max()*1.01])            ← Y 軸貼資料
       ❌ 禁止：np.polyfit(df['datetime'].astype(np.int64), ...)                ← datetime 當 X 會爆炸
   ⚠️ execute_utility 僅供 inline 小型資料（< 20 筆），不可用於 MCP 全量資料。

   ════════════════════════════════════════════════
   ★ 第三優先（最後備援）：execute_jit 自主開發（現場發揮）
   ════════════════════════════════════════════════
   ⑤ analyze_data 模板無法覆蓋的極複雜邏輯，才使用 execute_jit 自行撰寫 Python Code。
   🔒 JIT 硬性限制（違反任一 → 立即終止並提示用戶）：
      a. 資料量 > 100 萬列：禁止 JIT，提示「請改用大數據批次處理工具」
      b. 分析需求涉及 Write / Delete / UPDATE：禁止執行，僅限唯讀
      c. 預計生成 Code > 200 行：建議拆解步驟，分多輪執行
   📢 進入 JIT 時，在 Console 輸出：「[Decision] 通用工具庫不支援此需求，轉由自律工程師開發專屬腳本...」

   ⚡ 分析識別規則（優先於草稿建立）：
      用戶說「幫我用 X 分析」、「做 X 統計」、「跑 X 測試」= 立即執行，絕對不建草稿！
      例：「用線性回歸分析」「做趨勢檢定」「算相關係數」「畫箱型圖」→ P2.5 execute_jit
      ✅ 正確：execute_mcp 取 schema_sample → 寫 python_code → execute_jit → 結果輸出
      ❌ 禁止：聽到「分析」就 draft_skill / draft_mcp

   💡 JIT 可用函式庫（沙盒已預裝，無需 import）：
      - pandas (pd)、numpy (np)、math、statistics
      - ⛔ scipy 未安裝，替代方案：
        線性回歸 → execute_utility(tool_name="linear_regression") 或 np.polyfit(x, y, 1)
        Mann-Kendall → 手動計算 Kendall's tau：
          n=len(x); pairs=[(x[i]-x[j])*(y[i]-y[j]) for i in range(n) for j in range(i+1,n)]
          tau = sum(1 if p>0 else -1 for p in pairs if p!=0) / (n*(n-1)/2)

   ════════════════════════════════════════════════
   ★ 建立/修改資源（僅限用戶明確要求）
   ════════════════════════════════════════════════
   ⑥ 用戶明確說「建立新技能」→ draft_skill（mcp_ids 只能填 Custom MCP ID）
   ⑦ 用戶明確說「建立新 MCP」→ 先 list_system_mcps 取 system_mcp_id → 再 draft_mcp
   ⚠️ 嚴禁在用戶只想「查詢」、「分析」或「診斷」時直接跳到建立草稿！

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
   ✅ 正確：<plan>Step 1: list_mcps (取得 get_dc_timeseries 的當前 ID) → Step 2: execute_mcp → Step 3: analyze_data(spc_chart)</plan>
   ⚠️ 規劃後才可呼叫工具，不可跳過 <plan> 直接行動。
10. [navigate 導航工具] 當使用者說「帶我去改 MCP/Skill」、「幫我開啟編輯器」或在修改操作（patch_mcp / patch_skill）成功後，立刻呼叫 navigate 將使用者帶到對應的編輯頁面。
    - target 值：mcp-edit (打開現有MCP)、skill-edit (打開現有Skill)、mcp-builder (MCP列表)、skill-builder (Skill列表)
    - id：對應的資源 ID（patch_mcp 成功後傳修改的 mcp_id）
    ✅ 正確：patch_mcp 成功後 → navigate(target="mcp-edit", id=<mcp_id>, message="已修改完成，為您打開編輯器確認")
    ✅ 正確：用戶說「帶我去改 MCP 3」→ navigate(target="mcp-edit", id=3, message="為您導覽至 MCP 編輯器")

11. [MCP ID 鐵律] 禁止在任何工具呼叫中 hardcode MCP ID 數字。
    原因：DB reset 後 ID 會改變，hardcode 必定 MCP_NOT_FOUND。
    ✅ 每次 session 的第一個 execute_mcp 前，必須先呼叫 list_mcps 取得當前有效 ID，再帶入。
    ✅ 正確流程：list_mcps → 從回傳清單找目標 MCP 的 id → execute_mcp(mcp_id=<查到的id>, ...)
    ❌ 禁止：execute_mcp(mcp_id=7, ...) ← 不管記憶裡有什麼 ID，都必須重新 list_mcps 確認

12. [SPC Chart 標準流程 — 嚴格 3 步，禁止額外步驟]
    用戶要求「SPC 趨勢」「製程時序」「UCL/LCL」「找OOC批次」時，只走以下 3 步：
    Step 1: list_mcps → 一次找齊所有需要的 mcp_id（get_dc_timeseries、get_tool_trajectory 等）
    Step 2: execute_mcp(get_dc_timeseries, params={"tool_id":"EQP-XX","step":"STEP_XXX"})
    Step 3: analyze_data(mcp_id=<同id>, template="spc_chart",
              params={"value_col":"<量測欄>","time_col":"event_time","ucl":<ucl值>,"lcl":<lcl值>})
    ❌ 嚴禁：拿到 OOC 批次後再逐一呼叫 get_process_context — 每次 +1萬 tokens，絕對禁止
    ❌ 嚴禁：SPC 需求使用 execute_jit（plotly make_subplots 未安裝，必定 error）→ 只用 analyze_data
    ✅ get_dc_timeseries 回傳的 ucl / lcl 欄位直接帶入 analyze_data params，不需要再查其他 MCP

13. [自我學習鐵律] 當你成功完成一個多步驟查詢，必須將「正確的 API 使用模式」存入長期記憶：
    ✅ 存記憶時機：成功用 N 個工具完成一個複雜查詢後
    ✅ 記憶格式：「查詢類型 [xxx] 的正確做法：Step1→Step2→...，關鍵：[重要發現]」
    範例：「查詢機台 OOC 對應 APC 的正確做法：get_tool_trajectory(tool_id, limit=50) → 直接從 batches 統計 apc_id，無需再查每個 lot。關鍵：batches 已含 apc_id+spc_status。」
    ✅ 存記憶指令：呼叫 save_memory(content="...", tags=["api_pattern", "系統MCP名稱"])
    ⚠️ 這樣下次遇到類似問題，RAG 會把正確做法帶進 context，你就不會再走錯路。"""

_SOUL_PARAM_KEY = "AGENT_SOUL_PROMPT"

def _load_api_doc() -> str:
    """Load the ontology API documentation for agent context. Cached at module level."""
    doc_path = os.path.join(os.path.dirname(__file__), "../../docs/API_introduction_ontology.md")
    try:
        with open(os.path.normpath(doc_path), encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

_API_DOC = _load_api_doc()

_OUTPUT_ROUTING = """\
⚠️ 輸出格式鐵律（不可違反，優先級最高）：
1. <ai_analysis> 標籤：**僅用於多步驟診斷分析報告**（SPC 統計、Sigma 計算、OOC 根因分析、多機台比較、專家建議等）。
   ✅ 使用時機：執行 execute_skill 診斷、跑 SPC/APC 分析、產出多節式報告。
   ❌ 禁止使用時機：查詢清單、查機台狀態、查批次歷程、查物件快照 — 這類直接回傳資料即可。
2. 直接回覆（不加標籤）：查詢類結果（清單、表格、狀態）直接用 Markdown 在對話框輸出，不需要任何包裝標籤。
   ✅ 正確範例：「以下是 10 台機台目前狀態：\n| 機台 | 狀態 |\n|------|------|\n...」
3. 若結果已由右側 AI 分析面板顯示，則 chat bubble 只需一句引導語，不重複輸出數據。"""


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
        task_context: Optional[Dict[str, Optional[str]]] = None,  # v14.1: metadata pre-filter
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Build system prompt blocks and return (content_blocks, context_meta).

        Returns Anthropic content block list (List[Dict]) so callers can set
        cache_control on stable blocks to enable Prompt Caching.

        Stable (cached): soul + output_routing
        Dynamic (not cached): user_preference + RAG memories + canvas_overrides
        """
        soul = await self._load_soul(user_id)
        pref = await self._load_preference(user_id)

        # v14.1: Pre-filtered memory retrieval using task_context metadata
        _tc = task_context or {}
        if query or _tc.get("task_type"):
            memories, filter_meta = await self._memory_svc.search_with_metadata(
                user_id=user_id,
                query=query or "",
                top_k=top_k_memories,
                task_type=_tc.get("task_type"),
                data_subject=_tc.get("data_subject"),
                tool_name=_tc.get("tool_name"),
            )
        else:
            memories, filter_meta = [], {"strategy": "skipped"}

        rag_lines = [f"- {m.content}" for m in memories]
        rag_block = "\n".join(rag_lines) if rag_lines else "(無相關歷史記憶)"

        # ── Block 1: Soul + output rules + API doc (stable → cache) ──────────
        api_doc_section = (
            f"\n<ontology_api_reference>\n{_API_DOC}\n</ontology_api_reference>"
            if _API_DOC else ""
        )
        stable_text = f"""<soul>
{soul}
  ⚠️ 強制約束：若 <dynamic_memory> 與 <soul> 衝突，一律以 <soul> 鐵律為準。
</soul>
<output_routing_rules>
{_OUTPUT_ROUTING}
</output_routing_rules>{api_doc_section}"""

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
            "memory_filter": filter_meta,          # v14.1: pre-filter details for context_load SSE
            "task_context": _tc,                   # v14.1: extracted task context
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
