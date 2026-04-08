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
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.mcp_definition import MCPDefinitionModel
from app.models.skill_definition import SkillDefinitionModel
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

1.15 【時間窗使用鐵律 — 時序類 MCP】
    get_process_events / get_process_events 已採用「時間窗」設計，不是筆數導向：
    - 預設 since='7d' → 回傳過去 7 天所有事件（上限 limit=500）
    - 問「今天」或「最近 24 小時」→ 明確傳 since='24h'
    - 問「最近一週」或一般「最近」→ 不帶 since，用預設 7d
    - 問「本月」或「30 天」→ 傳 since='30d'
    - 統計類問題（例如「今天最差的機台」「OOC 排行」）→ 必須帶足夠時間窗
    ⚠️ since 參數格式鐵律（違反會回 INVALID_SINCE 錯誤）：
       ✅ 正確：since='24h' / since='7d' / since='14d' / since='30d'（字串！）
       ❌ 錯誤：since_hours=24 / hours=24 / since=24 / timeRange='today'
    ⚠️ 樣本量 < 5 筆時禁止講百分比（例如 1/1=100% 或 2/3=66% 都無統計意義）
    ⚠️ 看到樣本量很小時，先檢查是否用了太短的時間窗，考慮擴大 since

1.16 【歷史事件鐵律 — 禁止用 get_process_info 覆寫 ground truth】
    從 get_process_events / get_process_events 拿到的事件清單中的欄位：
      eventTime, lotID, toolID, step, spc_status, fdc_class
    是該事件當時的 ground truth，不可被其他 API 覆寫。
    ❌ 禁止：拿到事件後呼叫 get_process_info 「驗證」或「查實際 toolID」
    ❌ 禁止：看到 get_process_info 回的 toolID 跟 get_process_events 不同就「糾正」
       → 事實是你用 get_process_info 沒帶 eventTime，拿到的是後來的 snapshot，
         不是當時的事件；是你用錯 API，不是 get_process_events 錯了。
    ✅ 正確：要查某筆歷史事件的 SPC/DC 細節時，get_process_info 必須帶原事件的 eventTime
    ✅ 正確：要統計 toolID 分布、OOC 率 → 直接用 get_process_events 回傳的欄位即可，
       完全不需要呼叫 get_process_info 做二次驗證

1.2 【CHART 鐵律 — 圖表只能來自工具，絕對禁止 LLM 自行生成】
    ⛔ 所有圖表必須透過 tool 產出，只允許兩條路徑：
       (A) execute_skill 呼叫有 _charts output 的 Skill（例如「SPC 管制圖呈現」）
       (B) execute_jit 寫 python_code，在 return dict 中包含 _chart 或 _charts DSL
    ⛔ 絕對禁止在 <contract> 的 visualization 欄位直接寫 Vega-Lite 或 Plotly spec。
       即使你寫了，backend 會強制清空，圖不會出現在使用者畫面。
    ✅ 正確流程（統計/分析/視覺化類問題）：
       Step 1: execute_mcp 撈取原始資料（帶足夠的 since 範圍）
       Step 2: execute_jit 用 Python 處理資料 + 組裝 _chart DSL
       Step 3: synthesis 只給文字結論，contract.visualization = []
    ✅ _chart DSL 範例（在 execute_jit 的 python_code 裡，process 回傳 dict）：
       return {
         "status": "success",
         "_chart": {
           "type": "bar",
           "title": "各機台 OOC 率",
           "data": [{"tool": "EQP-01", "ooc_rate": 0.15}, ...],
           "x": "tool", "y": ["ooc_rate"],
         }
       }
    📢 使用者看到 tool result 含 "✅ CHART RENDERED" 標記時，代表圖已在畫面上。
       你只需要用文字說明觀察結論，不要再呼叫繪圖工具。

