# Agent Pipeline — S0 → S6 詳細行為說明

> 版本：v15 (S0 Intent Router 加入後)
> 實作檔案：`app/services/agent_orchestrator.py`

---

## 全局架構

```
用戶輸入
   │
   ▼
┌──────────────────────────────────────┐
│  S0  Intent Router  (意圖分流)        │
│  快速判斷：query / preference /       │
│           feedback / chitchat        │
└──────┬───────────────────────────────┘
       │
       ├─ preference ──▶ 直接寫入記憶 → 確認回覆 → DONE
       ├─ chitchat   ──▶ 輕量 LLM 回覆 → DONE
       ├─ feedback   ──▶ 寫入反饋記憶 → 繼續走 S1-S6（讓 LLM 確認）
       └─ query      ──▶ 繼續走 S1-S6
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  S1  Context Load        (情境感知)                  │
│  S2  Strategic Planning  (多路徑規劃)                │
│  S3  Tool Execution      (工具執行) ◀─────────────┐ │
│  S4  Parallel Synthesis  (推理彙整)                │ │
│      └─ 若還有 tool_use → 回到 S3 ────────────────┘ │
│  S5  Self-Reflection     (品質自省)                  │
│  S6  Memory Learning     (記憶蒸餾)                  │
└─────────────────────────────────────────────────────┘
```

---

## S0 — Intent Router（意圖分流）

**目的**：在進入高成本的完整 pipeline 之前，以最小代價判斷用戶的真實意圖，避免 Soul Prompt 膨脹。

**執行方式**

1. **關鍵字快速路徑**：先掃描訊息是否包含偏好觸發詞（「記得」「記住」「以後」「下次」等），若命中 → 直接標記為 `preference`，不呼叫 LLM
2. **LLM 分類**（未命中關鍵字時）：呼叫一個 system prompt 極短（~100 tokens）的 LLM call，輸出 `{"intent": "..."}`
3. **Fallback**：LLM 超時或解析失敗 → 預設為 `query`，保持現有行為不中斷

**四種意圖路由**

| Intent | 定義 | 路由 |
|---|---|---|
| `query` | 診斷/查詢/分析/執行任務 | → S1-S6 完整 pipeline |
| `preference` | 用戶要記住某條規則（「記得 APC 就查 APC」） | → save_memory → 確認 → DONE |
| `feedback` | 糾正 AI 錯誤（「不是這個意思」「你搞錯了」） | → 寫入 feedback 記憶 → 繼續 S1-S6 讓 LLM 回應 |
| `chitchat` | 打招呼/閒聊 | → 輕量 LLM 回覆 → DONE |

**SSE 事件**
```json
{"type": "stage_update", "stage": 0, "label": "意圖分流 (Intent Router)", "status": "running"}
{"type": "stage_update", "stage": 0, "status": "complete", "intent": "preference"}
```

---

## S1 — Context Load（情境感知）

**目的**：在 LLM 開始思考前，組裝所有必要的背景資訊。

**執行步驟**

1. **Task Context 萃取**（無 LLM）：從訊息文字用 regex/keyword 預判 `task_type`、`data_subject`、`tool_name`，用於後續記憶檢索的 metadata pre-filter
2. **系統上下文建構**（`ContextLoader.build()`）：
   - 載入 Soul Prompt（加 `cache_control: ephemeral` 啟用 Prompt Caching）
   - 載入用戶偏好（`AgentPreference`）
   - RAG 記憶檢索：用 `task_context` 過濾後取 top-5 相關記憶（包含 trap、preference、diagnosis）
   - 注入 MCP Catalog（`<mcp_catalog>`）與 Skill Catalog
3. **Session 載入**：從 DB 取出歷史對話（最多 12 輪），計算累積 token 數
4. **Token Compaction**：若累積 token > 60,000，壓縮歷史對話

**輸出**：`system_blocks`（供 S2 LLM call 使用）、`history`、`session_id`

