核心邏輯設計

Object-Oriented View: 以「機台」為父節點，掛載「當前批次 (Lot)」與「對應工具組 (APC/DC/SPC)」。

Event-Driven UI: 接受格式如下的 Event 並局部更新 UI：{ "machine_id": "EQP-01", "event": "LOT_START", "data": { "lot_id": "L123", "recipe": "RE-99" } }
Status Indicators: 透過顏色（綠/藍/橘/紅）即時反應 v14.0 五階段日誌 的進度。

2. 前端實作代碼 (Mock-up)

這個元件模擬了 10 個機台同時運行的狀況，並展示了你要求的 APC/DC/SPC 對接細節。

import React, { useState, useEffect } from 'react';
import { Cpu, Box, Activity, ShieldCheck, BarChart3, Settings } from 'lucide-react';

const MachineCard = ({ machine }) => {
  return (
    <div className="bg-slate-900 border border-slate-700 p-4 rounded-xl shadow-lg hover:border-blue-500 transition-all">
      <div className="flex justify-between items-center mb-4">
        <div className="flex items-center gap-2">
          <Cpu className="text-blue-400" size={20} />
          <h3 className="text-white font-bold">{machine.id}</h3>
        </div>
        <span className={`px-2 py-1 rounded text-xs ${machine.status === 'Running' ? 'bg-green-500/20 text-green-400' : 'bg-yellow-500/20 text-yellow-400'}`}>
          {machine.status}
        </span>
      </div>

      {/* 處理中的 Lot 資訊 */}
      <div className="space-y-3">
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-400 flex items-center gap-1"><Box size={14}/> Lot:</span>
          <span className="text-white font-mono">{machine.current_lot || 'Idle'}</span>
        </div>
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-400 flex items-center gap-1"><Settings size={14}/> Recipe:</span>
          <span className="text-blue-300 font-mono">{machine.recipe || '-'}</span>
        </div>

        {/* 自動化系統狀態 (APC/DC/SPC) */}
        <div className="grid grid-cols-3 gap-2 mt-4 pt-4 border-t border-slate-800">
          <div className="flex flex-col items-center">
            <ShieldCheck size={16} className={machine.apc ? "text-cyan-400" : "text-slate-600"} />
            <span className="text-[10px] mt-1 text-slate-500 font-bold">APC</span>
          </div>
          <div className="flex flex-col items-center">
            <Activity size={16} className={machine.dc ? "text-purple-400" : "text-slate-600"} />
            <span className="text-[10px] mt-1 text-slate-500 font-bold">DC</span>
          </div>
          <div className="flex flex-col items-center">
            <BarChart3 size={16} className={machine.spc ? "text-orange-400" : "text-slate-600"} />
            <span className="text-[10px] mt-1 text-slate-500 font-bold">SPC</span>
          </div>
        </div>
      </div>
    </div>
  );
};

