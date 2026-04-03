📝 v15.4 Agentic OS: 工業級 AI Ops 執行與追蹤規範

1. 核心願景 (Vision)

v15.4 旨在打造一個「透明、高效、可自進化」的工業 Agent 平台。核心理念是 「可解釋的 AI (XAI)」。當 Agent 在處理如 SPC、APC 等關鍵數據時，用戶能透過 Trace Inspector 深度審計 AI 的每一層思考與代碼邏輯。

2. 五階段 Agentic 執行循環 (Runtime Loop)

所有進入生產環境的請求必須嚴格執行以下循環：

Stage 1: Context & Memory Load

載入 Mem0 長效記憶與用戶偏好。

Stage 2: Strategic Planning

輸出 <plan> 標籤。優先檢索 Arsenal (武器室) 內的 150 個通用工具。

Stage 3: Async Execution (Layer 1 Distillation)

數據蒸餾：在 Sandbox 進行數據預處理，僅將「統計特徵」回傳給 LLM。

Stage 4: Self-Reflection (內部審計)

Reviewer 機制：在輸出前自動檢查圖表縮放是否合理、邏輯是否與歷史經驗衝突。

Stage 5: Final Output & Skill Promotion

產出報告。用戶可選擇將本次驗證成功的代碼「晉升 (Promote)」為正式 Skill。

3. 兵工廠：150 個通用原子工具 (Arsenal)

Agent 必須優先複用以下通用介面工具，嚴禁重複撰寫基礎運算：

通用運算：calc_statistics, linear_regression, frequency_analysis 等。

通用視覺化：plot_line, plot_scatter, plot_summary_card 等。

開發工具：AgenticRawEditor 用於代碼精確編輯。

4. 透明度核心：Agentic Trace Inspector (Detail)

前端必須提供 Detail 按鈕，點擊後展開日誌面板，包含以下四個維度：

A. Reasoning Log (思考鏈)

即時 Streaming 呈現 <thinking> 標籤內的原始推理過程。

B. Plan & Blueprint (計畫圖紙)

顯示 Stage 2 的原始計畫。

顯示 Stage 4 反思後修正的計畫（Plan Diff）。

C. Sandbox Trace (沙盒足跡)

展示 Agent 生成的 Python 原始碼。

展示 Sandbox 輸出的 Raw Output 與 Layer 1 蒸餾後的摘要。

D. Memory Context (記憶溯源)

標註本次決策參考了哪一筆歷史 Lesson Learned。

5. 效能與架構要求 (Performance & Architecture)

非同步驅動：所有機台（10+ Units）事件處理必須是非同步的。

流式傳輸 (Streaming)：Trace Inspector 與主要回答必須同步流式輸出，不得等待完整結果。

代碼獨立性：晉升的 Skill 必須是 Self-contained，所有調用的 Utility 代碼需在存檔時自動 Inject，移除外部 Dependency。