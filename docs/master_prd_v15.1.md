🧠 v15.0 決策引擎：工具調度權則 (Routing Rules)

當 Smart Sampling 完成後，系統應引導 LLM 按照以下順序進行「診斷」與「執行」：

1. 第一優先級：精準匹配 (Exact Skill Match)

觸發條件：DataProfile 中的欄位數量、類型與現有 Skill（如 SPC, Cp/Cpk）的 API 定義完全吻合（或 LLM 判斷 Mapping 信心度 > 95%）。

動作：強制使用現有工具。

理由：工業級 Skill 經過驗證，比 AI 現寫的 Code 更穩定且符合標準。

2. 第二優先級：Agent 累積工具 (Private Agent Tools)

觸發條件：現有 Skill 不適用，但 agent_tools 表中存在該使用者先前成功執行過、且描述相符的工具。

動作：載入該代碼並在沙盒中執行。

3. 第三優先級 (備援)：JIT 自主研發 (Just-in-Time Coding)

觸發條件：

上述兩者皆不適用。

數據結構特殊（例如：複合型欄位、特殊的數據分佈）。

使用者提出了現有工具無法滿足的「非常規分析需求」（例如：要求將壓力和良率做非線性相關分析）。

動作：生成 Python Code -> 注入變數 df -> 沙盒執行。

🛡️ 決策過濾器 (Constraints)

為了防止 LLM 亂用工具，增加以下限制：

數據量限制：若數據筆數超過 100 萬列，禁止 JIT Coding。必須提示使用者使用 MCP 端的 Big Data 查詢工具，避免沙盒崩潰。

安全性限制：若分析需求涉及寫入 (Write) 或 刪除 (Delete) 動作，禁止執行，僅限唯讀分析。

複雜度限制：若 LLM 預計生成的 Code 超過 200 行，應建議拆解步驟。

📋 補充給小柯的開發指令 (Decision Logic Part)

/task 實作「工具決策樹 (Tooling Decision Tree)」：

實作「信心度檢查機制」：在 Prompt 中加入指令：「優先從 Tools Manifest 找工具，並對其參數進行對齊度評分 (0-100)」。

定義「強制使用」門檻：若評分 > 90，禁止生成自定義 Code。

實作「異常退回」：若 LLM 決定 JIT Coding 但數據量過大，自動返回錯誤：「數據量過大，請選用大數據批次處理工具」。

沙盒預熱：當決定使用 JIT Coding 時，在 Console 顯示 [Decision] 匹配失敗，轉由自律工程師開發專屬腳本...。

💡 PM 的小撇步

你可以告訴小柯，這就像是**「標準作業程序 (SOP)」**：

有 SOP (現成 Skill) 就照 SOP。

沒 SOP 但有前例 (Agent Tools) 就學前例。

什麼都沒有才「現場發揮」(JIT Coding)。