# Spec: aiops-app

> AIOps 應用層 — 觸發 Agent、擁有 ontology 整合、渲染 Contract

---

## Context & Objective

`aiops-app` 是使用者直接互動的應用。它負責：
1. 接收 User 操作，將意圖轉給 Agent
2. 擁有並整合 ontology 資料服務
3. 暴露 MCP catalog（Data MCP + Handoff MCP）供 Agent 使用
4. 收到 Agent 回傳的 AIOps Report Contract 後，無邏輯地渲染

**核心原則：** aiops-app 不包含任何診斷或推理邏輯，它只是一個有能力的渲染層和觸發點。

---

## Tech Stack

- **Framework:** Next.js (TypeScript)
- **Contract types:** `aiops-contract` (npm local install)
- **Visualization:** Vega-Embed（vega-lite）+ 自訂 components
- **API communication:** REST + SSE（接收 Agent stream）

---

## Project Structure

```
aiops-app/
├── src/
│   ├── app/                    ← Next.js App Router
│   │   ├── page.tsx            ← 主頁面
│   │   └── api/
│   │       └── agent/
│   │           └── chat/route.ts   ← proxy to aiops-agent
│   ├── components/
│   │   ├── contract/
│   │   │   ├── ContractRenderer.tsx    ← 主 renderer
│   │   │   ├── EvidenceChain.tsx
│   │   │   ├── SuggestedActions.tsx
│   │   │   └── visualizations/
│   │   │       ├── VegaLiteChart.tsx
│   │   │       ├── KpiCard.tsx
│   │   │       ├── TopologyView.tsx
│   │   │       ├── GanttChart.tsx
│   │   │       └── UnsupportedPlaceholder.tsx
│   │   └── chat/
│   │       └── ChatPanel.tsx
│   └── mcp/
│       ├── catalog.ts          ← MCP catalog 定義（Data + Handoff）
│       └── handlers/           ← 每個 MCP 的實作
├── package.json
└── tsconfig.json
```

---

## Contract Renderer

`ContractRenderer` 是 aiops-app 的核心 component，接收 `AIOpsReportContract` 並渲染。

```typescript
// ContractRenderer.tsx
import { AIOpsReportContract } from "aiops-contract";

export function ContractRenderer({ contract }: { contract: AIOpsReportContract }) {
  return (
    <div>
      <Summary text={contract.summary} />
      {contract.visualization.map(viz => (
        <VisualizationRenderer key={viz.id} item={viz} />
      ))}
      <EvidenceChain items={contract.evidence_chain} />
      <SuggestedActions actions={contract.suggested_actions} onTrigger={handleAction} />
    </div>
  );
}
```

**Visualization Type Registry：**

```typescript
const VISUALIZATION_REGISTRY: Record<string, ComponentType<{spec: any}>> = {
  "vega-lite":  VegaLiteChart,
  "kpi-card":   KpiCard,
  "topology":   TopologyView,
  "gantt":      GanttChart,
};

function VisualizationRenderer({ item }: { item: VisualizationItem }) {
  const Component = VISUALIZATION_REGISTRY[item.type] ?? UnsupportedPlaceholder;
  return <Component spec={item.spec} />;
}
```

---

## Suggested Actions 行為

```typescript
function handleAction(action: SuggestedAction) {
  if (action.trigger === "agent") {
    // 以 action.message 重新觸發 Agent
    sendToAgent(action.message);
  } else if (action.trigger === "aiops_handoff") {
    // 直接呼叫 AIOps 的 Handoff MCP，AIOps 接管 UI
    executeMCP(action.mcp, action.params);
  }
}
```

---

## MCP Catalog（暴露給 Agent）

AIOps 向 Agent 暴露兩類 MCP：

### Data MCP（Agent 呼叫，拿資料，繼續推理）

| MCP Name | 說明 | 資料來源 |
|---|---|---|
| `get_dc_timeseries` | 取機台 DC 時序資料 | ontology |
| `get_event_log` | 取設備事件記錄 | ontology |
| `get_tools_status` | 取機台狀態總覽 | ontology |
| `get_lot_trace` | 取 lot 追蹤資料 | ontology |
| `get_spc_data` | 取 SPC 統計製程控制資料 | ontology |

### Handoff MCP（Agent 呼叫，AIOps 接管 UI）

| MCP Name | 說明 | AIOps 行為 |
|---|---|---|
| `open_lot_trace` | 開啟 Lot Trace 面板 | 開啟 LotTraceView |
| `open_drill_down` | 開啟詳細下鑽頁面 | 開啟 DetailPanel |
| `open_topology` | 開啟拓撲視圖 | 開啟 TopologyView |

---

## Agent 觸發流程

```
User 輸入
    │
    ▼
ChatPanel → POST /api/agent/chat { message, session_id }
    │
    ▼
Next.js API Route → proxy to aiops-agent /api/v1/chat (SSE)
    │
    ▼
SSE stream → 解析 events
    ├── stage_update → 顯示進度
    ├── thinking     → 顯示推理過程
    ├── tool_start/done → 顯示工具執行
    └── synthesis    → 取出 contract → ContractRenderer
```

---

## Edge Cases & Risks

| 風險 | 處理方式 |
|---|---|
| Agent 回傳純文字（非 Contract） | fallback 到 markdown renderer |
| Handoff MCP 呼叫失敗 | toast 錯誤通知，不影響主流程 |
| Vega-Lite spec 無效 | VegaLiteChart 內建 error boundary |
| 未知 visualization type | UnsupportedPlaceholder component |
| SSE 中斷 | 顯示 reconnect 提示 |

---

*最後更新：2026-03-21*
