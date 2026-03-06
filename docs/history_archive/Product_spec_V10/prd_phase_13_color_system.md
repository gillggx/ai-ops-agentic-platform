# Phase 13: UI/UX Design System & Color Theme (AI Ops 平台視覺規範)

## 1. 核心哲學 (Design Philosophy)
* **專業與信任 (Trust & Pro)**：以深藍色為主軸，營造企業級底層架構的穩定感。
* **科技與清晰 (Tech & Clarity)**：以霓虹青作為亮點，引導使用者視覺焦點（CTA, Active 狀態）。
* **極簡留白 (Clean & Whitespace)**：背景使用極淺灰，卡片使用純白，降低視覺雜訊，確保在 Dashboard 與 Event List 中的資訊層級清晰易讀。

## 2. 核心色板定義 (Color Palette)
前端需將以下色碼寫入全域變數（如 `tailwind.config.js` 或 CSS Variables）：

* **Primary (主色 - 深藍)**: `#0A6EF0` (用於 Header、主要按鈕、重要標題)
* **Accent (輔助色 - 霓虹青)**: `#2AA3AB` (用於 Hover 狀態、Toggle 切換開關、選取的 Tab)
* **Background (整體背景)**: `#F8FAFC` (Slate 50，極淺灰，用於網頁底色)
* **Surface (卡片與表單背景)**: `#FFFFFF` (純白，用於 Routine 與 Event 的資訊卡片，確保留白效果)
* **Status: Success (正常)**: `#2AA238` (科技綠，用於巡檢通過的燈號或標籤)
* **Text: Primary**: `#1E293B` (深灰黑，確保在白底上的最高閱讀性)

## 3. 前端 UI 規範與實作要求
* 將原本預設的按鈕與 Navbar 顏色替換為 `Primary (#0A6EF0)`。
* 側邊選單 (Sidebar) 保持乾淨白底，當前選中的項目 (Active) 左側加上 `Accent (#2AA3AB)` 的粗邊條作為提示。
* 所有的資料卡片 (Cards) 必須具備細微的陰影 (Shadow-sm) 與純白背景，與 `#F8FAFC` 的底色形成對比，以實現「大量留白」的層次感。