2. 【工具選擇建議順序 — 依需求靈活判斷，不必死守順序】
   ⚠️ 【MCP 呼叫鐵律】System MCP 必須透過 execute_mcp(mcp_name="...", params={...}) 呼叫。
      絕對禁止直接把 mcp_name 當 tool function name 呼叫（例如 get_process_info(...)，這樣會報 Unknown tool）。
      ⚠️ Custom MCP 已全面廢棄，請改用 Skill（execute_skill）。
   ════════════════════════════════════════════════
   ★ 優先考慮：精準 Skill 匹配（有 SOP 就照 SOP）
   ════════════════════════════════════════════════
   ① 不管是「診斷」、「分析」、「視覺化呈現」還是「標準查詢」，先查 <skill_catalog>（已在 system prompt 中注入）。
      不需要再呼叫 list_skills — catalog 清單已經在你眼前。
   ② 若找到高度吻合的 Skill → 優先選擇 execute_skill(skill_id=<id>, params={...})。
      Skill 已封裝完整邏輯（撈資料 + 處理 + 產圖 + 回結論），一次呼叫完成。
   ⚠️ Skill 不僅限於診斷用途。畫 chart、跑分析、呈現標準圖表都應優先用 Skill。
      例如：「看 SPC chart」→ <skill_catalog> 中的「SPC 管制圖呈現」→ 直接 execute_skill。
   ⚠️ Skill 產出的 chart 會自動渲染至使用者畫面（chart_intents 機制）。
      看到 tool result 含 CHART RENDERED 標記時，表示圖已出現，你的任務只是用文字說明結論，禁止再呼叫繪圖工具。

   ════════════════════════════════════════════════
   ★ 其次考慮：System MCP 撈原始資料
   ════════════════════════════════════════════════
   ③ 沒有合適的 Skill，需要單純查原始資料 → execute_mcp 呼叫 System MCP。
   ④ 注意：execute_mcp 只撈 raw data，不會自動產生圖表。要呈現圖表請改用 Skill 或 execute_jit。
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
   ★ 彈性方案：execute_analysis 動態分析（取代 execute_jit）
   ════════════════════════════════════════════════
   ⑤ <skill_catalog> 裡沒有合適的 Skill，且需要撈資料 + 處理 + 畫圖 + 判斷的複合分析
      → 使用 execute_analysis 動態生成分析步驟。
      ★ 這等同於「動態建一個一次性 Diagnostic Rule 並立刻執行」。
      ★ 結果顯示在中間分析面板（不是 copilot 右側），使用者可以一鍵「儲存為常用工具」。
      ★ steps 格式跟 Diagnostic Rule 一樣（step_id + nl_segment + python_code）。
      ★ python_code 裡可用 await execute_mcp(mcp_name, params) 撈資料。
      ★ 最後一步 assign _chart / _charts（圖）和 _findings（結論）。
      ★ 變數：equipment_id, lot_id, step, event_time, _input 可直接用。
   ⚠️ 禁止在 python_code 裡 import requests/os/sys/subprocess
   ⚠️ 不要猜 MCP 參數名 — 先用 get_object_info 查
   ⚠️ execute_jit 已廢棄，請改用 execute_analysis

   ════════════════════════════════════════════════
   ★ 建立/修改資源（僅限用戶明確要求）
   ════════════════════════════════════════════════
   ⑥ 用戶明確說「建立新技能」→ draft_skill
   ⚠️ Custom MCP 已廢棄，draft_mcp 和 list_mcps 不再使用
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

