# 🚀 Master PRD v12: AI Ops Agentic Platform 系統重構規格書 (High-Fidelity Spec)

## 1. 系統架構總覽與邊界 (Architecture & Boundary)
本系統將升級為 **Agentic AI Tool Registry (代理人工具註冊中心)**。
架構嚴格劃分「領域邊界 (Domain Boundary)」：
- **平台 (Platform/DB)**：負責「確定性」的硬核運算。把 Python 腳本封裝在後端 Sandbox 執行，並負責作為唯一 API Gateway 串接底層資料源，杜絕幻覺。
- **代理人 (Agent/OpenClaw)**：負責「機率性」的高階推理。只閱讀平台動態產生的 Markdown 說明書，發送 API 請求，並生成人類語意的總結報告。
- **前端 (Frontend)**：負責防呆輸入、資源庫挑選，並承接 Agent 草擬好的資料進行最後的 UI 確認與發佈。

---

## 2. 資料庫模型與權限設計 (Database Schema & Visibility)
嚴禁將設定寫死為實體 `.md` 檔案，必須採用資料庫集中管理，以實現跨任務 (N-to-N) 共用。

### 2.1 資料節點表 (`mcp_registry`)：萬物皆 MCP
系統將底層 IT API 與 User 加工腳本統一抽象為 MCP，透過 `mcp_type` 區分。
| 欄位名稱 | 型別 | 說明 |
| :--- | :--- | :--- |
| `mcp_id` | UUID (PK) | 唯一識別碼 |
| `mcp_type` | ENUM | **(核心)** 分為 `system` (系統預設底層 API) 與 `custom` (User 撰寫 Python 衍生加工的節點) |
| `name` | VARCHAR | MCP 顯示名稱 |
| `description` | TEXT | MCP 功能說明 |
| `source_endpoint` | VARCHAR | `system` 專用：綁定的底層 IT API 端點 |
| `execution_python` | TEXT | `custom` 專用：由 User/Agent 生成的資料處理腳本。負責清洗 Raw Data 並產出圖表設定 |
| `parameters_schema`| JSONB | 定義此 MCP 需傳入的參數結構 |
| `visibility` | ENUM | 權限：`private` (個人), `public` (全系統共用) |

### 2.2 診斷技能表 (`skill_registry`)
| 欄位名稱 | 型別 | 說明 |
| :--- | :--- | :--- |
| `skill_id` | UUID (PK) | 唯一識別碼 |
| `mcp_id` | UUID (FK) | 綁定的 MCP 節點 (可綁定 `system` 或 `custom` 類型) |
| `name` | VARCHAR | Skill 顯示名稱 |
| `diagnostic_prompt` | TEXT | 異常判斷條件 |
| `problematic_target` | VARCHAR| 異常物件目標 |
| `expert_action` | VARCHAR | 專家處置建議 |
| `generated_python` | TEXT | **(隱藏執行的核心)** 儲存 LLM 生成的沙盒診斷 Python 程式碼 |
| `visibility` | ENUM | 權限：`private`, `public` |

---

## 3. 後端 API 合約與動態編譯器 (API Contracts & Compiler)

### 3.1 執行呼叫 API (The Execution Endpoint & Wrapper Payload)
前端 UI 與 Agent 皆強烈依賴後端將資料縫合後的標準格式。
對於 `mcp_type: 'system'`，後端需提供 Default Wrapper，自動將資料轉為 `data_grid` 格式；對於 `custom`，則依據 `execution_python` 產出。

