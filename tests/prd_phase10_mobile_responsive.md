# Phase 10: Mobile-First 響應式佈局與手勢滑動切換

## 1. 核心哲學：無縫的跨裝置體驗
系統必須在小尺寸螢幕 (Mobile) 上提供與桌面版 (Desktop) 同等強大的功能，但透過不同的 UI 佈局來呈現。核心策略為「空間折疊」與「手勢導覽」。

## 2. 響應式佈局策略 (Responsive Layout)
- **Desktop 視角 (寬度 > 768px)**：維持現有的 `30% (左側 Chat)` / `70% (右側 Multi-Tab Workspace)` 雙欄並排佈局。
- **Mobile 視角 (寬度 <= 768px)**：
  - 廢除雙欄並排，改為**全螢幕單一視圖 (Single View)**。
  - 導入視圖狀態管理 (View State)：畫面只能顯示 `Chat` 或 `Workspace` 兩者之一。
  - 頂部需新增一個輕量級的導覽列 (Mobile Header) 或 Toggle 按鈕，顯示目前在哪個視圖，並允許點擊切換。

## 3. 觸控與滑動體驗 (Swipe Gestures)
- 導入手勢監聽機制 (例如使用 `react-swipeable` 或原生 Touch Events)。
- **操作邏輯**：
  - 在 `Chat` 畫面**向左滑動 (Swipe Left)** 👉 切換至 `Workspace` (看報告/圖表)。
  - 在 `Workspace` 畫面**向右滑動 (Swipe Right)** 👉 切換回 `Chat` (繼續對話/下指令)。
- 當 AI 在背後執行 MCP/Skill 並產生結果 (`is_ready=true` 且有新 Tab 時)，Mobile 版應**自動將畫面滑動/切換至 `Workspace`**，讓 User 能夠立刻看到剛產生的圖表。

## 4. 元件微調 (Component Adaptation)
- **對話框與快捷選單 (Slash Command)**：在手機鍵盤彈出時，必須確保 `/` 快捷選單不會被鍵盤遮擋，且容易點擊。
- **資料表 (Data Table)**：在手機版必須支援水平滑動 (Horizontal Scroll)，以防超出螢幕破版。
- **SPC 趨勢圖 (Charts)**：圖表寬度必須設定為 100% 響應式，自適應手機螢幕寬度，並支援觸控長按顯示數值提示 (Tooltip)。