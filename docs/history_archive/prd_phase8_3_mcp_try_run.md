# Phase 8.3：MCP 建構器「所見即所得 (WYSIWYG)」與防護網升級

## 1. 全新 MCP Builder UX 流程 (The 4-Step Flow)
前端 `/skills` 裡的新增 MCP 介面，必須重構為以下四個具備明確先後順序的步驟：

### 步驟 1：選定 Data Subject 與「撈取樣本 (Fetch Sample)」
- User 在下拉選單選定 `Data Subject` (例如 `APC_Data`) 後，不僅要顯示欄位字典 (Phase 8.2 的成果)。
- **[新增]** 畫面必須根據該 Data Subject 的 `input_schema`，動態生成一個「測試參數輸入表單」(例如：顯示 `lot_id` 與 `operation_number` 的輸入框)。
- **[新增]** 提供一個 `[撈取樣本資料]` 按鈕。點擊後，前端實際呼叫該 Data Subject 的 API，並在畫面上方顯示一小塊「真實 JSON 回傳結果 (Raw Data Preview)」。*(讓 User 看著真資料寫 Prompt)*

### 步驟 2：輸入加工意圖 (撰寫 Prompt)
- User 在觀看真實 JSON 樣本後，於文字框輸入加工意圖（例如：「檢查所有 model 的更新時間...以圖表顯示」）。

### 步驟 3：嚴格防護網與「試跑 (Try Run)」
- **[新增]** 在文字框下方加入一顆醒目的 `[▶️ 執行試跑 (Try Run)]` 按鈕。
- **嚴格防護邏輯 (Guardrails)**：當按下試跑時，後端 `/generate-script` 的 System Prompt 必須增加強制規範：
  > 「User 的提示詞僅限於要求『資料清洗、過濾、數學計算與圖表繪製』。你生成的 Python 腳本【絕對禁止】發起任何外部 HTTP 請求、禁止呼叫其他 API、禁止執行系統命令 (OS commands)。若 User 的要求超出資料處理範疇，請拒絕生成並回傳錯誤訊息。」
- **執行沙盒**：後端生成 Python 腳本後，立刻將【步驟 1 撈到的樣本資料】注入 Sandbox 執行。

### 步驟 4：結果預覽與儲存 (Preview & Save)
- **[新增]** 在「試跑」完成後，畫面下方必須立刻渲染出 Sandbox 跑出來的結果（實際的 Plotly 圖表或 Table 預覽）。
- **強制鎖定**：最下方的 `[儲存並建立 MCP]` 按鈕預設必須是 `Disabled` (反灰) 狀態。只有在「試跑 (Try Run)」成功且 User 看到圖表後，該按鈕才會解鎖 (Enabled)，允許儲存。