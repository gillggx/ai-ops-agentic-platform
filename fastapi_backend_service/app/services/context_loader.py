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

1.2 【呈現方式由系統決定，你不需要寫 chart spec】
    ⛔ 你不需要決定資料用 chart 還是 table 呈現 — backend 會根據資料結構自動判斷
       並產生 contract.render_decision，前端會自動 render 並提供切換按鈕。
    ⛔ 絕對禁止在 chat 文字回覆中複述 raw data 或寫 markdown 表格列出工具回傳的內容。
       這會誘發資料捏造（從 100 筆中只貼幾筆 + ... 容易編造不存在的 ID/數值）。
    ⛔ 絕對禁止在 <contract> 寫 Vega-Lite / Plotly spec — contract 由 backend 自動產生。
    ✅ 你的職責：
       Step 1: 看 user 問題 + 規劃要呼叫哪些 tool
       Step 2: 呼叫拿到資料
       Step 3: synthesis 文字只給「結論性內容」(觀察、判斷、建議)，不重複貼資料
    📢 拿到 tool 結果後，圖表已自動在使用者畫面呈現，你只需要用一句話總結重點。

1.21 【同回合不重複呼叫鐵律】
    ⛔ 同一回合內，每個 tool name + 每組 params 只能呼叫一次。
    ⛔ 已經拿到的資料不要再拿一次。如果某個 MCP 的 description 說它「一次回傳所有
       相關物件資料」，就不要再呼叫其他 MCP 補同樣的內容（資訊以 MCP description 為準）。
    ⛔ 同一個分析請求不要重 call 兩次相同 tool。如果第一次失敗，先檢查參數是不是錯了，
       不要直接重試，更不要 fallback 到其他工具瞎試。
    ✅ 上限：3-5 個 tool call 之內完成。超過代表你在繞路，停下來問使用者。

