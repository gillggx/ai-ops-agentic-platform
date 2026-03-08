# Agent 執行流程說明

> **場景**：使用者在 Agent v13 對話框輸入「幫我做 SPC 的檢查」

---

## 總覽

本系統採用 **5 階段有狀態迴圈（Stateful Agentic Loop）**，由 `AgentOrchestrator` 統籌，透過 **SSE 串流** 即時回傳每個階段的事件給前端。最大迭代次數為 5 輪（`MAX_ITERATIONS = 5`）。

```
User Message
     ↓
[Stage 1] Context Loading
     ↓
[Stage 2] Intent & Planning  ←──────────────────┐
     ↓                                           │
[Stage 3] Tool Execution & Security              │
     ↓                                           │
    有更多工具要呼叫？─────────────────────────── ┘
     ↓ 否
[Stage 4] Reasoning & Synthesis
     ↓
[Stage 5] Output & Memory
```

---

## Stage 1 — Context Loading（背景知識載入）

**負責模組**：`app/services/context_loader.py` → `ContextLoader.build()`

使用者送出訊息後，Agent 第一步是「組裝大腦」——把所有背景知識集中成一個 System Prompt，再帶入本輪對話。

### 三層 System Prompt 結構

```xml
<system>
  <soul>            <!-- 層 1: 鐵律 -->
  <user_preference> <!-- 層 2: 個人偏好 -->
  <dynamic_memory>  <!-- 層 3: RAG 記憶 -->
  <output_routing_rules> <!-- 輸出格式鐵律 -->
</system>
```

| 層 | 來源 | 內容 |
|----|------|------|
| **Soul（鐵律）** | `SystemParameter.AGENT_SOUL_PROMPT` → 使用者覆寫 → 程式預設 | 不可違反的行為規則：診斷優先序（先 Skill→再 MCP→才草稿）、禁止猜測參數、禁止解析 `ui_render_payload`、記憶引用需標注等 |
| **UserPref（個人偏好）** | `user_preferences` 資料表 | 使用者偏好語言、報告格式等（透過 `update_user_preference` 工具更新） |
| **Dynamic Memory（RAG）** | `agent_memory` 向量資料表，以使用者訊息做 keyword 搜尋，取 top-5 相關記憶 | 歷史診斷結果、使用者曾說的事情，例如「[記憶] TETCH01 於 2026-03-01 出現 APC 飽和異常」 |

**SPC 場景**：「幫我做 SPC 的檢查」這句話會觸發對 `agent_memory` 的搜尋，若過去有執行過 SPC 相關診斷，該結果會被注入到 `<dynamic_memory>`，讓 LLM 知道上次的情況。

### 同時載入的其他狀態

- **Session History**：從 `AgentSessionModel` 載入同一 `session_id` 的前 N 輪對話記錄（最多保留 20 則，`_SESSION_MAX_MESSAGES = 20`），確保多輪對話的連貫性。
- **Tool Schemas**：`TOOL_SCHEMAS`（來自 `tool_dispatcher.py`）同步提供給 LLM，讓它知道有哪些工具可以呼叫。

**SSE 事件**：`{ type: "context_load", rag_count: 2, soul_preview: "...", history_turns: 3 }`

---

## Stage 2 — Intent & Planning（意圖理解與規劃）

**負責模組**：`AgentOrchestrator._run_impl()` → `self._client.messages.create()`（Anthropic API）

System Prompt + 工具列表 + 對話歷史，送進 Claude Opus（`claude-opus-4-6`，`max_tokens=4096`），由 LLM 決定「下一步做什麼」。

### SPC 場景的決策樹

Soul 鐵律第 2 條規定了嚴格的優先順序：

```
① 先 list_skills → 找是否有「SPC 連續異常偵測」之類的 Skill
       ↓ 若有 → 直接 execute_skill（帶 skill_id + params）
       ↓ 若缺少參數（chart_name 是什麼？）→ 停下來向用戶詢問
② 若無合適 Skill → list_mcps → execute_mcp 直接取資料
③ 使用者明確要求建立新技能 → draft_skill
```

### Slot Filling（參數收集）

如果 LLM 判斷「有 Skill 但不知道 `chart_name`」，它**不會猜測**（Soul 鐵律第 8 條），而是直接回傳文字詢問：

