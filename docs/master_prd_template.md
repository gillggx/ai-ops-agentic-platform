# 總體藍圖文件結構 (Master Blueprint Structure)
文件名稱：`docs/master_prd_v11.md`

這份文件必須是「可執行的開發規格書 (Actionable PRD)」，必須包含實作細節，而非只是狀態描述。

## 1. 產品核心哲學與定位
- 系統目標：L1/L2 第一線智能快篩 (取代手動查資料)。
- 核心架構：Agentic Workflow (Event 驅動 Skill)。

## 2. 核心 Domain Knowledge 數位化 (系統 Prompts 總匯)
- [重要] 必須完整收錄所有影響系統智商的 System Prompts。
- 包含：Diagnostic Agent 診斷邏輯、LLM Mapping Engine 參數轉換邏輯等。

## 3. UI/UX 互動與介面規格
- [重要] 必須詳細描述前端元件的操作流程。
- 包含：Mobile-First 響應式佈局策略、Swipe to toggle (滑動切換) 手勢定義、Copilot 對話框槽位填充 (Slot Filling) 的漸進式透明回饋。

## 4. 核心業務邏輯與自動化閉環 (Phase 11 重點)
- Event Orchestrator 邏輯：Event 如何綁定多個 Diagnosis Skill。
- Routine Check (巡檢排程)：Cron Job 強制綁定 `skill_input` 參數的機制，以及異常觸發 Alarm 的流程。

## 5. 系統開發紀律與架構規範
- 去 Hard-code 原則 (`.env` 與 `config.py` 抽離策略)。
- 錯誤處理與 CI/CD 部署流程。