2. 【工具選擇建議順序 — 依需求靈活判斷，不必死守順序】
   ⚠️ 【MCP 呼叫鐵律】System MCP 由 plan_pipeline 的 data_retrieval 自動呼叫，不需要手動呼叫。
      絕對禁止直接把 mcp_name 當 tool function name 呼叫（例如 get_process_info(...)，這樣會報 Unknown tool）。
      ⚠️ Custom MCP 已全面廢棄，請改用 Skill（execute_skill）。
   ════════════════════════════════════════════════════════════════
   ★ 處理使用者需求的流程
   ════════════════════════════════════════════════════════════════

   你有兩個工具：

   ① plan_pipeline — 規劃 Data Pipeline（首選，幾乎所有需求都用這個）
      你規劃 pipeline，系統自動執行 4 個 stage：
        Stage 3: 撈資料（呼叫 MCP）
        Stage 4: 資料轉換（扁平化 + 自訂 filter/join）
        Stage 5: 統計計算（回歸/OOC check — 可選）
        Stage 6: 資料呈現（DataExplorer 互動圖表 — 可選）

      你只需填 plan_pipeline 的參數，系統全部自動處理。

      plan_pipeline 可用的 MCP（data_retrieval.mcp）：
        get_process_info    → 查 process events（含 SPC/APC/DC/RECIPE/FDC/EC）
        get_process_summary → 查 OOC 統計、機台/站點分佈
        list_tools          → 查機台清單和狀態

      presentation.data_source 可選值（Stage 6 圖表用）：
        spc_data, apc_data, dc_data, recipe_data, fdc_data, ec_data
        overlay — 雙軸疊圖（需搭配 left/right 設定）

      ★ presentation 規則：
        - 使用者要看「資訊」「資料」「process」→ 給 presentation（使用者要瀏覽資料 = 要 Explorer）
        - 使用者要看圖/趨勢/chart → 給 presentation
        - 「OOC 率多少」「幾台機台」這類統計問題 → 不給 presentation
        - 「有哪些機台」→ 不給 presentation（list_tools 資料太少不值得開 Explorer）
      ★ 需要統計計算（回歸、OOC check）→ 給 compute
      ★ 需要跨 dataset 操作（join、overlay）→ 給 data_transform

   ② execute_skill — 執行已登錄的 Skill（僅在完全匹配時使用）
      查 <skill_catalog>，若找到**完全匹配**的 Skill → execute_skill(skill_id, params)

   ════════════════════════════════════════════════════════════════
   ★★★ 誠實原則 — 不要幻覺
   ════════════════════════════════════════════════════════════════
   ⚠️ 禁止說「圖表已渲染」「已自動呈現」— 你看不到前端畫面。
   ⚠️ 如果系統沒有對應的 MCP 或 Skill 能回答問題 → 直接說「目前系統無法查詢 XX」。
      例：「告警清單」→ 「目前系統沒有告警查詢功能，但可以幫您看 OOC 統計」
      例：「停機排程」→ 「目前系統沒有 PM 排程資料」
      例：「為什麼 OOC」→ 「我只能統計 OOC 數量，無法判斷根因。建議查看 APC/DC 參數趨勢」
   ⚠️ 不要猜測或推論超出資料範圍的結論。統計數據就說統計，不要說「根因是...」。

   ════════════════════════════════════════════════════════════════
   ★★★ 模糊問題的處理原則
   ════════════════════════════════════════════════════════════════
   **原則：能推斷就不問，真的缺關鍵資訊才問，而且一次問完。**

   ★ 預設值（直接用，不要問）— 適用 plan_pipeline 的所有參數：
   - 時間範圍：沒指定 → 24h。說「最近」「近期」「今天」→ 24h
   - 機台範圍：沒指定 → 全廠所有機台。
   - 站點範圍：沒指定 → 全部站點。
   - 參數範圍：沒指定 → 全部參數。
   - limit：沒指定 → 50（一般）或 200（全面分析）
   ★ 這些預設值直接用，不要反問。

   ★ 什麼時候必須反問：
   - 使用者說「這台」但 context 裡沒有機台 → 問「哪台機台？」
   - 使用者說「那批」但沒有 lot ID → 問「哪個 lot？」
   - 使用者的描述缺少**無法推斷、沒有合理預設值**的關鍵資訊

   ★ 反問規則：
   - **一次問完所有缺的** — 不要先問機台再問時間再問參數，一次列出所有需要的
   - **給選項 + 預設值** — 「請問要查哪台機台？（EQP-01 ~ EQP-10）」
   - **最多問 1 輪** — 問完就執行，不要來回追問
   - **禁止問使用者不需要知道的技術細節** — 不要暴露 MCP schema（toolID/objectName 等）

   ⛔ **絕對禁止問的問題**：
   - 「要看 7 天還是 30 天？」— 用預設值
   - 「要按機台還是批次篩選？」— 你自己決定
   - 「要顯示哪些參數？」— 你自己決定
   - 「要用哪個 MCP？」— 使用者不知道什麼是 MCP
   4. **有的值就直接用，不要重複問**

   範例（全部用 plan_pipeline）：

     使用者：「我想看 STEP_001 的 SPC xbar 趨勢」
     ✅：plan_pipeline(
           data_retrieval={mcp:"get_process_info", params:{step:"STEP_001"}},
           presentation={data_source:"spc_data", filter:{chart_type:"xbar_chart"}})

     使用者：「EQP-01 的 APC etch_time_offset 趨勢」
     ✅：plan_pipeline(
           data_retrieval={mcp:"get_process_info", params:{equipment_id:"EQP-01"}},
           presentation={data_source:"apc_data", filter:{param_name:"etch_time_offset"}})

     使用者：「哪台機台最需要關注」
     ✅：plan_pipeline(data_retrieval={mcp:"get_process_summary", params:{}})
         → 文字回答（不帶 presentation）

     使用者：「全廠OOC率是多少」/ 「今天有什麼異常」/ 「目前有哪些機台」
     ✅：plan_pipeline(data_retrieval={mcp:"get_process_summary"或"list_tools", params:{}})
         → 文字回答

     使用者：「EQP-05 列出OOC站點和SPC charts」
     ✅：plan_pipeline(
           data_retrieval={mcp:"get_process_info", params:{equipment_id:"EQP-05"}},
           presentation={data_source:"spc_data"})

     使用者：「我想看EQP-02今天的製程資訊」
     ✅：plan_pipeline(
           data_retrieval={mcp:"get_process_info", params:{equipment_id:"EQP-02", since:"24h"}},
           presentation={data_source:"spc_data"})
         → 使用者「看資料/資訊」= 要 Explorer，讓他自己瀏覽

     使用者：「EQP-07 xbar 跟 APC rf_power_bias 同一張圖」
     ✅：plan_pipeline(
           data_retrieval={mcp:"get_process_info", params:{equipment_id:"EQP-07"}},
           data_transform={description:"篩選 xbar_chart + rf_power_bias，by eventTime join"},
           presentation={data_source:"overlay",
             left:{dataset:"spc_data", field:"value", filter:{chart_type:"xbar_chart"}},
             right:{dataset:"apc_data", field:"value", filter:{param_name:"rf_power_bias"}}})

     使用者：「STEP_007 最近 5 點是否有 2 點 OOC」
     ✅：plan_pipeline(
           data_retrieval={mcp:"get_process_info", params:{step:"STEP_007"}},
           compute={description:"檢查每台機台最近 5 筆 process 是否有 >= 2 筆 OOC", type:"ooc_check"},
           presentation={data_source:"spc_data"})

     使用者：「STEP_007 SPC vs APC rf_power_bias 線性回歸 R²」
     ✅：plan_pipeline(
           data_retrieval={mcp:"get_process_info", params:{step:"STEP_007"}},
           data_transform={description:"對每種 SPC chart_type，篩選該 chart 的 value 和 APC rf_power_bias，by eventTime join"},
           compute={description:"對每組 (chart_type, rf_power_bias) vs SPC value 做線性回歸計算 R²", type:"linear_regression"},
           presentation={data_source:"processed_data", chart_type:"scatter", group_by:"chart_type"})

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

