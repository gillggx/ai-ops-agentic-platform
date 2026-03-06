# Phase 8.4 補丁：Skill 決策大腦防盲與 MCP 輸出繼承

## 1. 架構連動核心 (Data Inheritance)
為了解決 Expert 在撰寫 Skill 診斷邏輯時的「空白畫布」問題，系統必須將 MCP Builder 試跑 (Try Run) 成功的結果，無縫傳遞給 Skill Builder 作為撰寫提示詞的參考字典。



## 2. 後端資料庫升級 (MCP Record Update)
當 MCP 在 Phase 8.3 執行「儲存」時，資料庫除了儲存 Python 腳本，必須強制寫入兩個新欄位：
- `output_schema` (JSON): LLM 分析處理後資料所產生的結構定義。
- `sample_output` (JSON): 試跑 (Try Run) 時產生的真實處理結果片段（例如前 3 筆 OOC 點位資料，或聚合後的 Table 資料）。

## 3. Skill Builder 前端介面優化 (UX Flow)
在 `/skills` 或 Event/Skill 綁定介面中，進行以下改造：

### 步驟 A：綁定 MCP 與展開字典
- 當 User 在 Skill 設定頁面中，下拉選定或關聯了某個 MCP (例如 `mcp_apc_change_check`) 後。
- 畫面在「診斷邏輯 (Diagnostic Prompt)」輸入框的上方或側邊，必須立刻動態展開一個 **「MCP 輸出參考區 (MCP Output Reference)」**。
- 該區塊需清楚渲染出該 MCP 的 `output_schema` (欄位名稱與說明) 以及 `sample_output` (真實數據預覽)。

### 步驟 B：精準撰寫診斷提示 (Guided Prompting)
- 由於 User 現在看得到 MCP 會吐出類似 `[{"parameter_name": "RF_Power", "update_time": "10 hrs ago"}]` 這樣的資料。
- User 就可以很有把握地在輸入框寫下：「*請檢查 MCP 回傳的 data_table，如果發現 parameter_name 有異動且 update_time 小於 12 小時，請判定為人為改機異常。*」

### 步驟 C：Skill 的試跑驗證 (Skill Try Run)
- 比照 MCP 的設計，在 Skill 診斷邏輯輸入完畢後，也提供一個 `[▶️ 模擬診斷 (Test Diagnosis)]` 按鈕。
- 點擊後，系統將 MCP 的 `sample_output` 直接餵給 LLM 搭配 User 寫的 Prompt 進行推論，並在下方直接顯示 LLM 產生的「最終診斷報告預覽」。
- 唯有模擬診斷成功，才能按下 `[儲存 Skill]`。