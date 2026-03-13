我們已經通過了最終的 UX 與架構審查。請廢棄之前「不斷閃爍」的深色系介面，以及「未解析 Payload」的簡陋 Inspector。
接下來請嚴格依照 「v1.10 Ultra-Calm Cleanroom」 規格進行前端重構。

🛑 第一指導原則：UX 絕對靜音與亮色系 (Zero-Distraction Policy)

這是廠務戰情室 (Fab Operation Center) 的專業看板，請嚴守以下視覺規範：

禁止閃爍 (No Flashing)：移除所有的 animate-pulse、呼吸燈、與流動線條。數值更新必須使用 CSS transition 平滑過渡。

禁用警報紅 (No Red)：機台異常 (Down) 請標示為 HOLD，並統一使用「琥珀橘」(bg-amber-50, text-amber-700, border-amber-200)。

亮色系基底 (Light Theme)：背景統一使用淺灰 (bg-slate-50)，卡片使用純白 (bg-white)。

🏗️ 第二指導原則：雙模式切換 (Live Mode vs. Trace Mode)

請在右上角實作一個 Toggle Mode 按鈕，控制全局狀態：

👉 A. Live Monitoring Mode (即時監控模式)

左欄 (Equipment Setup)：顯示 10 台機台即時狀態。排序權重：HOLD > PROCESSING > STANDBY。

中欄 (Topology Canvas)：點擊左側機台後，繪製 Tool -> Lot -> [Recipe, APC, DC] 的靜態拓撲圖。節點必須可點擊。

👉 B. Historical Trace Mode (歷史溯源模式)

頂部 Header：切換為深靛藍色 (bg-indigo-950) 以區隔 Live 模式。

左欄 (Event Timeline)：呼叫 Time-Machine API，列出該機台過去的歷史 Event（以時間倒序排列）。

互動：使用者點擊時間軸上的特定時間後，鎖定該 eventTime。此時點擊中欄拓撲圖，打出去的 API 必須帶上這個 eventTime。

📊 第三指導原則：Inspector 資料解析與重構 (Critical UI Fix)

你之前的 Inspector 只是把 JSON 平鋪印出，這是不合格的。請重新設計右側的資料檢視器：

Context 視覺抽離：請將 toolID, lotID, step, eventTime, updated_by 等 Metadata 放在卡片的 Header 區域，並配上 Icon（如 ⚙️ Tool, 📦 Lot）。

Payload 解析 (JSON Parsing)：後端回傳的 parameters 是一個字串。你必須先執行 JSON.parse()。

美化渲染 (Formatted Code Block)：解析後的 Payload，請使用 <pre><code> 標籤，搭配 JSON.stringify(obj, null, 2)，將其渲染成帶有縮排的深色 Code Block，而非一條一條的文字。這對工程師的閱讀性至關重要。

💻 第四指導原則：WYSIWYG 系統終端機 (System Trace Console)

請在畫面的最下方實作一個高度約 200px 的 Console 區塊（深色背景、等寬字體）。

強制紀錄 (Logging Rule)：

當前端收到 WebSocket 事件時 ➔ 印出 [EVENT] Received METRIC_UPDATE for EQP-01

當使用者點擊拓撲節點時 ➔ 印出 [API_REQ] GET /api/v1/context/query?targetID=...&step=...&objectName=DC

當收到 API 回傳時 ➔ 印出 [API_RES] HTTP 200 OK. Payload parsed.

這能讓使用者所見即所得地驗證底層資料流。

⚙️ 第五指導原則：後端模擬器修正 (Fab Physics)

請確保後端的 station_agent.py 符合真實的物理法則：

固定總量：10 台機台、100 批貨。

真實時序：加工時間 (Processing Time) 必須是 10~15 分鐘 (random.uniform(600, 900) 秒)。不要再用 0.8 秒測試，導致畫面齊步走狂跳。