- **Endpoint**: `POST /api/v1/execute/skill/{skill_id}` (或 MCP)
- **Response Payload (CRITICAL: 嚴格遵循此結構驅動 UI 與 Agent)**:
  ```json
  {
    "status": "success",
    "message": null,
    "data": {
      "success": true,
      "script": "def process(raw_data):\n    ...",
      "input_definition": {
        "params": [
          { "name": "chart_name", "type": "string", "required": true }
        ]
      },
      "output_data": {
        "output_schema": {
          "fields": [
            { "name": "tool", "type": "string", "description": "機台代碼" },
            { "name": "mean", "type": "number", "description": "平均值" }
          ]
        },
        "dataset": [
          { "tool": "TETCH01", "mean": 45.81, "OOC_count": 4 }
        ],
        "ui_render": {
          "type": "bar_chart",
          "chart_data": "{\"data\": [...], \"layout\": {...}}"
        },
        "_raw_dataset": [
          { "chart_name": "CD", "tool": "TETCH01", "values": [47.2, 46.9] }
        ],
        "_is_processed": true
      }
    }
  }

讀取鐵律:

Frontend UI 依賴 output_schema 畫 Grid，依賴 ui_render 畫圖，依賴 _raw_dataset 渲染 Raw 頁籤。

Agent (OpenClaw) 僅允許讀取 data.output_data.dataset 進行推理，嚴禁解析其他 UI 欄位。

3.2 列表過濾 API (MCP Visibility Logic)

Skill Builder 挑選依賴時：API 需回傳所有 system 與 custom MCP。

MCP Builder 編輯列表時：API 必須過濾，嚴禁顯示 system 類型的節點，避免 User 誤改 IT 基礎設施。

3.3 Agent 動態工具註冊 API (Dynamic Tool Injection)

Endpoint: GET /api/v1/agent/tools_manifest

防破碎與參數繼承 Markdown 模板 (CRITICAL):
後端必須使用 XML 標籤隔離使用者輸入，並強制繼承 MCP 參數。

---
name: {skill.name}
description: 本技能是一套完整的自動化診斷管線。{skill.description}
---
## 1. 執行規劃與優先級 (Planning Guidance)
- 優先使用：當意圖符合時直接呼叫，絕對不要要求使用者先提供 raw_data，系統會自動撈取。

## 2. 依賴參數與介面 (Interface)
- API: `POST /api/v1/execute/skill/{skill.skill_id}`
- 必須傳遞參數: {mcp.required_parameters_json_schema}
- ⚠️ 邊界鐵律: 呼叫 API 後，僅允許讀取 `data.output_data.dataset` 進行判斷。

## 3. 判斷邏輯與防呆處置 (Reasoning Rules)
請嚴格遵循以下 `<rules>` 標籤內的指示撰寫最終報告：
<rules>
  <condition>{skill.diagnostic_prompt}</condition>
  <target_extraction>{skill.problematic_target}</target_extraction>
  <expert_action>
    ⚠️ 若狀態為 ABNORMAL，必須強制在報告結尾附加處置建議：
    Action: {skill.expert_action}
  </expert_action>
</rules>

4. 系統級元技能與對話式建構管線 (Meta-Skills & Conversational Handover)
平台核心建構功能必須封裝為「系統級元技能」，預設註冊給 OpenClaw 調用。

4.1 預設建構工具定義 (Builder Tools for Agent)

draft_mcp_node: 要求加工資料並標準化流程時調用 (參數: source_mcp_id, python_script)

draft_skill_pipeline: 要求建立診斷邏輯時調用 (參數: mcp_id, diagnostic_prompt, expert_action)

draft_schedule_task: 要求定時執行時調用 (參數: skill_id, cron_expression)

draft_event_trigger: 要求異常觸發時調用 (參數: skill_id, event_topic)

4.2 從對話到 UI 的無縫交握與模擬流程 (Handover & Try Run Workflow)

Agent 絕對不可直接將設定寫入正式 DB，必須遵守交握管線：

Agent 草擬：Agent 呼叫 draft_* API 將設定發送至「草稿暫存區 (Draft DB)」。

返回深層連結：API 回傳帶有 Draft ID 的連結 (e.g., /builder/skill?draft_id=123)。

對話框引導：Agent 提示使用者點擊連結進行確認。

UI 喚醒與自動填表：使用者點擊後，系統自動將草稿填入 <NestedBuilder /> 表單。

人類把關與模擬：使用者點擊「Try Run」模擬無誤後，按下「正式發佈」才寫入 Registry 生效。

5. 專家模式與雙向解析編輯器 (Expert Mode & Bi-directional Parser)
提供「Agentic 原生視角」，允許透過標準 Markdown 格式直接檢視與編輯 Skill。

5.1 UI 實作：<AgenticRawEditor /> 雙模切換

於 <NestedBuilder /> 實作 Toggle：[ 👁️ 視覺化表單 | ⌨️ 專家代碼模式 ]。

切換至代碼模式時，提供語法高亮編輯器，即時渲染 OpenClaw 相容之 Markdown。

雙向綁定：修改 XML 標籤內純文本，需即時解析並反向更新 UI 表單欄位。

5.2 後端雙向解析 API (Bi-directional Parsing API)

Endpoint: PUT /api/v1/agentic/skills/{skill_id}/raw

邏輯：接收 Raw Markdown，使用 AST 或正則表達式精準萃取 YAML 與 XML 內容，反向 UPDATE 資料庫扁平欄位。

5.3 Agent 技能編修元技能 (Agent Update Meta-Skill)

Tool: patch_skill_markdown

邏輯：允許 Agent 讀出 Markdown，修改條件後呼叫上述 PUT API 覆蓋更新，並回傳深層連結交由人類 Review。

6. 前端元件架構與狀態管理 (Frontend Architecture)
全面導入 Tailwind CSS 實作響應式佈局。

6.1 <MissionControlDashboard /> (戰情中心)

Layout: max-w-[1400px] mx-auto p-6.

Active Tasks (Left): 列表顯示運行中任務。明確標示 <Badge color="purple">Skill</Badge> 展現解耦。

Execution Log (Right): 歷史紀錄列表。狀態為 ABNORMAL 時直接預覽專家處置。

6.2 <NestedBuilder /> (巢狀建構器)

Layout: flex flex-col xl:flex-row h-full。左側設定區 xl:w-1/2，右側 Console 區 xl:w-1/2。

視覺層級: 透過左側粗邊框展現 L1 Task -> L2 Skill -> L3 MCP 包覆感。

預覽機制: 嚴禁直接顯示 Raw JSON。使用 <details> 包裹 <table class="min-w-full"> 渲染 Schema 網格。

6.3 <TryRunConsole /> (狀態切換終端機)

Tab 1: Streaming Logs: 點擊 Try Run 時自動切換，印出執行 Log。

Tab 2: Execution Report: Log 印完自動跳轉。

Skill 區塊: ABNORMAL 套用紅底警示風格。

MCP 區塊: 讀取 API data.output_data.ui_render，提供 📊 Charting、📑 Summary、💾 Raw Data 頁籤。

7. 強制驗收清單與測試報告要求 (Mandatory QA Checklist)
開發必須於 feature/v12-agentic-registry 分支進行。開發完成後，工程師 (小柯) 必須親自執行以下測試，並輸出 v12_test_report.md 交由架構師審查。報告內需附上 API 回傳 JSON、Terminal Log 或 UI 狀態截圖證明。

[ ] Test Case 1: 後端 Wrapper 測試
呼叫 system MCP API，驗證系統是否自動產出標準 JSON Payload，且 ui_render 預設為 Grid/Tree。

[ ] Test Case 2: UI 列表權限測試
呼叫 MCP Builder 列表 API，驗證 system MCP 確實被過濾隱藏；呼叫 Skill 依賴 API，驗證兩者皆存在。

[ ] Test Case 3: 對話式交握 (E2E) 測試
模擬呼叫 draft_skill_pipeline，驗證系統確實返回深層連結 (?draft_id=)，且未直接寫入正式 DB。前端能透過 API 正確取回草稿內容。

[ ] Test Case 4: 雙向解析與防破碎測試
呼叫 PUT /api/v1/agentic/skills/{id}/raw 傳入包含干擾符號(#)的 Markdown，驗證 DB 欄位正確被 Update 且未發生結構崩潰。

[ ] Test Case 5: 防幻覺邊界測試
模擬排程執行，驗證 Agent 的總結報告所擷取的異常物件，100% 來自 dataset 的回傳值，並成功強制附加 Action。