# Phase 4：Glass Box (玻璃盒) 智能體前端介面實作

## 1. 開發目標
建立一個純前端的單頁應用 (Single Page Application)，直接串接我們剛寫好的 `/api/v1/diagnose` SSE 串流端點。實現「左側動態報表、右側實況對話」的現代化 Agentic UI。

## 2. 技術選型 (極簡 MVP)
為了快速驗證且不增加額外的前端編譯環境，請嚴格遵守：
- **純靜態檔案**：只使用 HTML5, Vanilla JavaScript (無框架), 以及原生的 CSS (或透過 CDN 載入 Tailwind CSS)。
- **後端整合**：在 FastAPI 的 `main.py` 中，將這包前端檔案掛載 (Mount) 到靜態目錄，讓使用者連線 `http://127.0.0.1:8000/` 就能直接看到畫面。

## 3. UI 版面配置 (Layout)
畫面分為左右兩大區塊 (例如 70% / 30% 比例)：
- **左側 (診斷報告區 Workspace)**：
  - 頂部有一個頁籤列 (Tab Navigation)。
  - 預設顯示 [總結報告] 頁籤。
  - 當收到 SSE 的 `tool_call` 事件時，動態新增一個對應工具名稱的頁籤（並顯示 Loading 狀態）。
  - 當收到 `tool_result` 事件時，將該工具的回傳 JSON 或報告渲染進對應的頁籤內容中。
- **右側 (對話助手區 Chat)**：
  - 底部有輸入框 (Input) 與送出按鈕。
  - 上方為對話歷史區塊。
  - 當收到 SSE 的 `report` 或打字機串流事件時，即時將文字渲染在 Chat 泡泡中。

## 4. SSE 事件監聽邏輯 (EventSource / Fetch API)
前端發送問題時，必須帶上正確的 Headers (包含剛才測試用的 JWT Token，或若開發環境已關閉驗證則免)。
必須正確解析 `event: <type>` 並觸發對應的 DOM 更新：
- `event: session_start` -> 在 Chat 區顯示「診斷開始...」
- `event: tool_call` -> 左側新增頁籤。
- `event: tool_result` -> 更新左側頁籤內容。
- `event: report` / `event: message` -> 右側 Chat 區實況打字。
- `event: done` -> 解鎖輸入框，等待下一輪對話。