案目標：廢除「動態生成 Python 程式碼」的不穩定流程，全面導入 Node-based Visual Programming (節點視覺化編程) 架構。由底層提供標準化積木，由 Agent (LLM) 輔助生成管線草圖，並將最終參數的微調權與資料預覽權，透過圖形化介面交還給製程工程師 (PE)。

1. 核心 UX 佈局 (四大工作區)
介面需參考業界標準 (如 Palantir Foundry)，劃分為四個具備連動關係的面板：

左側 - 積木庫 (Block Library)：分類收納所有可用的節點，支援拖曳 (Drag & Drop) 至畫布。

中央 - 節點畫布 (DAG Canvas)：無限延伸的網格畫布。節點之間以貝茲曲線 (Bezier curves) 連接，呈現由左至右的資料處理流向。

右側 - 屬性檢視器 (Node Inspector)：當點擊畫布上的節點時，顯示該節點專屬的表單介面（如：下拉選單、閾值輸入框），供使用者微調邏輯。

底部 - 即時資料預覽 (Data Preview)：本架構靈魂功能。點擊任意節點時，即時以 Table 呈現「資料流經此節點時的實際樣貌」，確保使用者能除錯與驗證邏輯。

2. 標準積木庫定義 (Node Library)
初期開發請優先實作以下 4 大類原子化積木，後續可無限擴充。

📥 類別一：資料源 (Data Sources)

MCP 歷史查詢 (MCP Fetch)：拉取指定機台、時間區間的製程資料 (包含 SPC, APC, DC)。

MES 狀態查詢 (Tool Status)：即時取得機台當下是 RUN, IDLE 或 PM 狀態。

⚙️ 類別二：資料處理 (Transforms)

過濾器 (Filter)：根據欄位條件過濾資料 (例如 Step == STEP_002)。

關聯併表 (Join)：將兩份資料表 (如 SPC 與 APC) 透過 Lot_ID 進行合併。

時間滑動視窗 (Rolling Window)：計算近 N 筆資料的移動平均 (Moving Average) 或標準差。

🧠 類別三：邏輯與診斷 (Logic & ML)

閾值觸發 (Threshold)：設定上下限 (UCL/LCL) 進行大於/小於判斷。

連續規則 (Consecutive Rule)：判斷是否「連續 N 筆」滿足特定條件。

異常偵測 (Isolation Forest)：[ML 積木] 輸入特徵，輸出 Anomaly Score (0~1)。

模型遷移 (Transfer Learning)：[ML 積木] 匯入 Golden Tool 的預訓練權重，快速套用至新機台特徵。

🚀 類別四：輸出與行動 (Outputs & Actions)

生成圖表 (Chart Builder)：將結果資料流導向視覺化元件，渲染折線圖或對比圖。

發送告警 (Alert Trigger)：將異常清單拋送至 Alarm Center，標記嚴重等級 (HIGH/MEDIUM)。

3. Agent (LLM) 協作流程定義
輸入：使用者自然語言需求（例：「幫我建一個規則盯著 EQP-01，只要 xbar 連續 3 次 OOC 就發告警。」）

輸出 (Agent Intent)：Agent 嚴禁產出 Python Code。必須產出一份描述節點與連線的 Pipeline JSON。

渲染與接手：前端讀取 Pipeline JSON，瞬間於畫布上畫出完整的積木流。工程師接手審閱，點擊節點微調參數後即可佈署。

