Agentic OS v16: AIOps MCP (Model Context Protocol) Registry

發布目標：本規格書定義 AI Agent 在執行自動化診斷與維運時，可以呼叫的標準化 API 工具集 (MCPs)。這些 MCP 是 Agent 的「眼睛 (讀取)」、「大腦 (統計)」，以及「雙手 (寫入)」。
架構原則：摒棄死板的 limit 查詢與硬編碼的警報清單（如 OOC List）。全面導入 「時間區間 (Time Window)」 概念，讓 Agent 能針對特定 Domain 實體 (Lot/Tool/Object) 精準截取歷史片段，並隨時還原現場。

1. 核心時序取證 (High Value - Time-Window Forensics)

Agent 用來調閱特定目標歷史軌跡的基礎能力，全面支援 startTime 與 endTime 區間查詢。

MCP Name

API Endpoint

Input Schema

用途 (Use Case)

get_process_context

GET /api/v2/ontology/context

lot_id, step (或 event_time)

還原現場。一次取回 Lot+Step 當時的 Recipe/APC/DC/SPC 完整快照。這是 Agent 拿到時序事件後，用來展開細節的最核心 API。

get_lot_trajectory

GET /api/v2/ontology/trajectory/lot/{lot_id}

lot_id,



start_time (ISO8601),



end_time (ISO8601)

批次旅程。查案提問：「這批貨在昨天下午 13:00 到 17:00 之間，到底去過哪些機台？狀態為何？」

get_tool_trajectory

GET /api/v2/ontology/trajectory/tool/{tool_id}

tool_id,



start_time,



end_time

設備履歷。查案提問：「這台機台發生異常前的 2 小時內 (T-2h to T-0)，到底跑過哪些貨？有沒有做過保養？」

get_object_history

GET /api/v2/ontology/history/{type}/{id}

object_type, object_id,



start_time,



end_time

物件效能。查案提問：「APC-0042 這個演算法模型，在上週三整天的運作表現與補償值為何？」

2. 統計與聚合 (High Value - Baseline & Aggregation)

LLM 不擅長處理大量原始數據的數學運算。此類 MCP 提供大數據統計結果，讓 Agent 能判斷「現在的值到底算不算異常」。

MCP Name

API Endpoint

Input Schema

用途 (Use Case)

get_baseline_stats

GET /api/v2/ontology/stats/baseline

tool_id, recipe_id,



start_time, end_time

Agent 的判斷基準。回傳特定區間內所有 DC 參數的 mean (平均值) 與 std_dev (標準差)。Agent 可藉此計算當前參數是否超過 3-Sigma。

search_semantic_events

POST /api/v2/ontology/search

{"step": "...", "status": "OOC", "tool_id": "..."}

交叉比對搜尋。Agent 查案時可提問：「幫我找出過去 24 小時內，同樣在 EQP-01 發生 OOC 的所有 Lot」。

3. 開發與底層驗證規範 (Test Script Requirements)

依照團隊 [2026-02-27] 制定的除錯與驗證協議，後端工程師在實作 API v2.3/v2.4 時，必須確保上述時間區間邏輯能與 Context 還原邏輯完美串接。

開發者行動 (Action Item)：
請撰寫 verify_mcp_time_window_rca.py 腳本，模擬 Agent 完整的思考閉環：

設定時間區間：定義 T-2h 到 T-0。

呼叫時間軸 API (get_tool_trajectory)：取得 ETCH-LAM-01 在這兩小時內的所有 Events。

呼叫還原 API (get_process_context)：針對上述拿到的每一個 Event (帶著它的 lot_id 與 step)，跑迴圈呼叫 Context API，把真實的 Process 資料 (DC, APC) 全部印出來。

斷言 (Assert)：確認所有抓出來的事件都嚴格落在指定的 start_time 與 end_time 之間。