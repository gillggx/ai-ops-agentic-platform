# Phase 9：Copilot 意圖驅動、直接呼叫 (Direct Invocation) 與對話 UI 升級

## 1. 核心哲學：從「被動警報」到「主動探索」
系統必須支援 User 在主畫面(`/diagnosis`) 的對話框中，直接透過「自然語言」或「UI 選單」來呼叫已經建好的 MCP (資料查詢) 或 Skill (邏輯診斷)，打破過去必須綁定 Event 才能執行的限制。

## 2. 豐富化輸入方塊 (Rich Chat Input UI)
- **提示句 (Placeholder/Hint)**：輸入框預設顯示引導式提示詞，例如：`「描述症狀，或輸入 '/' 呼叫工具... 例如：我想查 N97A45.00 在 24981 站點的 APC 資料」`。
- **快捷選單 (Slash Command Menu)**：
  - 當 User 在輸入框打出 `/` 時，向上彈出一個精緻的選單 (Pop-up Menu)。
  - 選單分兩大類：`[🔍 MCP 資料查詢工具]` 與 `[🧠 Skill 智能診斷技能]`。
  - User 可以點選特定 MCP/Skill，系統會自動將該工具的描述填入對話框作為上下文。

## 3. 意圖解析與槽位填充 (Intent Parsing & Slot Filling)
- **意圖判斷 (Intent Detection)**：LLM 接收到 User 的輸入後，需判斷是要「單純查資料 (呼叫 MCP)」還是「進行異常檢查 (呼叫 Skill)」。
- **參數擷取 (Parameter Extraction)**：LLM 需自動從自然語言中萃取 Data Subject 需要的 Input 參數（例如從 "查 N97A45.00 在 24981 的 APC" 中抓出 `lot_id=N97A45.00`, `operation_number=24981`）。
- **互動式追問 (Conversational Slot Filling)**：如果 LLM 發現 User 呼叫的 MCP/Skill 有「必填參數 (Required Input)」缺失，**禁止直接報錯**。AI 必須在對話框回覆反問 User (例如：`「好的，準備為您查詢 APC 資料。請告訴我您想查詢的『機台編號 (ToolID)』是？」`)，待 User 補齊後再執行。

## 4. 執行與渲染分離 (Execution & UI Rendering)
- **直接呼叫 MCP**：執行完畢後，在右側報告區渲染 `<UniversalDataViewer>` (僅呈現 Data Table 或 Charting)，讓 User 快速看數據。
- **直接呼叫 Skill**：執行完畢後，在右側報告區渲染完整的「診斷報告卡片 (Report Card)」，包含 AI Summary、數據圖表證據與專家建議。