4. HTML Wireframe (給小柯的實作參考)
請將以下程式碼儲存為 pipeline-builder.html 並於瀏覽器開啟。此原型展示了 畫布、連線、屬性面板與資料預覽的即時連動，是後續導入 React Flow 前的完美概念驗證 (POC)。
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AIOps Pipeline Builder</title>
    <style>
        :root {
            --bg-dark: #1e1e24; --bg-panel: #2b2b36; --bg-canvas: #f0f2f5;
            --border: #e0e0e0; --primary: #1890ff; --text-main: #333; --text-light: #fff;
            --node-source: #52c41a; --node-transform: #fa8c16; --node-logic: #722ed1; --node-output: #f5222d;
        }
        body { margin: 0; font-family: system-ui, sans-serif; display: flex; flex-direction: column; height: 100vh; overflow: hidden; background-color: var(--bg-canvas); }
        
        /* 頂部導覽 */
        .header { background: #fff; padding: 12px 24px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; box-shadow: 0 1px 4px rgba(0,0,0,0.05); z-index: 10; }
        .header h1 { margin: 0; font-size: 18px; color: var(--text-main); }
        .deploy-btn { background: var(--primary); color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-weight: bold; }

        /* 中間工作區 */
        .workspace { display: flex; flex: 1; overflow: hidden; }

        /* 左側：積木庫 */
        .sidebar { width: 220px; background: #fff; border-right: 1px solid var(--border); padding: 16px; overflow-y: auto; }
        .sidebar h3 { font-size: 14px; color: #888; margin-top: 0; }
        .block-item { padding: 10px; margin-bottom: 8px; border-radius: 4px; border: 1px solid var(--border); font-size: 13px; cursor: grab; background: #fafafa; display: flex; align-items: center; gap: 8px; }
        .block-item.source { border-left: 4px solid var(--node-source); }
        .block-item.transform { border-left: 4px solid var(--node-transform); }
        .block-item.logic { border-left: 4px solid var(--node-logic); }
        
        /* 中央：節點畫布 */
        .canvas-container { flex: 1; position: relative; background-image: radial-gradient(#d9d9d9 1px, transparent 1px); background-size: 20px 20px; overflow: hidden; }
        
        /* SVG 連線 */
        .edges { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }
        .edge-path { fill: none; stroke: #b0b0b0; stroke-width: 3; }
        
        /* 節點樣式 */
        .node { position: absolute; width: 160px; background: #fff; border-radius: 6px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border: 2px solid transparent; cursor: pointer; user-select: none; transition: 0.2s border-color; z-index: 2; }
        .node.active { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(24,144,255,0.2); }
        .node-header { padding: 8px 12px; border-top-left-radius: 4px; border-top-right-radius: 4px; color: #fff; font-size: 12px; font-weight: bold; }
        .node-body { padding: 12px; font-size: 13px; color: var(--text-main); }
        
        .node.source .node-header { background: var(--node-source); }
        .node.transform .node-header { background: var(--node-transform); }
        .node.logic .node-header { background: var(--node-logic); }
        .node.output .node-header { background: var(--node-output); }

        /* 節點連接點 */
        .port { position: absolute; width: 10px; height: 10px; background: #fff; border: 2px solid #888; border-radius: 50%; top: 50%; transform: translateY(-50%); }
        .port.in { left: -6px; } .port.out { right: -6px; }

        /* 右側：屬性檢視器 */
        .inspector { width: 300px; background: #fff; border-left: 1px solid var(--border); display: flex; flex-direction: column; }
        .inspector-header { padding: 16px; border-bottom: 1px solid var(--border); font-weight: bold; background: #fafafa; }
        .inspector-content { padding: 16px; flex: 1; overflow-y: auto; }
        .form-group { margin-bottom: 16px; }
        .form-group label { display: block; font-size: 12px; color: #666; margin-bottom: 6px; }
        .form-group input, .form-group select { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }

        /* 底部：資料預覽面板 */
        .bottom-panel { height: 250px; background: #fff; border-top: 1px solid var(--border); display: flex; flex-direction: column; z-index: 10; }
        .panel-header { padding: 10px 16px; background: #f0f0f0; border-bottom: 1px solid var(--border); font-size: 13px; font-weight: bold; display: flex; justify-content: space-between; }
        .data-table-wrapper { flex: 1; overflow: auto; padding: 0 16px; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px; }
        th, td { text-align: left; padding: 8px; border-bottom: 1px solid #eee; }
        th { color: #888; position: sticky; top: 0; background: #fff; }
        .highlight-row { background-color: #fff1f0; }

        .placeholder-text { color: #aaa; text-align: center; margin-top: 40px; font-size: 14px; }
    </style>
</head>
<body>

    <div class="header">
        <h1>🛠️ AIOps Pipeline Builder <span style="color: #888; font-size: 14px; font-weight: normal;">| EQP-01 SPC 巡檢規則</span></h1>
        <button class="deploy-btn">佈署管線 (Deploy)</button>
    </div>

    <div class="workspace">
        <div class="sidebar">
            <h3>📥 資料源 (Sources)</h3>
            <div class="block-item source">🗄️ MCP 歷史查詢</div>
            <div class="block-item source">🏭 MES 狀態查詢</div>
            
            <h3 style="margin-top: 20px;">⚙️ 處理 (Transforms)</h3>
            <div class="block-item transform">🔍 條件過濾 (Filter)</div>
            <div class="block-item transform">🔗 關聯 (Join)</div>
            
            <h3 style="margin-top: 20px;">🧠 邏輯與 ML (Logic)</h3>
            <div class="block-item logic">📏 閾值檢查 (Threshold)</div>
            <div class="block-item logic">⚠️ 連續觸發 (Consecutive)</div>
            <div class="block-item logic">🧠 模型遷移 (Transfer)</div>
            
            <h3 style="margin-top: 20px;">🚀 輸出 (Outputs)</h3>
            <div class="block-item" style="border-left: 4px solid #f5222d;">🚨 發送告警 (Alert)</div>
        </div>

        <div class="canvas-container">
            <svg class="edges">
                <path class="edge-path" d="M 190 120 C 250 120, 250 120, 310 120" />
                <path class="edge-path" d="M 470 120 C 530 120, 530 200, 590 200" />
            </svg>

            <div class="node source" style="left: 30px; top: 80px;" onclick="selectNode('source')">
                <div class="node-header">MCP 歷史查詢</div>
                <div class="node-body">抓取 EQP-01 資料</div>
                <div class="port out"></div>
            </div>

            <div class="node transform active" style="left: 310px; top: 80px;" onclick="selectNode('filter')">
                <div class="node-header">條件過濾</div>
                <div class="node-body">Step == STEP_002</div>
                <div class="port in"></div>
                <div class="port out"></div>
            </div>

            <div class="node logic" style="left: 590px; top: 160px;" onclick="selectNode('logic')">
                <div class="node-header">連續觸發規則</div>
                <div class="node-body">連續 3 次 > UCL</div>
                <div class="port in"></div>
                <div class="port out"></div>
            </div>
        </div>

        <div class="inspector">
            <div class="inspector-header" id="inspector-title">設定：條件過濾</div>
            <div class="inspector-content" id="inspector-form">
                <div class="form-group">
                    <label>目標欄位 (Column)</label>
                    <select><option>Step_Name</option><option>Lot_ID</option></select>
                </div>
                <div class="form-group">
                    <label>運算子 (Operator)</label>
                    <select><option>Equals (==)</option><option>Contains</option></select>
                </div>
                <div class="form-group">
                    <label>比對數值 (Value)</label>
                    <input type="text" value="STEP_002">
                </div>
            </div>
        </div>
    </div>

    <div class="bottom-panel">
        <div class="panel-header">
            <span>📊 即時資料預覽 (Data Lineage)</span>
            <span style="color: var(--primary);" id="preview-subtitle">目前檢視：條件過濾 (輸出結果 3 筆)</span>
        </div>
        <div class="data-table-wrapper" id="preview-table">
            <table>
                <tr><th>Timestamp</th><th>Tool_ID</th><th>Lot_ID</th><th>Step_Name</th><th>SPC_xbar</th></tr>
                <tr><td>2026-04-18 10:00</td><td>EQP-01</td><td>LOT-221</td><td>STEP_002</td><td>1490.5</td></tr>
                <tr><td>2026-04-18 10:15</td><td>EQP-01</td><td>LOT-222</td><td>STEP_002</td><td>1510.2</td></tr>
                <tr class="highlight-row"><td>2026-04-18 10:30</td><td>EQP-01</td><td>LOT-223</td><td>STEP_002</td><td style="color:red; font-weight:bold;">1560.8 (OOC)</td></tr>
            </table>
        </div>
    </div>

    <script>
        // 模擬點擊節點切換右側與下方資料
        function selectNode(type) {
            // 移除所有 active 狀態
            document.querySelectorAll('.node').forEach(n => n.classList.remove('active'));
            event.currentTarget.classList.add('active');

            const title = document.getElementById('inspector-title');
            const form = document.getElementById('inspector-form');
            const previewTitle = document.getElementById('preview-subtitle');
            const table = document.getElementById('preview-table');

            if (type === 'source') {
                title.innerText = '設定：MCP 歷史查詢';
                form.innerHTML = `<div class="form-group"><label>機台 (Tool)</label><input type="text" value="EQP-01"></div><div class="form-group"><label>時間範圍</label><select><option>過去 24 小時</option></select></div>`;
                previewTitle.innerText = '目前檢視：MCP 歷史查詢 (原始資料 500 筆)';
                table.innerHTML = '<div class="placeholder-text">[顯示 500 筆未過濾的原始製程資料]</div>';
            } 
            else if (type === 'filter') {
                title.innerText = '設定：條件過濾';
                form.innerHTML = `<div class="form-group"><label>目標欄位</label><select><option>Step_Name</option></select></div><div class="form-group"><label>運算子</label><select><option>==</option></select></div><div class="form-group"><label>數值</label><input type="text" value="STEP_002"></div>`;
                previewTitle.innerText = '目前檢視：條件過濾 (輸出結果 3 筆)';
                table.innerHTML = `<table><tr><th>Timestamp</th><th>Tool_ID</th><th>Lot_ID</th><th>Step_Name</th><th>SPC_xbar</th></tr><tr><td>10:00</td><td>EQP-01</td><td>LOT-221</td><td>STEP_002</td><td>1490.5</td></tr><tr><td>10:15</td><td>EQP-01</td><td>LOT-222</td><td>STEP_002</td><td>1510.2</td></tr><tr class="highlight-row"><td>10:30</td><td>EQP-01</td><td>LOT-223</td><td>STEP_002</td><td style="color:red; font-weight:bold;">1560.8 (OOC)</td></tr></table>`;
            }
            else if (type === 'logic') {
                title.innerText = '設定：連續觸發規則';
                form.innerHTML = `<div class="form-group"><label>監控指標</label><input type="text" value="SPC_xbar"></div><div class="form-group"><label>條件</label><select><option>大於 UCL</option></select></div><div class="form-group"><label>連續次數</label><input type="number" value="3"></div>`;
                previewTitle.innerText = '目前檢視：連續觸發規則 (觸發告警 1 筆)';
                table.innerHTML = `<table><tr><th>告警時間</th><th>觸發主體</th><th>異常描述</th></tr><tr class="highlight-row"><td>10:30</td><td>LOT-223</td><td>連續 3 次 xbar 違反管制界線</td></tr></table>`;
            }
        }
    </script>
</body>
</html>