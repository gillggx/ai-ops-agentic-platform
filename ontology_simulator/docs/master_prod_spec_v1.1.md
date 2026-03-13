v1.1 聯調規格書：解決小柯的致命問題
1. ID 命名體系統一 (改後端優先)

為了符合數位孿生的專業感，我們統一採用前端的命名格式，後端需配合修改 Mock Generator：

Tool: EQP-01 ~ EQP-10

Lot: LOT-xxxx，採零填充序號格式 (e.g., LOT-0001 ~ LOT-0100)，與後端 seeding 保持一致。

Recipe: RCP-xxxx (e.g., RCP-ETCH-01)

APC/DC/SPC: 統一為 APC-xxx, DC-xxx, SPC-xxx

2. 後端 WebSocket 增補方案

確認在後端加入 WebSocket (WS) 推送層。

Heartbeat: 每 5~10 秒推送一次狀態。

Mechanism: 每當 MES 推進一個 Step，Agent 組織完數據後，除了存入 Mongo，必須依序廣播三類事件以驅動 UI 五階段動畫：

  Step 1 → 發送 ENTITY_LINK（觸發 STAGE_LOAD 藍色）
  Step 2 → 延遲約 800ms → 發送 TOOL_LINK（觸發 STAGE_PROCESS 橘色脈衝）
  Step 3 → 延遲約 800ms → 發送 METRIC_UPDATE（觸發 STAGE_ANALYSIS 紫色，最後轉為 STAGE_DONE）

3. 資料結構補強 (Schema Mapping)

為了解決小柯提到的「欄位不存在」問題，我們在後端 object_snapshots 增加 Metadata 欄位：

APC: 增加 mode (預設 "Run-to-Run")。

DC: 增加 collection_plan (預設 "HIGH_FREQ")。

Metric: 在 METRIC_UPDATE 事件中，從 20 個 APC 參數中取第一個作為 bias，unit 固定為 nm，trend 根據與前一筆快照的差值判定（新值 > 舊值 → "UP"，否則 "DOWN"）。

APC bias 語意定義: param_01 代表「製程補償偏移量」，初始範圍設定為 0.0 ~ 0.1（非 0.1 ~ 1.0），每次 ±5% 漂移。警報閾值 bias > 0.05 在此範圍下具有實際意義（約一半機率觸發）。

4. 關鍵定義：v14.0 五階段日誌 (The 5 Stages)

這是我漏掉的定義，請小柯依照此邏輯實作 UI 顏色：

STAGE_IDLE (灰色): 機台待機中。

STAGE_LOAD (藍色): ENTITY_LINK 觸發，Lot 已掛載至 Tool。

STAGE_PROCESS (橘色脈衝): TOOL_LINK 觸發，APC/DC 已啟動。

STAGE_ANALYSIS (紫色): METRIC_UPDATE 觸發，SPC 正在計算。

STAGE_DONE (綠色/紅色): 完成。若 spc_status == "OOC" 則閃紅燈，否則綠燈。

5. Agent Reflection & AI 功能範疇

本期範圍 (Current Sprint): 採用 Rule-based Reflection。

邏輯: 當 spc_status == "OOC" 時，後端 Agent 簡單組合字串："[Agent Reflection] 偵測到 {tool_id} 的參數 {param_name} 偏移，建議執行線性回歸診斷。"

Future Scope: 真正的 AI 推理層（LLM integration）放在下一階段。

6. 圖表 API 定義 (The Plotting API)

小柯提到的 plot_line 等工具，請實作以下 Endpoint：

Endpoint: GET /api/v1/analytics/history

Params: targetID, objectName, limit=50

Output: 回傳該物件最近 50 筆的歷史數據（用於繪製 Trend Chart）。

7. 異常預警觸發 (Alert Condition)

定義: 只要 SPC.status == "OOC" 或 APC.bias > threshold (0.05)，前端卡片邊框即刻閃爍紅光。

💡 給小柯的最終回覆 (PM Memo)

「小柯，拍謝！之前的規格確實存在前後端落差。以下是你的開發指引：

ID 統一: 請以 EQP-xx / LOT-xxxx 為準，我會同步更新後端。

WS 優先: 請先幫我架設 WS Server，推送三種事件，Schema 缺少的欄位（如 mode, bias）我授權你在後端模擬器先給『預設值』。

五階段日誌: 請參考上面定義的 5 個 STAGE 進行顏色切換。

Reflection: 先做成字串模板拼接即可，重點在於 UI 的呈現感。

API: 我會多給你一支 /analytics/history，方便你餵資料給 plot_line。」