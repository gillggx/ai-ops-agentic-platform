# Phase 6 前端 UI 規格：AI 智能技能建構器 (Skill Builder Copilot)

## 1. 開發目標
在 React 前端的「技能與事件庫 (`/skills`)」頁面中，實作一個具備高度互動性的「新增技能 (Create Skill)」介面。必須無縫串接後端的 `/suggest-logic`, `/auto-map`, 與 `/validate-logic` 三大輔助 API，打造 No-Code 的極致體驗。

## 2. 介面佈局與互動流程 (UI Flow)



請實作一個大型的側邊抽屜 (Right Drawer) 或全螢幕的精靈表單 (Wizard)，包含以下三個核心區塊：

### 區塊 A：事件觸發與智能提示 (Event & Suggestions)
1. **下拉選單**：讓使用者選擇觸發事件 (例如 `SPC_OOC_Etch_CD`)。
2. **AI 提示區 (The Magic UI)**：
   - 當使用者選定 Event 後，前端立刻在背景呼叫 `POST /api/v1/builder/suggest-logic`。
   - 在畫面右側或下方彈出一個科技感十足的卡片區塊（帶有微光或漸層邊框，標題為 `💡 AI 資深 PE 診斷建議`）。
   - 將 API 回傳的 5 條排障邏輯以列表呈現。每條建議旁邊放一個 `[套用]` 按鈕，點擊後直接把該文字填入下方的「診斷邏輯輸入框」。

### 區塊 B：工具綁定與自動映射 (Tools & Auto-Mapping)
1. **工具多選框**：讓使用者勾選這個 Skill 要用到哪些 MCP Tools (例如 `mcp_check_apc_params`, `mcp_check_recipe_offset`)。
2. **映射視覺化區塊**：
   - 勾選工具後，前端呼叫 `POST /api/v1/builder/auto-map`。
   - 將回傳的 Mapping 結果以視覺化的「節點連線 (Node Connection)」或「清晰的對照表」呈現。
   - **UI 範例**：
     `[Event] eqp_id`  ──────✨ AI 自動對應 ──────> `[Tool: APC] target_equipment`
   - 提供一個 `[編輯]` 按鈕讓使用者可以手動覆寫 AI 的對應。

### 區塊 C：診斷大腦與語意防呆 (Diagnostic Logic & Validation)
1. **邏輯編輯器**：一個大型的 Textarea，讓使用者輸入（或從上方建議套用）診斷提示詞。
2. **即時防呆機制**：
   - 在 Textarea 右下角放置一個 `[✨ 驗證邏輯]` 按鈕。
   - 點擊後呼叫 `POST /api/v1/builder/validate-logic`。
   - 若通過，顯示綠色勾勾 Toast：「✅ 邏輯完美，所需數據工具皆已齊備。」
   - 若不通過，顯示醒目的黃色警告 Alert：「⚠️ 警告：您提到了 MFC 氣體流量，但目前選擇的工具並未提供此數據。」

## 3. 視覺設計規範 (Tailwind CSS)
- **AI 輔助元素**：所有由 AI 生成或輔助的區塊，統一使用 Indigo (`text-indigo-600`, `bg-indigo-50`) 或 Purple 色系來與一般的靜態表單做視覺區隔。
- **微互動 (Micro-interactions)**：呼叫 API 等待回傳時，必須有 Skeleton Loading 或脈衝動畫 (Pulse)，讓使用者感知到「AI 正在思考」。