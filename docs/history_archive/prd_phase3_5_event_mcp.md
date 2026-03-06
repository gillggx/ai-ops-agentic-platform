# Phase 3.5 架構升級：全 MCP 事件分診機制 (All-in-MCP Triage)

## 1. 架構升級目標
貫徹「通用型診斷框架」與「萬物皆 MCP」的設計理念，廢除系統外部的 Hardcode 路由或 Middleware。將「判斷問題與觸發事件」的邏輯，封裝成一個標準的 MCP Tool (`mcp_event_triage`)。

## 2. 核心 Skill 規格：mcp_event_triage
此工具負責接收使用者的原始抱怨，並將其轉化為帶有屬性的「結構化事件 (Event Object)」，同時過濾出後續該使用的 Skills。

- **Tool Name**: `mcp_event_triage`
- **Description**: 當使用者提出問題時，【必須優先且唯一呼叫】此工具。它會分析症狀，觸發對應的系統事件，並回傳你接下來應該呼叫哪些檢查工具 (Skills)。
- **Input Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "user_symptom": {
        "type": "string",
        "description": "使用者描述的原始問題，例如 '系統很慢'"
      }
    },
    "required": ["user_symptom"]
  }
-  **Expected Output**:
{
  "event_id": "EVT-自動生成",
  "event_type": "Performance_Degradation",
  "attributes": {"target": "unknown", "urgency": "high"},
  "recommended_skills": ["mcp_mock_cpu_check"]
}