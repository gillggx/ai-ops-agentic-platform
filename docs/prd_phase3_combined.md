# Phase 3 終極整合版：Agentic SSE 實況引擎與全 MCP 事件分診

## 1. 架構升級目標
本次開發結合兩大核心目標，將系統升級為企業級的 AIOps 診斷框架：
1. **全 MCP 分診 (All-in-MCP Triage)**：廢除外部路由，建立 `mcp_event_triage` 技能，將使用者問題轉化為標準 Event Object 並過濾可用工具。
2. **SSE 實況轉播 (Streaming)**：將 `/api/v1/diagnose` 改為 Server-Sent Events (SSE) 輸出，即時推播 Agent 的思考與工具調度過程。

## 2. 核心 Skill 規格：mcp_event_triage
此工具必須被 Agent **優先且唯一**呼叫，用於限縮後續的排障範圍。
- **Input Schema**: `{"type": "object", "properties": {"user_symptom": {"type": "string"}}}`
- **Output (Event Object) 格式**:
  ```json
  {
    "event_id": "EVT-自動生成",
    "event_type": "Performance_Degradation",
    "attributes": {"symptom": "系統很慢"},
    "recommended_skills": ["mcp_mock_cpu_check"]
  }