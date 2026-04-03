# Phase 11：主動巡檢排程 (Routine Check) 與 LLM 事件映射引擎 (Skill-to-Event)

## 1. 核心產品哲學
系統從「被動接收 Event 進行診斷」進化為「主動巡檢 (Detection) 並生成 Event (Alarm)」。
Skill 不再只是底層工具，它具備了「主動報警」的權限；並且透過 LLM 的語意理解能力，自動將巡檢拿到的凌亂數據，無縫轉換 (Mapping) 成觸發 Event 所需的標準參數。

## 2. Routine Check (例行巡檢排程) 系統
- **新增資料庫實體 `RoutineCheck`**：
  - `id`: 唯一識別碼
  - `skill_id`: 關聯的目標 Skill (被選為 Detection 用的技能)
  - `preset_parameters`: JSON 格式，存放使用者預先設定的 Data Subject (例如 `{"lot_id": "N97A45.00", "operation_number": "24981"}`)
  - `schedule_interval`: 巡檢頻率 (Enum: `30m`, `1h`, `4h`, `8h`, `12h`, `daily`)
  - `is_active`: Boolean，是否啟用此排程
- **後端排程引擎**：在 FastAPI 導入 `APScheduler` (或類似套件)，依照上述頻率定時在背景執行對應的 Skill。

## 3. Skill-to-Event 關聯與 LLM 映射引擎 (Mapping Engine)
- **Skill 擴充定義**：
  - 在 Skill 設定中，新增一個可選欄位 `trigger_event_id`。
  - 當 Skill 被 Routine Check 或手動執行後，若診斷結果判斷為 **"異常 (Abnormal)"**，且有設定 `trigger_event_id`，則必須觸發「事件映射引擎」。
- **LLM 參數映射 (Auto-Mapping by LLM)**：
  - **痛點**：Skill 撈回來的資料欄位，與目標 Event 需要的 `required_parameters` 往往不一致。
  - **解法**：實作一個全新的 System Prompt，專門負責 Data Mapping。
  - **LLM Mapping Prompt 邏輯**：
    > [Context]
    > 1. Skill 執行結果的原始數據：{skill_result_data}
    > 2. 目標 Event 需要的參數清單：{event_required_parameters}
    > [Task]
    > 請分析 Skill 的原始數據，精準萃取出目標 Event 所需的參數值。若無法找到完全匹配的值，請根據上下文進行合理推斷（例如從 Symptom 描述中抓取）。
    > [Output]
    > 嚴格回傳 JSON 格式：`{"參數1": "值1", "參數2": "值2"}`
- **生成 Event**：後端取得 LLM 完美填寫的 JSON 參數後，直接在資料庫中新建一筆 Event 紀錄，等同於系統發出一個正式的 Alarm。

## 4. UI / UX 升級規範
- **Routine Check 管理介面**：
  - 在側邊欄新增 `[⏱️ 排程巡檢]` 頁面。
  - 提供表單讓使用者設定：選擇 Skill ➔ 填寫 Data Subject (LLM 動態生成輸入框) ➔ 選擇頻率 (30m ~ Daily)。
- **Skill 編輯介面擴充**：
  - 增加一個區塊：`[🚨 異常觸發設定]`。
  - 提供下拉選單，讓使用者選擇：「當此 Skill 檢查異常時，觸發以下 Event」。