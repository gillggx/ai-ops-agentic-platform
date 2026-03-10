Agentic OS v14.2 — Master Engineering Spec (Self-Healing Builder Edition)
================================================================================
上版：v14.1 Hybrid Memory Edition
本版新增：輕量化自癒架構 (Self-Healing Builder) — LLM 生成品質閉環

--------------------------------------------------------------------------------
1. 核心願景 (Core Vision)
--------------------------------------------------------------------------------
打造一個具備 Glass Box (玻璃盒) 架構、微型反饋閉環 (Micro-Feedback Loop)，以及
高精準混合記憶系統 (Hybrid Memory System) 的工業級 Agentic OS。
系統遵循「先學會走（避開錯誤指令），再學會跑（吸收人類偏好）」的原則。

v14.2 新增核心原則：LLM 生成的任何產出（MCP 腳本、Skill 診斷函式）在進入執行前，
必須通過「Schema Guard」格式驗證。驗證失敗時，錯誤細節作為 error_context 自動
回饋給 LLM 進行修正，不對使用者顯示中間失敗狀態。


--------------------------------------------------------------------------------
2. 五階段透明化日誌 (5-Stage Status Tracking) — 同 v14.1
--------------------------------------------------------------------------------
Stage 1: 情境感知與精準提取 (Context Load & Hybrid Retrieval)
  → 載入 Soul、RAG 通用知識。
  → 透過 Metadata (task_type, data_subject, tool_name) 對記憶庫進行預先過濾，
    精準提取 User Profile 與 Trap 避坑指南並注入 Prompt。
  → v14.2 新增：同時拉取 [DS_Schema] 記憶（task_type=mcp_draft, data_subject=DS名），
    讓 LLM 在 MCP Try-Run 時直接使用已驗證的欄位名稱。

Stage 2: 意圖解析與規劃 (Intent & Planning)
  → 強制覆誦（Acknowledge）檢索到的記憶約束後，生成 <plan> 步驟標籤。

Stage 3: 工具調用與安全審查 (Tool Execution & Security)
  → 執行 Tool，進行 Token 蒸餾與權限檢查。
  → v14.2 新增：LLM 生成產出在執行前通過 Schema Guard 驗證；失敗時觸發 LLM Fix。

Stage 4: 邏輯推理與反思 (Reasoning & Reflection)
  → 擔任 Evaluator。若驗證失敗，啟動「現場修正」；若成功，進行最終分析。

Stage 5: 回覆與記憶寫入 (Output & Indexing Memory)
  → 輸出回覆，將 Trap/Rule 與操作偏好綁定 Metadata 寫入記憶。
  → v14.2 新增：MCP Try-Run 成功後，自動將 DS 欄位名稱對照寫入 [DS_Schema] 記憶。


--------------------------------------------------------------------------------
3. 混合記憶系統 (Hybrid Memory System) — v14.1 + v14.2 更新
--------------------------------------------------------------------------------
3.1 結構化記憶標籤 (Metadata Indexing)
  所有記憶必須綁定：
    task_type    : mcp_draft | draw_chart | troubleshooting | ...
    data_subject : DS 名稱 / 機台 ID（如：Huge_SPC_DATA, TETCH01）
    tool_name    : 具體工具名稱（如：draw_spc_chart, search_logs）

3.2 混合搜尋與預先過濾 (Hybrid Search & Pre-filtering)
  Stage 1 讀取記憶時：先用 Metadata 條件過濾（WHERE task_type = '...'），
  再對候選池進行關鍵字評分，返回 top_k。
  確保「畫圖表」任務只喚醒「畫圖表」的經驗，徹底杜絕記憶污染。

3.3 v14.2 新增：DS Schema 記憶（Lesson Learnt）
  格式：[DS_Schema] ts | DS=Huge_SPC_DATA | 正確欄位: toolId, lotId, value | LLM 錯誤猜測: tool_id
  綁定：task_type=mcp_draft, data_subject=DS名
  寫入時機：MCP Try-Run 成功後，自動呼叫 write_ds_schema_lesson()
  應用時機：Stage 1 在下次同 DS 的 Try-Run 中，pre-filter 拿到此記憶 →
    LLM 第一次就使用正確欄位名，完全跳過 retry。

3.4 記憶類型彙整
  source='diagnosis'        : [診斷記錄] Skill 執行 ABNORMAL 記錄（已有）
  source='trap'             : [Trap] Agent Tool Call 失敗 + 修正規則（已有）
  source='hitl_preference'  : [使用者偏好] canvas_overrides 人工修正記錄（已有）
  source='ds_schema_lesson' : [DS_Schema] DS 欄位命名對照（v14.2 新增）


