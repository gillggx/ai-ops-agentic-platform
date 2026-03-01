# Phase 8.9.1 核心邏輯重構：LLM 語意映射與 MCP 全鏈路執行

## 1. 溯源 Data Subject 的 Input Schema
當 Expert 在 Skill Builder 中選定了單一 MCP 後，系統必須在背景執行「溯源」：
- 透過該 `MCP.data_subject_id` 撈出底層 Data Subject 的 `input_schema`。
- 這些 Input (如 APC 的 `lot_id`, `operation_number`) 才是我們真正需要映射的目標。

## 2. LLM 智能語意對應 (Semantic Auto-Mapping)
廢除前端簡單的字串比對。選定 MCP 後，前端必須立刻呼叫一個新的後端 API (例如 `POST /api/v1/skills/auto-map`)，由 LLM 完成初步對應。

**後端 LLM 系統提示詞設計 (Auto-Mapping Prompt)：**
```text
你是一個半導體資料工程師。請幫我將 Event 的屬性，映射到 Data Subject 的 Input 參數上。
【Data Subject 需要的 Input】：{data_subject_inputs_json}
【Event 提供的 Attributes】：{event_attributes_json}

請判斷語意並回傳 JSON 格式的對應關係。若無法確定，請將對應值設為 null。
格式範例：
{
  "mapping": [
    {
      "mcp_input": "lot_id",
      "mapped_event_attribute": "lotID",
      "confidence": "HIGH"
    }
  ]
}