Agentic OS v2.1: Ontology & Event-Driven Architecture Spec

本規格書定義 Agentic OS 底層的資料模型與事件流。系統設計參考 Palantir Ontology 概念，實現「物件 (Objects)」、「事件 (Events)」與「關聯 (Links)」的深度解耦與語意綁定。

1. 核心驅動：Process Event (製程事件)

整個生態系的起點是 Process Event。當機台加工完成時，會觸發此事件。系統不直接儲存原始事件，而是將其「扇出 (Fan-out)」轉換為針對不同主體的 Semantic Events。

2. 事件扇出與上下文綁定 (Event Fan-out)

接收到 Process Event 後，系統會產生兩條平行的事件軌跡：

A. Tool Event (機台履歷)

視角：以「機台」為中心，記錄機台在特定時間點處理了什麼。

Payload 包含：

toolId (主鍵)

eventTime

step (執行的站點)

lotId (關聯的批次)

recipeID (關聯的配方版本)

B. Lot Event (批次軌跡)

視角：以「批次 (晶圓)」為中心，記錄這批貨在特定時間點經歷了哪些控制與數據收集。

Payload 包含：

lotId (主鍵)

eventTime

step (經歷的站點)

toolId (關聯的機台)

APC (關聯的 APC Controller Name)

DC (關聯的 Data Collection Name)

SPC (包含對應 Charts 的描述與層級結構)

3. 子系統獨立性與 API 串聯 (Decoupling & API Registration)

核心精神：這是一個純粹由 Event 與 API 串聯的生態系。每個子系統 (APC, DC, SPC, Recipe) 完全獨立，自行保管實際的資料物件 (Data Object)，並基於收到的 Context 建立好查詢索引 (Index) 即可。

共通註冊介面 (Context Interface): 所有子系統 API 皆須接收以下 4 個維度的複合鍵作為索引：
{ targetId (lotId/toolId), eventTime, objectName, step }

APC / DC 系統：

行為：接收到 Payload 後，將原始資料 (30個 sensor 數據或 bias 計算結果) 作為獨立物件存入 MongoDB。

建立索引：記錄 (lotId, eventTime, APCName/DC, step) -> Payload_ObjectID，確保未來能精準撈出這份 JSON 快照。

SPC 系統：

行為：SPC 系統持續接收點位並維護其 Charts (Cross-Lot)。

建立索引：接收到註冊請求時不複製資料，僅記錄 Marker：(lotId, eventTime, SPCChart, step)，標示該批次在此 SPC Chart 的具體落點。

Recipe 系統：

行為：Recipe 是依版本 (Version) 獨立存放的靜態物件。

建立索引：接收到請求時，只需記錄 (toolId, eventTime, recipeID, step) 的調用歷史。資料不重複儲存，查詢時以索引反查對應版本的靜態配方。

4. 前端介面架構 (Web UI Architecture)

前端 Web 的互動邏輯完全建構在上述的 Ontology 與 API 串聯之上，劃分為三大獨立模組：

模組一：即時監控看板 (Live Monitor)

定位：當下工廠狀態的快照。

邏輯：基於最新的一筆 Lot Event 或 Tool Event 進行渲染。畫面展示當前機台正在處理的 Lot，以及最新的 APC/DC 連線狀態。

模組二：歷史溯源瀏覽器 (Trace Explorer)

定位：以 Tool 或 Lot 為主題 (Subject) 的深度追蹤。

邏輯：

From Tool：點選機台，展開該機台所有的 Tool Events 時間軸。點擊關聯的 Recipe 節點，前端即組合 (toolId, eventTime, recipe, step) 透過 API 向 Recipe 系統調取當初的配方物件。

From Lot：點選批次，展開該批次的 Lot Events 時間軸。點擊 APC 或 DC 節點，前端即組合 (lotId, eventTime, objectName, step) 透過 API 向子系統還原當初的參數快照。

模組三：系統物件與索引追蹤器 (Object & Index Tracker)

定位：系統健康度與資料庫維護的監控後台。

邏輯：用於追蹤與稽核（Audit）每個 Ontology Object 的儲存狀態。

檢視各個子系統（如 DC 服務）目前累積了多少筆關聯索引 (Indices)。

對照檢視實際保管了多少份實體資料物件 (Actual Data Objects)。

（例如：Recipe 可能有 50,000 筆調用索引，但底層實際 keep 的 Recipe Data Object 只有 15 個版本）。

[開發者備註 - 驗證規範]
如團隊 [2026-02-27] 協議，後端在實作此 Event Fan-out 與 Ontology API 註冊邏輯時，必須提供類似 verify_event_fanout.py 的測試腳本。該腳本需能模擬傳入 Process Event，並在 Console 印出成功拆解為 Tool/Lot Events，以及模擬向 DC/APC API 註冊成功的回傳結果，藉此驗證「子系統各自獨立保管資料與建立索引」的底層邏輯無誤。