--------------------------------------------------------------------------------
4. v14.2 自癒架構設計 (Self-Healing Builder)
--------------------------------------------------------------------------------
設計決策記錄（來自 Gemini 建議 + 內部架構評審）：

4.1 llm_retry() Helper（採納）
  位置：app/utils/llm_utils.py
  介面：async llm_retry(fn, validator, max_retries=2) -> Any
    - fn(error_context: str | None) → raw_result   ← 第一次傳 None；retry 傳錯誤字串
    - validator(raw_result) → validated_result      ← 失敗時 raise ValueError
  設計原則：只覆蓋「LLM 生成 → 格式驗證」這一條路。
    Agent Tool Call 失敗（環境問題）走 write_trap()，本質不同，不共用此 helper。

4.2 Schema Guard — Pydantic 驗證層（採納，最高優先）
  McpTryRunOutputGuard（Pydantic BaseModel）：
    - processing_script: 必須含 'def process'
    - output_schema: 必須含 'fields' 陣列
    驗證失敗 → pydantic.ValidationError.str() 作為 error_context 回饋 LLM。
    LLM 對「精確到欄位的報錯」修正率極高。

  SkillCodeOutputGuard（class + staticmethod validate）：
    - 必須含 'def diagnose'
    - 回傳 dict 必須含 'status', 'diagnosis_message', 'problem_object' 三個 key
    同樣透過 llm_retry 驅動，最多重試 2 次。

4.3 錯誤分類器 classify_error()（採納）
  位置：app/utils/llm_utils.py
  6 種類型：MISSING_COLUMN, TYPE_MISMATCH, IMPORT_ERROR, EMPTY_DATA, SYNTAX_ERROR, LOGIC_ERROR
  用途：沙盒執行失敗時，在錯誤訊息前加上 [MISSING_COLUMN] 等標籤，
    讓 LLM 看到「我上次犯了什麼種類的錯」，顯著提升第二次 retry 的成功率。

4.4 Lesson Learnt 限縮（採納，範圍縮小至 DS Schema）
  原始建議：任何 retry 成功都寫入記憶。
  問題：大部分 retry 是 LLM 格式問題，不是 session-specific 知識，寫入會造成記憶噪音。
  最終決策：只針對「DS 欄位命名慣例」做跨 Session 學習。
    每次 Try-Run 成功 → write_ds_schema_lesson(ds_name, correct_fields)
    下次同 DS 的 Try-Run，Stage 1 直接注入正確欄位名 → 跳過 retry。

4.5 不採納項目
  execute_with_retry 基類：三種場景（MCP 沙盒 / LLM 格式 / Agent Tool）本質不同，
    共用基類會強行統一，反而難以維護。改用 llm_retry() 輕量 helper 覆蓋 LLM 生成路徑。
  全自動 upsert_lesson：限縮為只記錄 DS 欄位（見 4.4）。


--------------------------------------------------------------------------------
5. 自癒流程全景 (End-to-End Self-Healing Flow)
--------------------------------------------------------------------------------
MCP Try-Run 完整流程（v14.2）：

Step 1  使用者輸入加工意圖 + 選擇 DataSubject
Step 2  前端取得 DS 的 sample_data（含真實欄位名）
Step 3  後端：Stage 1 從記憶庫 pre-filter 取 [DS_Schema] 記憶（同 DS）
Step 4  後端：generate_for_try_run() 呼叫，含：
          - sample_row（1筆真實資料，帶正確欄位名）
          - [DS_Schema] 記憶注入（若有）
Step 5  LLM 生成 Python process() 函式 → McpTryRunOutputGuard 驗證
          ① 通過 → 繼續
          ② 失敗 → error_context 回饋 LLM → 最多 2 次重試
Step 6  沙盒執行 process(sample_data)
          ① 成功 → 繼續
          ② 失敗 → classify_error() 標籤化 → 帶 error_context 重新呼叫 generate_for_try_run()
                  → 沙盒再試一次；若仍失敗 → 返回錯誤 + _analyze_sandbox_error() 診斷
Step 7  成功 → write_ds_schema_lesson(ds_name, correct_fields)
          （自動把本次用到的正確欄位名寫入記憶，下次跳過 retry）
Step 8  返回 MCPTryRunResponse（含 script, output_data, ui_render_config）

