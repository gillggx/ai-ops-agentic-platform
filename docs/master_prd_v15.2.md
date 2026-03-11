Agentic OS v15.2 完整規格書：異步影子分析與自律進化系統
1. 核心願景 (Vision)
徹底剷除「AI 廢話」。將右側面板從「文字摘要」轉型為「實時科學實驗室」。當左側 MCP 進行數據渲染時，右側異步啟動影子任務，利用實打實的沙盒運算（JIT Code）或專業工具（Skills）產出具備統計意義的分析報告。

2. 核心機制：異步影子分析鏈 (Async Shadow Analysis)
2.1 觸發與監聽 (Master-Slave Async)

主任務 (Left)：負責執行 User 指令（如：畫出 SPC 圖），優先渲染。

影子任務 (Right)：

[P0] 異步攔截：監聽所有 MCP execute 結果，若 is_data_source: true 且資料筆數 > 5，立即觸發 ShadowAnalyst。

[P0] 智能採樣：自動生成該數據的 DataProfile (Schema + Stats + Top 5 Samples) 作為分析基礎。

2.2 分析決策與執行 (JIT Analysis)

[P1] 優先級媒合：

優先匹配 系統 Skill (如：Correlation Matrix)。

次之匹配 agent_tools (User 的私有工具箱)。

最後啟動 JIT Coding (沙盒內執行變數注入的 Python Code)。

[P1] 禁止純文字：分析 Prompt 強制要求輸出必須包含統計指標（CV, Pearson R, P-value 等），嚴禁產出純敘述摘要。

3. UI/UX 與用戶反饋閉環 (Feedback Loop)
3.1 右側面板變革 (Analysis Panel)

[P2] 異步狀態：左側圖表出現時，右側顯示 ⚡ 影子工程師計算中...。

[P2] 微組件渲染：分析結果以「數值卡片」或「小型熱圖」呈現，取代長篇大論。

3.2 功勞自述與工具進化 (Self-Evolution)

[P1] 功勞自述：AI 必須在報告開頭說明：「我自發執行了相關性分析，發現壓力與偏移高度相關。」

[P1] 記憶晉升：

每個分析塊下方附帶 👍/👎 與 💾 儲存工具 按鈕。

若 User 點擊 👍 或 💾，系統調用 register_agent_tool 將此邏輯存入該使用者的 私有工具箱 (agent_tools 表，含 user_id)。