**SSE 事件**
```json
{"type": "stage_update", "stage": 1, "status": "running"}
{"type": "context_load", "soul_loaded": true, "rag_count": 3, "history_turns": 4}
{"type": "stage_update", "stage": 1, "status": "complete"}
```

---

## S2 — Strategic Planning（多路徑規劃）

**目的**：LLM 根據完整 context 進行推理，決定「要做什麼、用哪些工具、按什麼順序」。

**執行步驟**

1. 組合 `system_blocks + history + 當前訊息` 送入 LLM（帶完整 TOOL_SCHEMAS）
2. LLM 輸出可能包含：
   - `<plan>` 標籤：顯式的執行計劃（DAG 工具鏈）
   - `<thinking>` 標籤（Claude 擴展推理模式）：內部推理過程
   - 直接 `tool_use`：跳過 plan，直接呼叫工具

**計劃解析**

- 若有 `<plan>` → 萃取並 emit `tool_start` 系列事件，按 DAG 順序排列工具
- 若無 `<plan>` 但有 `tool_use` → 直接進入 S3（emit「直接進入工具執行」日誌）
- 若 `stop_reason == "end_turn"` 且無工具 → 跳至 S4 合成

**SSE 事件**
```json
{"type": "stage_update", "stage": 2, "status": "running"}
{"type": "thinking", "text": "...LLM 內部推理..."}
{"type": "llm_usage", "input_tokens": 8774, "output_tokens": 320, "iteration": 1}
{"type": "stage_update", "stage": 2, "status": "complete"}
```

---

## S3 — Tool Execution（工具執行）

**目的**：執行 LLM 決定的工具，含安全審查（HITL）與 preflight 驗證。

**執行步驟（每個 tool_use block）**

1. **Preflight 驗證**（`_preflight_validate()`）：
   - `execute_mcp`：確認 `mcp_name` 存在、必填 params 是否齊全
   - `execute_skill`：確認 `skill_id` 存在
   - 若缺必填參數 → 回傳 `MISSING_PARAMS` 錯誤，強制 LLM 詢問用戶
   - 全選填 params 的 MCP（overview 類）→ 直接放行
2. **HITL 安全門**（破壞性工具）：
   - `patch_skill_raw`、`draft_routine_check`、`draft_event_skill_link` 等需人工審核
   - 發出 `approval_required` SSE → 等待用戶確認（最多 300 秒）
   - 用戶拒絕 → 記入 Trap 記憶，終止該工具
3. **工具分發**（`ToolDispatcher.execute()`）：
   - `execute_mcp` → `POST /api/v1/agent-execute/mcp/{id}` → `MCPDefinitionService.run_with_data()`
   - System MCP → proxy 到 `localhost:8099`（OntologySimulator）
   - Custom MCP → 執行 processing_script
   - `analyze_data` → 內建模板分析
   - `execute_jit` → sandbox 執行用戶自訂 Python
4. **Data Distillation**：大型 dataset 先做統計摘要（Pandas），避免 LLM context 爆炸
5. **Trap 記憶寫入**：工具出錯 → 自動寫入 trap memory，下次 RAG 召回防止重犯
6. **DataProfile 注入**：MCP 結果的欄位統計 profile 注入為 `<hidden_data_profile>`，供下輪 LLM 參考

**SSE 事件**
```json
{"type": "tool_start", "tool": "execute_mcp", "input": {...}, "iteration": 2}
{"type": "approval_required", "approval_token": "...", "tool": "patch_skill_raw"}
{"type": "tool_done", "tool": "execute_mcp", "result_summary": "10 rows", "render_card": {...}}
{"type": "memory_write", "source": "trap", "memory_type": "trap", "fix_rule": "..."}
{"type": "stage_update", "stage": 3, "status": "complete"}
```

---

## S4 — Synthesis / Reasoning（推理彙整）

**目的**：LLM 整合所有工具結果，產生最終回覆。

**觸發條件**

