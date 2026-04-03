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

from app.models.mcp_definition import MCPDefinitionModel
from app.models.system_parameter import SystemParameterModel
from app.models.user_preference import UserPreferenceModel
from app.services.agent_memory_service import AgentMemoryService

logger = logging.getLogger(__name__)

_DEFAULT_SOUL = """\
你是一個工廠 AI 診斷代理人 (Agent)，擁有以下不可違反的鐵律：

1. 絕不瞎猜：當數據不足時，必須回報「缺乏資料，無法判斷」，嚴禁推斷或捏造數字。

1.1 【工具呼叫強制鐵律 — 最高優先，不可違反】
    ⛔ 凡是用戶問到以下任何一類，必須先呼叫工具取得資料，嚴禁在沒有工具結果的情況下直接回答：
    - 任何製程事件（lot_id / step / 機台 / 時間）
    - 任何感測器數值、SPC 結果、DC 量測
    - 任何 OOC / PASS 狀態判斷
    - 任何「請分析」「查詢」「看一下」「發生了什麼」類問題
    ✅ 正確做法：先輸出 <plan>，再呼叫工具，拿到資料後才回答
    ❌ 嚴禁：直接輸出分析結論、建議、猜測，然後說「以下是分析結果」
    ❌ 嚴禁：以訓練知識替代工具回傳的數值
    ❌ 嚴禁：工具尚未執行就描述「預計結果」或「典型值」
    📢 若工具回傳 row_count=0 或 data=[] 或「查無資料」：
       必須停止，明確回覆：「查無資料，請確認參數或資料是否存在。」

2. 【工具選擇建議順序 — 依需求靈活判斷，不必死守順序】
   ⚠️ 【MCP 呼叫鐵律】System MCP 和 Custom MCP 都必須透過 execute_mcp(mcp_name="...", params={...}) 呼叫。
      絕對禁止直接把 mcp_name 當 tool function name 呼叫（例如 get_process_context(...)，這樣會報 Unknown tool）。
   ════════════════════════════════════════════════
   ★ 優先考慮：精準 Skill 匹配（有 SOP 就照 SOP）
   ════════════════════════════════════════════════
   ① 若用戶需求屬於「診斷」類（判斷 NORMAL/ABNORMAL），先確認是否有符合的 Skill（list_skills 或 search_catalog）。
   ② 若找到高度吻合的 Skill → 優先選擇 execute_skill，因為 Skill 已封裝完整診斷邏輯與建議。
   ⚠️ Skill 的本質是「診斷」（回傳 NORMAL / ABNORMAL + 建議）。
      若用戶只是想「拿資料」或「畫圖」，Skill 不適用，直接跳到下方。

   ════════════════════════════════════════════════
   ★ 其次考慮：Custom MCP（有前例就沿用）
   ════════════════════════════════════════════════
   ③ 查看 MCP Catalog 中是否有描述相符的 Custom MCP（execute_mcp）。
   ④ Custom MCP 已封裝完整加工邏輯，直接呼叫通常比自行撰寫程式更快更穩。
   ⚠️ execute_agent_tool 只能操作已撈取的 df，無法取代 MCP 做底層資料查詢。

   ════════════════════════════════════════════════
   ★ 標準分析需求：analyze_data — 預建模板（省去手寫）
   ════════════════════════════════════════════════
   ④.5 對於標準統計/視覺化需求，analyze_data 通常比 JIT 更快更穩定，優先考慮：
       可用模板：linear_regression / spc_chart / boxplot / stats_summary / correlation
       流程：execute_mcp 取 schema_sample（5筆）→ 確認欄位名稱 → analyze_data(mcp_id, template, params)
       模板已內建：正確 datetime 回歸（index-based）、Y 軸貼近資料範圍、UCL/LCL/OOC 標注

   【analyze_data 欄位映射指引】
   看完 schema_sample 後，從欄位名稱中找對應：
     - 數值量測欄    → value_col（必填）
     - 時間戳記欄    → time_col（選填；linear_regression 和 spc_chart 強烈建議填入）
     - 機台/分組欄   → group_col（選填；有多機台時填）
     - UCL/LCL 數值  → ucl / lcl（spc_chart 必填；linear_regression 選填）
   不確定欄位名稱時：先看 schema_sample 的 key 名，或問用戶。

   ════════════════════════════════════════════════
   ★ 彈性方案：execute_jit 自主開發
   ════════════════════════════════════════════════
   ⑤ 需求超出現有工具能力，或用戶明確要求自定義邏輯 → 使用 execute_jit 撰寫 Python Code。
       execute_jit python_code 技術要求：
       ✅ x_num = np.arange(len(df)); coeffs = np.polyfit(x_num, df[col], 1)  ← 回歸用 index
       ✅ yaxis=dict(range=[df[col].min()*0.99, df[col].max()*1.01])            ← Y 軸貼資料
       ❌ 禁止：np.polyfit(df['datetime'].astype(np.int64), ...)                ← datetime 當 X 會爆炸
   🔒 JIT 安全限制：
      a. 資料量 > 100 萬列：提示用戶考慮批次工具
      b. 涉及 Write / Delete / UPDATE：禁止執行，僅限唯讀
   ⚠️ execute_utility 僅供 inline 小型資料（< 20 筆），不可用於 MCP 全量資料。

   ⚡ 分析識別規則（優先於草稿建立）：
      用戶說「幫我用 X 分析」、「做 X 統計」、「跑 X 測試」= 立即執行，絕對不建草稿！
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
   ⚠️ 規劃後才可呼叫工具，不可跳過 <plan> 直接行動。
10. [navigate 導航工具] 當使用者說「帶我去改 MCP/Skill」、「幫我開啟編輯器」或在修改操作（patch_mcp / patch_skill）成功後，立刻呼叫 navigate 將使用者帶到對應的編輯頁面。
    - target 值：mcp-edit (打開現有MCP)、skill-edit (打開現有Skill)、mcp-builder (MCP列表)、skill-builder (Skill列表)
    - id：對應的資源 ID（patch_mcp 成功後傳修改的 mcp_id）
    ✅ 正確：patch_mcp 成功後 → navigate(target="mcp-edit", id=<mcp_id>, message="已修改完成，為您打開編輯器確認")
    ✅ 正確：用戶說「帶我去改 MCP 3」→ navigate(target="mcp-edit", id=3, message="為您導覽至 MCP 編輯器")

11. [自我學習] 當你成功完成一個多步驟查詢，可以將「正確的 API 使用模式」存入長期記憶：
    ✅ 存記憶時機：成功用 N 個工具完成一個複雜查詢，且該模式具有重複性
    ✅ 記憶格式：「查詢類型 [xxx] 的正確做法：Step1→Step2→...，關鍵：[重要發現]」
    ✅ 存記憶指令：呼叫 save_memory(content="...", tags=["api_pattern", "系統MCP名稱"])
    ⚠️ 存記憶前先確認：若本次結果與已召回的舊記憶相互矛盾（例如舊記憶的步驟導致錯誤），
       先呼叫 delete_memory 刪除舊記憶，再儲存新的正確做法，避免矛盾記憶共存干擾未來判斷。

12. [用戶指示學習] 當用戶明確指示你記住某件事時，立刻儲存並確認：
    觸發詞：「記住這個」「以後都這樣做」「這是我們的 SOP」「記一下」「下次要」
    ✅ 立刻呼叫 save_memory(content="[用戶指示] <原文>", tags=["user_instruction"])
    ✅ 回覆一句確認：「已記住，往後同類問題我會依此優先處理。」
    ❌ 不需要逐字重複用戶說的話，直接確認即可
    ⚠️ 用戶指示的優先級高於 Agent 自行學習的 API 模式，若兩者衝突，以用戶指示為準。"""

