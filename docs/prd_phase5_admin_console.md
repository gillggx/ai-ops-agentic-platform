# Phase 5：企業級 Agentic 平台控制台 (v5 Admin Console)

## 1. 產品升級目標
將原本單一的靜態診斷頁面，全面重構為具備專業 UX/UI 的「企業級 AI 診斷管理後台」。解決目前配色不佳、佈局簡陋的問題，並實作完整的系統管理與技能維護介面。

## 2. 前端技術選型與視覺規範 (UI/UX Guidelines)
- **前端框架**：請放棄純 HTML，改用 Vite + React (或 Next.js) 來建構標準的單頁應用 (SPA)。
- **樣式與元件**：強制使用 Tailwind CSS。建議搭配 shadcn/ui 或類似的現代化無頭元件庫，以確保高度專業感。
- **配色系統 (Color Scheme)**：
  - 捨棄高飽和度的刺眼色彩。
  - **主色調 (Primary)**：使用沉穩的科技藍 (Tailwind: `blue-600` 或 `indigo-600`)。
  - **背景色 (Background)**：使用淺灰白 (`slate-50`) 作為主背景，元件使用純白 (`white`) 搭配輕微陰影 (`shadow-sm`)。
  - **狀態色 (Status)**：成功 (`emerald-500`)、警告 (`amber-500`)、錯誤 (`rose-500`)。
  - **字體**：使用 Inter 或系統預設的無襯線字體，確保高可讀性。

## 3. 全域佈局設計 (Global Layout)
採用標準的 SaaS 後台佈局：
- **左側 (Sidebar Navigation)**：固定寬度 (約 250px) 的深色或淺色側邊導覽列。
- **右側 (Main Workspace)**：佔據剩餘空間的主工作區，頂部帶有 Header (顯示當前頁面標題與使用者頭像)。

## 4. 核心模組與頁面路由 (Core Modules)

### 模組 A：🖥️ 診斷工作站 (Diagnosis Console) - `/diagnosis`
- **重構目標**：將 Phase 4 的「玻璃盒介面」搬移至此並美化。
- **排版**：右側主工作區再拆分為「左報表 (Tabs, 佔 65%)」與「右對話 (Chat, 佔 35%)」。
- **UI 優化**：
  - 報表區的 Tab 設計必須有明顯的層級感。
  - Chat 區的對話泡泡需區分 User 與 Agent 樣式，並支援 Markdown 渲染與打字機效果流暢度。

### 模組 B：🧰 技能與事件庫 (Skill & Event Registry) - `/skills`
- **重構目標**：管理所有 MCP 技能，並區分其用途。
- **UI 設計**：頁面頂部包含兩個大頁籤 (Tabs)：
  - **[ 事件分診庫 (Event Triage) ]**：列表顯示用於判斷大腦路由的技能 (如 `mcp_event_triage`)。列表需呈現該事件會觸發哪些後續 Skills。
  - **[ 診斷工具庫 (Diagnostic Actions) ]**：列表顯示實際執行排障的工具 (如 `mcp_mock_cpu_check`)。
- **互動**：點擊任何 Skill 可滑出或彈出一個 Right Drawer (側邊抽屜)，顯示該 Skill 的 JSON Schema 詳情。

### 模組 C：⚙️ 系統與環境變數 (System Variables) - `/settings`
- **重構目標**：提供給 Admin 修改系統底層設定的介面。
- **UI 設計**：表單形式呈現，包含以下區塊：
  - **全局提示詞 (Global Prompt)**：大型的 Textarea，用於修改 Agent 的 System Prompt。
  - **模型設定 (Model Routing)**：下拉選單切換 Anthropic 或其他 LLM 模型。
  - **金鑰管理 (Secrets)**：API Key 輸入框 (需支援密碼遮蔽顯示)。

## 5. 開發與驗證步驟 (Actionable Steps)
1. **初始化專案**：在專案根目錄或子目錄 (如 `frontend/`) 初始化 React 專案。
2. **Mock Data 優先**：在串接後端 API 之前，必須先用 Mock Data (假資料) 把這三個頁面的靜態切版與路由 (React Router) 刻出來。
3. **SSE 整合**：將 Phase 4 的 SSE 接收邏輯遷移到「診斷工作站」的 React 元件中。