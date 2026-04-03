# Spec: aiops-agent

> AI 推理微服務 — 只有 MCP/Skill，輸出 AIOps Report Contract

---

## Context & Objective

`aiops-agent` 是獨立的 AI 推理微服務。它完全不知道 UI 的存在，只透過 MCP/Skill 與外界互動，並輸出符合 `aiops-contract` 定義的 AIOps Report Contract。

**核心原則：**
- Agent 只能透過 MCP/Skill 取得資料或觸發操作
- Agent 不直接呼叫 ontology 或任何 AIOps 內部服務
- Agent 的輸出是 AIOps Report Contract，不是 free-form text

---

## Tech Stack

- **Framework:** Python (FastAPI)
- **Contract schema:** `aiops-contract` (pip local install)
- **LLM:** Claude (via Anthropic SDK)
- **SSE streaming:** 供 aiops-app 消費

---

## Project Structure

```
aiops-agent/
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── chat.py              ← SSE chat endpoint
│   ├── services/
│   │   ├── agent_orchestrator.py    ← S0-S6 pipeline
│   │   ├── tool_dispatcher.py       ← MCP/Skill 執行
│   │   ├── contract_builder.py      ← LLM 輸出 → AIOpsReportContract
│   │   ├── context_loader.py        ← S1 context 組裝
│   │   └── memory_service.py        ← RAG 記憶
│   ├── mcp/
│   │   └── catalog.py               ← 從 aiops-app 取得的 MCP catalog
│   └── main.py
├── pyproject.toml
└── README.md
```

---

## S0–S6 Pipeline（核心流程）

詳細行為見 `docs/agent-flow.md`，以下為 v17 的關鍵差異：

### S0 — Intent Router（不變）
- keyword fast-path → preference/chitchat/feedback/query
- preference/chitchat 直接回應，不走完整 pipeline

### S1 — Context Load（新增：Contract schema 注入）
- 載入 Soul Prompt、用戶偏好、RAG 記憶
- **新增：** 注入 AIOps Report Contract schema 定義到 system prompt

### S2 — Strategic Planning（不變）
- LLM 決定工具鏈與執行順序

### S3 — Tool Execution（新增：Evidence 追蹤）
- 執行 MCP/Skill
- **新增：** 每次 tool_done 後，將 `{step, tool, result_summary}` append 到 `_evidence_log`
- **新增：** Handoff MCP 偵測 — 若 MCP 標記為 `is_handoff=True`，fire-and-forget，不等結果

### S4 — Synthesis（核心變更：輸出 Contract）
- LLM 被指示輸出 `<contract>` tag 包住的 JSON
- `contract_builder.py` 負責 parse + validate → `AIOpsReportContract`
- SSE emit:
  ```json
  {"type": "synthesis", "contract": {...AIOpsReportContract...}, "text": "summary 摘要"}
  ```
- fallback：若 parse 失敗 → emit 純文字 synthesis（向下相容）

### S5 — Self-Reflection（不變）
- UI 展示用的 stage label

### S6 — Memory Learning（不變）
- 診斷記憶、偏好記憶、成功模式記憶寫入

---

## MCP Catalog

MCP catalog 由 aiops-app 提供，Agent 在 S1 載入。每個 MCP 定義包含：

```python
class MCPDefinition(BaseModel):
    name: str
    description: str
    parameters: dict          # JSON Schema
    is_handoff: bool = False  # True = Handoff MCP，fire-and-forget
```

**is_handoff 的 tool_dispatcher 行為：**
```python
if mcp.is_handoff:
    await call_mcp(mcp.name, params)  # 不等結果
    return {"status": "handoff", "mcp": mcp.name}
```

---

## Contract Builder

```python
# contract_builder.py

import re
from aiops_contract import AIOpsReportContract

def extract_contract(llm_output: str, evidence_log: list) -> AIOpsReportContract | None:
    match = re.search(r"<contract>(.*?)</contract>", llm_output, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        # 若 LLM 沒產出 evidence_chain，用 evidence_log 補
        if not data.get("evidence_chain"):
            data["evidence_chain"] = evidence_log
        return AIOpsReportContract(**data)
    except Exception:
        return None
```

---

## System Prompt Contract 指令（注入 S1）

```
你必須在回應結尾輸出以下格式的 Contract JSON，包在 <contract> tag 內：

<contract>
{
  "$schema": "aiops-report/v1",
  "summary": "...",
  "evidence_chain": [{"step": 1, "tool": "...", "finding": "..."}],
  "visualization": [{"id": "viz-0", "type": "vega-lite", "spec": {...}}],
  "suggested_actions": [{"label": "...", "trigger": "agent", "message": "..."}]
}
</contract>

visualization 必須使用 Vega-Lite spec 格式（type: "vega-lite"）。
若無需視覺化，visualization 可為空陣列。
```

---

## SSE 事件（v17 新增）

既有事件保留，新增：

```json
{"type": "synthesis", "contract": {...AIOpsReportContract...}, "text": "summary"}
{"type": "tool_handoff", "mcp": "open_lot_trace", "params": {...}}
```

---

## Edge Cases & Risks

| 風險 | 處理方式 |
|---|---|
| LLM 不產出 `<contract>` tag | fallback 到純文字 synthesis |
| Contract JSON 不合 schema | Pydantic validation 失敗 → fallback |
| Handoff MCP timeout | fire-and-forget，不影響主流程 |
| evidence_log 為空 | Contract 的 evidence_chain 為空陣列，合法 |
| Vega-Lite spec 由 LLM 生成錯誤 | 前端 Vega-Embed 有 error boundary |

---

## Migration 說明

現有 `fastapi_backend_refactored` 的核心邏輯將 migrate 至此 project：
- `agent_orchestrator.py` → 保留 S0-S6 架構，加入 evidence 追蹤與 contract 輸出
- `tool_dispatcher.py` → 加入 `is_handoff` 處理
- `context_loader.py` → 加入 Contract schema 注入
- `memory_service.py` → 直接搬移
- MCP catalog → 重新設計，從 aiops-app 動態載入

---

*最後更新：2026-03-21*
