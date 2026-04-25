# aiops-contract — Spec

**Date:** 2026-04-25
**HEAD:** 5114b9b
**Status:** Living Document（依 code 實況萃取，非規劃文件）

---

## 1. 定位

雙語言 type-only 共享 lib。定義 **Agent ↔ Frontend** 之間流通的 `AIOpsReportContract`
schema — 後端 LLM Agent 產 contract dict，前端 React 元件依此 schema 渲染。

- **TypeScript pkg**：`aiops-app` 透過 `package.json` 的 `"file:../aiops-contract/typescript"` 直接 link，import 完整型別 + type guards
- **Python pkg**：pydantic models — *理論上*給 backend / sidecar import，但**目前實際上沒被任何 service import**（grep 0 命中）；後端 Agent 直接 hardcode `"$schema": "aiops-report/v1"` 字面值組 dict

`SCHEMA_VERSION = "aiops-report/v1"` — 兩邊各自定義，沒有單一來源。

## 2. 技術棧

| Side | Lang | Version | Build | Output |
|---|---|---|---|---|
| TypeScript | TS 5.9.3 | `typescript` 5.x devDep | `tsc` → `dist/` | CJS（`main: dist/index.js`）+ `.d.ts` |
| Python | Python ≥3.11 | `pydantic >= 2.0` | `hatchling` | wheel: `aiops_contract` package |

兩邊都沒有 runtime 依賴（pydantic 不算 — 是 schema 載體）。

## 3. 模組樹

```
aiops-contract/
├── typescript/
│   ├── package.json         name=aiops-contract@0.1.0, exports dist/
│   ├── tsconfig.json
│   └── src/
│       ├── index.ts         re-export of report.ts
│       ├── report.ts        ★ 158 LOC — schema + type guards
│       └── test_contract.ts 149 LOC（手寫 sample；非 test runner）
└── python/
    ├── pyproject.toml       hatchling, pydantic ≥2
    ├── aiops_contract/
    │   ├── __init__.py      re-export
    │   └── report.py        ★ 146 LOC — pydantic mirror
    └── tests/
        └── test_contract.py
```

## 4. Schema Surface

### 4.1 Root: `AIOpsReportContract`

| Field | Type | Required | Notes |
|---|---|---|---|
| `$schema` | `"aiops-report/v1"` | ✓ | 字面值；用作前端認證 |
| `summary` | string | ✓ | 給人讀的根因結論 |
| `evidence_chain` | `EvidenceItem[]` | ✓ | 推理過程每步 |
| `visualization` | `VisualizationItem[]` | ✓ | **legacy** — 新流程用 `charts` |
| `suggested_actions` | `SuggestedAction[]` | ✓ | 點擊按鈕 |
| `findings` | `SkillFindings?` | – | DR/AP-style 結果 |
| `output_schema` | `Array<dict>?` | – | 給 RenderMiddleware 用 |
| `charts` | `ChartDSL[]?` | – | 取代 `visualization` |

### 4.2 子型別

- **`EvidenceItem`** — `step / tool / finding / viz_ref` + 擴充 `step_id / nl_segment / python_code / status / output / error`
- **`VisualizationItem`** — `id / type / spec`，`type` 標準值：`"vega-lite" | "kpi-card" | "topology" | "gantt" | "table"`，未知 type 前端顯示 `UnsupportedPlaceholder`
- **`SuggestedAction`** — discriminated union：
  - `AgentAction { trigger: "agent", message }` — 觸發下一輪 Agent 對話
  - `HandoffAction { trigger: "aiops_handoff", mcp, params? }` — 移交給 AIOps UI
- **`SkillFindings`** — `condition_met / summary / outputs / evidence / impacted_lots`
- **`ChartDSL`**（TS only）— `type / title / data / x / y / rules? / highlight?`

### 4.3 Type Guards（TS only）

- `isAgentAction(action)`
- `isHandoffAction(action)`
- `isValidContract(value)` — runtime $schema check

Python pydantic 透過 `Union[AgentAction, HandoffAction]` 的 discriminator 自動判別。

## 5. 消費端清單

### TypeScript（`aiops-app`）

| File | 用法 |
|---|---|
| `package.json` | `"aiops-contract": "file:../aiops-contract/typescript"` |
| `src/context/AppContext.tsx` | type AIOpsReportContract |
| `src/components/contract/EvidenceChain.tsx` | render evidence_chain |
| `src/components/contract/SuggestedActions.tsx` | type guards + render |
| `src/components/contract/ContractRenderer.tsx` | root renderer |
| `src/components/copilot/ContractCard.tsx` | inline preview |
| `src/components/chat/ChatPanel.tsx` | parse + dispatch |
| `src/app/{lots,events}/page.tsx` | 顯示歷史 contract |

### Python（**未實際使用**）

```
$ grep -rn "from aiops_contract\|import aiops_contract" \
    fastapi_backend_service/ python_ai_sidecar/
(no matches)
```

`fastapi_backend_service/app/services/agent_orchestrator_v2/helpers.py` 與
`python_ai_sidecar/agent_orchestrator_v2/helpers.py` 都是 hardcode：

```python
"$schema": "aiops-report/v1",   # helpers.py L321, L413
if data.get("$schema") != "aiops-report/v1":   # L453
```

## 6. Build / Deploy

- **TS**：`cd aiops-contract/typescript && npm run build` → `dist/`。aiops-app 在 `npm install` 時透過 file: link 直接讀 `dist/`
- **Python**：`pip install ./aiops-contract/python`（沒人執行 — 各 service requirements.txt 沒列）
- 沒 CI、沒 publish 到 registry、沒版本 bump 流程

## 7. 已知缺口（Gap List）

1. **SCHEMA_VERSION 雙邊獨立** — TS / Python 各自宣告 `"aiops-report/v1"`，version bump 容易脫鉤
2. **Python 端是 vestigial** — pydantic models 完整但無人 import；要嘛開始用、要嘛廢掉省維護
3. **`ChartDSL` 只在 TS** — Python helpers.py 直接 emit dict，沒有 pydantic 對應
4. **沒有 schema validation test** — `tests/test_contract.py` 只是型別 instantiate sample，沒檢查跨語言一致
5. **沒 publish flow** — 任何 schema 修改要靠人工兩邊同步

## 8. 變更指南

新增 / 修改欄位時：
1. 改 `typescript/src/report.ts`（同步 type guard 若有 discriminator）
2. 改 `python/aiops_contract/report.py`（pydantic Field + alias 對齊 `$schema` 用法）
3. `cd typescript && npm run build` rebuild dist/
4. **不要** bump SCHEMA_VERSION，除非真的 break 舊 contract（現在 prod 沒版本 negotiation 機制）
5. 加新欄位請設 `Optional` 並有 default — 舊 Agent 不會發、舊 Frontend 不會炸
