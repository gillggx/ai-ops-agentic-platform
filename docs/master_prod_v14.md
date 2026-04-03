🚀 Agentic OS v14.0 - Master Production Spec (Complete Version)
1. 核心願景 (Core Vision)
本版本將系統從「對話框」擴展為「工業級協作環境」，透過 5 階段透明化日誌、三層 Token 壓縮技術 與 動態規劃 (Sequential Planning)，確保在海量工廠數據環境下的 100% 數據準確性 與 高可靠安全性。

2. 五階段透明化日誌 (5-Stage Status Tracking)
Agent 每次運作必須明確經歷並透過 SSE (stage_update) 與 Console 回報以下階段：

情境感知 (Context Load)：載入 Soul、RAG、Mem0 與 Prompt Cache 狀態。

意圖解析與規劃 (Intent & Planning)：生成並輸出具備步驟依賴的 Sequential Plan。

工具調用與安全審查 (Tool Execution & Security)：執行 程式化工具、進行安全攔截 (HITL)。

邏輯推理與彙整 (Reasoning & Synthesis)：結合 Sandbox 運算結果進行分析。

回覆與記憶寫入 (Output & Memory)：輸出回覆並執行具備 「衝突解決 (Conflict Resolution)」 邏輯的記憶寫入。

3. Token 效能防護網 (Token Efficiency Strategy)
Layer 1: 程式化語義蒸餾 (Programmatic Distillation)：

規則：數據型工具嚴禁回傳原始 JSON。

做法：在 Sandbox (Pandas/Numpy) 執行運算，僅回傳「統計摘要 + 關鍵異常點」給 LLM。

Layer 2: 動態摘要 (Dynamic History Compaction)：

觸發點：當 Session 消耗超過 60k tokens 時。

動作：同步將前半段對話壓縮為單一 <archive_summary>。

Layer 3: 緩存優化 (Prompt Caching)：

做法：對 SOUL 與 MCP_Registry 加上 cache_control: {"type": "ephemeral"}。

4. 修改範圍 (Scope of Work)
A. 執行引擎與工作區 (Execution & Workspace)

Sequential Planning：Agent 優先輸出 <plan> 說明路徑。

Workspace Sync：在 DB 新增 workspace_state (JSONB)，儲存於 AgentSessionModel。

Context Override：請求帶入的 canvas_overrides 具備最高權重，優先於 AI 判斷（放入 Request Context）。

Security Pre-commit (HITL)：對標記為 is_destructive: true 的工具，實作 SSE approval_required 攔截。

B. 記憶系統 (Memory System)

Mem0/pgvector 整合：實作跨 Session 的用戶偏好與機台診斷因果鏈結。

衝突解決 (Conflict Resolution)：寫入前先檢索。若新舊記憶衝突（語義相似度 > 0.9 且邏輯相悖），執行 UPDATE 而非 ADD。

C. SSE 與通訊 (Observability)

Event: stage_update：更新 1-5 階段狀態與進度。

Event: token_usage：每輪結束回傳精確 Token 消耗資訊。

Event: workspace_update：傳送最新的工作區 JSON。

Event: approval_required：觸發高風險操作的審核請求。

5. 驗證標準 (Definition of Done) - 所有的測式項和報告請完成在master_prd_v14_test.md 裡
[ ] 5 階段可視化：Console 與 Frontend 必須能依序看到 1-5 階段跳轉。

[ ] 100% 數據準確率：SPC 統計摘要必須與 Sandbox 計算結果一致。

[ ] 高風險防護：執行「修改機台參數」工具時，系統必須進入 Suspend 狀態等待 Approve。

[ ] 記憶一致性：若新診斷推翻舊結論，Mem0 應更新該條目。

[ ] Token 效能：連續對話中，Prompt Caching 標記應確實降低輸入成本。