> 「請問要查哪個 Chart Name？例如 CD_Control、Etch_Rate...」

這是 LLM 層的 Slot Filling——不需要額外的 Slot Filling 框架，Claude 直接用自然語言追問。

### `end_turn` vs `tool_use`

- **`stop_reason = "tool_use"`**：LLM 決定要執行工具 → 進入 Stage 3
- **`stop_reason = "end_turn"`**：LLM 直接回答（如純諮詢問題） → 跳到 Stage 4

---

## Stage 3 — Tool Execution & Security（工具執行與安全閘門）

**負責模組**：`_preflight_validate()` + `ToolDispatcher.execute()`

### Pre-flight 驗證（安全閘門）

每次工具呼叫**執行前**，`_preflight_validate()` 先做攔截：

| 工具 | 驗證內容 |
|------|---------|
| `execute_skill` | skill_id 存在？DB 查 `SkillDefinitionModel` |
| `execute_mcp` | mcp_id 存在？必填參數有無提供？從 System MCP 的 `input_schema.fields` 對照 |

若驗證失敗，錯誤訊息以 `tool_result` 注入回對話（LLM 看到錯誤會自動調整），不對用戶拋出例外。

### SPC Skill 執行路徑（`execute_skill`）

```
ToolDispatcher.execute("execute_skill", {skill_id: 3, params: {chart_name: "CD_Control"}})
        ↓
POST /api/v1/execute/skill/3  (內部 HTTP 呼叫)
        ↓
SkillExecuteService.execute()
  ├─ 1. 從 skill.mcp_ids 取得綁定的 MCP
  ├─ 2. 從 System MCP.api_config 取得 endpoint_url
  ├─ 3. EventPipelineService._fetch_ds_data() → 呼叫外部 API 取得原始 SPC 資料
  ├─ 4. execute_script(mcp.processing_script, raw_data) → Python sandbox 執行 MCP 腳本
  │      ※ 純 Python，無 LLM，確保速度 < 2 秒
  └─ 5. execute_diagnose_fn(diagnose_code, mcp_outputs) → Python sandbox 執行診斷函式
         ※ 使用 Skill Builder 模擬時預先生成並儲存的 diagnose() Python code
         ※ 純 Python，無 LLM，回傳 {status, diagnosis_message, problem_object}
```

**黃金法則**：執行階段完全不呼叫 LLM——只有 MCP/Skill Builder 的 Try-Run 才會呼叫 LLM 生成腳本；執行時直接跑已儲存的 Python。

### 工具回傳結果處理

`_trim_for_llm()` 在把結果送回 LLM 前做截斷：

```python
# execute_skill → 只給 LLM 讀 llm_readable_data（不給 ui_render_payload）
{
  "skill_name": "SPC 連續異常偵測",
  "llm_readable_data": {
    "status": "ABNORMAL",
    "diagnosis_message": "Chart CD_Control 連續 7 點超出 3σ 控制線",
    "problematic_targets": ["TETCH01", "TETCH03"],
    "expert_action": "立即通知製程工程師確認機台狀態"
  }
}
# ui_render_payload（圖表資料）→ 只給前端渲染，LLM 不讀
```

**SSE 事件**：
- `{ type: "tool_start", tool: "list_skills", ... }`
- `{ type: "tool_done", tool: "execute_skill", render_card: {...} }`

---

## Stage 4 — Reasoning & Synthesis（推理與綜合分析）

**負責模組**：`AgentOrchestrator._run_impl()` → `stop_reason == "end_turn"`

所有工具呼叫完成後，LLM 收到完整的 tool_results，進行**最終推理**：

### 輸出格式鐵律（System Prompt 的 `output_routing_rules`）

```
Chat Bubble：一句簡短狀態 + UI 引導語
  ✅ 「✅ SPC 診斷完成，發現 2 台機器異常。👉 請檢視右側 AI 分析報告。」

<ai_analysis> 標籤內：詳細分析（只顯示在右側面板）
  - 哪幾台機器異常
  - 異常原因（diagnosis_message）
  - 專家建議（expert_action）
  - Sigma 計算等數據
```

### Token 節省設計