const FactoryDashboard = () => {
  const [machines, setMachines] = useState(
    Array.from({ length: 10 }, (_, i) => ({
      id: `EQP-0${i + 1}`,
      status: 'Idle',
      current_lot: null,
      recipe: null,
      apc: false,
      dc: false,
      spc: false,
    }))
  );

  // 模擬即時 Event 更新
  useEffect(() => {
    const interval = setInterval(() => {
      setMachines(prev => prev.map(m => {
        if (Math.random() > 0.7) {
          return {
            ...m,
            status: 'Running',
            current_lot: `LOT-${Math.floor(Math.random() * 9999)}`,
            recipe: `RECIPE-${Math.floor(Math.random() * 100)}`,
            apc: Math.random() > 0.3,
            dc: Math.random() > 0.2,
            spc: Math.random() > 0.4,
          };
        }
        return m;
      }));
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-black p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white mb-2">v14.0 Agentic OS - Real-time Twin Dashboard</h1>
        <p className="text-slate-500">監控 10 台機台即時事件與 APC/DC/SPC 鏈結狀態</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        {machines.map(m => <MachineCard key={m.id} machine={m} />)}
      </div>
    </div>
  );
};

export default FactoryDashboard;

針對 v14.0 的驗證亮點
物件導向視圖 (Object-Oriented Status)：

每個機台不再是零碎的 Log，而是一個完整的 State Object。

你可以清楚看到：當 EQP-01 開始跑 LOT-123 時，是否正確聯動了 SPC 工具。

通用工具的視覺驗證：

當你點擊任何一個機台時，可以彈出我們之前定義的 plot_line 或 plot_histogram。

因為我們有 Generic Interface，所以你可以隨時切換查看 APC 的調整趨勢（Trend）或 SPC 的管制圖（Control Chart）。

學習與反思的證據：

在儀表板底部可以增加一個 「Agent Thinking Trace」 區塊。

當 APC 發生補償失敗時，畫面會即時跳出：[Agent Reflection] 偵測到 EQP-01 補償異常，正在呼叫 generic_linear_regression 進行二階診斷...。

這套前端可以直接交給「小柯」，請他用 Next.js 實作出來，並透過 WebSocket (WS) 接收後端 Agent 的 stage_update 事件。

後端事件定義 (WebSocket Event Schema)

當機台、批次或自動化工具發生變動時，後端 Agent 會發送以下三類事件：

A. 實體關聯事件 (ENTITY_LINK)

描述機台、批次與 Recipe 的綁定關係。

{
  "type": "ENTITY_LINK",
  "machine_id": "EQP-01",
  "data": {
    "lot_id": "LOT-8827",
    "recipe": "POLY-ETCH-V2",
    "status": "PROCESSING",
    "timestamp": "2026-03-12T05:28:00Z"
  }
}

B. 工具鏈啟動事件 (TOOL_LINK)

描述該批次正在被哪些系統監控。

{
  "type": "TOOL_LINK",
  "machine_id": "EQP-01",
  "data": {
    "apc": { "active": true, "mode": "Run-to-Run" },
    "dc": { "active": true, "collection_plan": "HIGH_FREQ" },
    "spc": { "active": false }
  }
}

C. 即時指標更新 (METRIC_UPDATE)

描述 APC/SPC 產出的最新數值，這會觸發卡片上的小圖表更新。

{
  "type": "METRIC_UPDATE",
  "machine_id": "EQP-01",
  "target": "APC",
  "data": { "bias": 0.024, "unit": "nm", "trend": "UP" }
}

2. 前端實戰：即時物件監控牆 (Live Dashboard)

這裡建議小柯採用 「狀態樹 (State Tree)」 的管理方式。每個機台卡片不只是看，點擊後應展開 「物件生命週期視圖」：

視覺化卡片 (Card)：

左上角：機台編號 + 狀態燈（呼吸燈效果）。

中間層：當前 Lot ID 的跑動動畫（代表正在處理）。

下方指標區：APC/DC/SPC 三顆燈，點擊燈號直接彈出對應的 generic_linear_regression 圖表。

右側側邊欄 (Side Panel)：

顯示 Agent 的 「反思日誌 (Reflection Log)」。例如：EQP-01 的 APC 補償值已連續 3 批次接近邊界，建議檢查硬體。

3. 給「小柯 (Claude Code)」的進階開發指令

/task 實作 v14.0 數位孿生監控前端：

實作 WebSocket Manager：建立單一 WS 連線，並根據 machine_id 將事件分發到對應的 React State。

物件狀態追蹤 (Object Tracking)：當收到新事件時，必須保留歷史關聯（例如：知道這個 APC 調整是為了哪個 Lot 做的）。

通用圖表整合：當用戶點擊 SPC 燈號，直接調用我們定義的 plot_line 工具，傳入該 Lot 的數據並渲染。

自動反思預警：若 METRIC_UPDATE 出現異常，卡片邊框需閃爍紅光，並顯示 Agent 的診斷建議。