AIOps 架構解耦與 Agentic AI 整合規格書
1. Context & Goal (背景與目標)
目前 AIOps 系統中的 Application 與 AI Agent 在資料蒐集與診斷呈現上存在職責重疊與高度耦合。
本規格書的目標是推動**「三層式鬆散耦合架構」**，透過標準化合約 (Standard Contract) 與 MCP (Model Context Protocol) 機制，將前端應用、渲染介面與底層 Agent 完全抽離。這將確保 Agent 能作為獨立微服務運作，並具備高度的可測試性與擴展性。

2. Architecture Mapping (系統架構與職責劃分)
系統將嚴格劃分為以下三層，嚴禁跨層越權操作：

Layer 1: Application (設定與控制台)

職責： 負責接收使用者的初始意圖 (User Intent)、設定檔管理與最終畫面呈現。

限制： 本層不包含任何診斷驗證 (Validator) 邏輯，Validator 功能不在 AIOps Application 的範疇內。Application 僅作為單純的觸發點與展示層。

Layer 2: Standard Data & Report Rendering (標準合約與渲染層)

職責： 作為 Agent 與 Application 之間的橋樑。定義統一的 API 供 Agent 撈取底層資料，並定義統一的 JSON Schema 供 Agent 輸出診斷結果，讓前端無腦渲染。

Layer 3: AI Agent (決策與推理層)

職責： 作為獨立微服務，完全不知道前端 UI 的存在。透過組合不同的 MCP/Skills 進行自主規劃、撈取資料與根因分析。

3. Stage-by-Stage Flow (詳細執行階段說明)
為確保評估與開發的清晰度，Agentic AI 的運作拆解為以下 6 個標準階段。每個階段的 Input 與 Output 必須嚴格遵守。

Stage 1: Event Trigger & Semantic Memory Retrieval (事件觸發與語意記憶存取)

運作邏輯： 當系統發生異常告警，或使用者在介面輸入指令時觸發。此階段必須進行一次記憶存取，這份記憶是直接從 User 給定的 Message 語意中萃取與記錄的（例如：使用者過去要求優先關注的服務節點或特定的排障偏好）。

Input: System Event Payload 或 User Natural Language Message。

Output: Context Payload (包含標準化 Event 資訊 + 從語意萃取出的歷史記憶與偏好設定)。

Stage 2: MCP / Skill Discovery (能力探索)

運作邏輯： Agent 根據 Stage 1 傳入的 Context，動態向系統查詢目前有哪些 MCP Servers 或 Skills 可供調用（如 LogSearch, MetricQuery）。

Input: Stage 1 的 Context Payload。

Output: 針對此次異常事件篩選出的可用 Tools API List。

Stage 3: Agent Planning (自主規劃)

運作邏輯： Agent 根據 Context 與可用的 Skills，建立初步的診斷計畫 (Chain of Thought)，決定第一步需要呼叫哪個 Tool 來獲取進一步的系統狀態。

Input: Context Payload + Tools API List。

Output: 準備發送給特定 Skill 的 Execution parameters。

Stage 4: Execution via Standard Interface (工具執行)

運作邏輯： 透過中立的標準介面打 API 給對應的 Skill 執行資料蒐集。此層為純粹的資料搬運，不帶任何業務判斷。

Input: Agent 產出的 Execution parameters。

Output: Raw Data / Metrics (如：特定時間段的 Error Logs 或 CPU 負載數據)。此階段可能與 Stage 3 反覆循環，直到 Agent 認為資訊充足。

Stage 5: Diagnosis & Synthesis (診斷與收斂)

運作邏輯： Agent 綜合所有蒐集到的數據，進行問題根因分析 (Root Cause Analysis)，並產出修復建議。

Input: 彙整後的所有 Raw Data / Metrics。

Output: 純資料導向的分析結論 (非 UI 格式)。

Stage 6: Standard Report Rendering (標準合約輸出與介面渲染)

運作邏輯： Agent 將診斷結論轉換為嚴格定義的 Standard Report JSON Schema。Application 收到此 JSON 後，單純負責 Parse 欄位並套用對應的 UI Component 渲染畫面，不進行任何邏輯運算。

Input: Agent 的分析結論。

Output (JSON Contract):

summary: 給人類閱讀的白話文根因結論。

evidence_chain: 標記結論是基於哪個 Skill 獲取的哪一段具體 Log 或 Metric，提供完整的可解釋性。

visualization_directives: 明確指示前端該使用何種圖表（如 time-series, network-graph）以及對應的資料源。

suggested_actions: 建議的下一步操作及對應的 Payload。