11. [反思型記憶 — Phase 1]
    系統會自動在背景把每次成功的多步驟任務萃取成抽象經驗存入 <dynamic_memory>，
    你不需要主動呼叫 save_memory。**你的責任是正確地引用記憶**：
    ✅ 若你決定採用 <dynamic_memory> 中某條記憶的策略，必須在回答中加上 `[memory:<id>]` 標記
       範例：「根據 [memory:3]，先用 get_process_events(since='7d') 取得完整樣本...」
    ✅ 引用標記讓系統能正確追蹤哪條記憶有效（成功 +1）、哪條誤導（失敗 -2）
    ⚠️ 若 <dynamic_memory> 中的記憶與當前情境矛盾（例如工具名不對、策略過時），直接忽略不要引用。
       被忽略的記憶會在累積失敗後自動 STALE。
    ⚠️ 記憶的 confidence_score 顯示在每條記憶後面（例如 "信心:7/10"）。
       低於 4 分的記憶要特別警覺、寧可忽略。

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
        # Phase 1: new reflective memory system (pgvector + health scoring)
        from app.services.experience_memory_service import ExperienceMemoryService
        self._exp_memory_svc = ExperienceMemoryService(db)

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

        # ── Phase 1: Reflective Memory (primary) ──────────────────────────
        # Hybrid-filter retrieve: semantic + health + freshness.
        # Each result is wrapped with a prompt-injection guard that includes
        # the memory id so the Agent can attribute its decisions back via
        # [memory:<id>] tags for the feedback loop.
        _tc = task_context or {}
        exp_memories: List[Tuple[Any, float]] = []
        if query:
            try:
                exp_memories = await self._exp_memory_svc.retrieve(
                    user_id=user_id,
                    query=query,
                    top_k=top_k_memories,
                )
            except Exception as exc:
                logger.warning("Experience memory retrieve failed: %s", exc)
                exp_memories = []

        # ── Legacy keyword-based memories (fallback for back-compat) ──────
        # Only queried when no experience memories hit — eventually removable.
        if not exp_memories and (query or _tc.get("task_type")):
            try:
                memories, filter_meta = await self._memory_svc.search_with_metadata(
                    user_id=user_id,
                    query=query or "",
                    top_k=top_k_memories,
                    task_type=_tc.get("task_type"),
                    data_subject=_tc.get("data_subject"),
                    tool_name=_tc.get("tool_name"),
                )
            except Exception:
                memories, filter_meta = [], {"strategy": "error"}
        else:
            memories, filter_meta = [], {"strategy": "experience_memory"}

        # Build the prompt-visible RAG block
        rag_lines: List[str] = []
        for mem, sim in exp_memories:
            # Prompt injection guard — tells the model this is advisory, not fact,
            # and prefixes with [memory:<id>] so the model can cite it.
            rag_lines.append(
                f"- [memory:{mem.id}] (信心:{mem.confidence_score}/10, "
                f"使用:{mem.use_count}, 相似度:{sim:.2f})\n"
                f"  意圖: {mem.intent_summary}\n"
                f"  策略: {mem.abstract_action}"
            )
        for mem in memories:  # legacy fallback
            rag_lines.append(f"- (legacy) {mem.content}")

        rag_block = "\n".join(rag_lines) if rag_lines else "(無相關歷史記憶)"
        if exp_memories:
            rag_block = (
                "⚠️ 以下為過往經驗記憶 (advisory)。這不是絕對真理，請根據當前情境獨立判斷。\n"
                "若引用某條記憶來做決定，請在回答中加上 `[memory:<id>]` 標記以便追蹤。\n"
                "若發現記憶與現實矛盾，請忽略該條並考慮標記為錯誤。\n\n"
                + rag_block
            )

        # ── Block 1: Soul + output rules (stable → cache) ─────────────────────
        stable_text = f"""<soul>
{soul}
  ⚠️ 強制約束：若 <dynamic_memory> 與 <soul> 衝突，一律以 <soul> 鐵律為準。
</soul>
<output_routing_rules>
{_OUTPUT_ROUTING}
</output_routing_rules>"""

        # ── Skill + MCP catalogs: inject at Stage 1 so model never guesses IDs ─────
        # Skill catalog is placed BEFORE mcp_catalog so agent sees the high-level
        # abstractions first (work-in-one-call) before falling back to raw MCPs.
        skill_catalog = await self._load_skill_catalog()
        mcp_catalog = await self._load_mcp_catalog()

        # ── Block 2: Dynamic context (changes each turn → no cache) ───────────
        dynamic_parts = [
            f"<user_preference>\n{pref or '(使用者尚未設定個人偏好)'}\n</user_preference>",
            f"<dynamic_memory>\n{rag_block}\n</dynamic_memory>",
            f"<skill_catalog>\n{skill_catalog}\n</skill_catalog>",
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

        # Build rag_hits from both paths for the SSE event
        from app.services.experience_memory_service import ExperienceMemoryService as _ExpSvc
        rag_hits: List[Dict[str, Any]] = []
        for mem, sim in exp_memories:
            hit = _ExpSvc.to_dict(mem)
            hit["similarity"] = round(sim, 3)
            hit["_source"] = "experience"
            rag_hits.append(hit)
        for mem in memories:
            hit = AgentMemoryService.to_dict(mem)
            hit["_source"] = "legacy"
            rag_hits.append(hit)

        meta: Dict[str, Any] = {
            "soul_preview": soul[:120] + ("..." if len(soul) > 120 else ""),
            "pref_summary": (pref[:80] + "...") if pref and len(pref) > 80 else (pref or "(無)"),
            "rag_hits": rag_hits,
            "rag_count": len(rag_hits),
            "exp_memory_count": len(exp_memories),  # for observability
            "cache_blocks": 1,
            "has_canvas_overrides": bool(canvas_overrides),
            "memory_filter": filter_meta,
            "task_context": _tc,
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
        """Load System MCP list from DB for direct injection into context.

        Custom MCPs are deprecated — the catalog shows only System MCPs (raw data
        sources). For visualization/analysis, the Agent should use Skills via
        execute_skill (see _load_skill_catalog for that list).
        """
        try:
            result = await self._db.execute(
                select(MCPDefinitionModel)
                .where(MCPDefinitionModel.mcp_type == "system")
                .order_by(MCPDefinitionModel.id)
            )
            mcps = result.scalars().all()
        except Exception:
            return "(MCP 目錄載入失敗)"

        if not mcps:
            return "(目前無可用 System MCP)"

        import json as _json

        system_lines = ["## System MCPs（⚠️ 必須透過 execute_mcp(mcp_name=..., params={...}) 呼叫，只負責撈原始資料）",
                        "| id | name | 說明 | 必填參數 |",
                        "|----|------|------|---------|"]

        for mcp in mcps:
            desc = (mcp.description or "")[:120].replace("\n", " ").replace("|", "｜")
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

        return "\n".join(system_lines) if len(system_lines) > 3 else "(目前無可用 System MCP)"

    async def _load_skill_catalog(self) -> str:
        """Load public Skills list for injection into agent context.

        Skills encapsulate "data + processing + visualization" in one callable unit.
        Agent should prefer execute_skill over execute_mcp + execute_jit whenever
        a matching Skill exists — that's why this catalog goes *before* the MCP
        catalog in the system prompt.
        """
        try:
            result = await self._db.execute(
                select(SkillDefinitionModel)
                .where(SkillDefinitionModel.visibility == "public")
                .where(SkillDefinitionModel.is_active == True)
                .order_by(SkillDefinitionModel.id)
            )
            skills = result.scalars().all()
        except Exception:
            logger.debug("_load_skill_catalog failed", exc_info=True)
            return "(Skill 目錄載入失敗)"

        if not skills:
            return "(目前無可用 public Skill)"

        import json as _json

        lines = [
            "## Available Skills（⭐ 優先使用 — 先查此清單再考慮 execute_mcp / execute_jit）",
            "呼叫方式：execute_skill(skill_id=<id>, params={<input_schema 欄位>})",
            "",
            "| id | name | 說明 | 輸入參數 |",
            "|----|------|------|---------|",
        ]

        for skill in skills:
            name = skill.name
            desc = (skill.description or "")[:120].replace("\n", " ").replace("|", "｜")
            required_params = ""
            raw_schema = skill.input_schema
            if raw_schema:
                try:
                    schema = _json.loads(raw_schema) if isinstance(raw_schema, str) else raw_schema
                    # input_schema can be a list of {key,type,required,...} dicts
                    if isinstance(schema, list):
                        req = [f["key"] for f in schema if isinstance(f, dict) and f.get("required")]
                        required_params = ", ".join(req) if req else "-"
                    elif isinstance(schema, dict) and "fields" in schema:
                        req = [f["name"] for f in schema["fields"] if f.get("required")]
                        required_params = ", ".join(req) if req else "-"
                except Exception:
                    required_params = "-"
            lines.append(f"| {skill.id} | {name} | {desc} | {required_params} |")

        return "\n".join(lines)
