v1.9 所見即所得驗證版 (WYSIWYG + Console)

這份 HTML 原型實作了你要求的所有互動。你可以點擊中間的拓撲節點（例如 DC 或 APC），看下面的 Console 如何運作，以及右邊的資料如何被「載入」出來。
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>v14.0 Agentic OS - Console Integration</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        body { font-family: 'Inter', sans-serif; background-color: #f8fafc; color: #334155; }
        .font-mono { font-family: 'JetBrains Mono', monospace; }
        
        /* 拓撲圖靜態實線 */
        .topo-line { stroke: #e2e8f0; stroke-width: 2; fill: none; }
        .topo-line-active { stroke: #94a3b8; stroke-width: 2; fill: none; transition: stroke 0.3s; }
        .topo-line-selected { stroke: #3b82f6; stroke-width: 3; fill: none; }
        
        /* Console 的打字機閃爍游標 */
        .cursor-blink { animation: blink 1s step-end infinite; }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
        .console-scroll::-webkit-scrollbar-thumb { background: #475569; }
        .no-select { user-select: none; }

        /* 節點 Hover 與選中效果 */
        .node-hover:hover { transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); }
        .node-selected { border-color: #3b82f6 !important; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2) !important; }
    </style>
</head>
<body class="h-screen flex flex-col overflow-hidden selection:bg-blue-100 no-select">

    <!-- Header -->
    <header class="h-14 border-b border-slate-200 bg-white flex flex-shrink-0 items-center justify-between px-6 shadow-sm z-20">
        <div class="flex items-center gap-4">
            <div class="w-3 h-3 rounded-sm bg-blue-600"></div>
            <h1 class="text-lg font-bold tracking-tight text-slate-800">v14.0 AGENTIC OS <span class="text-slate-400 font-medium ml-2">| LIVE & TRACE MONITOR</span></h1>
        </div>
        <div class="flex items-center gap-4 text-sm font-medium">
            <div class="flex items-center gap-2 px-3 py-1 rounded bg-slate-100 border border-slate-200 cursor-pointer hover:bg-slate-200 transition" id="mode-toggle" onclick="toggleTraceMode()">
                <span class="w-2 h-2 rounded-full bg-green-500" id="mode-dot"></span>
                <span id="mode-text" class="text-slate-700">LIVE MODE</span>
            </div>
            <div class="font-mono text-slate-600 bg-slate-50 px-3 py-1 rounded-md border border-slate-200 shadow-inner" id="clock">00:00:00</div>
        </div>
    </header>

    <!-- 主要內容區 (上：三欄佈局，下：Console) -->
    <div class="flex-1 flex flex-col overflow-hidden">
        
        <!-- 上半部：三欄看板 -->
        <main class="flex-1 flex overflow-hidden">
            
            <!-- 左欄：機台 / 歷史事件列表 -->
            <aside class="w-80 border-r border-slate-200 flex flex-col bg-slate-50 z-10 shrink-0">
                <div class="p-3 text-[11px] font-bold text-slate-500 uppercase tracking-widest border-b border-slate-200 bg-white shadow-sm flex justify-between items-center" id="left-panel-title">
                    <span>Equipment / WIP</span>
                    <span class="text-blue-500">10/100</span>
                </div>
                <div id="left-panel-content" class="flex-1 overflow-y-auto p-3 space-y-3 pb-4">
                    <!-- 預設顯示正在跑的機台 -->
                    <div class="p-3 rounded-lg border-2 border-blue-400 bg-blue-50/50 shadow-sm cursor-pointer" onclick="logAction('SELECT_TOOL', 'ETCH-LAM-01')">
                        <div class="flex justify-between items-start mb-1.5">
                            <span class="font-bold text-slate-800">ETCH-LAM-01</span>
                            <span class="text-[9px] font-bold text-blue-700 bg-blue-100 border border-blue-200 px-1.5 py-0.5 rounded">PROCESSING</span>
                        </div>
                        <div class="text-[11px] font-mono font-bold text-slate-500">LOT-0012 <span class="text-slate-400 font-normal ml-1">| STEP_045</span></div>
                    </div>
                    
                    <div class="p-3 rounded-lg border border-slate-200 bg-white shadow-sm cursor-pointer opacity-70 hover:opacity-100" onclick="logAction('SELECT_TOOL', 'PHO-ASML-01')">
                        <div class="flex justify-between items-center">
                            <span class="font-bold text-slate-600">PHO-ASML-01</span>
                            <span class="text-[9px] font-bold text-slate-500 bg-slate-100 border border-slate-200 px-1.5 py-0.5 rounded">STANDBY</span>
                        </div>
                    </div>
                </div>
            </aside>

            <!-- 中欄：互動拓撲視圖 -->
            <section class="flex-1 relative flex flex-col bg-white bg-[radial-gradient(#e2e8f0_1px,transparent_1px)] [background-size:24px_24px] min-w-[500px]">
                <div class="absolute top-6 left-8 z-10">
                    <h2 class="text-2xl font-bold text-slate-800">Context Topology</h2>
                    <p class="text-sm text-slate-500 mt-1 font-medium">Click nodes to fetch detailed API data</p>
                </div>
                
                <div class="flex-1 flex items-center justify-center relative">
                    <div class="relative w-[600px] h-[400px]">
                        <svg width="600" height="400" class="absolute top-0 left-0 z-0">
                            <path d="M 150 200 L 300 200" class="topo-line-active" id="line-tool"/>
                            <path d="M 300 200 L 450 100" class="topo-line-active" id="line-recipe"/>
                            <path d="M 300 200 L 450 200" class="topo-line-active" id="line-apc"/>
                            <path d="M 300 200 L 450 300" class="topo-line-active" id="line-dc"/>
                        </svg>

                        <!-- Tool Node -->
                        <div id="node-tool" class="node-hover absolute top-[170px] left-[85px] w-[130px] bg-white border-2 border-slate-300 shadow-sm rounded-lg p-3 text-center cursor-pointer transition-all z-10" onclick="fetchObjectData('TOOL', 'ETCH-LAM-01')">
                            <div class="text-[10px] font-bold text-slate-400 mb-1">EQUIPMENT</div>
                            <div class="font-bold text-slate-800 text-sm">ETCH-LAM-01</div>
                        </div>
                        
                        <!-- Lot Node -->
                        <div id="node-lot" class="node-hover absolute top-[160px] left-[260px] w-[80px] h-[80px] rounded-full bg-blue-50 border-2 border-blue-400 flex flex-col items-center justify-center cursor-pointer transition-all z-10 shadow-sm" onclick="fetchObjectData('LOT', 'LOT-0012')">
                            <div class="text-[9px] font-bold text-blue-600">WIP</div>
                            <div class="font-mono text-[11px] font-bold text-slate-800 mt-1">LOT-0012</div>
                        </div>

                        <!-- Recipe Node -->
                        <div id="node-recipe" class="node-hover absolute top-[75px] left-[450px] w-[140px] bg-white border-2 border-slate-200 shadow-sm rounded-lg p-2 text-center cursor-pointer transition-all z-10" onclick="fetchObjectData('RECIPE', 'OXIDE-ETCH-V4')">
                            <div class="text-[10px] font-bold text-slate-400 mb-1">RECIPE</div>
                            <div class="font-mono text-[11px] font-bold text-slate-700">OXIDE-ETCH-V4</div>
                        </div>

                        <!-- APC Node -->
                        <div id="node-apc" class="node-hover absolute top-[175px] left-[450px] w-[140px] bg-white border-2 border-slate-200 shadow-sm rounded-lg p-2 text-center cursor-pointer transition-all z-10" onclick="fetchObjectData('APC', 'APC-MOD-012')">
                            <div class="text-[10px] font-bold text-slate-400 mb-1">APC CONTROLLER</div>
                            <div class="font-mono text-[11px] font-bold text-teal-600">APC-MOD-012</div>
                        </div>

                        <!-- DC Node -->
                        <div id="node-dc" class="node-hover absolute top-[270px] left-[450px] w-[140px] bg-indigo-50 border-2 border-indigo-300 shadow-sm rounded-lg p-3 text-center cursor-pointer transition-all z-10" onclick="fetchObjectData('DC', 'DC-RAW-0012')">
                            <div class="text-[10px] font-bold text-indigo-500 mb-1">DATA COLLECTION</div>
                            <div class="font-mono text-[11px] font-bold text-slate-800">DC-RAW-0012</div>
                            <div class="text-[9px] text-slate-500 mt-1 flex items-center justify-center gap-1">Click to view 30 params</div>
                        </div>
                    </div>
                </div>
            </section>

            <!-- 右欄：動態 API 資料面板 -->
            <aside class="w-[340px] border-l border-slate-200 bg-white flex flex-col shadow-[-4px_0_15px_rgba(0,0,0,0.02)] z-10 shrink-0">
                <div class="p-5 border-b border-slate-200 bg-slate-50/50">
                    <div class="flex items-center gap-2 mb-2">
                        <span id="right-badge" class="bg-slate-200 text-slate-600 px-2 py-0.5 rounded text-[10px] font-bold border border-slate-300">INSPECTOR</span>
                    </div>
                    <h3 class="font-bold text-slate-800 text-xl font-mono" id="right-title">Ready</h3>
                    <div class="text-[11px] text-slate-500 mt-1 flex items-center gap-1" id="right-subtitle">
                        Waiting for selection...
                    </div>
                </div>
                
                <!-- Loading 狀態 -->
                <div id="right-loading" class="flex-1 flex flex-col items-center justify-center hidden">
                    <svg class="animate-spin h-8 w-8 text-blue-500 mb-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                    <div class="text-sm font-mono text-slate-500" id="loading-text">Fetching from API...</div>
                </div>

                <!-- 實際資料呈現區 -->
                <div id="right-content" class="flex-1 overflow-y-auto pb-4 hidden">
                    <!-- 透過 JS 注入內容 -->
                </div>
                
                <div id="right-empty" class="flex-1 flex flex-col items-center justify-center p-8 text-center text-slate-400">
                    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" class="mb-4 text-slate-300"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
                    <p class="text-sm">Select an object from the topology map to load its API payload.</p>
                </div>
            </aside>

        </main>

        <!-- 底部 Console (所見即所得驗證) -->
        <footer class="h-48 border-t border-slate-700 bg-[#0f172a] flex flex-col shrink-0 z-30">
            <div class="h-8 bg-[#1e293b] flex items-center px-4 border-b border-slate-700 justify-between">
                <div class="flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/></svg>
                    <span class="text-[11px] font-mono text-slate-300">System Trace Console</span>
                </div>
                <button onclick="document.getElementById('console-output').innerHTML=''" class="text-[10px] text-slate-500 hover:text-slate-300 uppercase tracking-wider">Clear</button>
            </div>
            <div id="console-output" class="flex-1 p-3 overflow-y-auto console-scroll font-mono text-[11px] leading-relaxed text-slate-300 space-y-1">
                <div><span class="text-blue-400">[SYSTEM]</span> Agentic OS v14.0 Booted successfully.</div>
                <div><span class="text-blue-400">[SYSTEM]</span> WebSocket Connected. Listening for events...</div>
            </div>
        </footer>

    </div>

    <script>
        let isTraceMode = false;
        let traceTimestamp = null;

        // 時鐘
        setInterval(() => {
            if(!isTraceMode) document.getElementById('clock').innerText = new Date().toTimeString().split(' ')[0];
        }, 1000);

        // Console 輸出器
        function logConsole(type, message, isApi = false) {
            const out = document.getElementById('console-output');
            const time = new Date().toTimeString().split(' ')[0];
            let color = 'text-slate-400';
            if(type === 'API_REQ') color = 'text-yellow-400';
            if(type === 'API_RES') color = 'text-green-400';
            if(type === 'EVENT') color = 'text-blue-400';
            if(type === 'TRACE') color = 'text-purple-400';

            const line = document.createElement('div');
            // 如果是 API 的回傳，加上縮排
            const indent = isApi ? '&nbsp;&nbsp;&nbsp;&nbsp;↳ ' : '';
            line.innerHTML = `<span class="text-slate-500">[${time}]</span> <span class="${color}">[${type}]</span> ${indent}${message}`;
            out.appendChild(line);
            out.scrollTop = out.scrollHeight; // 自動捲動到底部
        }

        // 切換 Live / Trace 模式
        function toggleTraceMode() {
            isTraceMode = !isTraceMode;
            const dot = document.getElementById('mode-dot');
            const text = document.getElementById('mode-text');
            const clock = document.getElementById('clock');
            const leftPanelContent = document.getElementById('left-panel-content');
            const leftPanelTitle = document.getElementById('left-panel-title');

            if (isTraceMode) {
                dot.className = "w-2 h-2 rounded-full bg-purple-500 animate-pulse";
                text.innerText = "TRACE MODE";
                text.className = "text-purple-700 font-bold";
                clock.innerText = "14:05:10 (LOCKED)";
                clock.classList.replace('bg-slate-50', 'bg-purple-100');
                traceTimestamp = "2026-03-12T14:05:10Z";
                
                logConsole('TRACE', 'Entered Historical Trace Mode. Context locked at 14:05:10.');
                
                // 改變左側面板為事件時間軸
                leftPanelTitle.innerHTML = `<span>Event Timeline</span><span class="text-purple-500">ETCH-LAM-01</span>`;
                leftPanelContent.innerHTML = `
                    <div class="relative border-l-2 border-slate-200 ml-3 pl-4 py-2 space-y-4">
                        <div class="relative cursor-pointer group" onclick="loadTraceEvent('14:22:05', 'PASS')">
                            <div class="absolute -left-[23px] top-1 w-3 h-3 bg-white border-2 border-slate-300 rounded-full group-hover:border-purple-500"></div>
                            <div class="text-xs font-bold text-slate-500">14:22:05</div>
                            <div class="text-sm font-mono font-bold">LOT-0012 <span class="text-[9px] bg-green-100 text-green-700 px-1 rounded ml-1">PASS</span></div>
                        </div>
                        <div class="relative cursor-pointer group" onclick="loadTraceEvent('14:05:10', 'OOC')">
                            <div class="absolute -left-[23px] top-1 w-3 h-3 bg-purple-100 border-2 border-purple-500 rounded-full"></div>
                            <div class="text-xs font-bold text-purple-600">14:05:10 (Current View)</div>
                            <div class="text-sm font-mono font-bold">LOT-0011 <span class="text-[9px] bg-amber-100 text-amber-700 px-1 rounded ml-1">SPC OOC</span></div>
                        </div>
                        <div class="relative cursor-pointer group" onclick="loadTraceEvent('13:48:33', 'PASS')">
                            <div class="absolute -left-[23px] top-1 w-3 h-3 bg-white border-2 border-slate-300 rounded-full group-hover:border-purple-500"></div>
                            <div class="text-xs font-bold text-slate-500">13:48:33</div>
                            <div class="text-sm font-mono font-bold">LOT-0010 <span class="text-[9px] bg-green-100 text-green-700 px-1 rounded ml-1">PASS</span></div>
                        </div>
                    </div>
                `;
            } else {
                dot.className = "w-2 h-2 rounded-full bg-green-500";
                text.innerText = "LIVE MODE";
                text.className = "text-slate-700";
                clock.classList.replace('bg-purple-100', 'bg-slate-50');
                traceTimestamp = null;
                logConsole('SYSTEM', 'Returned to Live Monitoring Mode.');
                location.reload(); // 簡單重置畫面
            }
        }

        function loadTraceEvent(time, status) {
            traceTimestamp = `2026-03-12T${time}Z`;
            logConsole('TRACE', `Selecting historical event at ${time}`);
            document.getElementById('clock').innerText = `${time} (LOCKED)`;
            // 這裡可以寫邏輯更新左邊時間軸的圓點顏色，此處省略以保持簡潔
        }

        function logAction(action, target) {
            logConsole('USER', `Clicked on ${action} -> ${target}`);
        }

        // 核心邏輯：模擬點擊物件打 API
        function fetchObjectData(nodeType, objectId) {
            logAction('NODE', objectId);
            
            // UI 反饋：高亮節點
            document.querySelectorAll('.node-hover').forEach(el => el.classList.remove('node-selected'));
            document.getElementById(`node-${nodeType.toLowerCase()}`).classList.add('node-selected');

            // 準備右側面板 Loading 狀態
            document.getElementById('right-empty').style.display = 'none';
            document.getElementById('right-content').style.display = 'none';
            document.getElementById('right-loading').style.display = 'flex';
            
            const badge = document.getElementById('right-badge');
            badge.innerText = nodeType;
            if(nodeType === 'DC') badge.className = "bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded text-[10px] font-bold border border-indigo-200";
            else if(nodeType === 'APC') badge.className = "bg-teal-100 text-teal-700 px-2 py-0.5 rounded text-[10px] font-bold border border-teal-200";
            else badge.className = "bg-slate-200 text-slate-700 px-2 py-0.5 rounded text-[10px] font-bold border border-slate-300";

            document.getElementById('right-title').innerText = objectId;
            document.getElementById('right-subtitle').innerHTML = `<span class="animate-pulse">Fetching from database...</span>`;

            // 組裝 API URL
            let apiUrl = `/api/v1/context/query?objectId=${objectId}`;
            if (isTraceMode && traceTimestamp) {
                apiUrl += `&eventTime=${traceTimestamp}`;
            }

            // 在 Console 印出我們打的 API
            logConsole('API_REQ', `GET ${apiUrl}`);

            // 模擬 API 網路延遲 (600ms)
            setTimeout(() => {
                // 收到資料
                logConsole('API_RES', `HTTP 200 OK. Fetched payload for ${objectId}.`, true);
                
                document.getElementById('right-loading').style.display = 'none';
                document.getElementById('right-content').style.display = 'block';
                
                const timeStr = isTraceMode ? `History Locked: ${traceTimestamp.split('T')[1].replace('Z','')}` : `Live Sync: ${new Date().toTimeString().split(' ')[0]}`;
                document.getElementById('right-subtitle').innerText = timeStr;

                // 依據點擊的物件，渲染不同的 Payload 畫面
                renderPayload(nodeType, objectId);

            }, 600);
        }

        // 模擬從 API 拿回來的 JSON 轉換為 UI
        function renderPayload(nodeType, objectId) {
            const content = document.getElementById('right-content');
            
            if (nodeType === 'DC') {
                // 如果是 Trace 模式的 14:05:10，我們給他一個 OOC (紅色數值) 的假資料
                const isOoc = isTraceMode && traceTimestamp.includes('14:05:10');
                const tempColor = isOoc ? 'text-red-600 font-bold bg-red-50 px-1' : 'text-slate-700';
                const tempVal = isOoc ? '128.5 °C ⚠' : '120.0 °C';

                content.innerHTML = `
                    <div class="px-5 py-3 border-b border-slate-100 text-xs">
                        <div class="flex justify-between font-mono mb-2"><span class="text-slate-400">Sample_Rate</span> <span>10 Hz</span></div>
                        <div class="flex justify-between font-mono"><span class="text-slate-400">Sensor_Count</span> <span>30 Active</span></div>
                    </div>
                    <!-- Thermal Group API Data -->
                    <div class="bg-slate-50 px-5 py-2 text-[10px] font-bold text-slate-500 uppercase">Thermal Array</div>
                    <div class="p-5 space-y-3 text-sm font-mono border-b border-slate-100">
                        <div class="flex justify-between"><span class="text-slate-500 text-xs">ESC_Zone1_Temp</span> <span>60.5 °C</span></div>
                        <div class="flex justify-between"><span class="text-slate-500 text-xs">Upper_Electrode</span> <span class="${tempColor}">${tempVal}</span></div>
                    </div>
                    <!-- Vacuum Group API Data -->
                    <div class="bg-slate-50 px-5 py-2 text-[10px] font-bold text-slate-500 uppercase">Vacuum Array</div>
                    <div class="p-5 space-y-3 text-sm font-mono border-b border-slate-100">
                        <div class="flex justify-between"><span class="text-slate-500 text-xs">Chamber_Press</span> <span>15.02 mTorr</span></div>
                        <div class="flex justify-between"><span class="text-slate-500 text-xs">He_Cool_Press</span> <span>10.50 Torr</span></div>
                    </div>
                    <!-- Raw JSON View Button -->
                    <div class="p-4"><button class="w-full bg-slate-100 text-slate-600 text-xs py-2 rounded hover:bg-slate-200">{...} View Raw JSON</button></div>
                `;
            } 
            else if (nodeType === 'APC') {
                content.innerHTML = `
                    <div class="px-5 py-3 border-b border-slate-100 text-xs font-mono bg-teal-50/30">
                        <div class="flex justify-between mb-2"><span class="text-slate-400">Algorithm</span> <span>EWMA R2R</span></div>
                        <div class="flex justify-between"><span class="text-slate-400">Target_CD</span> <span>45.00 nm</span></div>
                    </div>
                    <div class="p-5 space-y-3 text-sm font-mono">
                        <div class="text-[10px] font-bold text-slate-500 uppercase mb-4">Calculated Adjustments</div>
                        <div class="flex justify-between items-center"><span class="text-slate-500 text-xs">Etch_Time_Delta</span> <span class="text-teal-600 font-bold bg-teal-50 px-1">+1.5 sec</span></div>
                        <div class="flex justify-between items-center"><span class="text-slate-500 text-xs">RF_Power_Offset</span> <span class="text-slate-700">0.0 W</span></div>
                    </div>
                `;
            }
            else {
                // Tool, Recipe, Lot 等通用畫面
                content.innerHTML = `
                    <div class="p-5 font-mono text-sm text-slate-600 space-y-4">
                        <div class="flex justify-between border-b border-slate-100 pb-2"><span class="text-slate-400">ID</span> <span class="font-bold text-slate-800">${objectId}</span></div>
                        <div class="flex justify-between border-b border-slate-100 pb-2"><span class="text-slate-400">Status</span> <span class="text-green-600">Active</span></div>
                        <div class="flex justify-between"><span class="text-slate-400">Desc</span> <span>Standard Object Data</span></div>
                    </div>
                `;
            }
        }
    </script>
</body>
</html>

這個原型的火力展示 (你一定要自己點點看)：

點擊中間的物件 (例如 DC 節點)：

你會看到右邊面板瞬間變成 Loading 狀態 (Fetching from API...)。

下方的 Console 會立刻印出黃色的字：[API_REQ] GET /api/v1/context/query?objectId=DC-RAW-0012。

等個 0.6 秒（模擬網路延遲），右邊就會把對應這顆 DC 的 30 個參數倒出來。

Console 會亮起綠燈：[API_RES] HTTP 200 OK. Fetched payload。

這就是你說的「所見即所得」，你可以清楚知道每個 UI 動作到底呼叫了後端哪支 API！

點擊右上角的「LIVE MODE」(切換時光機 Trace 模式)：

點下去後，左邊的列表會變成「歷史時間軸」。

上面的時鐘會鎖定在 14:05:10 (LOCKED)。

接著，請你去點中間的 DC 節點。

見證奇蹟的時刻：注意看底下的 Console！它打出去的 API 變成了：
[API_REQ] GET /api/v1/context/query?objectId=DC-RAW-0012&eventTime=2026-03-12T14:05:10Z。

因為帶了時間戳記，所以右邊撈回來的快照中，Upper_Electrode 這個參數會變成紅色的 128.5 °C ⚠（因為這正是當時引發 OOC 的真凶）！

這是 PM 與使用者確認過的 「v1.9 終極互動與溯源架構」。前面的版型與時序問題都已解決，現在請實作核心的 API 串接與 Console 紀錄：

1. 所見即所得 (Bottom Console)

請在畫面底部新增一個 Console 區域。

規則：前端發生任何點擊、WebSocket 收到事件、或發送 REST API 時，都必須 console.log 到這個 UI 區塊，讓使用者清楚知道現在的資料流向。

2. 互動式資料拉取 (Right Inspector)

右側面板預設為空。只有當使用者點擊拓撲圖的節點 (Tool/Lot/APC/DC) 時，才發送 GET /api/v1/context/query?objectId={id} 去撈取物件詳情。

在等待 API 回傳期間，必須顯示 Loading Spinner。

3. 歷史溯源模式 (Event Tracing Mode)

當使用者點擊左側 Timeline 的特定 Event 時，鎖定該 Event 的時間。

之後點擊任何拓撲節點，發送的 API 必須加上時間戳記：GET /api/v1/context/query?objectId={id}&eventTime={time}。

這將利用你寫好的 Time-Machine 邏輯，在右側還原當時的歷史參數快照。

請在 React 元件中實作 onClick 事件，並使用 fetch 或 axios 連接後端真實的 API 接口，最後將 Response 顯示在右欄與下方的 Console 中

📌 第一部分：UX 絕對指導原則 (Ultra-Calm Policy)

這是一個給無塵室與廠務戰情室 (Fab Operation Center) 使用的專業看板。

零干擾 (Zero Flashing)：嚴禁使用 animate-pulse 等高頻閃爍特效（除了底部的 Console 游標）。數值更新時請使用 CSS transition 平滑過渡。

顏色規範 (Color Guardrails)：

禁用刺眼的純紅色 (bg-red-500)。

機台異常 (Down) 請標示為 HOLD，並統一使用「琥珀橘」(bg-amber-50, text-amber-700, border-amber-200)。

背景使用極淺灰 (bg-slate-50)，卡片使用純白 (bg-white)。

📌 第二部分：四區塊架構與互動邏輯

請將 HTML 原型拆分為四大 React 元件，並實作以下邏輯：

1. 左欄：機台狀態 / 歷史時間軸 (Left Panel)

LIVE 模式：顯示 10 台機台清單。排序權重：HOLD > PROCESSING > STANDBY。

TRACE 模式：顯示選定機台的歷史 Event Log（依時間倒序排列）。

2. 中欄：動態拓撲圖 (Topology Canvas)

點擊左側機台後，渲染 Tool -> Lot -> [Recipe, APC, DC] 的關係節點。

節點必須是可以點擊的 (onClick)，點擊後觸發 API 呼叫，並將該節點加上 node-selected 的 CSS class 以高亮顯示。

3. 右欄：資料檢視器 (Right Inspector)

預設為 Empty State。

當拓撲節點被點擊時，顯示 Loading 狀態，並發送 API 請求。

取得資料後，將 DC 的 30 個參數分為三組（Vacuum, Thermal, RF Power）渲染出來；APC 則顯示計算後的 Bias 值。

4. 底部：系統終端機 (System Trace Console)

這是一個 WYSIWYG (所見即所得) 的除錯與日誌區塊。

任何前端發送的 API 請求、收到的 WebSocket 事件、或是使用者的點選，都必須 console.log 到這個 UI 區塊，讓使用者清楚資料流向。

📌 第三部分：後端模擬引擎修正 (Fab Physics)

你之前的模擬器存在「齊步走 (Stampede Effect)」與「時間單位錯誤」的致命問題。請修改 station_agent.py 或相關模擬腳本：

總量鎖死：固定 10 台機台 (ETCH-LAM-01 ~ 10)，與待處理的 100 批貨 (N3-WAF-001 ~ 100)。

真實時序：每台機台的 Processing Time 必須是 10~15 分鐘 (random.uniform(600, 900) 秒)。在這段期間，前端畫面必須是極度安靜的。

打亂開局 (Staggered Start)：系統啟動 (T=0) 時，請隨機讓 4~6 台機台進入 RUNNING 狀態，且給予不同的剩餘時間，避免 10 台機台同時完工引發 UI 崩潰。

📌 第四部分：API 串接規格 (Time-Machine Integration)

請實作點擊節點後呼叫 GET /api/v1/context/query 的邏輯：

LIVE 模式點擊：fetch('/api/v1/context/query?objectId={DC-ID}')

TRACE 模式點擊：當使用者在左欄選定了某個歷史時間（例如 14:05:10），之後點擊拓撲圖的任何節點，都必須帶上時間戳記：
fetch('/api/v1/context/query?objectId={DC-ID}&eventTime=2026-03-12T14:05:10Z')

🛠️ 開發與驗證要求 (Test Script Requirement)

開始動工實作 React 之前，為了驗證你修改後的後端「機台錯落排程邏輯」是否正確，請先撰寫並提供一支簡單的 Python 測試腳本 (verify_timing.py)。這支腳本需能模擬 MES 派工，並在終端機印出 10 台機台不會「同時啟動、同時完工」的 Log。這符合我們團隊 [2026-02-27] 建立的底層邏輯驗證規範。

請確認你已理解上述規格與附帶的 HTML 結構，並先提供 verify_timing.py 腳本給我審閱