Skill Generate Code 流程（v14.2）：

Step 1  使用者填寫 diagnostic_prompt + problem_subject → 執行 Skill Builder
Step 2  generate_code_diagnosis() 呼叫 LLM 生成 diagnose() 函式
Step 3  SkillCodeOutputGuard 驗證（含 def diagnose / status / diagnosis_message / problem_object）
          ① 通過 → 繼續
          ② 失敗 → error_context 回饋 LLM → 最多 2 次重試
Step 4  沙盒執行 diagnose(mcp_sample_outputs)
Step 5  返回結果（包含 check_output_schema 供 RoutineCheck 使用）


--------------------------------------------------------------------------------
6. Token 效能防護網 (Token Efficiency) — 同 v14.1
--------------------------------------------------------------------------------
Layer 1: 語義蒸餾 — Stage 3 工具執行後，傳統計摘要 + 關鍵異常點，禁止原始大型 JSON
Layer 2: 動態摘要 — Session 預估 Token > 60k 時，壓縮前半段對話為 <summary>
Layer 3: 緩存優化 — System Prompt 加 cache_control: {"type": "ephemeral"}


--------------------------------------------------------------------------------
7. 微型反饋與記憶閉環 — 同 v14.1 + v14.2 擴充
--------------------------------------------------------------------------------
7.1 指令自動修復與 Negative Index（v14.1）
  - Agent Tool Call 錯誤 → write_trap()，綁定 tool_name Metadata
  - 下次 Stage 1 pre-filter 提取 → LLM 不重蹈覆轍

7.2 HITL 參數覆寫與偏好記憶（v14.1）
  - canvas_overrides → write_preference()，綁定 task_type + data_subject

7.3 DS Schema 學習（v14.2 新增）
  - MCP Try-Run 成功 → write_ds_schema_lesson()，綁定 task_type=mcp_draft + data_subject=DS名


--------------------------------------------------------------------------------
8. Glass Box 透明化 — 同 v14.1
--------------------------------------------------------------------------------
- Console 實時推送：Metadata 過濾條件、失敗重試、Feedback 反思
- 雙向狀態同步：workspace_state (JSONB)，前端修改直接觸發 SSE
- Dry-Run：破壞性操作觸發 SSE approval_required，等待人類點擊 Approve


--------------------------------------------------------------------------------
9. 實作清單 (Implementation Checklist)
--------------------------------------------------------------------------------

✅ v14.1 已完成
  - AgentMemoryModel: task_type / data_subject / tool_name 欄位 + Alembic migration
  - search_with_metadata(): primary pool (metadata filter) + legacy supplement
  - write_trap() / write_preference() — 帶 Metadata 的記憶寫入
  - task_context_extractor.py — 純函式，從 message + canvas_overrides 提取 Metadata
  - context_loader.py — 呼叫 search_with_metadata() 並回傳 filter_meta SSE
  - agent_orchestrator.py — Stage 1 注入 task_context，Stage 3/5 觸發 write_trap/write_preference

✅ v14.2 已完成
  - app/utils/llm_utils.py — classify_error() + llm_retry()
  - mcp_builder_service.py — McpTryRunOutputGuard + SkillCodeOutputGuard 模型定義
  - mcp_builder_service.py::generate_for_try_run() — 改用 llm_retry + McpTryRunOutputGuard
  - mcp_builder_service.py::generate_code_diagnosis() — 改用 llm_retry + SkillCodeOutputGuard
  - mcp_definition_service.py::try_run() — 沙盒失敗分類 + auto-retry（1次）+ DS Schema 記憶觸發點預留
  - agent_memory_service.py::write_ds_schema_lesson() — DS 欄位命名 Lesson Learnt

⬜ 待實作（優先級排序）
  P1: try_run() 成功後實際呼叫 write_ds_schema_lesson()
    （需要將 AgentMemoryService 注入 MCPDefinitionService，或透過事件觸發）
  P2: Stage 1 在 context_loader 中拉取 [DS_Schema] 記憶並注入 MCP Try-Run prompt
  P3: triage_error() 回傳格式升級至 { error_type, raw_traceback, fix_hint }（統一錯誤格式）
  P4: Gap 10 — 多輪對話中 Copilot LLM 生成 MCP 參數的 Schema Guard


--------------------------------------------------------------------------------
10. 關鍵文件清單
--------------------------------------------------------------------------------

