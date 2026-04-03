# Phase 8.7：Skill Builder 專業化、參數映射確認與人類決策邊界

## 1. 核心理念 (Core Philosophy)
在 Skill 的執行階段，**LLM 只做「數據檢查與總結」，絕對不自動生成「處置建議」**。處置建議必須由建立 Skill 的領域專家 (Expert) 以靜態文字定義。

---

## 2. Skill Builder 全新四步建構流程 (UX Flow)

### Step 1: 選定 MCP 與「參數映射確認 (Mapping Verification)」
- 當 Expert 選擇了某個 MCP 後，畫面必須展開一個 **「MCP 完整說明卡片」**（包含 MCP 名稱、描述）。
- **自動映射與確認 UI**：
  - 系統呼叫 LLM 進行 Auto-Mapping，比對 Event 的屬性（如 `lotID`）與此 MCP 需要的 Input（如 APC Data Subject 需要的 `lotID`, `OperationNumber`）。
  - **【關鍵防呆】**：映射結果不能直接黑箱儲存！必須在畫面上渲染出一個「對應關係表」，讓 Expert 檢視並可以手動修改下拉選單。
  - *UI 範例*：`MCP Input: OperationNumber` ⬅️ [下拉選單：對應到 `Event.operation_number`]
  - 必須點擊 `[確認參數綁定]` 後，才能進入下一步。

### Step 2: 顯示 MCP 輸出結果 (Output Reference)
- 綁定完成後，使用上一版開發的 `<UniversalDataViewer>`，在畫面上展示該 MCP 執行後會吐出的 `output_schema` 與 `sample_data`。
- 讓 Expert 清楚知道有哪些參數（例如 APC 的各項設定值）可以拿來寫檢查邏輯。

### Step 3: 撰寫檢查邏輯與「人為處置建議」
 Expert 需填寫兩個獨立的輸入框：
- **A. 檢查意圖 (Diagnostic Prompt)**：
  - 告訴 LLM 怎麼看資料。例如：「*檢查 MCP 結果，判斷 CHF3_Gas_Offset 是否超過 5，或更新時間小於 24 小時。*」
- **B. 專家建議處置 (Human-Defined Next Action)**：
  - **[全新欄位]**：這是一段純文字描述，由 Expert 親自撰寫。例如：「*若檢查發現異常，請聯絡設備工程師執行 Chamber 濕式清洗 (Wet Clean)，並將該批號 Hold 住。*」

### Step 4: 模擬診斷與 Summary (Try Run)
- 點擊 `[▶️ 模擬診斷]` 進行試跑。
- **後端 Prompt 拔除建議權限**：必須修改 IT Admin 維護的 `PROMPT_SKILL_DIAGNOSIS`，嚴格規定 LLM 的 JSON 輸出格式只能包含：
  ```json
  {
    "conclusion": "檢查結論 (例如：發現 CHF3_Gas_Offset 超標)",
    "severity": "LOW|MEDIUM|HIGH|CRITICAL",
    "evidence": ["支持結論的具體數據點 1", ...],
    "summary": "一句話總結檢查結果" // ❌ 絕對不可包含 recommendation
  }