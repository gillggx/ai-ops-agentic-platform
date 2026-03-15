Agentic OS v2.2.1: Ontology Micro-Trace & Scenario Browser Spec

版本定位：v2.2 完成了底層 Data Services API 的建置與巨觀視圖 (Sankey/Ratio)。本版次 (v2.2.1) 專注於補齊**「微觀查案視角 (Micro-Trace Views)」，並新增一個極具商業價值的「廠務情境瀏覽器 (Scenario Browser)」**，讓底層 API 的威力能被肉眼看見且輕鬆操作。

1. 補齊微觀溯源視角 (The Missing Explorers)

系統必須在 /simulator/nexus 模組中，新增以下兩個 Tab 或子頁面，補足工程師下鑽查案的需求：

1.1 Lot-Centric Trace View (批次生命週期時間軸)

定位：以「批次 (Lot)」為主體的深度溯源。

UI 互動：

頂部搜尋吧輸入 Lot ID (預設帶入最新的 N3-WAF-XX)。

左側展開該 Lot 的垂直時間軸，列出所有經歷的 Step。

點擊任一 Step 節點，右側立即展開該站點綁定的 Tool, Recipe, APC, DC 索引卡片。

點擊卡片，右側 Inspector 顯示高可讀性 (語法高亮) 的 JSON Snapshot。

API 依賴：呼叫 GET /api/v2/ontology/trajectory/{lot_id}。

1.2 Object-Centric Index Explorer (物件索引與實體瀏覽器)

定位：確保 DBA 與工程師能直接對特定子系統的資料庫實體進行狀態檢核。

UI 互動：

下拉選單選擇 Object Type（如 APC, DC, RECIPE）。

畫面顯示由新到舊 (ORDER BY eventTime DESC) 排序的索引紀錄列表（顯示複合鍵：eventTime, lotID, toolID, step）。

核心功能：點擊列表列，系統自動追隨該索引向 MongoDB 取回真實的 Data Object (JSON 實體)，並在 Inspector 中渲染。

API 依賴：呼叫 GET /api/v2/ontology/indices/{objectType}?limit=50。

2. 全新頁面：Use Case Scenario Browser (廠務情境瀏覽器)

這是一個將「20 個真實廠務 Use Case」與「底層 API」完美結合的互動式展示平台。它既是高階主管的 Demo 神器，也是 PE 查案的快速捷徑。

2.1 UI 佈局 (Three-Pane Layout)

左欄 (Use Case Library)：
分類列出系統支援的商業情境。例如：

[RCA] 單點 SPC OOC 關聯還原

[EE] 腔體健康度 (PM 前後比對)

[PI] 跨站點晶圓履歷溯源

中欄 (API Playground & Story)：
當左側點選某情境時，此處顯示：

Story：用白話文描述這個情境在解決什麼工廠痛點。

API Endpoint：顯示系統即將呼叫的完整 URL (如 GET /api/v2/ontology/context?lot_id=LOT-007&step=STEP_045)。

Execute 按鈕：點擊後觸發 API 拉取資料。

右欄 (Dynamic Visualizer)：
根據不同情境，動態決定渲染哪一種 UI Component：

若是 OOC 展開 ➔ 渲染 Graph Context (關聯拓樸圖)。

若是晶圓溯源 ➔ 渲染 Vertical Timeline (垂直時間軸)。

若是腔體匹配 ➔ 渲染 Tabular Data Grid (數據寬表)。

2.2 首批實作情境 (MVP Scenarios)

在 v2.2.1 中，請先實作以下 3 個情境並綁定對應的 API：

Scenario 1: SPC OOC 根因分析 (對應 Graph Context Service)

展示重點：點擊 Execute 後，右欄瞬間長出 5 個節點的關聯圖。

Scenario 2: Data Orphan 系統抓漏 (對應 Ontology Audit Service)

展示重點：點擊 Execute 後，右欄繪製 Sankey 圖，並刻意用「紅色斷裂閃電」標示出遺失 Payload 的異常節點。

Scenario 3: Recipe 版本漂移審計 (對應 Object Index Explorer)

展示重點：撈出 RECIPE Object Type 的最新 2 筆紀錄，對比參數差異。

3. 開發與底層驗證規範 (Test Script Requirements)

根據團隊 [2026-02-27] 協議，在刻畫 React UI 之前，請先確保後端 API 能穩定支撐這兩個新功能。

開發者行動 (Action Item)：
請實作一支 Python 測試腳本 verify_v221_scenarios.py，該腳本需依序執行：

模擬 Lot-Centric Trace：傳入一個 lot_id，印出它經歷的 Step 陣列。

模擬 Object-Centric Explorer：抓取 APC 的最新 3 筆索引，並根據索引成功拉回 JSON 實體。

模擬 Scenario Browser 參數組裝：印出 Scenario 1 預計會打出去的完整 HTTP GET URL，並試打該 URL 確認回傳 HTTP 200。

請確認腳本順利 Pass 後，再進行 Next.js 的頁面實作 (/simulator/scenarios 路由)。