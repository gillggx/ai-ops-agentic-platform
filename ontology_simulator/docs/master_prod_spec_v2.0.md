請將回傳的每一筆 JSON Snapshot 渲染成時間軸上的一張卡片。禁止使用簡單的 Object.entries.map 平鋪印出。必須實作以下層級：

1. 卡片 Header (Context 抽離)
將 objectID, toolID, lotID, step 抽離出來，放在頂部的 Header，並加上 icon 標示。

2. Metadata 條
將 eventTime, updated_by, collection_plan 放在 Header 下方淺色底的橫條中。

3. Payload 格式化渲染 (重點要求)
後端回傳的 parameters 欄位是一個 字串 (String)。你必須：

執行 JSON.parse(record.parameters)。

將解析後的 Object 放進一個 <pre><code> 標籤中。

使用 JSON.stringify(parsedObj, null, 2) 來渲染出帶有縮排的高可讀性結構。

外框請套用 bg-[#1e293b] (Slate-800) 的深色背景，模仿編輯器的語法高亮感。

🛠️ 底層邏輯驗證要求 (Test Script)

在開始寫 React 之前，為了驗證你的後端 Time-Machine API 真的能接收這 4 個參數並吐出歷史紀錄，請提供一支 Python 測試腳本 (verify_trace_api.py)。這支腳本需模擬發送 GET /api/v1/context/query?objectName=DC&targetID=LOT-0001&step=STEP_007 並印出結果。
（這符合我們 [2026-02-27] 制定的除錯驗證規範）。

請先回覆 Python 驗證腳本，再開始照著 HTML 原型實作 React 元件。

使用以下的格式來顯示頁面功能

<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>v14.0 Agentic OS - Object Trace Explorer</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
        body { font-family: 'Inter', sans-serif; background-color: #f8fafc; color: #334155; }
        .font-mono { font-family: 'JetBrains Mono', monospace; }
        
        /* 隱藏原生捲軸，改為極簡樣式 */
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

        /* JSON 語法高亮模擬 */
        .json-key { color: #818cf8; } /* Indigo 400 */
        .json-num { color: #f59e0b; } /* Amber 500 */
        
        /* 時間軸線 */
        .timeline-line {
            position: absolute;
            left: 23px;
            top: 40px;
            bottom: -20px;
            width: 2px;
            background-color: #e2e8f0;
            z-index: 0;
        }
    </style>
</head>
<body class="h-screen flex flex-col overflow-hidden selection:bg-indigo-100">

    <!-- Header -->
    <header class="h-14 border-b border-slate-200 bg-white flex flex-shrink-0 items-center justify-between px-6 shadow-sm z-20">
        <div class="flex items-center gap-4">
            <div class="flex items-center justify-center w-6 h-6 rounded bg-indigo-100 text-indigo-600">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            </div>
            <h1 class="text-lg font-bold tracking-tight text-slate-800">v14.0 AGENTIC OS <span class="text-slate-400 font-medium ml-2">| OBJECT TRACE EXPLORER</span></h1>
        </div>
        <div class="flex items-center gap-4 text-sm font-medium">
            <button class="flex items-center gap-2 px-3 py-1.5 rounded bg-white border border-slate-300 text-slate-600 hover:bg-slate-50 transition shadow-sm font-bold">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg>
                Exit to Dashboard
            </button>
        </div>
    </header>

    <main class="flex-1 flex overflow-hidden">
        
        <!-- 左欄：查詢條件 (Query Filters) -->
        <aside class="w-[320px] border-r border-slate-200 bg-white flex flex-col shadow-[4px_0_15px_rgba(0,0,0,0.02)] z-10 shrink-0">
            <div class="p-4 border-b border-slate-100 bg-slate-50/50">
                <h2 class="font-bold text-slate-700 flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-indigo-500"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
                    Historical RCA Query
                </h2>
            </div>
            
            <div class="p-5 space-y-5 overflow-y-auto flex-1 text-sm">
                <!-- Object Type Filter -->
                <div class="space-y-2">
                    <label class="font-bold text-slate-500 text-[10px] uppercase tracking-wider">Target Object Type</label>
                    <select class="w-full border border-slate-300 rounded-md px-3 py-2 bg-slate-50 text-slate-700 font-bold focus:outline-none focus:border-indigo-500">
                        <option value="DC" selected>DC (Data Collection)</option>
                        <option value="APC">APC (Adv. Process Control)</option>
                        <option value="SPC">SPC (Stat. Process Control)</option>
                    </select>
                </div>

                <!-- Context Filters -->
                <div class="space-y-3 pt-4 border-t border-slate-100">
                    <label class="font-bold text-slate-500 text-[10px] uppercase tracking-wider">Context Linkage (Required)</label>
                    
                    <div>
                        <div class="text-[10px] text-slate-400 mb-1 font-bold">Tool ID</div>
                        <input type="text" value="ETCH-LAM-01" class="w-full border border-slate-300 rounded-md px-3 py-1.5 bg-white text-slate-700 font-mono text-xs focus:outline-none focus:border-indigo-500">
                    </div>
                    
                    <div>
                        <div class="text-[10px] text-slate-400 mb-1 font-bold">Lot ID (targetID)</div>
                        <input type="text" value="LOT-0001" class="w-full border border-slate-300 rounded-md px-3 py-1.5 bg-white text-slate-700 font-mono text-xs focus:outline-none focus:border-indigo-500">
                    </div>

                    <div>
                        <div class="text-[10px] text-slate-400 mb-1 font-bold">Step</div>
                        <input type="text" value="STEP_007" class="w-full border border-slate-300 rounded-md px-3 py-1.5 bg-white text-slate-700 font-mono text-xs focus:outline-none focus:border-indigo-500">
                    </div>
                </div>
            </div>

            <!-- Execute Button -->
            <div class="p-4 border-t border-slate-100 bg-slate-50">
                <button class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-2.5 px-4 rounded shadow-sm transition-colors flex justify-center items-center gap-2 text-sm" onclick="alert('Fetching from API: /api/v1/context/query...')">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
                    Fetch Historical Data
                </button>
            </div>
        </aside>

        <!-- 右欄：時間軸查詢結果 (Timeline Feed) -->
        <section class="flex-1 flex flex-col bg-slate-50/50 relative overflow-hidden">
            <div class="p-4 border-b border-slate-200 bg-white shadow-sm flex justify-between items-center shrink-0 z-10">
                <div class="text-sm font-medium text-slate-600">
                    Showing timeline for <span class="bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded border border-indigo-100 font-mono font-bold text-xs">DC</span> on <span class="font-mono text-xs font-bold text-slate-800">ETCH-LAM-01</span> (<span class="font-mono text-xs font-bold text-slate-800">LOT-0001</span>)
                </div>
            </div>

            <!-- 時間軸結果列表 -->
            <div class="flex-1 overflow-y-auto p-8 relative">
                
                <!-- 紀錄 1: 最新的 DC Snapshot -->
                <div class="relative pl-12 pb-10">
                    <div class="timeline-line"></div>
                    <!-- 時間點圓圈 -->
                    <div class="absolute left-[15px] top-[6px] w-4 h-4 rounded-full bg-indigo-100 border-[3px] border-indigo-500 z-10 shadow-sm"></div>
                    <!-- 時間標籤 -->
                    <div class="absolute left-[-80px] top-[4px] text-xs font-bold font-mono text-slate-500">12:17:50</div>

                    <!-- 資料卡片 (黃金標準：層級分離 + JSON 渲染) -->
                    <div class="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden hover:shadow-md transition-shadow">
                        
                        <!-- 1. Card Header: 抽出 Context Interface -->
                        <div class="bg-slate-50 border-b border-slate-100 px-4 py-3 flex items-center justify-between">
                            <div class="flex items-center gap-3">
                                <span class="bg-indigo-100 text-indigo-700 px-2 py-1 rounded text-xs font-bold border border-indigo-200 tracking-wider">DC SNAPSHOT</span>
                                <span class="font-mono text-sm font-bold text-slate-800">DC-LOT-0001-STEP_007-2...</span>
                            </div>
                            <!-- 圖像化 Context 標籤 -->
                            <div class="text-[10px] text-slate-500 font-mono flex gap-3 bg-white px-2 py-1 rounded border border-slate-200 shadow-sm">
                                <span title="Tool ID">⚙️ ETCH-LAM-01</span>
                                <span title="Lot ID">📦 LOT-0001</span>
                                <span title="Step">🏷️ STEP_007</span>
                            </div>
                        </div>

                        <div class="p-0 flex flex-col">
                            <!-- 2. Metadata 條 -->
                            <div class="bg-slate-50/50 px-4 py-2 border-b border-slate-100 text-xs text-slate-500 flex gap-6">
                                <div><span class="text-slate-400 font-bold">collection_plan:</span> <span class="font-mono font-bold text-slate-700">HIGH_FREQ</span></div>
                                <div><span class="text-slate-400 font-bold">updated_by:</span> <span class="font-mono font-bold text-slate-700">dc_service</span></div>
                                <div><span class="text-slate-400 font-bold">eventTime:</span> <span class="font-mono font-bold text-slate-700">2026-03-12T12:17:50.342Z</span></div>
                            </div>
                            
                            <!-- 3. Parameters 區塊 (高可讀性 JSON 渲染) -->
                            <div class="p-4 bg-[#1e293b] rounded-b-xl overflow-x-auto text-[13px] leading-relaxed font-mono shadow-inner border-t border-slate-800">
<pre class="m-0"><span class="text-slate-400">"parameters"</span><span class="text-slate-300">: {</span>
  <span class="json-key">"sensor_01_chamber_press"</span><span class="text-slate-300">: </span><span class="json-num">0.088116</span><span class="text-slate-300">,</span>
  <span class="json-key">"sensor_02_foreline_press"</span><span class="text-slate-300">: </span><span class="json-num">1.204550</span><span class="text-slate-300">,</span>
  <span class="json-key">"sensor_03_he_cooling"</span><span class="text-slate-300">: </span><span class="json-num">10.50000</span><span class="text-slate-300">,</span>
  <span class="json-key">"sensor_04_esc_temp_1"</span><span class="text-slate-300">: </span><span class="json-num">60.45000</span><span class="text-slate-300">,</span>
  <span class="json-key">"sensor_05_esc_temp_2"</span><span class="text-slate-300">: </span><span class="json-num">65.20000</span><span class="text-slate-300">,</span>
  <span class="json-key">"sensor_06_rf_power_hf"</span><span class="text-slate-300">: </span><span class="json-num">1500.000</span><span class="text-slate-300">,</span>
  <span class="text-slate-500 italic">... (24 more parameters parsed from JSON string)</span>
<span class="text-slate-300">}</span></pre>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 紀錄 2: 更早的快照 (APC) -->
                <div class="relative pl-12 pb-10">
                    <div class="timeline-line"></div>
                    <div class="absolute left-[15px] top-[6px] w-4 h-4 rounded-full bg-teal-100 border-[3px] border-teal-500 z-10 shadow-sm"></div>
                    <div class="absolute left-[-80px] top-[4px] text-xs font-bold font-mono text-slate-500">12:17:45</div>

                    <div class="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden opacity-90">
                        <div class="bg-slate-50 border-b border-slate-100 px-4 py-3 flex items-center justify-between">
                            <div class="flex items-center gap-3">
                                <span class="bg-teal-100 text-teal-700 px-2 py-1 rounded text-xs font-bold border border-teal-200 tracking-wider">APC SNAPSHOT</span>
                                <span class="font-mono text-sm font-bold text-slate-800">APC-LOT-0001-STEP_007-9...</span>
                            </div>
                            <div class="text-[10px] text-slate-500 font-mono flex gap-3 bg-white px-2 py-1 rounded border border-slate-200 shadow-sm">
                                <span title="Tool ID">⚙️ ETCH-LAM-01</span>
                                <span title="Lot ID">📦 LOT-0001</span>
                                <span title="Step">🏷️ STEP_007</span>
                            </div>
                        </div>

                        <div class="p-0 flex flex-col">
                            <div class="bg-slate-50/50 px-4 py-2 border-b border-slate-100 text-xs text-slate-500 flex gap-6">
                                <div><span class="text-slate-400 font-bold">algorithm:</span> <span class="font-mono font-bold text-slate-700">EWMA</span></div>
                                <div><span class="text-slate-400 font-bold">updated_by:</span> <span class="font-mono font-bold text-slate-700">apc_service</span></div>
                            </div>
                            <div class="p-4 bg-[#1e293b] rounded-b-xl overflow-x-auto text-[13px] leading-relaxed font-mono shadow-inner border-t border-slate-800">
<pre class="m-0"><span class="text-slate-400">"parameters"</span><span class="text-slate-300">: {</span>
  <span class="json-key">"etch_time_delta"</span><span class="text-slate-300">: </span><span class="json-num">+1.5</span><span class="text-slate-300">,</span>
  <span class="json-key">"rf_power_offset"</span><span class="text-slate-300">: </span><span class="json-num">0.0</span><span class="text-slate-300">,</span>
  <span class="json-key">"calculated_bias"</span><span class="text-slate-300">: </span><span class="json-num">0.0125</span>
<span class="text-slate-300">}</span></pre>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="text-center mt-6">
                    <button class="text-xs font-bold text-slate-400 hover:text-indigo-600 transition-colors bg-white border border-slate-200 rounded-full px-6 py-2 shadow-sm">
                        Load Older Records ↓
                    </button>
                </div>

            </div>
        </section>

    </main>
</body>
</html>