Agentic OS v2.2: Ontology Data Services & Use Case Architecture Spec

本規格書定義 Agentic OS 作為「工廠級資料服務平台 (Data Service Platform)」的底層架構。本平台不直接綁定特定應用程式 UI，而是透過事件驅動 (Event-Driven) 建立語意關聯，並對外提供具備真實世界物理特性的 Data Services。

1. 核心底層：事件扇出與上下文綁定 (Ontology Foundation)

以 Process Event 為核心驅動，將資料解耦並建立索引：

Tool Event (機台視角)：記錄 (toolId, eventTime, step, lotId, recipeID)

Lot Event (批次視角)：記錄 (lotId, eventTime, step, toolId, APC, DC, SPC)

子系統獨立註冊：APC, DC, SPC, Recipe 各自保管實體資料 (Data Object)，並向平台註冊共通複合鍵索引 { targetId, eventTime, objectName, step }。

2. 平台核心管理：Ontology Nexus (本體論樞紐)

為了讓 Data Engineer 能依據 Object Type 審查索引與 Data Object 的建置狀況，平台必須實作「三路追蹤器 (The Triple-Trace)」與對應的稽核 API：

Sankey Diagram (桑基圖) - 物件流向追蹤

用途：視覺化「事件」如何「扇出 (Fan-out)」成不同子系統的索引。

呈現：

左側 (Events)：顯示源頭 Process Event (數量)。

中間 (Indices)：線段流向各子系統 (APC, DC, SPC, Recipe) 的註冊點。

右側 (Storage)：匯聚到實體 Object (例如：1000 個 Lot Event 指向 1 個 Recipe Object)。

異常捕捉：如果某個事件扇出失敗（只有索引卻沒存到資料），該線段會在中途斷裂並顯示為紅色火花。

Event Timeline Inspector (事件時間軸檢查器)

用途：針對單一 Lot 或 Tool，展開其垂直的時間軸。

交互：點擊時間軸上的「加工完成」節點。

動態呈現：UI 會自動彈出側邊欄 (Drawer)，列出該時間點產生的所有索引記錄 (Indices)。

下鑽查核：點擊索引，直接從底層 API (如 MongoDB) 撈出實體 JSON 快照 (Actual Data Object) 並進行語法高亮 (Syntax Highlighting)。

Object-Index Ratio Chart (物件索引比率圖)

用途：一眼看出系統的「去重 (De-duplication)」效率，依 Object Type 分類監控。

邏輯：這是一個柱狀圖，對比「索引數」與「實體物件數」。

範例：Recipe 系統有 10,000 筆索引 (Index)，但只有 5 個實體物件 (Object)。這代表資料重複利用率極高 (2000:1)，系統非常健康。

Audit API v2.2 (稽核專用接口)
為了支撐上述 UI，後端需新增一組實作：

GET /v2/ontology/fanout/{eventId}：查詢特定事件產生的所有子系統註冊清單 (供 Sankey 圖使用)。

GET /v2/ontology/orphans：偵測那些有 Index 但找不到實體文件的「孤兒物件」 (供異常捕捉與清理使用)。

3. 核心資料服務定義 (Core Data Services)

為支援上層各種 Application，平台對外提供以下 4 大類 Data Services：

Graph Context Service (圖譜上下文服務)

Feature: 給定單一節點 (如一個 SPC Out-of-Control 點)，瞬間展開其水平與垂直的所有關聯實體。

Data Format: JSON Graph (Nodes & Edges)，包含實體快照。

Trajectory Trace Service (軌跡追溯服務)

Feature: 沿著時間軸，撈取特定 Lot 或 Tool 的生命週期序列資料。

Data Format: Time-Series Array of Objects，依 eventTime 排序。

Semantic Aggregation Service (語意聚合服務)

Feature: 跨批次、跨站點的條件聚合 (例如：所有跑過某台機台 + 某個配方的 DC 資料)。

Data Format: Tabular/DataFrame-ready JSON (Flattened context for Data Science)。

Ontology Audit Service (本體稽核服務)

Feature: 提供 v2.2 Nexus 的底層 API，確保各子系統獨立註冊與物件存放的健康度。

4. 驅動平台的 20 大真實廠務使用情境 (20 Core Fab Use Cases)

這 20 個真實故事定義了為何我們需要上述的 Data Services 以及特定 Data Formats。

類別一：異常排除與根因分析 (RCA & Defect Tracing)

號

情境故事 (Story)

依賴的 Data Service

資料格式與特徵要求

1

單一 SPC OOC 關聯還原：工程師看見某批貨 CD 偏小，需瞬間拉出當下機台、Recipe、APC 補償值與 DC 壓力。

Graph Context Service

需以 (lotId, step) 為 Root Node，展開 1-degree 關聯的 Nested JSON。

2

晶圓報廢軌跡追溯 (Scrap Tracing)：某批貨破片報廢，需撈出它生前所有經歷過的 Tool Events，尋找應力異常點。

Trajectory Trace Service

Array of LotEvents，需包含沿途所有的 DC max/min summaries。

3

良率 Excursion 隔離：產品良率驟降，需比對「壞批次」與「好批次 (Golden Lot)」的 Ontology 軌跡差異。

Trajectory Trace Service

支援多 targetId 的軌跡陣列比對，回傳 Diff JSON。

4

Chamber Matching (腔體匹配)：同型號機台 Chamber A 與 B 刻出來的產品不一樣，需調出兩者跑同 Recipe 的歷史。

Semantic Aggregation Service

以 (toolId, recipeId) 聚合，回傳包含大量 DC 陣列的 Tabular 格式以供畫圖。

