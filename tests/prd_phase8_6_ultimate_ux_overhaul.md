# Phase 8.6 究極體驗重構：品牌、檢視器、自癒引擎與對話動線

## 1. 品牌正名與多語系 (Branding & i18n)
- **平台正名**：全站的 "Glass Box" 替換為 **"AI Ops"**。
- **Icon 升級**：廢除側邊欄 Emoji，全面替換為 `lucide-react` 或 `heroicons` 的專業線條圖示。
- **多語系 (i18n)**：實作【繁體中文 / English】切換功能，並套用於主要選單與按鈕。

## 2. 診斷工作站重構 (Chat-First & 模擬測試)
重構 `/diagnosis` 頁面，將動線改為「對話優先，報告後出」。

- **進入狀態**：主視覺為 Chat 介面。AI 自動發送打招呼歡迎語。
- **找回模擬按鈕 (Crucial)**：在聊天輸入框的上方，**必須保留/加回【⚡ 模擬觸發：TETCH01 PM2 發生 SPC OOC】的快捷按鈕**。點擊後自動發送該訊息，方便快速測試排障管線。
- **動態報告**：原本左側的「總結報告」移至右側，預設隱藏，待產出結論時才滑出。頂部需支援「歷史 Case 切換」頁籤，確保每個排障會話有獨立報告。

## 3. 通用資料檢視器 (Universal Data Viewer)
建立全域共用的 `<UniversalDataViewer data={jsonData} />` 元件，徹底消滅生硬的 JSON 字串。
- **三重視角**：包含 **Tree View** (物件折疊)、**Grid View** (陣列轉 React Table)、**Raw View** (純文字與複製按鈕)。
- **全面套用**：替換 MCP Builder Step 1 (樣本預覽)、Step 4 (輸出預覽)，以及 Skill Builder 的 MCP 參考區塊。

## 4. MCP 自癒引擎與多 Tab 迭代介面 (Self-Healing)
解決 MCP Try Run 失敗時的死胡同體驗。

- **錯誤分診 (Error Triage)**：Sandbox 發生 Exception 時，呼叫 LLM 分析錯誤，回傳 `error_type` (User_Prompt_Issue 或 System_Issue) 與 `suggested_prompt`。
- **多 Tab 迭代 UI**：MCP Builder 的輸入與試跑區塊改為 Tabs 架構 (例：`[Try 1]`, `[Try 2]`)。
  - **User 錯誤**：自動開新 Tab 並填入 LLM 修正後的 Prompt，提示 User 再次試跑。
  - **System 錯誤**：顯示 IT 聯絡提示卡片，並使用 UniversalDataViewer (Raw 模式) 顯示 Error Dump 供 User 複製報修。