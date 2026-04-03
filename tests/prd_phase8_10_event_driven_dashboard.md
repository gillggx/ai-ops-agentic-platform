# Phase 8.10 完工收尾：事件驅動主畫面與全鏈路驗證

## 1. 診斷工作站 UI 比例與動線重構 (Dashboard Layout)
- **版面比例調整**：在 `/diagnosis` 頁面中，將原本的佈局調整為 **對話視窗佔 30% (`w-[30%]`)**，**右側報告區塊佔 70% (`w-[70%]`)**，讓豐富的圖表與數據有足夠的展示空間。
- **對話區視覺優化**：保留並優化輸入框上方的「⚡ 模擬觸發」按鈕區塊。

## 2. 真實事件模擬與通知機制 (Event-Driven Trigger)
重構「⚡ 模擬觸發」按鈕的行為，使其不再只是單純發送文字訊息：
- 點擊「模擬觸發：SPC OOC」後，畫面上（對話框內或上方）必須彈出一個醒目的 **「🚨 事件通知卡片 (Event Alert Card)」**。
- **卡片內容**：顯示事件名稱 (如 `SPC_OOC_Etch_CD`)、時間，以及預設的 Mock 參數（如 `LotID: L12345, ToolID: TETCH01`）。
- **行動呼籲 (CTA)**：卡片上必須包含一個明確的 `[🔍 啟動診斷分析]` 按鈕。

## 3. 全鏈路真實執行管線 (Full Pipeline Execution)
當 User 點擊上述的 `[啟動診斷分析]` 按鈕時，系統必須真正串起所有的設定：
1. **讀取關聯**：找出所有綁定至該 Event 的 Skills。
2. **參數代入**：將模擬事件的參數 (LotID 等) 依照 Skill 設定好的 Mapping 規則，代入對應的 MCP (Data Subject)。
3. **真實呼叫與運算**：實際打 API 撈取資料，並丟進 Python Sandbox 執行運算與圖表渲染。
4. **LLM 智能檢查**：將沙盒吐出的 Dataset 餵給 LLM，並套用 Expert 撰寫的檢查意圖 (Diagnostic Prompt)。
5. **報告渲染 (70% 區塊)**：在右側的大報表區，將每一個 Skill 的檢查結果（包含 LLM 生成的 Summary、實體圖表/Table、以及 Expert 事先寫好的『建議動作』）分區塊或分 Tab 完整呈現。

## 4. Skill Builder 終極防呆限制 (Strict Mapping Validation)
在 Expert 設定 Skill 的介面中加入強制阻擋邏輯：
- 系統必須檢查 Data Subject 的 `input_schema` 是否都有被成功 Mapping 到 Event 的屬性上。
- **阻擋條件**：如果出現「無法 Mapping」或「必填 Input 留空」的狀況，最下方的 `[儲存 Skill]` 按鈕必須強制 `Disabled` (反灰)，並顯示紅字提示：「*參數映射未完成，無法儲存此 Skill。*」