5

Alarm Flood 關聯分析：機台當機前噴出上百個 Alarm，需找出前 10 分鐘哪個 DC Sensor 發生劇烈抖動。

Trajectory Trace Service

支援 eventTime range 查詢，回傳高頻 DC Sensor Time-Series Data。

類別二：設備健康與維護 (Equipment Engineering)

號

情境故事 (Story)

依賴的 Data Service

資料格式與特徵要求

6

機台零件老化追蹤：RF 產生器老化會導致反射功率漸增，需連續追蹤某機台過去 1000 批貨的 DC 電力參數。

Semantic Aggregation Service

ToolId 為 Key 的長序列 DC Data，需過濾掉 Idle 狀態。

7

PM (預防保養) 復機驗證：工程師洗完 Chamber 後，需比對 PM 前後 3 批貨的熱力與真空 DC 分佈是否有回到 Baseline。

Semantic Aggregation Service

需支援基於 eventTime 的 Before/After 區間比較 Data Format。

8

耗材壽命 (Edge Ring) 計算：需統計某個 Focus Ring 已經陪伴機台經歷了多少個 Tool Events (多少 RF Hours)。

Trajectory Trace Service

計算 Tool Events 中 RF_ON 的時間總和 (Aggregated Value)。

9

機台 First-Wafer Effect (首片效應)：機台閒置過久後的第一片晶圓常有溫度異常，需篩選出「Idle 超過 4 小時後的第一個 Lot Event」。

Trajectory Trace Service

需支援事件間隔 (Time-delta) 過濾邏輯的查詢。

10

機台 Dedication (專機專用) 稽核：某些關鍵 Layer 只能特定機台跑，需反查是否有機台偷跑不該跑的 Recipe。

Semantic Aggregation Service

回傳 ToolId 對應的所有 Unique RecipeId 列表 (Set Data)。

類別三：製程控制與配方管理 (Process Control & APC/Recipe)

號

情境故事 (Story)

依賴的 Data Service

資料格式與特徵要求

11

APC Model 準確度調校：比較 APC 算出來的 Bias 預測值，與下一站量測機台 (MET) 實際量到的 CD 差異。

Graph Context Service

需支援跨站點查詢 (Step N 的 APC 關聯 Step N+1 的 SPC/MET)。

12

EWMA 控制器震盪審計：確認 R2R (Run-to-Run) 系統是否因為給錯補償，導致連續批次的 SPC 呈波浪狀震盪。

Trajectory Trace Service

連續的 APC_Payload Array，專注於 offset 欄位的序列變化。

13

Recipe 版本漂移 (Version Drift)：工程師偷改 Recipe 參數後存成新版，需比對 v4.2 與 v4.3 靜態參數差異。

Ontology Audit Service

給定 RecipeId，回傳兩個 Version Object 的 JSON Diff。

14

虛擬量測 (VM) 特徵工程提取：Data Scientist 需要拿前 3 個 step 的 DC data 去訓練 AI 預測第 4 step 的厚度。

Semantic Aggregation Service

大寬表 (Wide Table Format)，以 lotId 為 Row，所有 DC Sensor 為 Columns。

15

跨製程參數關聯 (Step-Correlation)：想知道「蝕刻機的 Chamber 壓力」是否會影響「下一站沉積機的成膜應力」。

Graph Context Service

複雜的跨節點查詢，回傳 Node N (DC) 與 Node M (DC) 的聯合 JSON。

類別四：工廠營運與系統健康 (Fab Ops & IT)

號

情境故事 (Story)

依賴的 Data Service

資料格式與特徵要求

16

Q-Time (Queue Time) 效應分析：晶圓在兩站之間等太久會長原生氧化層，需計算 Lot Event 間的 Time-delta 對後續 DC 的影響。

Trajectory Trace Service

需自動計算相鄰事件的 time_gap 並附於回傳的 JSON Meta 中。

17

Rework (重工) 效率與參數對比：某批貨洗掉重做，需對比 Pass 1 與 Pass 2 的 DC 參數差異。

Graph Context Service

同一 lotId 但 Run_Number 不同的雙軌跡比較物件。

18

跨廠轉移 (Fab-to-Fab) 基準驗證：Fab 1 的 Recipe 轉移到 Fab 2，需證明兩邊產出的 DC 訊號特徵 (Fingerprint) 是一致的。

Semantic Aggregation Service

支援跨 Database / 跨 Site 的聚合查詢，回傳標準化後的特徵陣列。

19

Data Orphan 抓漏 (系統健康度)：某個 APC 服務當機，導致只有 Index 沒有實體 Payload，IT 需要報表清理孤兒節點。

Ontology Audit Service

呼叫 /v2/ontology/orphans，回傳 Broken Link Array 供 Sankey 圖渲染為紅線。

20

去重效率稽核 (Storage Cost Audit)：DBA 想知道這個月因為「Recipe 共用機制」，我們幫公司省了多少 TB 的硬碟空間。

Ontology Audit Service

回傳 Object-Index Ratio 的統計數據 (如 { "Recipe": { "indices": 100k, "objects": 50 } })。

[開發者備註 - 底層驗證規範]
如同團隊 [2026-02-27] 協議，日後在協助排解系統錯誤或安裝問題時，必須考慮提供簡單的測試腳本來驗證底層邏輯。
在實作上述 Data Services 與 Audit APIs 前，後端工程師必須提供一支對應的 Python API 測試腳本 (verify_data_services.py)，確認 /v2/ontology/fanout 能夠正確吐出包含索引與實體狀態的關聯資料，以驗證底層圖譜建立無誤。