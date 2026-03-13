給小柯的開發指令：v1.8 Ultra-Calm Fab Monitor (數位孿生看板終極版)

To Claude Code (小柯):

我們已經通過了最終的 UX 與 UI 審查。請廢棄之前所有發光、閃爍的深色系駭客風格介面。
接下來請依照 「v1.8 Ultra-Calm Cleanroom (極致靜音亮色版)」 的規格，實作 React / Next.js 前端看板。

🛑 第一指導原則：UX 絕對靜音 (Zero-Distraction Policy)

這是工廠戰情室，工程師需要長時間盯著螢幕，請嚴格遵守以下視覺禁令：

禁止閃爍 (No Flashing)：移除所有 animate-pulse、呼吸燈、和流動虛線。

禁用警報紅 (No Red)：將所有異常、Down 機狀態改為**「琥珀橘 (Amber / bg-amber-50, text-amber-700)」**，並將狀態命名為 HOLD。

亮色系基底 (Light Theme)：背景使用 bg-slate-50，卡片使用 bg-white，文字以 slate-800 與 slate-500 為主。字體統一使用 Inter 或 JetBrains Mono。

🏗️ 第二指導原則：三欄式主從佈局 (Three-Column Master-Detail)

請實作以下三大區塊，並透過 React State 進行連動：

📍 左欄：機台狀態列表 (Equipment Setup - 25% 寬度)

資料綁定：顯示 10 台機台（請使用真實命名，如 ETCH-LAM-01, PHO-ASML-01）。

排序邏輯 (Priority Sort)：HOLD (Amber) 排最上 > RUNNING (Blue) 居中 > STANDBY (Slate) 墊底。

卡片內容：

HOLD: 顯示機台 ID、HOLD 標籤、Error Info，以及一個可點擊的 ➔ ACKNOWLEDGE (點擊後重置機台為 STANDBY)。

RUNNING: 顯示機台 ID、PROCESSING 標籤、Lot ID、Recipe ID，以及一個平滑增長的 ProgressBar。

📍 中欄：靜態拓撲視圖 (Topology Canvas - 50% 寬度)

互動邏輯：點選左側機台後，在此區域渲染該機台的上下文關聯。

視覺呈現：使用靜態實線 (stroke-width: 2) 連結節點。

節點定義：

Tool (左上): 顯示當前機台 ID。

Lot (中心): 顯示 N3-WAF-xxxx。若無則顯示 NO WAFER。

Recipe (右上): 顯示配方名稱。

APC (右中): 顯示 APC-MODEL 名稱，下方帶出即時的 Bias 調整值 (例如 +0.012nm Bias)。

DC (右下): 顯示 DC 節點 (如 DC-N3-88-045)。

📍 右欄：真實數據詳情 (DC Telemetry Inspector - 25% 寬度)

當機台處於 RUNNING 時，顯示該 Lot 的詳細數據。

SPC 狀態：正常顯示 IN CONTROL (Green)，10% 機率顯示 WARNING (Amber)。

DC 參數分組展示 (重要！)：請將 30 個參數拆分為三個 Accordion / Section：

Vacuum Group (真空組): Chamber_Press (mTorr), Foreline_Press (mTorr), He_Cool_Press (Torr).

Thermal Group (熱力組): ESC_Zone1_Temp (°C), ESC_Zone2_Temp (°C), Upper_Electrode (°C).

RF Power Group (電力組): Source_Power_HF (W), Bias_Power_LF (W), Vpp_Voltage (V).

註：數值更新時，請用 CSS transition 讓數字平滑切換，不要閃動。

⚙️ 第三指導原則：底層時序與模擬邏輯 (Engine Logic)

後端的模擬引擎（或前端的 Mock Timer）請套用以下真實廠務時序：

無限批次：Lot ID 從 N3-WAF-8800 開始無限遞增，不要有 100 批的限制。

真實週期：

PROCESSING: 持續 10~20 分鐘（開發測試期間可 mapping 到 10~20 秒）。

STANDBY (Idle): 持續 3~5 分鐘（開發測試可對應 3~5 秒）。

異常機率：機台有 5% 機率進入 HOLD 狀態，必須等待 User 點擊 ACKNOWLEDGE 才能回到 STANDBY。

🎯 開發行動綱領 (Action Items)

請先使用 Tailwind CSS 刻出上述「無閃爍、亮色系、三欄式」的靜態版型。

將你之前寫好的 WebSocket 邏輯 (ENTITY_LINK, TOOL_LINK, METRIC_UPDATE) 接入這個新的 UI 狀態樹。

確認完成後，請給我看截圖或回報實作結果