🚀 PRD v13.3 追加規格：大腦記憶瘦身與 AI 分析分流管線 (Token Optimization & Output Routing)
背景與目的 (Context & Goal)
在先前的架構中，系統面臨兩大 UX 與效能瓶頸：

Token 爆炸：執行 MCP 或 Skill 後，巨量的 Raw Data 與 UI 渲染設定被完整塞入 Agent 的歷史紀錄中，導致 max_tokens (200k+) 溢位錯誤。

對話框洗版：Agent 產出的詳細 Markdown 數據表格與分析，直接渲染於左側 Chat UI，嚴重破壞對話體驗與可讀性。

v13.3 將實作「工具回傳值強制截斷 (Payload Truncation)」與「輸出路由解耦 (Output Routing Decoupling)」，徹底解決上述問題。

1. 上下文與 Token 瘦身管理 (Context & Token Optimization)
後端 Orchestrator 必須嚴格控管傳遞給 LLM 的歷史紀錄 (messages 陣列)，確保每一次 API 請求的 Token 使用量維持在安全且高效的範圍內。

1.1 工具回傳值強制截斷 (Payload Truncation) - ⚠️ CRITICAL

當後端在本地 Sandbox 執行完 execute_skill 或 MCP 後，絕對禁止將完整的 _raw_dataset 或龐大的 ui_render JSON 設定放入 tool_result 傳給 Agent。

後端清洗邏輯：後端必須攔截並重組 tool_result。

資料抽樣與摘要：若 dataset 包含大量數據，後端僅允許保留 Top N 筆 (例如前 5 筆) 作為 Schema 參考，並由後端硬塞一段統計摘要。
(範例：{"dataset_summary": "總共 100 筆資料，平均值 45.03。已截斷，僅顯示前 5 筆供結構參考。", "sample_data": [...] })

1.2 歷史對話滑動視窗 (Sliding Window History)

歷史紀錄不能無止盡堆疊，必須實作動態修剪機制：

全域保留區：System Prompt (SOUL, USER, MEMORY, tools_manifest) 永遠置頂保留。

動態滑動視窗：messages 陣列僅保留最近的 N 輪對話 (建議 N=5 到 10)。

超出視窗的舊對話直接從 Request Payload 中剔除，避免無效 Token 消耗。

2. 輸出路由解耦與專屬分析面板 (Output Routing & Insights Panel)
我們不需要限制 Agent 產出詳細的統計表格與分析，但必須將「簡短對話」與「長篇報告」在前端進行精準的物理分流。

2.1 Agent 輸出標籤規範 (Prompt Engineering)

在 SOUL.md 或 System Prompt 的「Stage 4: 邏輯推理與彙整」階段，強制規定 Agent 的輸出格式：

Agent 必須使用 <ai_analysis> XML 標籤將詳細的數據表格、統計量與深度專家建議包裝起來。

標籤外的文字僅限一句簡短的狀態報告與 UI 引導。
(範例輸出：)

✅ 常態分佈分析已完成，未發現異常。👉 [請檢視右側的 AI 分析報告與圖表]
<ai_analysis>
### 📊 基礎統計量
| 項目 | 數值 |
|---|---|
| μ (平均值) | 45.039 nm |
... (詳細內容)
</ai_analysis>

2.2 前端 SSE 串流攔截器 (Stream Parser)

前端在接收 POST /api/v1/agent/chat/stream 的 [EVENT: message] 時，必須實作 Regex Parser 即時分流：

標籤外文字：保留並渲染於左側的 Chat Bubble 中。

<ai_analysis> 標籤內文字：即時 (Streaming) 轉發並渲染至右側的專屬面板狀態中。

2.3 UI 版面升級：新增「Analysis from AI」區塊

在右側 <TryRunConsole /> 的 Execution Report 頁籤中進行版面分割：

主要視圖區：維持原樣，透過 ui_render 繪製 Plotly 圖表或 DataGrid。

AI 洞察側邊欄 (AI Insights Panel)：在圖表旁或下方新增一個專屬區塊，標題定為 「✨ Analysis from AI」。該區塊專門接收並渲染上述被攔截的 <ai_analysis> Markdown 內容。

3. 強制驗收清單與測試報告要求 (v13.3 QA Checklist)
開發完成後，工程師必須親自執行以下測試，並提交 v13.3_test_report.md (需附上 API JSON 回傳、Terminal Log 或 UI 截圖)：

[ ] Test Case 1: Token 瘦身截斷測試

Action: 執行一個會撈取超過 1000 筆 Raw Data 的 Skill。

Evidence: 截取後端發送給 Claude API 的 Payload，證明 tool_result 裡的 dataset 已經被成功截斷為 5 筆，且沒有包含 ui_render 的龐大設定。

[ ] Test Case 2: UI 路由分流測試 (Output Decoupling)

Action: 在對話框要求 Agent：「請幫我分析 CD SPC 的常態分佈，並列出 1 到 4 sigma 的詳細數據表」。

Evidence: 提供 UI 截圖，證明左側聊天室只有簡短的一句話，而長篇的 Markdown 表格與詳細分析完美地被渲染在右側的 「✨ Analysis from AI」 面板中。