- `stop_reason == "end_turn"`（LLM 不再呼叫工具）
- `_force_synthesis == True`（工具出現不可恢復錯誤，強制結束）
- `iteration >= MAX_ITERATIONS`（達到上限 12 次，強制終止）

**執行步驟**

1. 萃取 LLM 回覆文字（`_extract_text()`）
2. 若 `_force_synthesis`：另起一次輕量 LLM call（max_tokens=512）生成錯誤摘要
3. Emit `synthesis` SSE

**SSE 事件**
```json
{"type": "stage_update", "stage": 4, "status": "running"}
{"type": "synthesis", "text": "根據查詢結果，EQP-01 今日共有 11 筆 OOC..."}
{"type": "stage_update", "stage": 4, "status": "complete"}
```

---

## S5 — Self-Reflection（品質自省）

> 注意：前端 console 顯示的 "S5 Self-Reflection" 對應到 orchestrator 內部的 Stage 4（合成）最後階段，與 Stage 5（記憶寫入）的過渡期。此標籤為 UI 展示用途。

---

## S6 — Memory Learning（記憶蒸餾與寫入）

**目的**：將本輪對話中有價值的資訊持久化，供未來對話召回。

**執行步驟**

1. **診斷記憶**：若本輪有 `execute_skill` 且結果為 `ABNORMAL` → 寫入診斷記憶（含 conflict check，避免重複）
2. **HITL 偏好記憶**：若 `canvas_overrides` 有值 → 寫入為用戶偏好調整記憶
3. **成功模式記憶**：若本輪成功呼叫 ≥ 2 個工具 → 記錄工具鏈 pattern（`execute_mcp(get_dc_timeseries) → analyze_data`），供未來相似任務參考
4. **Session 儲存**：去除 `<hidden_data_profile>` 等臨時注入，存入 DB（最多 12 輪歷史）

**SSE 事件**
```json
{"type": "stage_update", "stage": 5, "status": "running"}
{"type": "memory_write", "source": "success_pattern", "memory_type": "pattern", "content": "【成功模式】..."}
{"type": "memory_write", "source": "auto_diagnosis", "memory_type": "diagnosis", "conflict_resolved": true}
{"type": "stage_update", "stage": 5, "status": "complete"}
{"type": "done", "session_id": "..."}
```

---

## 完整 SSE 事件類型總覽

| 事件 | 觸發時機 |
|---|---|
| `stage_update` | 每個 stage 開始/結束 |
| `context_load` | S1 完成後（含 soul/rag/history 統計）|
| `workspace_update` | 有 canvas_overrides 時 |
| `thinking` | LLM 輸出 `<thinking>` block |
| `llm_usage` | 每次 LLM call 完成（token 計數）|
| `token_usage` | Token Compaction 觸發時 |
| `tool_start` | 工具執行前 |
| `approval_required` | HITL 破壞性工具等待確認 |
| `tool_done` | 工具執行後（含 render_card）|
| `synthesis` | 最終回覆文字 |
| `memory_write` | 任何記憶寫入（diagnosis/preference/trap/pattern）|
| `error` | LLM 失敗或達到最大迭代上限 |
| `done` | Stream 結束（含 session_id）|

---

## 記憶類型說明

| 類型 | source 值 | 寫入時機 | 用途 |
|---|---|---|---|
| 診斷記憶 | `auto_diagnosis` | Skill 結果 ABNORMAL | 歷史故障記錄，RAG 召回 |
| Trap 記憶 | `trap` | 工具出錯 | 防止 LLM 重犯同類錯誤 |
| 偏好記憶（S0） | `user_preference` | 用戶說「記得/下次」| 長期行為規則 |
| 偏好記憶（HITL） | `hitl_preference` | canvas_overrides | 用戶手動調整 |
| 反饋記憶 | `user_feedback` | 用戶糾正 AI | 修正方向 |
| 成功模式 | `success_pattern` | ≥2 工具成功 | 工具鏈最佳實踐 |

---

*最後更新：2026-03-21 | 對應 commit：S0 Intent Router*
