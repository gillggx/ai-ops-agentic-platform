# Phase 8.5 急件補丁：視覺化渲染引擎與 Prompt 外部化管理

## 1. 架構升級：Prompt 外部化 (Prompt Externalization)
為了解決沙盒無法存檔畫圖的問題，並賦予 IT Admin 調校大腦的權限，必須將系統的 LLM Prompts 從程式碼中抽離。

### 1.1 資料庫升級 (`SystemParameters` Table)
建立系統參數資料表，必須包含以下三個預設 Key：
1. `PROMPT_MCP_GENERATE` (MCP 設計時生成)
2. `PROMPT_MCP_TRY_RUN` (MCP Try Run 時生成)
3. `PROMPT_SKILL_DIAGNOSIS` (Skill 模擬診斷)

### 1.2 前端設定介面 (`/settings`)
在 IT Admin 的介面中新增「系統大腦調校 (Prompt Settings)」區塊，提供 Textarea 讓 IT 編輯這三個 Prompt。後端必須從 DB 讀取最新 Prompt 替換變數後再呼叫 LLM。

---

## 2. 沙盒解禁與記憶體內繪圖 (In-Memory Rendering)
為解決 LLM 寫入檔案被阻擋的問題，必須開放特定白名單，並在 `PROMPT_MCP_TRY_RUN` 中教導 LLM 使用記憶體繪圖。

### 2.1 沙盒白名單擴充
安全環境中**必須允許匯入**：`io`, `base64`, `pandas`, `plotly` (或 matplotlib)。

### 2.2 LLM 輸出強制規範 (Standard Payload)
在資料庫預設的 `PROMPT_MCP_TRY_RUN` 提示詞中，必須加入以下嚴格規範：
> 【安全與視覺化規範】
> 1. 絕對禁止外部 HTTP 請求與讀寫檔案 (os, open, savefig 等)。
> 2. 回傳的 dict 必須包含三個 Key：
>    - `output_schema`: 描述 dataset 的結構。
>    - `dataset`: 處理後的資料陣列。
>    - `ui_render`: `{ "type": "table" | "trend_chart" | "bar_chart", "chart_data": "..." }`。
> 3. 若需要畫圖，【絕對禁止存檔】！請使用 plotly 將圖表轉為 HTML 字串 (呼叫 `.to_html(full_html=False, include_plotlyjs='cdn')`)，或將 matplotlib 畫入 `io.BytesIO()` 轉為 Base64，並填入 `chart_data` 中。若無圖表需求，type 設為 "table"，chart_data 設為 null。

---

## 3. 前端 Step 4 (Result Preview) 渲染引擎升級
前端在接收到 Sandbox 試跑結果後，必須根據 `ui_render.type` 動態渲染，**絕對禁止只印出 JSON 字串**。

1. **表格渲染 (`type: "table"`)**：讀取 `dataset`，使用 React 表格元件 (Table) 整齊呈現資料。
2. **圖表渲染 (`type: "trend_chart" | "bar_chart"`)**：讀取 `ui_render.chart_data`，將 HTML 字串或 Base64 圖片渲染於畫面上。
3. **找回 Output Schema UI**：在 Step 4 區塊上方，新增一個唯讀區塊，優雅地條列出 Payload 中的 `output_schema` 欄位定義，證明系統已掌握資料結構。