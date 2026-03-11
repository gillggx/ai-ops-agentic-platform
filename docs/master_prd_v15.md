📑 Agentic OS v15.0 修正版規格書：數據感知與自律工具箱
1. 核心願景 (Vision)
讓 AI 從「盲目寫 Code」進化為「看樣品辦事」。透過 Smart Sampling 讓 Agent 具備數據直覺，並整合現有的 copilot_service 執行路徑，賦予 Agent 建立、儲存與複用自定義工具的能力。

2. 核心機制：三段式數據鏈 (Data-Centric Chain)
2.1 階段一：情境抽樣 (Smart Sampling) - [P0]

機制：攔截所有工具回傳的數據流。

輸出：封裝一個 DataProfile 物件傳給 LLM：

Sample：前 20 筆資料。

Meta：欄位清單、資料型態、空值分佈。

Stats：df.describe() 的統計摘要。

2.2 階段二：工具媒合與 JIT 生成 (Decision Logic) - [P2]

整合路徑：直接複用現有的 MCP Try-run 邏輯，不建立新引擎。

判斷邏輯：

優先：從 AI Tool Chest (含 Public & Agent Tools) 媒合。

備援：若無匹配，則進入 JIT (Just-in-Time) Coding。

沙盒注入 (關鍵)：禁止使用檔案路徑 I/O。後端在沙盒啟動時，預先將數據載入為變數 df。LLM 生成的代碼直接對 df 進行運算。

2.3 階段三：Agent 專屬工具箱 (Agent Tool Chest) - [P1]

持久化儲存：新增 agent_tools 資料表，存放由 Agent 自主生成的工具。

元工具 (Meta Tool)：提供 register_agent_tool 介面，讓 LLM 判斷這段 Script 具備複用價值時，自動存入工具箱，供跨 Session 使用。

3. UI/UX 視覺呈現 (右側 Analysis 區)
依據 image_5c77d8 進行組件升級：

[🔍 數據預覽視窗]：顯示當前 AI 參考的 20 筆樣品特徵。

[🛠️ 執行路徑 (Stepper)]：

Step 1: 數據採樣成功

Step 2: 媒合自律工具 [Correlation_Analysis]

Step 3: 沙盒運算完成

[✨ 分析結論]：最終的文字解讀與建議。

4. 給小柯 (Claude Code) 的精簡開發指令
/task 實作 v15.0 數據感知分析流 (與現有機制整合)：

實作後端攔截器：在數據返回前端前，先跑一次 Smart Sampling，將 Profile 存入當前對話 Context。

修改沙盒 Runner：支援 Variable Injection。確保執行前，樣品數據已作為 df 變數存在於 Python 環境中。

建立 agent_tools 資料表：欄位需包含 name, code, description, usage_count。

實作 register_agent_tool 元工具：在 Prompt 中引導 LLM：「如果這段分析代碼具備通用性，請呼叫此工具將其儲存」。

UI 串接：在 Analysis 面板顯示執行步驟，讓使用者看到 AI 是根據哪 20 筆資料做出的判斷。