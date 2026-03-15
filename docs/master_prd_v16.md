Agentic OS v16: AIOps Application Architecture Spec (含時空溯源引擎)

本規格書定義 Agentic OS 上層的 AI Ops (智能維運應用) 架構。透過分離「左側的 Control Pane (工程師大腦)」與「右側的 Event Handling Panel (助理處置面板)」，實現廠務知識的系統化。
本版次 (v16.1) 導入核心靈魂：「Ontology Time Machine (本體時空溯源引擎)」，賦予系統與 AI Agent 穿越過去、完美還原歷史現場的鑑識能力 (Forensic RCA)。

1. 核心靈魂：Ontology Time Machine (本體時空溯源引擎)

在傳統系統中，資料會被覆蓋（例如 Recipe V1 被更新為 V2）。但在本系統中，由於所有 Ontology 關聯皆綁定 eventTime，我們具備了**「時空凍結 (Temporal Context Freeze)」**的能力。

還原現場 (Scene Reconstruction)：當使用者輸入一個歷史時間點（如 3 個月前的某個 Lot Process Event），系統的 UI、拓撲圖、關聯資料庫，會瞬間「凍結」並切換回那個毫秒的狀態。

穿越視角 (Time-Travel Perspective)：

看到的 Recipe 不是最新版，而是當時機台正在跑的歷史版本。

看到的 SPC Chart 會以那天為基準點展開，遮蔽未來的數據。

Agent 的診斷邏輯會被強制置入該時空背景進行推論。

2. 雙角色定義與 UI 實體佈局 (Persona & Layout)

系統的應用層嚴格區分為兩個獨立的工作站，並以不同的 Chat 介面呈現：

👨‍🔬 Persona A: 負責工程師 (PE/EE - Process/Equipment Engineer)

專屬介面：Control Pane (控制面板) —— 固定於畫面左側。

時空機應用 (Time-Travel Debugger)：
PE 可以使用過去的「歷史災難事件」來測試自己剛寫好的 AI Skill。

PE 輸入指令："將系統切換至 2025-11-15 14:30 的大當機現場，並用我剛寫的 SKILL_OOC_RCA 跑一次，看 Agent 能不能抓出兇手。"

👷‍♂️ Persona B: 助理工程師 / 輪班技術員 (AE/TE - Assistant Engineer / Technician)

專屬介面：Event Handling Panel (事件處置面板) —— 固定於畫面右側。

時空機應用 (Forensic Investigation)：
當 AE 接到一筆客訴退貨 (RMA) 的查案任務時。

AE 點擊 Lot 事件，畫面中央的 Topology Map 會泛起一陣藍光（視覺回饋），提示已進入**「歷史還原模式 (Historical Snapshot)」**。

AE 可以在右側 Chat 要求 Agent："幫我調出這批貨在 STEP_045 那天的機台現場，畫出當時的 DC 溫度曲線，並與前後 5 批貨比對。"

3. 核心模組一：Control Pane (PE 左側大腦中心)

這是給工程師打造 Agent 的 Low-Code 儀表板與 Chat 介面。

Event Overview (全局事件監控)

總覽系統所有 Events、未處理狀態，及 Trigger 觸發頻率。

MCP & Skill Builder (大腦與技能建置)

設計 MCP：PE 定義 Agent 的工具。特別是必須開放 get_historical_graph_context(eventTime) 這個時空 API 給 Agent。

設計 Skills：將 MCP 封裝成特定的技能。

Trigger Linkage (連動檢查設定)

設定「當 X 事件發生時，自動觸發 Y 技能」。

4. 核心模組二：Event Handling Panel (AE 右側處置面板)

這是專為 AE 快速決策與查案設計的智能助理介面，位於畫面右側。

Event Alert & Auto-Diagnostic (事件捕捉與自動診斷)：

異常發生時，右側面板主動彈出 RCA 報告。

Interactive Time-Machine Chat (時光機對話)：

AE 可以要求 Agent 進行時空穿梭。

💬 AE 指令範例："回到上週三下午的 PM 復機現場，比對當時的 APC 補償與現在有何不同？"

🤖 Agent 回應："🕒 已啟動時空還原。回到 2026-03-04 15:00... 發現當時的 Recipe 是 v4.1，而現在是 v4.2。當時的 APC 補償極限設定較為寬鬆。以下為當時的現場拓撲數據..."

1-Click Disposition (一鍵處置按鈕)：

[ 🔴 HOLD 機台並派發工單 ]

[ 🟢 忽略警告並 Release Lot ]

[ ⚠️ 異常無法判斷，Escalate to PE ]

5. AI 技能庫與時光機的結合 (PE 定義的 Skills)

技能代碼 (由 PE 定義)

觸發條件 (Event)

賦予 Agent 的時空能力 (MCP)

Agent 鑑識邏輯 (Forensic Logic)

SKILL_RMA_FORENSIC

收到客訴 Lot ID

Time-Travel Context Service

將系統時鐘撥回加工當下。凍結當時的 Recipe 靜態參數與 APC 狀態，抓出潛在的邊緣失效 (Marginality)。

SKILL_OOC_RCA

收到 SPC OOC 警報

Graph Context Service

鎖定 OOC 當下毫秒，展開關聯圖譜。比對 DC 參數。

SKILL_RECIPE_AUDIT

每日凌晨 00:00

Ontology Audit Service

對比昨天與今天的 Recipe Ontology 實體，找出未被授權的版本漂移。

6. 開發與底層驗證規範 (Test Script for Time-Machine)

如同團隊 [2026-02-27] 協議，在實作 AIOps 介面前，必須提供測試腳本來驗證「時光機 (Temporal Freeze)」與「雙角色 (Dual-Persona)」的底層邏輯。

開發者行動 (Action Item)：
請實作一支 Python 腳本 simulate_time_machine.py。該腳本需模擬：

[資料準備] 在 Mock DB 中塞入同一個 Recipe 的兩個版本 (v1 at T-10, v2 at T-0)。

[時空穿梭測試] 腳本模擬 Agent 接收到 AE 的指令："查詢 T-5 時間點的現場狀態"。

[鑑識還原驗證] 腳本呼叫 Ontology Data Services，必須精準印出："🕒 還原 T-5 現場... 取得的 Recipe 版本為 v1 (而非最新的 v2)"，以此證明系統具備真正穿梭過去、凍結歷史的鑑識能力。