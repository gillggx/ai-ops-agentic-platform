# Phase 8.9.2 終極重構：1-to-1 Skill 架構、智能映射與全鏈路試跑

## 1. 架構降維與單選 UI (1-to-1 Relationship)
系統強制規定 **「一個 Skill 只能綁定一個 MCP」**，徹底拔除多選邏輯。
- **資料狀態**：前端與後端必須將綁定的 MCP 從 Array 更改為單一 String/ID。
- **UI 限制**：移除 Checkbox 列表，改用單選的 Dropdown 或 `<select>` 來挑選 MCP。

## 2. 溯源 Data Subject 與 LLM 智能映射 (Semantic Auto-Mapping)
當 Expert 選定單一 MCP 後，系統不能只顯示黑箱的 `raw_data`，必須啟動以下智能管線：
1. **溯源 Input**：從該 `MCP.data_subject_id` 撈出底層 Data Subject 的 `input_schema` (例如 APC 的 `lot_id`, `operation_number`)。
2. **呼叫 LLM 進行映射**：前端呼叫 `/api/v1/skills/auto-map`。後端將 Data Subject Inputs 與 Event Attributes 丟給 LLM，要求回傳兩者的語意對應關係 (JSON)。

## 3. 參數映射與測試面板 (Mapping & Try Run UI)
收到 LLM 的映射建議後，必須在畫面上渲染出【參數綁定與測試區塊】，嚴格遵守三欄式設計：
- **第一欄 (Data Subject 需要的參數)**：例如 `lot_id`。
- **第二欄 (Event 自動映射)**：一個下拉選單，預設選中 LLM 建議的 Event 屬性（如 `Event.lotID`），允許使用者手動修改確認。
- **第三欄 (Try Run 測試值)**：一個明確標示「請輸入測試值 (Try Run Value)」的 Text Input，讓 Expert 填寫真實批號或機台號碼 (如 `L12345`)。



## 4. MCP 全鏈路執行與視覺化 (Full Pipeline Execution)
- 填寫完測試值後，點擊 `[▶️ 執行 MCP 處理管線]`。
- **真實執行**：系統必須拿著測試值去打 Data Subject API 撈資料，接著將資料丟進該 MCP 的 Python Sandbox 執行運算。
- **結果展示**：執行成功後，在下方展開 `<UniversalDataViewer>` 顯示這份「加工完畢的最終結果 (Output Schema, Dataset, 圖表)」。
- Expert 必須看著這份最終結果，才能在最下方的輸入框撰寫精準的「Diagnostic Prompt (檢查意圖)」。