| 文件 | 說明 |
|------|------|
| app/utils/llm_utils.py | classify_error + llm_retry (v14.2 新增) |
| app/services/mcp_builder_service.py | McpTryRunOutputGuard + SkillCodeOutputGuard + generate_for_try_run retry |
| app/services/mcp_definition_service.py | try_run() 沙盒 auto-retry + classify_error |
| app/services/agent_memory_service.py | write_ds_schema_lesson() (v14.2 新增) |
| app/services/task_context_extractor.py | 純函式 extract() — keyword + regex |
| app/services/context_loader.py | search_with_metadata() 呼叫 + filter_meta SSE |
| app/services/agent_orchestrator.py | Stage 1 task_context + Stage 3/5 write_trap/preference |
| app/models/agent_memory.py | task_type / data_subject / tool_name 欄位 |
| alembic/versions/20260310_0001_add_memory_metadata.py | v14.1 migration |


--------------------------------------------------------------------------------
11. 驗證腳本 (v14.2 Self-Healing Lifecycle Test)
--------------------------------------------------------------------------------

# 情境 A：MCP Try-Run Schema Guard
# 驗證：LLM 生成的 process() 函式缺少 def process → 自動 retry → 成功
POST /mcp-definitions/try-run
{ "processing_intent": "...", "data_subject_id": 1, "sample_data": [...] }
期望：即使第一次 LLM 輸出格式不對，最終仍返回 success=true；
    Builder UI 不顯示中間失敗狀態。

# 情境 B：Sandbox MISSING_COLUMN Auto-Retry
# 驗證：沙盒執行因欄位名稱錯誤失敗 → classify_error() 回 MISSING_COLUMN
#      → LLM 看到 [MISSING_COLUMN] 標籤重新生成 → 第二次沙盒成功
POST /mcp-definitions/try-run
{ "processing_intent": "用 toolId 分組計算 CD 均值", "sample_data": [{"toolId": "T01", "CD_val": 47.5}] }
期望：MCPTryRunResponse.success=true，不需要使用者重新輸入。

# 情境 C：DS Schema Lesson Learnt
# 驗證：第一次 Try-Run 成功後，DS Schema 記憶寫入
#      → 第二次同 DS 的 Try-Run，Stage 1 拉到 [DS_Schema] 記憶
#      → LLM 直接用正確欄位，不再需要 retry
GET /agent/memory?user_id=1
期望：包含 source='ds_schema_lesson', data_subject='Huge_SPC_DATA' 的記憶條目。

# 情境 D：Skill Code Guard
# 驗證：generate_code_diagnosis() 生成的 diagnose() 缺少 problem_object key
#      → SkillCodeOutputGuard 捕捉 → error_context 回饋 → retry 後包含所有 3 個 key
POST /skill-definitions/{id}/simulate
期望：結果含 status / diagnosis_message / problem_object 三個欄位。


--------------------------------------------------------------------------------
12. Gemini 建議採納記錄 (Design Decision Log)
--------------------------------------------------------------------------------

Gemini Round 1 建議：
  1. BaseFeedbackLoop 基類                    → 拒絕：三種錯誤場景本質不同，過度抽象
  2. 統一錯誤格式 { error_type, raw_traceback, fix_hint } → 部分採納：classify_error() 標籤化
  3. Schema Guard (Pydantic)                  → 完全採納：McpTryRunOutputGuard + SkillCodeOutputGuard
  4. Lesson Learnt 全自動 upsert             → 縮小範圍：只記錄 DS Schema，避免記憶噪音

Gemini Round 2 (修正版) 採納記錄：
  1. llm_retry() helper（非基類）            → 採納。fn 接受 error_context: str | None。
  2. Schema Guard 強制實作                   → 採納。ValidationError.str() 直接作 error_context。
  3. _classify_error() 6 種類型              → 採納，補充至完整 6 種（Gemini 原版只列 2 種）。
  4. Lesson Learnt 限縮為 DS Schema          → 採納。upsert key = (user_id, ds_name)。

小柯補充（採納到最終實作）：
  - fn 參數：第一次傳 None，retry 傳 ValidationError string（非 JSON）
  - 兩個不同 Guard：McpTryRunOutputGuard (JSON output) vs SkillCodeOutputGuard (Python code)
  - classify_error 完整 6 種類型覆蓋最常見 sandbox 錯誤
  - DS Schema 記憶觸發點：Try-Run 成功後（無論是否曾 retry），寫入正確欄位名
  - 沙盒 auto-retry 上限 1 次（不是 2 次），避免 Token 消耗過大
