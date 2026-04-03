Tech Spec: AIOps Skill Builder (Intent-Driven & Result-Oriented)
Version: v3.0 (Final UX Revision)
Date: 2026-03-28
Target Audience: Frontend/Backend Engineering Team (小柯團隊)

1. 產品定位與 UX 核心理念 (Core Philosophy)
為了解決過往 RPA 或 Agent Builder「程式碼感過重、學習門檻過高」的痛點，本模組全面改版為 「意圖驅動 (Intent-Driven)」 與 「結果導向 (Result-Oriented)」 架構。

對產線工程師 (PE/QA)： 隱藏所有 Python 程式碼與 API 呼叫細節。使用者只需輸入「自然語言意圖」與「模擬機台 ID」，系統回傳直覺的「診斷結果儀表板 (Result Dashboard)」。

對 IT 管理員 (IT/Admin)： 保留底層 Python 腳本的修改權限，確保特例邏輯具備可維護性。

2. 使用者互動流程 (User Workflow)
意圖輸入 (Intent)： User 選擇 Trigger Event，並用白話文描述監控邏輯 (Prompt) 與期望處置 (Action)。

AI 提案 (Proposal)： 點擊生成後，LLM 在背景生成 Python Code，但前端僅顯示 LLM 翻譯的「白話文執行計畫 (Steps)」。

沙盒模擬 (Try-Run)： User 輸入模擬機台 ID (如 EQP-01) 進行測試。

結果視覺化 (Result)： Sandbox 執行完畢後，不顯示 Console Log，而是渲染出包含「關鍵證據、影響批號、執行動作」的結構化報告卡。

安全發佈 (Publish)： 唯有 Try-Run 成功，方可解鎖「儲存 Skill」按鈕。

3. 前後端資料合約 (Data Contracts)
為了達成上述 UX，前後端溝通需嚴格遵守以下兩個 JSON Schema：

Contract A: LLM 生成結果 (AI Proposal & Code)

當前端點擊「讓 AI 設計」時，後端 LLM 需回傳以下結構。前端僅將 proposal_steps 渲染給 User，generated_python_code 則隱藏保留。

{
  "skill_name": "OOC_Continuous_Monitor",
  "proposal_steps": [
    "呼叫系統工具取得該機台最近 5 筆紀錄。",
    "比對這 5 筆紀錄中，狀態為 'OOC' 的總次數。",
    "若 OOC 次數 ≥ 3，則自動發送 HIGH 級別警報。"
  ],
  "generated_python_code": "def process_event(event_payload):\n..."
}

Contract B: Sandbox 模擬結果 (Try-Run Result)

當前端點擊「執行模擬」時，後端 Sandbox 執行 Python 腳本後，必須強制回傳結構化的 JSON，供前端渲染 Result Dashboard，嚴禁直接回傳 Exception Stack Trace。
{
  "status": "ALARM_TRIGGERED", 
  "is_success": true,
  "dashboard_data": {
    "evidence": {
      "checked_records": 5,
      "ooc_found": 4,
      "condition_met": true
    },
    "impacted_lots": ["LOT-0002", "LOT-0003", "LOT-0004", "LOT-0005"],
    "executed_actions": [
      {
        "type": "ALARM",
        "severity": "HIGH",
        "title": "連續 OOC 警報 (發現 4 次)",
        "target": "EQP-01"
      }
    ]
  },
  "error_message": null
}

4. 前端實作原型 (HTML/UI Prototype)
前端開發請直接參考此 HTML 結構與 CSS 樣式刻畫 React/Vue 元件。此版本已實作「AI 提案卡片」與「視覺化結果儀表板」。

