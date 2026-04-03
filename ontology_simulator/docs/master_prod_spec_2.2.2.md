Agentic OS v2.2.2: UX Refinement & Semantic Data Spec

發布目標：修正 v2.2.1 實作中嚴重的 UX 版面邏輯錯誤，以及 Mock Data 語意遺失問題。本版次確立「動態三欄式佈局 (Dynamic 3-Pane Layout)」的設計模式，並強制要求資料庫欄位具備真實半導體領域語意。

1. 核心 UX 缺陷指正 (The UX Disasters to Fix)

根據前端實作截圖，目前的 UI 存在以下致命問題，必須立即重構：

萬年機台列表 (Static Sidebar Issue)：左側 Sidebar 綁死了 EQP-01 ~ EQP-10。當使用者切換到 Lot Trace 或 Obj Index 時，這些機台按鈕毫無意義且佔用空間。

無意義的參數名稱 (Semantic Loss)：右側 JSON 檢視器中，參數名稱變成了 param_01, param_02。這在廠務分析中完全無法閱讀。

動線不一致 (Flow Inconsistency)：沒有將「右側面板 (Right Panel)」確立為系統唯一的 Universal Object Inspector。

2. 三欄式動態佈局規範 (Dynamic 3-Pane Layout)

系統的佈局必須基於使用者的**「查詢主體 (Subject)」動態變更左欄與中欄，而右欄永遠固定為 Object Inspector**。

模式 A：Tool View (機台視角)

[左欄] Context Navigator：顯示 Tool List (EQP-01 ~ EQP-10)。點擊機台，展開該機台的時間軸或狀態。

[中欄] Context Canvas：顯示 Topology Map (拓樸圖)。展示該機台當下或歷史關聯的 Lot, Recipe, APC, DC。

[右欄] Universal Inspector：當點擊中欄拓樸圖的任一節點時，在此處顯示該 Object 的 Meta Data 與 JSON 實體。

模式 B：Lot View (批次溯源視角) - 需大幅重構

[左欄] Context Navigator：

頂部為 Lot ID 搜尋框。

搜尋後，下方顯示該 Lot 的 Vertical Timeline (垂直時間軸)，列出它經歷的每一個 Step 與狀態。

[中欄] Context Canvas：

當點選左側時間軸的某個 Step 時，中欄動態繪製 該 Step 當下的 Topology Map (包含當時處理它的機台、配方、APC、DC)。

[右欄] Universal Inspector：點擊中欄拓樸圖的任一節點，在此顯示該 Object 的 JSON 實體。

模式 C：Object Index View (物件索引視角) - 需大幅重構

[左欄] Context Navigator：

頂部為 Object Type 切換器 (APC, DC, RECIPE, SPC)。

下方提供進階過濾器 (Filter by Date, Tool ID 等)。

[中欄] Context Canvas：

顯示 Data Grid (資料列表)。依照 eventTime 由新到舊，列出所有符合條件的索引 (包含欄位：eventTime, lotID, toolID, step)。

[右欄] Universal Inspector：當點擊中欄列表的某一列時，右欄立即 Fetch 並顯示該筆索引對應的真實 JSON Data Object。

3. 資料語意強制規範 (Ban on "param_N")

Ontology 的價值在於查案，參數若失去語意，系統將毫無價值。
嚴格禁止後端 Mock Data Generator 產生 param_01, param_02 等無意義 key 值。

請立即修正 Mock 資料產生器，必須依照不同 Object Type 給予真實的半導體參數名稱：

APC Payload：必須包含 etch_time_offset, rf_power_bias, gas_flow_comp, model_r2_score 等。

DC Payload：必須包含 chamber_pressure, helium_coolant_press, esc_zone1_temp, rf_forward_power, reflected_power 等。

Recipe Payload：必須包含 target_thickness, etch_rate, step_time, gas_ratio_c4f8 等。

4. 開發與底層驗證規範 (Test Script Requirements)

依照團隊 [2026-02-27] 協議，我們不接受盲目的 UI 修改。在重構 Frontend 之前，必須先修正 Backend 的 Mock 資料產生邏輯，並提供驗證腳本。

開發者行動 (Action Item)：
請實作並執行 Python 腳本 verify_semantic_data_v222.py。

模擬調用 GET /api/v2/ontology/indices/APC?limit=1。

從回傳的 JSON 中提取 Payload parameters。

Assert (斷言)：檢查 keys 是否包含真實語意 (如 etch_time_offset)，若發現任何 key 包含 param_ 字串，腳本必須拋出 AssertionError 測試失敗。

請先確保資料庫裡生出來的資料是「能看的」，再開始進行 React 介面的 3-Pane Layout 重構。