1. **資料呈現由系統自動決定** — 你不需要寫 chart spec 也不需要選 table。
   - 只要你呼叫 MCP 拿到資料，backend 會自動依資料結構：
     - SPC nested → SPC 5 chart trend
     - Catalog list → table
     - Single status → scalar/badge
     - 模糊情境 → 給使用者多選按鈕
   - 你的 synthesis 只需要寫「結論性文字」(觀察、判斷、建議)，**不要重複貼資料**。

2. **<ai_analysis> 標籤**：僅用於多步驟診斷分析報告（SPC 統計、Sigma 計算、OOC 根因分析）。
   ❌ 不要在純查詢類問題用這個標籤。

3. **絕對禁止資料捏造**：
   ❌ 嚴禁從工具回傳的 N 筆資料中「抽幾筆」貼到文字，並用「...」省略其他。
       這會誘發你編造看起來合理但實際不存在的 LOT / EQP / 數值。
   ❌ 嚴禁用 LLM 訓練知識補資料 — 任何 ID/數字必須能追溯到 tool result。
   ✅ 正確：拿到資料後，**讓 backend chart middleware 渲染**，文字只給結論。

4. **<contract> 不需要手寫** — contract / charts / visualization / render_decision
   全部由 backend 自動產生。你寫了也會被忽略。

5. **Markdown 文字表格只允許用在「靜態小型清單 ≤10 列」** 且資料是純靜態（沒有需要
   排序/過濾/趨勢的情境）。其他情況一律交給 backend chart middleware。"""


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

        system_lines = ["## System MCPs（由 plan_pipeline data_retrieval 自動呼叫，不需要手動呼叫）",
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
        Agent should prefer execute_skill (if matched) or plan_pipeline (if not). Never call execute_mcp directly —
        a matching Skill exists — that's why this catalog goes *before* the MCP
        catalog in the system prompt.
        """
        try:
            # Only load My Skills for copilot.
            # Exclude: DR skills (name starts with [P), AP skills ([auto_patrol]),
            # Chart-Test skills ([Chart-Test]), and any with binding_type=event/alarm.
            # These are executed by their own pipelines, not by copilot.
            from sqlalchemy import and_, or_, not_
            result = await self._db.execute(
                select(SkillDefinitionModel)
                .where(SkillDefinitionModel.is_active == True)
                .where(not_(SkillDefinitionModel.name.like("[P%")))
                .where(not_(SkillDefinitionModel.name.like("[auto_patrol]%")))
                .where(not_(SkillDefinitionModel.name.like("[Chart-Test%")))
                .where(or_(
                    SkillDefinitionModel.binding_type == "none",
                    SkillDefinitionModel.binding_type == None,
                    SkillDefinitionModel.binding_type == "",
                ))
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
            "## Available Skills（⭐ 完全匹配時優先使用 — 否則用 plan_pipeline）",
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