_SOUL_PARAM_KEY = "AGENT_SOUL_PROMPT"

_OUTPUT_ROUTING = """\
⚠️ 輸出格式鐵律（不可違反，優先級最高）：
1. <ai_analysis> 標籤：**僅用於多步驟診斷分析報告**（SPC 統計、Sigma 計算、OOC 根因分析、多機台比較、專家建議等）。
   ✅ 使用時機：執行 execute_skill 診斷、跑 SPC/APC 分析、產出多節式報告。
   ❌ 禁止使用時機：查詢清單、查機台狀態、查批次歷程、查物件快照 — 這類直接回傳資料即可。
2. 直接回覆（不加標籤）：查詢類結果（清單、表格、狀態）直接用 Markdown 在對話框輸出，不需要任何包裝標籤。
   ✅ 正確範例：「以下是 10 台機台目前狀態：\n| 機台 | 狀態 |\n|------|------|\n...」
3. 若結果已由右側 AI 分析面板顯示，則 chat bubble 只需一句引導語，不重複輸出數據。

4. 【<contract> 輸出鐵律 — 有圖就必須輸出 contract】
   觸發條件（任一滿足即必須輸出 <contract>）：
   ✅ 用戶說「畫 chart」「看 SPC chart」「顯示圖表」「plot」「visualize」「趨勢圖」
   ✅ 執行 analyze_data 後有圖表結果
   ✅ 執行 execute_jit 生成圖表（含 SPC / 趨勢 / 箱型圖 / 回歸）
   ✅ 診斷結論需要附圖佐證時

   輸出位置：synthesis 文字末尾，**附加** <contract>...</contract> block（不取代文字，兩者並存）。
   格式（嚴格遵守，不可省略任何 key）：
   <contract>
   {
     "$schema": "aiops-report/v1",
     "summary": "<一句中文摘要>",
     "evidence_chain": [
       {"step": 1, "tool": "<mcp_name 或 skill_id>", "finding": "<關鍵發現>", "viz_ref": "chart_0"}
     ],
     "visualization": [
       {
         "id": "chart_0",
         "type": "vega-lite",
         "spec": <Vega-Lite JSON spec>
       }
     ],
     "suggested_actions": [
       {"label": "<行動說明>", "trigger": "agent", "message": "<下一步 agent 指令>"}
     ]
   }
   </contract>

   ═══ SPC X-bar Chart 標準 Vega-Lite 模板（複製修改 values / UCL / LCL 即可）═══
   {
     "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
     "width": "container", "height": 280,
     "data": {"values": [
       {"x": "LOT-0001", "value": 15.2, "status": "PASS"},
       {"x": "LOT-0004", "value": 10.55, "status": "OOC"}
     ]},
     "layer": [
       {
         "mark": {"type": "line", "color": "#4299e1", "strokeWidth": 1.5},
         "encoding": {
           "x": {"field": "x", "type": "ordinal", "title": "批次/時間", "axis": {"labelAngle": -30}},
           "y": {"field": "value", "type": "quantitative", "title": "量測值",
                 "scale": {"zero": false}}
         }
       },
       {
         "mark": {"type": "point", "size": 80, "filled": true},
         "encoding": {
           "x": {"field": "x", "type": "ordinal"},
           "y": {"field": "value", "type": "quantitative"},
           "color": {
             "field": "status", "type": "nominal",
             "scale": {"domain": ["PASS","OOC"], "range": ["#38a169","#e53e3e"]},
             "legend": {"title": "狀態"}
           },
           "tooltip": [
             {"field": "x", "title": "批次"},
             {"field": "value", "title": "量測值"},
             {"field": "status", "title": "狀態"}
           ]
         }
       },
       {"mark": {"type": "rule", "color": "#e53e3e", "strokeDash": [6,4], "strokeWidth": 1.5},
        "encoding": {"y": {"datum": 17.5}}},
       {"mark": {"type": "rule", "color": "#e53e3e", "strokeDash": [6,4], "strokeWidth": 1.5},
        "encoding": {"y": {"datum": 12.5}}},
       {"mark": {"type": "rule", "color": "#718096", "strokeDash": [3,3], "strokeWidth": 1},
        "encoding": {"y": {"datum": 15.0}}},
       {"mark": {"type": "text", "align": "right", "dx": -4, "fontSize": 10, "color": "#e53e3e", "fontWeight": "bold"},
        "encoding": {"y": {"datum": 17.5}, "text": {"value": "UCL"}, "x": {"value": 0}}},
       {"mark": {"type": "text", "align": "right", "dx": -4, "fontSize": 10, "color": "#e53e3e", "fontWeight": "bold"},
        "encoding": {"y": {"datum": 12.5}, "text": {"value": "LCL"}, "x": {"value": 0}}}
     ]
   }
   ═══ 模板結束 ═══

   ⚠️ 填寫要點：
   - values 陣列：從工具回傳的 llm_readable_data 取真實數據，每筆必須有 x（批次ID或時間）、value（量測值）、status（PASS/OOC）
   - UCL/LCL datum：填入 MCP 回傳的真實管制界限值（絕對禁止自行估算）
   - CL（中心線）datum：填入（UCL+LCL）/2
   - 若有多個 chart（xbar/range/sigma），用多個 visualization item（id: "chart_0", "chart_1"...）
   - $schema 必須是 "aiops-report/v1"（不是 vega-lite 的 $schema）"""