<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AIOps Skill Builder - 意圖與結果導向</title>
    <style>
        :root {
            --bg-base: #18181b; --bg-panel: #27272a; --bg-input: #18181b;
            --text-main: #f8fafc; --text-muted: #a1a1aa;
            --border: #3f3f46; --primary: #6366f1; --primary-hover: #4f46e5;
            --success: #10b981; --danger: #ef4444; --warning: #f59e0b;
        }
        body { margin: 0; font-family: system-ui, -apple-system, sans-serif; background: var(--bg-base); color: var(--text-main); display: flex; flex-direction: column; height: 100vh; }
        
        .header { padding: 16px 24px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; background: #1f1f22; }
        .workspace { display: flex; flex: 1; padding: 20px; gap: 20px; overflow: hidden; }
        .panel { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px; display: flex; flex-direction: column; overflow: hidden; flex: 1; }
        .panel-header { padding: 14px 20px; border-bottom: 1px solid var(--border); font-size: 14px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.2);}
        .panel-body { padding: 20px; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 20px;}
        
        label { font-size: 12px; font-weight: bold; color: var(--text-muted); margin-bottom: 8px; display: block; }
        textarea, select, input { width: 100%; background: var(--bg-input); border: 1px solid var(--border); color: white; padding: 12px; border-radius: 6px; box-sizing: border-box; font-family: inherit; font-size: 14px;}
        textarea:focus, input:focus { outline: 1px solid var(--primary); }
        
        .btn-primary { background: var(--primary); color: white; border: none; padding: 12px 20px; border-radius: 6px; cursor: pointer; font-weight: bold; transition: 0.2s; display: flex; justify-content: center; align-items: center; gap: 8px; width: 100%;}
        .btn-primary:hover { background: var(--primary-hover); }
        .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--text-main); padding: 8px 16px; border-radius: 4px; cursor: pointer;}
        
        .proposal-card { background: rgba(99, 102, 241, 0.1); border-left: 4px solid var(--primary); padding: 16px; border-radius: 0 6px 6px 0; display: none; }
        .proposal-card ul { margin: 10px 0 0 0; padding-left: 20px; color: #e2e8f0; line-height: 1.6; font-size: 14px;}
        
        .test-inputs { display: flex; gap: 12px; background: rgba(0,0,0,0.2); padding: 16px; border-radius: 6px; border: 1px dashed var(--border);}
        
        .result-dashboard { display: none; flex-direction: column; gap: 16px; border: 1px solid var(--border); border-radius: 8px; padding: 20px; background: #18181b; margin-top: 10px; animation: fadeIn 0.5s ease;}
        .result-header { display: flex; align-items: center; gap: 12px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
        .status-badge { background: rgba(239, 68, 68, 0.2); color: var(--danger); padding: 6px 12px; border-radius: 20px; font-weight: bold; font-size: 14px; border: 1px solid var(--danger); }
        .result-section-title { font-size: 12px; color: var(--text-muted); font-weight: bold; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;}
        
        .data-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
        .data-card { background: var(--bg-panel); padding: 12px; border-radius: 6px; border: 1px solid var(--border); }
        .data-value { font-size: 20px; font-weight: bold; margin-top: 4px; color: white;}
        .highlight-red { color: var(--danger); }
        
        .action-log { background: rgba(0,0,0,0.3); padding: 12px; border-radius: 6px; border-left: 3px solid var(--danger); font-size: 13px; font-family: monospace; color: #cbd5e1; display: flex; flex-direction: column; gap: 6px;}
        
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
    </style>
</head>
<body>

    <div class="header">
        <div style="font-size: 18px; font-weight: bold;">✨ 新增智能監控規則 (Skill Builder)</div>
        <div>
            <button class="btn-outline" style="margin-right: 8px;">取消</button>
            <button class="btn-primary" style="display: inline-block; width: auto; opacity: 0.5; cursor: not-allowed;" id="save-btn" onclick="alert('規則已正式部署！')">儲存並啟用 Skill</button>
        </div>
    </div>

    <div class="workspace">
        <div class="panel" style="flex: 0 0 40%;">
            <div class="panel-header">1. 告訴 AI 您的監控意圖</div>
            <div class="panel-body">
                <div>
                    <label>觸發時機 (Trigger Event)</label>
                    <select><option>SPC_OOC (管制圖異常)</option></select>
                </div>
                <div>
                    <label>監控邏輯 (請用白話文描述)</label>
                    <textarea rows="4">我想檢查這個機台最近5次的process 是否有大於3次OOC</textarea>
                </div>
                <div>
                    <label>若條件成立，希望系統做什麼？</label>
                    <select><option>發送 HIGH 級別 Alarm</option></select>
                </div>

                <button class="btn-primary" onclick="generateProposal()" id="gen-btn">✨ 讓 AI 設計監控腳本</button>

                <div class="proposal-card" id="proposal">
                    <div style="font-weight: bold; color: var(--primary); font-size: 14px; margin-bottom: 8px;">🤖 AI 已理解您的意圖，預計執行以下計畫：</div>
                    <ul>
                        <li>呼叫 <code>get_recent_processes</code> 取得該機台最近 5 筆紀錄。</li>
                        <li>比對這 5 筆紀錄中，狀態為 "OOC" 的總次數。</li>
                        <li>若 <b>OOC 次數 ≥ 3</b>，則自動呼叫 <code>trigger_alarm</code> 發送 HIGH 警報。</li>
                    </ul>
                    <div style="margin-top: 12px; font-size: 12px; color: var(--text-muted);">*底層 Python 程式碼已生成並鎖定，請在右側進行模擬測試。</div>
                </div>
            </div>
        </div>

        <div class="panel">
            <div class="panel-header">
                <span>2. 模擬執行與結果預覽 (Try-Run)</span>
                <span style="font-size: 12px; font-weight: normal; color: var(--text-muted); cursor: pointer;" onclick="alert('開啟程式碼編輯器 (Admin Only)')">⚙️ 檢視底層 Code (IT專用)</span>
            </div>
            <div class="panel-body">
                
                <div class="test-inputs" id="test-area" style="opacity: 0.5; pointer-events: none;">
                    <div style="flex: 1;"><label>模擬機台</label><input type="text" value="EQP-01"></div>
                    <div style="flex: 1;"><label>模擬時間</label><input type="text" value="2026-03-28T10:00:00Z"></div>
                    <div style="display: flex; align-items: flex-end;">
                        <button class="btn-primary" style="width: auto; padding: 12px 24px;" onclick="runSimulation()" id="run-btn">▶ 執行模擬</button>
                    </div>
                </div>

                <div id="loading-sim" style="display: none; text-align: center; padding: 40px; color: var(--primary); font-weight: bold;">
                    ⏳ 正在沙盒中拉取 EQP-01 的歷史資料並執行邏輯...
                </div>

                <div class="result-dashboard" id="result-dashboard">
                    <div class="result-header">
                        <div class="status-badge">🚨 警報條件成立 (Alarm Triggered)</div>
                        <div style="color: var(--text-muted); font-size: 14px;">測試完成時間：剛剛</div>
                    </div>

                    <div>
                        <div class="result-section-title">📊 收集到的關鍵數據 (Evidence)</div>
                        <div class="data-grid">
                            <div class="data-card"><div style="font-size: 12px; color: var(--text-muted);">檢查範圍</div><div class="data-value">5 <span style="font-size: 14px; font-weight: normal; color: var(--text-muted);">筆</span></div></div>
                            <div class="data-card" style="border-color: rgba(239, 68, 68, 0.5); background: rgba(239, 68, 68, 0.05);"><div style="font-size: 12px; color: var(--danger);">發現 OOC 次數</div><div class="data-value highlight-red">4 <span style="font-size: 14px; font-weight: normal; color: var(--text-muted);">次 (≥ 3)</span></div></div>
                        </div>
                    </div>

                    <div>
                        <div class="result-section-title">🔍 關聯異常批號 (Impacted LOTs)</div>
                        <div style="background: var(--bg-input); padding: 12px; border-radius: 6px; border: 1px solid var(--border); font-size: 13px; color: #cbd5e1; display: flex; gap: 8px; flex-wrap: wrap;">
                            <span style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 4px;">LOT-0002</span>
                            <span style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 4px;">LOT-0003</span>
                            <span style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 4px;">LOT-0004</span>
                            <span style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 4px;">LOT-0005</span>
                        </div>
                    </div>

                    <div>
                        <div class="result-section-title">⚡ 系統執行處置 (Executed Actions)</div>
                        <div class="action-log">
                            <div>[Action 1] 建立 Alarm Record 成功</div>
                            <div style="color: var(--text-muted); margin-left: 10px;">├─ Severity: HIGH</div>
                            <div style="color: var(--text-muted); margin-left: 10px;">├─ Target: EQP-01</div>
                            <div style="color: var(--text-muted); margin-left: 10px;">└─ Title: 連續 OOC 警報 (發現 4 次)</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        function generateProposal() {
            const btn = document.getElementById('gen-btn');
            btn.innerHTML = "⏳ AI 思考中...";
            setTimeout(() => {
                btn.style.display = 'none';
                document.getElementById('proposal').style.display = 'block';
                const testArea = document.getElementById('test-area');
                testArea.style.opacity = '1';
                testArea.style.pointerEvents = 'auto';
            }, 1000);
        }

        function runSimulation() {
            const runBtn = document.getElementById('run-btn');
            runBtn.innerHTML = "執行中...";
            runBtn.style.opacity = '0.7';
            document.getElementById('result-dashboard').style.display = 'none';
            document.getElementById('loading-sim').style.display = 'block';

            setTimeout(() => {
                document.getElementById('loading-sim').style.display = 'none';
                document.getElementById('result-dashboard').style.display = 'flex';
                runBtn.innerHTML = "▶ 重新模擬";
                runBtn.style.opacity = '1';
                
                const saveBtn = document.getElementById('save-btn');
                saveBtn.style.opacity = '1';
                saveBtn.style.cursor = 'pointer';
            }, 1500);
        }
    </script>
</body>
</html>

Gemini 說了
這是一份為你量身打造的 AIOps Skill Builder (意圖驅動版) - Product & Tech Spec。

這份規格書完美封裝了你這幾次架構推翻與 UX 收斂的精華。它清楚定義了「前端該怎麼畫」、「後端該怎麼傳資料」，以及「LLM 與 Sandbox 的職責分工」。你可以直接整包複製，貼到你們的 Jira、Confluence 或 Notion 交給小柯團隊開工！

Tech Spec: AIOps Skill Builder (Intent-Driven & Result-Oriented)
Version: v3.0 (Final UX Revision)
Date: 2026-03-28
Target Audience: Frontend/Backend Engineering Team (小柯團隊)

1. 產品定位與 UX 核心理念 (Core Philosophy)
為了解決過往 RPA 或 Agent Builder「程式碼感過重、學習門檻過高」的痛點，本模組全面改版為 「意圖驅動 (Intent-Driven)」 與 「結果導向 (Result-Oriented)」 架構。

對產線工程師 (PE/QA)： 隱藏所有 Python 程式碼與 API 呼叫細節。使用者只需輸入「自然語言意圖」與「模擬機台 ID」，系統回傳直覺的「診斷結果儀表板 (Result Dashboard)」。

對 IT 管理員 (IT/Admin)： 保留底層 Python 腳本的修改權限，確保特例邏輯具備可維護性。

2. 使用者互動流程 (User Workflow)
意圖輸入 (Intent)： User 選擇 Trigger Event，並用白話文描述監控邏輯 (Prompt) 與期望處置 (Action)。

AI 提案 (Proposal)： 點擊生成後，LLM 在背景生成 Python Code，但前端僅顯示 LLM 翻譯的「白話文執行計畫 (Steps)」。

沙盒模擬 (Try-Run)： User 輸入模擬機台 ID (如 EQP-01) 進行測試。

結果視覺化 (Result)： Sandbox 執行完畢後，不顯示 Console Log，而是渲染出包含「關鍵證據、影響批號、執行動作」的結構化報告卡。

安全發佈 (Publish)： 唯有 Try-Run 成功，方可解鎖「儲存 Skill」按鈕。

3. 前後端資料合約 (Data Contracts)
為了達成上述 UX，前後端溝通需嚴格遵守以下兩個 JSON Schema：

Contract A: LLM 生成結果 (AI Proposal & Code)

當前端點擊「讓 AI 設計」時，後端 LLM 需回傳以下結構。前端僅將 proposal_steps 渲染給 User，generated_python_code 則隱藏保留。

JSON
{
  "skill_name": "OOC_Continuous_Monitor",
  "proposal_steps": [
    "呼叫系統工具取得該機台最近 5 筆紀錄。",
    "比對這 5 筆紀錄中，狀態為 'OOC' 的總次數。",
    "若 OOC 次數 ≥ 3，則自動發送 HIGH 級別警報。"
  ],
  "generated_python_code": "def process_event(event_payload):\n..."
}
Contract B: Sandbox 模擬結果 (Try-Run Result)

當前端點擊「執行模擬」時，後端 Sandbox 執行 Python 腳本後，必須強制回傳結構化的 JSON，供前端渲染 Result Dashboard，嚴禁直接回傳 Exception Stack Trace。

JSON
{
  "status": "ALARM_TRIGGERED", 
  "is_success": true,
  "dashboard_data": {
    "evidence": {
      "checked_records": 5,
      "ooc_found": 4,
      "condition_met": true
    },
    "impacted_lots": ["LOT-0002", "LOT-0003", "LOT-0004", "LOT-0005"],
    "executed_actions": [
      {
        "type": "ALARM",
        "severity": "HIGH",
        "title": "連續 OOC 警報 (發現 4 次)",
        "target": "EQP-01"
      }
    ]
  },
  "error_message": null
}
4. 前端實作原型 (HTML/UI Prototype)
前端開發請直接參考此 HTML 結構與 CSS 樣式刻畫 React/Vue 元件。此版本已實作「AI 提案卡片」與「視覺化結果儀表板」。

HTML
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AIOps Skill Builder - 意圖與結果導向</title>
    <style>
        :root {
            --bg-base: #18181b; --bg-panel: #27272a; --bg-input: #18181b;
            --text-main: #f8fafc; --text-muted: #a1a1aa;
            --border: #3f3f46; --primary: #6366f1; --primary-hover: #4f46e5;
            --success: #10b981; --danger: #ef4444; --warning: #f59e0b;
        }
        body { margin: 0; font-family: system-ui, -apple-system, sans-serif; background: var(--bg-base); color: var(--text-main); display: flex; flex-direction: column; height: 100vh; }
        
        .header { padding: 16px 24px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; background: #1f1f22; }
        .workspace { display: flex; flex: 1; padding: 20px; gap: 20px; overflow: hidden; }
        .panel { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px; display: flex; flex-direction: column; overflow: hidden; flex: 1; }
        .panel-header { padding: 14px 20px; border-bottom: 1px solid var(--border); font-size: 14px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.2);}
        .panel-body { padding: 20px; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 20px;}
        
        label { font-size: 12px; font-weight: bold; color: var(--text-muted); margin-bottom: 8px; display: block; }
        textarea, select, input { width: 100%; background: var(--bg-input); border: 1px solid var(--border); color: white; padding: 12px; border-radius: 6px; box-sizing: border-box; font-family: inherit; font-size: 14px;}
        textarea:focus, input:focus { outline: 1px solid var(--primary); }
        
        .btn-primary { background: var(--primary); color: white; border: none; padding: 12px 20px; border-radius: 6px; cursor: pointer; font-weight: bold; transition: 0.2s; display: flex; justify-content: center; align-items: center; gap: 8px; width: 100%;}
        .btn-primary:hover { background: var(--primary-hover); }
        .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--text-main); padding: 8px 16px; border-radius: 4px; cursor: pointer;}
        
        .proposal-card { background: rgba(99, 102, 241, 0.1); border-left: 4px solid var(--primary); padding: 16px; border-radius: 0 6px 6px 0; display: none; }
        .proposal-card ul { margin: 10px 0 0 0; padding-left: 20px; color: #e2e8f0; line-height: 1.6; font-size: 14px;}
        
        .test-inputs { display: flex; gap: 12px; background: rgba(0,0,0,0.2); padding: 16px; border-radius: 6px; border: 1px dashed var(--border);}
        
        .result-dashboard { display: none; flex-direction: column; gap: 16px; border: 1px solid var(--border); border-radius: 8px; padding: 20px; background: #18181b; margin-top: 10px; animation: fadeIn 0.5s ease;}
        .result-header { display: flex; align-items: center; gap: 12px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
        .status-badge { background: rgba(239, 68, 68, 0.2); color: var(--danger); padding: 6px 12px; border-radius: 20px; font-weight: bold; font-size: 14px; border: 1px solid var(--danger); }
        .result-section-title { font-size: 12px; color: var(--text-muted); font-weight: bold; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;}
        
        .data-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
        .data-card { background: var(--bg-panel); padding: 12px; border-radius: 6px; border: 1px solid var(--border); }
        .data-value { font-size: 20px; font-weight: bold; margin-top: 4px; color: white;}
        .highlight-red { color: var(--danger); }
        
        .action-log { background: rgba(0,0,0,0.3); padding: 12px; border-radius: 6px; border-left: 3px solid var(--danger); font-size: 13px; font-family: monospace; color: #cbd5e1; display: flex; flex-direction: column; gap: 6px;}
        
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
    </style>
</head>
<body>

    <div class="header">
        <div style="font-size: 18px; font-weight: bold;">✨ 新增智能監控規則 (Skill Builder)</div>
        <div>
            <button class="btn-outline" style="margin-right: 8px;">取消</button>
            <button class="btn-primary" style="display: inline-block; width: auto; opacity: 0.5; cursor: not-allowed;" id="save-btn" onclick="alert('規則已正式部署！')">儲存並啟用 Skill</button>
        </div>
    </div>

    <div class="workspace">
        <div class="panel" style="flex: 0 0 40%;">
            <div class="panel-header">1. 告訴 AI 您的監控意圖</div>
            <div class="panel-body">
                <div>
                    <label>觸發時機 (Trigger Event)</label>
                    <select><option>SPC_OOC (管制圖異常)</option></select>
                </div>
                <div>
                    <label>監控邏輯 (請用白話文描述)</label>
                    <textarea rows="4">我想檢查這個機台最近5次的process 是否有大於3次OOC</textarea>
                </div>
                <div>
                    <label>若條件成立，希望系統做什麼？</label>
                    <select><option>發送 HIGH 級別 Alarm</option></select>
                </div>

                <button class="btn-primary" onclick="generateProposal()" id="gen-btn">✨ 讓 AI 設計監控腳本</button>

                <div class="proposal-card" id="proposal">
                    <div style="font-weight: bold; color: var(--primary); font-size: 14px; margin-bottom: 8px;">🤖 AI 已理解您的意圖，預計執行以下計畫：</div>
                    <ul>
                        <li>呼叫 <code>get_recent_processes</code> 取得該機台最近 5 筆紀錄。</li>
                        <li>比對這 5 筆紀錄中，狀態為 "OOC" 的總次數。</li>
                        <li>若 <b>OOC 次數 ≥ 3</b>，則自動呼叫 <code>trigger_alarm</code> 發送 HIGH 警報。</li>
                    </ul>
                    <div style="margin-top: 12px; font-size: 12px; color: var(--text-muted);">*底層 Python 程式碼已生成並鎖定，請在右側進行模擬測試。</div>
                </div>
            </div>
        </div>

        <div class="panel">
            <div class="panel-header">
                <span>2. 模擬執行與結果預覽 (Try-Run)</span>
                <span style="font-size: 12px; font-weight: normal; color: var(--text-muted); cursor: pointer;" onclick="alert('開啟程式碼編輯器 (Admin Only)')">⚙️ 檢視底層 Code (IT專用)</span>
            </div>
            <div class="panel-body">
                
                <div class="test-inputs" id="test-area" style="opacity: 0.5; pointer-events: none;">
                    <div style="flex: 1;"><label>模擬機台</label><input type="text" value="EQP-01"></div>
                    <div style="flex: 1;"><label>模擬時間</label><input type="text" value="2026-03-28T10:00:00Z"></div>
                    <div style="display: flex; align-items: flex-end;">
                        <button class="btn-primary" style="width: auto; padding: 12px 24px;" onclick="runSimulation()" id="run-btn">▶ 執行模擬</button>
                    </div>
                </div>

                <div id="loading-sim" style="display: none; text-align: center; padding: 40px; color: var(--primary); font-weight: bold;">
                    ⏳ 正在沙盒中拉取 EQP-01 的歷史資料並執行邏輯...
                </div>

                <div class="result-dashboard" id="result-dashboard">
                    <div class="result-header">
                        <div class="status-badge">🚨 警報條件成立 (Alarm Triggered)</div>
                        <div style="color: var(--text-muted); font-size: 14px;">測試完成時間：剛剛</div>
                    </div>

                    <div>
                        <div class="result-section-title">📊 收集到的關鍵數據 (Evidence)</div>
                        <div class="data-grid">
                            <div class="data-card"><div style="font-size: 12px; color: var(--text-muted);">檢查範圍</div><div class="data-value">5 <span style="font-size: 14px; font-weight: normal; color: var(--text-muted);">筆</span></div></div>
                            <div class="data-card" style="border-color: rgba(239, 68, 68, 0.5); background: rgba(239, 68, 68, 0.05);"><div style="font-size: 12px; color: var(--danger);">發現 OOC 次數</div><div class="data-value highlight-red">4 <span style="font-size: 14px; font-weight: normal; color: var(--text-muted);">次 (≥ 3)</span></div></div>
                        </div>
                    </div>

                    <div>
                        <div class="result-section-title">🔍 關聯異常批號 (Impacted LOTs)</div>
                        <div style="background: var(--bg-input); padding: 12px; border-radius: 6px; border: 1px solid var(--border); font-size: 13px; color: #cbd5e1; display: flex; gap: 8px; flex-wrap: wrap;">
                            <span style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 4px;">LOT-0002</span>
                            <span style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 4px;">LOT-0003</span>
                            <span style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 4px;">LOT-0004</span>
                            <span style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 4px;">LOT-0005</span>
                        </div>
                    </div>

                    <div>
                        <div class="result-section-title">⚡ 系統執行處置 (Executed Actions)</div>
                        <div class="action-log">
                            <div>[Action 1] 建立 Alarm Record 成功</div>
                            <div style="color: var(--text-muted); margin-left: 10px;">├─ Severity: HIGH</div>
                            <div style="color: var(--text-muted); margin-left: 10px;">├─ Target: EQP-01</div>
                            <div style="color: var(--text-muted); margin-left: 10px;">└─ Title: 連續 OOC 警報 (發現 4 次)</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        function generateProposal() {
            const btn = document.getElementById('gen-btn');
            btn.innerHTML = "⏳ AI 思考中...";
            setTimeout(() => {
                btn.style.display = 'none';
                document.getElementById('proposal').style.display = 'block';
                const testArea = document.getElementById('test-area');
                testArea.style.opacity = '1';
                testArea.style.pointerEvents = 'auto';
            }, 1000);
        }

        function runSimulation() {
            const runBtn = document.getElementById('run-btn');
            runBtn.innerHTML = "執行中...";
            runBtn.style.opacity = '0.7';
            document.getElementById('result-dashboard').style.display = 'none';
            document.getElementById('loading-sim').style.display = 'block';

            setTimeout(() => {
                document.getElementById('loading-sim').style.display = 'none';
                document.getElementById('result-dashboard').style.display = 'flex';
                runBtn.innerHTML = "▶ 重新模擬";
                runBtn.style.opacity = '1';
                
                const saveBtn = document.getElementById('save-btn');
                saveBtn.style.opacity = '1';
                saveBtn.style.cursor = 'pointer';
            }, 1500);
        }
    </script>
</body>
</html>
5. 後端實作待辦清單 (Backend Action Items)
Context Loader 掛載: LLM 進行意圖編譯前，必須將可用的 MCP Catalog Schema 動態注入 System Prompt，確保生成的 Python Code 呼叫正確的內部 API。

Sandbox 攔截器 (Mock Layer): Sandbox 環境不應發出真實的 Alarm。請實作 Mock Tools，攔截 tools.trigger_alarm() 等破壞性操作，並將其轉化為 JSON Contract 中的 executed_actions 陣列回傳給前端。

錯誤捕捉 (Error Handling): 若 Sandbox 執行 Python 時發生 Exception，需攔截錯誤並由 LLM 翻譯為白話文建議，透過 error_message 欄位傳遞給前端，嚴禁拋出原生 Stack Trace。