- `list_skills` 結果去除 `last_diagnosis_result`、`diagnostic_prompt`、`processing_script` 等大欄位（每個 Skill 可省 2,000+ tokens）
- `execute_skill` 只把 `llm_readable_data` 送給 LLM（ui_render_payload 可能有完整圖表 JSON，10KB+）
- Session 歷史最多保留最近 20 則，超過自動截斷

**SSE 事件**：`{ type: "synthesis", text: "✅ SPC 診斷完成..." }`

---

## Stage 5 — Output & Memory（輸出與記憶寫入）

**負責模組**：`AgentOrchestrator._run_impl()` Stage 5 段 + `AgentMemoryService.write_diagnosis()`

### 自動記憶寫入

若本輪診斷結果為 **ABNORMAL**，系統自動寫入長期記憶（無需 LLM 主動呼叫 `save_memory`）：

```python
# 觸發條件：execute_skill 回傳 llm_readable_data.status == "ABNORMAL"
mem = await self._memory_svc.write_diagnosis(
    user_id=user_id,
    skill_name="SPC 連續異常偵測",
    targets=["TETCH01", "TETCH03"],
    diagnosis_message="Chart CD_Control 連續 7 點超出 3σ",
    skill_id=3,
)
```

下次相同用戶問起 TETCH01 相關問題，這條記憶會被 RAG 撈出注入 `<dynamic_memory>`。

**SSE 事件**：`{ type: "memory_write", content: "TETCH01 SPC 異常...", memory_id: 42 }`

### 前端輸出

| 輸出位置 | 內容 |
|---------|------|
| **Chat Bubble（左側）** | 一句話結論 + 引導語 |
| **DATA & CHART 面板（右側）** | Skill 執行結果 tab：圖表（Plotly）+ 資料表格 |
| **AI ANALYSIS 面板（右側）** | `<ai_analysis>` 標籤內的詳細報告 |
| **草稿卡片（若有）** | `draft_routine_check` 工具呼叫後的審核卡，帶「開啟編輯器 — 審核並發佈」按鈕 |

### Session 儲存

對話歷史寫回 `AgentSessionModel`，保留最後 20 則並清除邊界孤立的 `tool_result`（`_clean_history_boundary()`），確保下次呼叫 Anthropic API 不因 orphaned block 而 400 錯誤。

**SSE 事件**：`{ type: "done", session_id: "abc123" }`

---

## 完整 SSE 事件時序（SPC 場景）

```
→ context_load      { rag_count: 1, history_turns: 2 }
→ tool_start        { tool: "list_skills" }
→ tool_done         { tool: "list_skills", result_summary: "5 skills found" }
→ tool_start        { tool: "execute_skill", input: { skill_id: 3, params: { chart_name: "CD_Control" } } }
→ tool_done         { tool: "execute_skill", render_card: { type: "skill_result", ... } }
→ synthesis         { text: "✅ SPC 診斷完成，TETCH01 異常。👉 請檢視右側 AI 分析報告。\n<ai_analysis>...</ai_analysis>" }
→ memory_write      { content: "SPC CD_Control ABNORMAL: TETCH01...", memory_id: 42 }
→ done              { session_id: "abc123" }
```

---

## 架構摘要

```
使用者訊息
    │
    ▼
AgentOrchestrator.run()          # 總控，SSE 串流
    │
    ├─[Stage 1] ContextLoader.build()
    │             Soul (鐵律) + UserPref + RAG top-5
    │
    ├─[Stage 2] Anthropic API (Claude Opus)
    │             System Prompt + TOOL_SCHEMAS + session history
    │             → 決定呼叫哪個工具，或直接 end_turn
    │
    ├─[Stage 3] _preflight_validate() → ToolDispatcher.execute()
    │             execute_skill → SkillExecuteService (純 Python sandbox)
    │             execute_mcp   → MCP 腳本 sandbox (純 Python)
    │             list_skills / list_mcps → DB 查詢
    │             draft_routine_check → AgentDraftModel (草稿存 DB)
    │             search_memory / save_memory → AgentMemoryService
    │
    ├─[Stage 4] Anthropic API end_turn
    │             合成最終回答，格式鐵律：Chat Bubble + <ai_analysis>
    │
    └─[Stage 5] AgentMemoryService.write_diagnosis()
                  ABNORMAL 結果自動寫入長期記憶
                  Session 寫回 AgentSessionModel
```
