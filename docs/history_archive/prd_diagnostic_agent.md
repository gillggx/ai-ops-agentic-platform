# 產品需求規格書 (PRD)：通用型 AI 診斷引擎 (Generic Diagnostic AI Agent)

## 1. 產品概述 (Product Overview)
- **一句話定義**：一個領域無關 (Domain-Agnostic) 的 AI 診斷框架，能根據使用者描述的問題，動態編排 (Orchestrate) 包含標準 MCP 工具、RAG 知識檢索與被動問答的 Skills，以產出最終診斷報告。
- **核心目標**：在 MVP 階段，建立一個基於 MCP (Model Context Protocol) 標準的「Skill 註冊機制」，讓 Agent 能自主決定何時查閱文件 (RAG)、何時呼叫 API (Tools)、何時詢問人類，並給出唯讀的診斷結論。

## 2. 邊界定義 (Scope & Constraints)
### ✅ In-Scope (本次必須開發)
1. **標準 MCP 協定實作 (Standard MCP Protocol)**：
   - 所有的 Skill/Tools 必須繼承統一的 Base Class，並能輸出標準的 **JSON Schema** 格式 (`name`, `description`, `inputSchema`)，確保能無縫對接 LLM 的 Tool Calling 機制。
2. **內建 RAG 檢索機制 (RAG via MCP Resources)**：
   - 將 RAG 視為一種標準 Tool。實作一個模擬的知識庫檢索 Skill (`mcp_rag_knowledge_search`)，讓 Agent 在動手查系統前，能先檢索過去的除錯 SOP。
3. **混合式資料蒐集 (Hybrid Data Collection)**：
   - **主動型 (Type B)**：Agent 自主呼叫 API 或 RAG 獲取資訊。
   - **被動型 (Type A)**：Agent 發現資訊不足時，能中止工具執行，向使用者發問要求補充資訊。
4. **診斷報告產出**：所有 Skill 執行完畢後，LLM 必須統整資料，輸出 Markdown 格式的「原因分析與解決建議」。

### ❌ Out-of-Scope (本次絕對不做)
1. **自動修復 (Auto-Remediation)**：Agent 絕對不具備寫入系統、重啟服務的權限。所有結論僅供人類參考。
2. **綁死特定領域 (Domain Hardcoding)**：禁止在核心路由邏輯中寫死任何具體的排障邏輯（如 `if error == '500': do_something`）。必須完全交由 LLM 根據 Skill 描述動態判斷。
3. **真實外部系統串接**：MVP 階段的 Tools 皆為 Mock (模擬回傳固定值)，專注於驗證 Agent 的調度邏輯 (Agent Loop)。

## 3. 核心使用者故事 (User Stories)
- **[P0]** 身為開發者，我想要依照 JSON Schema 規範新增一個 Tool，系統就能自動將其註冊給 Agent 使用，無需修改核心路由。
- **[P1]** 身為使用者，我想要輸入一句「系統變好慢」，Agent 會先去查 RAG 找 SOP，接著自動呼叫 MCP 查 CPU，最後告訴我診斷結果。
- **[P2]** 身為維運人員，我想要在對話結束時，收到一份清楚的 Markdown 診斷報告，告訴我觸發了哪些工具、可能的原因與建議處置。

## 4. 系統與 API 期待 (System & API Expectations)
- **核心端點**：實作 `POST /api/v1/diagnose`，接收 JSON `{"issue_description": "問題描述"}` (需受 JWT 保護)。
- **MCP Tool 介面設計 (JSON Schema)**：
  開發者定義的 Skill 必須能轉換成如下格式供 LLM 解析：
  ```json
  {
    "name": "mcp_mock_cpu_check",
    "description": "查詢特定服務的當前 CPU 使用率",
    "inputSchema": {
      "type": "object",
      "properties": {
        "service_name": { "type": "string", "description": "服務名稱" }
      },
      "required": ["service_name"]
    }
  }