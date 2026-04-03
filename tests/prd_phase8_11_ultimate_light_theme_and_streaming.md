# Phase 8.11：終極視覺導正、漸進式報告渲染與系統補強

## 1. 終極視覺導正 (Hard Reset to Light Theme)
全站介面必須硬性回復至乾淨、清爽的 **「淺色配色 (Global Light Theme)」**，徹底消除沉悶的深色主題，確保符合企業級 AI Ops 的專業嚴謹度。
- **色彩基準**：全站背景為白/極淺灰，文字為黑/深灰。保留原 v7 設計的「深紫藍色調」作為 Active 狀態與標題列的點綴色。
- **品牌與 Icon**：確認全站名稱為 "AI Ops"。Icon 繼續使用 sleakSVG (Lucide/Heroicons 類)，並確保在淺色背景下具備極佳辨識度與質感。
- **套用範圍**：包含 Dashboard、所有 Builders、UniversalDataViewer、卡片與彈出視窗。

## 2. 診斷工作站 30/70 佈局與事件驅動 (Event-Driven UI)
- **版面比例**：`/diagnosis` 頁面強制劃分為「左側對話區佔 30%」、「右側報告區佔 70%」。
- **事件通知卡片**：點擊對話區的「⚡ 模擬觸發」時，顯示淺色質感的「🚨 事件通知卡片」，包含事件名稱、發生時間、Mock 參數（如 LotID），以及明確的 `[🔍 啟動診斷分析]` 執行按鈕。

## 3. 獨立 Skill 診斷報告結構 (Evidence-Driven Report Cards)
右側 70% 的報告區塊中，每次觸發的每一個 Skill 都必須生成一張獨立且圖文並茂的「診斷報告卡片 (或折疊面板)」，絕對禁止將所有結果混為一談純文字。
**每張卡片必須包含：**
1. **標頭區 (Header)**：Skill 名稱、檢查狀態 (正常/異常)、嚴重程度。
2. **AI 診斷總結 (AI Summary)**：顯示 LLM 產出的結論 (conclusion) 與總結 (summary)。
3. **數據與圖表證據 (Evidence Data & Charting) [極度重要]**：必須將該 Skill 底層 MCP 執行產生的真實結果嵌進來！讀取 MCP 的 `ui_render`，使用 `<UniversalDataViewer>` 渲染出 Data Table 或 Plotly/Matplotlib 圖表，作為判斷的絕對證據。
4. **專家處置建議 (Human Recommendation)**：以醒目區塊（如 💡 提示框）展示 Expert 在建立 Skill 時撰寫的 SOP 建議動作。

## 4. 系統防呆與遺忘核心補強 (Logs & Validation)
- **Skill 儲存防呆**：在 Skill Builder 中，若 Data Subject 必填 input 未完成 mapping，強制 Disable 儲存按鈕。
- **綜合日誌系統 (Audit and Error Logs)**：建立結構化日誌（包含 RBAC 操作審計、Data Subject API 呼叫、Sandbox Error Dumps、LLM Prompts）。實作 IT Admin 專屬的日誌檢視與下載介面。

## 5. 漸進式執行與動態渲染 (Progressive Execution & Streaming UI) [核心 UX 修正]
廢除「長時間轉圈等待後，一次性吐出所有報告」的同步黑箱模式。系統必須改為漸進式執行：
- **對話區 (30%) 進度播報**：點擊啟動診斷後，左側的 AI 必須即時以文字回報進度（例如：「*正在呼叫 Recipe Offset 檢查...*」 ➔ 「*✅ Recipe 檢查完成。接著進行 APC 參數檢查...*」）。
- **報告區 (70%) 逐一長出**：右側的報告卡片必須「**跑完一個 Skill，就立刻在畫面上渲染出一張卡片**」。讓使用者可以先審閱第一個檢查的圖表與數據，不需要乾等所有流程全部跑完。