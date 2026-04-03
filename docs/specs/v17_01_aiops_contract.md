# Spec: aiops-contract

> 共同語言 Package — Agent 與 AIOps 的溝通標準

---

## Context & Objective

`aiops-contract` 是獨立於 Agent 和 AIOps 之外的第三方 package。它定義雙方的溝通語言（AIOps Report Contract），任何實作此 Contract 的前端都能接入 Agent，不被鎖定在特定應用。

---

## Project Structure

```
aiops-contract/
├── python/
│   ├── aiops_contract/
│   │   ├── __init__.py
│   │   ├── report.py          ← Pydantic schema
│   │   └── visualization.py   ← Visualization type definitions
│   ├── pyproject.toml
│   └── README.md
└── typescript/
    ├── src/
    │   ├── index.ts
    │   ├── report.ts           ← TypeScript interfaces
    │   └── visualization.ts
    ├── package.json
    └── tsconfig.json
```

---

## AIOps Report Contract Schema

### 完整結構

```json
{
  "$schema": "aiops-report/v1",
  "summary": "string — 給人類閱讀的根因結論或回應",
  "evidence_chain": [...],
  "visualization": [...],
  "suggested_actions": [...]
}
```

### EvidenceItem

```python
class EvidenceItem(BaseModel):
    step: int                    # 執行順序
    tool: str                    # mcp_name 或 skill_id
    finding: str                 # 一句話結論，給人類讀
    viz_ref: Optional[str]       # 對應 visualization[].id（可選）
```

### VisualizationItem

```python
class VisualizationItem(BaseModel):
    id: str                      # 唯一識別，供 evidence_chain 引用
    type: str                    # 見下方 Type Registry
    spec: dict                   # 對應 type 的 schema
```

**Visualization Type Registry：**

| type | renderer | spec schema |
|---|---|---|
| `vega-lite` | Vega-Embed (前端原生) | 標準 Vega-Lite JSON spec |
| `kpi-card` | 自訂 component | `{label, value, unit, trend}` |
| `topology` | 自訂 component (Cytoscape.js) | `{nodes: [...], edges: [...]}` |
| `gantt` | 自訂 component | `{tasks: [{id, label, start, end}]}` |
| `table` | 自訂 component | `{columns: [...], rows: [...]}` |

未知 type → 前端顯示 unsupported placeholder，不 crash。

### SuggestedAction

```python
class SuggestedAction(BaseModel):
    label: str                                        # 按鈕文字
    trigger: Literal["agent", "aiops_handoff"]

    # trigger = "agent"
    message: Optional[str]                            # 帶入 Agent 的 next message

    # trigger = "aiops_handoff"
    mcp: Optional[str]                                # AIOps Handoff MCP name
    params: Optional[dict]
```

**trigger 行為差異：**
- `agent` — User 點擊後，AIOps 以 `message` 重新觸發 Agent
- `aiops_handoff` — AIOps 直接呼叫對應 MCP，接管該功能的 UI 互動

### 完整 Pydantic Model

```python
class AIOpsReportContract(BaseModel):
    schema_version: str = "aiops-report/v1"
    summary: str
    evidence_chain: List[EvidenceItem] = []
    visualization: List[VisualizationItem] = []
    suggested_actions: List[SuggestedAction] = []
```

---

## TypeScript Interface

```typescript
export interface AIOpsReportContract {
  $schema: "aiops-report/v1";
  summary: string;
  evidence_chain: EvidenceItem[];
  visualization: VisualizationItem[];
  suggested_actions: SuggestedAction[];
}

export interface EvidenceItem {
  step: number;
  tool: string;
  finding: string;
  viz_ref?: string;
}

export interface VisualizationItem {
  id: string;
  type: "vega-lite" | "kpi-card" | "topology" | "gantt" | "table" | string;
  spec: Record<string, unknown>;
}

export type SuggestedAction =
  | { label: string; trigger: "agent"; message: string }
  | { label: string; trigger: "aiops_handoff"; mcp: string; params?: Record<string, unknown> };
```

---

## 安裝方式（Pre-production）

**aiops-agent（Python）：**
```bash
pip install -e ../aiops-contract/python
```

**aiops-app（TypeScript）：**
```bash
npm install ../aiops-contract/typescript
```

---

## Edge Cases

| 情況 | 處理 |
|---|---|
| `evidence_chain` 為空 | 允許，前端不渲染 evidence section |
| `visualization` 為空 | 允許，只顯示 summary |
| `suggested_actions` 為空 | 允許，不顯示 action buttons |
| 未知 `visualization.type` | 前端顯示 placeholder，記 console warning |
| `vega-lite` spec 格式錯誤 | Vega-Embed 內建 error boundary |

---

*最後更新：2026-03-21*
