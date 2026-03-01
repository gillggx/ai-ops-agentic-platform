# Phase 8.8：Skill Builder 參數映射、擴展性與真實執行管線

## 1. 可擴展的 MCP 選擇器 (Scalable MCP Selection)
廢除原本的「Checkbox 列表 + 預先試跑」設計。
- **UI 重構**：改用「可搜尋的下拉選單 (Searchable Dropdown / Combobox)」或「新增按鈕 + 彈出式挑選清單」。
- **邏輯修正**：使用者只需挑選需要的 MCP，不需要在列表中看到所有 MCP 的試跑狀態。

## 2. 精準的參數映射與測試面板 (Parameter Mapping & Test UI)
解決 `raw_data (object)` 的黑箱問題。當使用者選定某個 MCP（例如 APC Parameter Check）後，系統必須讀取該 MCP 底層 Data Subject 的 `input_schema`（例如 `lot_id`, `operation_number`），並渲染出以下對應介面：

**介面排版規範 (每列代表一個參數)：**
- `[參數名稱]` = `[下拉選單：對應的 Event 屬性]` ➔ `[文字輸入框：請輸入 Try Run 測試值]`
- *畫面範例*：
  `APC lot ID` = `[Event.LotID]` ➔ `[ Input: L12345.00 ]`
  `APC operation` = `[Event.OperationNumber]` ➔ `[ Input: 3200 ]`

## 3. 真實 MCP 執行與視覺化 (Real Execution & Visibility)
在參數對應與測試值填寫完畢後：
- 提供一顆明確的 `[▶️ 執行載入 MCP 數據]` 按鈕。
- 點擊後，系統必須**真實傳入上述的 Try Run 測試值**，去打 API 並跑完 Python 腳本。
- **結果展示**：在下方直接渲染出該 MCP 的 `Output Schema`、`Data Grid / Tree` (使用 UniversalDataViewer)，以及 `Charting (圖表)`。
- *目的*：讓 Expert 看著真實跑出來的圖表與資料，才有辦法在下一步精準撰寫「檢查意圖 (Diagnostic Prompt)」。

## 4. 簡化 Skill Try Run 輸出 (Simplified Summary)
- 在看著上述圖表寫完「檢查意圖」後，點擊最下方的 Skill 試跑。
- LLM 只需要根據 MCP 的結果與檢查意圖，產出一段純文字的「診斷總結 (Summary 描述)」。不需要生成無關的建議動作 (Recommendation) 或是複雜的 JSON，保持邊界清晰。