# Phase 9.1：Copilot 槽位填充大腦與右側多頁籤工作區 (Multi-Tab Workspace)

## 1. 核心邏輯架構 (Slot Filling Engine)
當 User 在左側對話框直接輸入自然語言時，FastAPI 後端必須使用 System Prompt 引導 LLM 進行意圖解析與參數追問 (Slot Filling)。

**[終極 System Prompt 輸出規範]**
LLM 的回覆必須是純粹的 JSON 格式：
{
  "intent": "execute_mcp" | "execute_skill" | "general_chat",
  "target_tool": "工具名稱",
  "extracted_params": { "參數名": "參數值" },
  "missing_params": ["缺少的參數名"],
  "is_ready": boolean,
  "reply_message": "給使用者的話 (追問參數或播報進度)",
  "tab_title": "若準備執行，請生成一個簡短的 Tab 標題 (例如：'🔍 APC: N97A45.00' 或 '🚨 EVT-12345')"
}

## 2. 右側多頁籤工作區 (Multi-Tab UI in 70% Area) [新增核心 UX]
廢除右側 70% 報告區「單一畫面到底」的設計，全面升級為 **「多頁籤工作區 (Multi-Tab Workspace)」**。

**運作邏輯：**
1. **預設/首頁籤 (Default Tab)**：如果是由左側點擊「⚡ 模擬觸發」產生的 Event 診斷，自動開啟一個名為 `[🚨 診斷: {EventID}]` 的 Tab，並在裡面渲染原本的圖文報告卡片。
2. **動態新增頁籤 (Dynamic Tabs)**：當 User 透過對話框直接呼叫 MCP 或 Skill 且 `is_ready=true` 時：
   - 右側工作區自動**新增一個 Tab**，標題由後端 LLM 提供的 `tab_title` 決定（例如 `[🔍 MCP: APC 查詢]`）。
   - 自動將畫面切換 (Focus) 到這個新 Tab。
   - 在這個新 Tab 內部，獨立渲染該次執行的 `<UniversalDataViewer>` (若是 MCP) 或 報告卡片 (若是 Skill)。
3. **頁籤管理**：User 可以自由在不同的 Tab 之間點擊切換，以比對不同 Lot 或不同 Skill 的數據。Tab 右側需提供 `[x]` 按鈕讓 User 關閉不需要的頁籤。