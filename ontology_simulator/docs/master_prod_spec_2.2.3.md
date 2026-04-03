Agentic OS v2.2.3: OOC Forensic Showcase (沉浸式查案大廳)

發布目標：廢棄先前零散的微觀視圖，整合為單一且具備強大商業價值的「OOC 沉浸式查案大廳」。本版次定義從「發現警報」到「時空交叉比對」，再到「底層 JSON 取證」的端到端 (End-to-End) 使用者體驗與 API 聯動規格。

1. 核心查案動線 (The Forensic Flow)

階段一：鎖定案發現場 (Global OOC Watchlist)

UI 位置：畫面最左側的固定面板。

行為：使用者進入系統時，左側自動列出全廠依時間降序排列的 OOC (Out of Control) 警報清單。

API 聯動：

呼叫 GET /api/v2/ontology/indices/SPC?status=OOC&limit=50

渲染出包含 eventTime, lotID, toolID, step 的紅燈警報卡片。

階段二：建構時空雙軌 (Dual-Track Time Machine)

UI 位置：畫面中下方的「時序鑑識滑桿 (Forensic Scrubber)」。

行為：當使用者在左側點擊某一筆 OOC (例如 LOT-8815 @ ETCH-LAM-01)，系統並發 (Promise.all) 拉出該 Lot 與該 Tool 的完整歷史，並繪製成上下平行的兩條時間軸。

快速抓漏：時間軸上所有的 OOC 都標示為紅點。工程師可一眼看出「機台是不是累犯」或「Lot 是不是天生體質不良」。

API 聯動：

Lot Track: GET /api/v2/ontology/trajectory/{lot_id}

Tool Track: GET /api/v1/events?toolID={tool_id}

階段三：還原歷史拓樸 (Historical Context Reconstruction)

UI 位置：畫面中上半部的「拓樸圖譜 (Topology Canvas)」。

行為：使用者拖拉下方的「時間滑桿 (Playhead)」，停留在任何一個歷史 Event 點時，上半部的拓樸圖會瞬間「切換」為該時間點的現場狀態 (當時的 Tool, Lot, Recipe, APC, DC)。

API 聯動：

呼叫 GET /api/v2/ontology/context?lot_id=...&step=... (依據滑桿停留的 Event 動態帶入參數)。

階段四：底層資料取證 (Actual Data Inspection)

UI 位置：畫面右側的「萬能檢視器 (Universal Inspector)」。

行為：在特定的歷史時間點下，工程師點擊拓樸圖上的任一節點 (如 DC)，右側立即顯示具有真實廠務語意 (如 chamber_pressure) 的 JSON Payload。

限制與防呆：嚴格禁止出現 param_N 這類無意義的 Mock Data 欄位。

2. 開發與底層驗證規範 (Test Script Requirements)

根據 [2026-02-27] 團隊協議，在排解系統錯誤或驗證新架構時，必須提供簡單的測試腳本。為確保上述 UI 動線能被後端 API 完美支撐，後端開發者需提供以下腳本。

開發者行動 (Action Item)：
請撰寫 verify_dual_track_rca.py 腳本：

呼叫 /indices/SPC 找出最新一筆 OOC 作為 Target。

同時拉出該 Target 的 Lot Trajectory 與 Tool Events。

在 Terminal 印出一個「依時間排序的合併 Timeline Log」。

斷言 (Assert)：確認兩支 API 回傳的 eventTime 具備一致的 ISO 8601 格式，且能成功合併排序。

斷言 (Assert)：取其中一個歷史時間點呼叫 /context，確認回傳的 DC Payload 中包含真實語意鍵值 (如 pressure, temp)，若含有 param_ 則拋出錯誤。