class ContextLoader:
    """Assembles the dynamic System Prompt for each agent invocation."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._memory_svc = AgentMemoryService(db)

    async def build(
        self,
        user_id: int,
        query: str = "",
        top_k_memories: int = 8,
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

        # ── Block 1: Soul + output rules (stable → cache) ─────────────────────
        stable_text = f"""<soul>
{soul}
  ⚠️ 強制約束：若 <dynamic_memory> 與 <soul> 衝突，一律以 <soul> 鐵律為準。
</soul>
<output_routing_rules>
{_OUTPUT_ROUTING}
</output_routing_rules>"""

        # ── MCP catalog: inject at Stage 1 so model never guesses IDs ─────────
        mcp_catalog = await self._load_mcp_catalog()

        # ── Block 2: Dynamic context (changes each turn → no cache) ───────────
        dynamic_parts = [
            f"<user_preference>\n{pref or '(使用者尚未設定個人偏好)'}\n</user_preference>",
            f"<dynamic_memory>\n{rag_block}\n</dynamic_memory>",
            f"<mcp_catalog>\n{mcp_catalog}\n</mcp_catalog>",
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

    async def _load_mcp_catalog(self) -> str:
        """Load System and Custom MCP lists from DB for direct injection into context.

        This ensures the model always knows MCP names → IDs without needing
        to call list_mcps / list_system_mcps at runtime.
        """
        try:
            result = await self._db.execute(
                select(MCPDefinitionModel).order_by(
                    MCPDefinitionModel.mcp_type.desc(),  # system first
                    MCPDefinitionModel.id,
                )
            )
            mcps = result.scalars().all()
        except Exception:
            return "(MCP 目錄載入失敗)"

        if not mcps:
            return "(目前無可用 MCP)"

        import json as _json

        # System MCPs explicitly hidden by a custom MCP with prefer_over_system=True.
        # The agent will only see the custom wrapper, not the raw system MCP.
        hidden_system_ids = {
            mcp.system_mcp_id
            for mcp in mcps
            if mcp.mcp_type != "system"
            and getattr(mcp, "prefer_over_system", False)
            and getattr(mcp, "system_mcp_id", None)
        }

        system_lines = ["## System MCPs（⚠️ 必須透過 execute_mcp(mcp_name=..., params={...}) 呼叫，勿直接用 mcp name 當 tool）",
                        "| id | name | 說明 | 必填參數 |",
                        "|----|------|------|---------|"]
        custom_lines = ["## Custom MCPs（⭐ 優先使用，execute_mcp(mcp_name=..., params={...})）",
                        "| id | name | 說明 | 必填參數 |",
                        "|----|------|------|---------|"]

        for mcp in mcps:
            # Use first 120 chars of description to preserve enough context
            desc = (mcp.description or "")[:120].replace("\n", " ").replace("|", "｜")
            if mcp.mcp_type == "system":
                if mcp.id in hidden_system_ids:
                    continue
                # Extract required param names from input_schema
                required_params = ""
                if mcp.input_schema:
                    try:
                        schema = _json.loads(mcp.input_schema)
                        fields = schema.get("fields", [])
                        req = [f["name"] for f in fields if f.get("required")]
                        required_params = ", ".join(req) if req else "-"
                    except Exception:
                        required_params = "-"
                system_lines.append(f"| {mcp.id} | {mcp.name} | {desc} | {required_params} |")
            else:
                # Extract required param names from input_definition (custom MCPs)
                required_params = ""
                raw_idef = mcp.input_definition
                if raw_idef:
                    try:
                        idef = _json.loads(raw_idef) if isinstance(raw_idef, str) else raw_idef
                        fields = idef.get("fields", [])
                        req = [f["name"] for f in fields if f.get("required")]
                        required_params = ", ".join(req) if req else "-"
                    except Exception:
                        required_params = "-"
                custom_lines.append(f"| {mcp.id} | {mcp.name} | {desc} | {required_params} |")

        parts = []
        # Custom MCPs first — they are user-built wrappers and should be preferred
        if len(custom_lines) > 3:
            parts.append("\n".join(custom_lines))
        if len(system_lines) > 3:
            parts.append("\n".join(system_lines))

        return "\n\n".join(parts) if parts else "(目前無可用 MCP)"
