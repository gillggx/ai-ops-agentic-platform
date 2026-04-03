# v17 系統架構總覽

> 本文件記錄 v17 架構重建的所有核心決策，是 5 個 project spec 的共同基礎。

---

## 三層架構

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: AIOps App  (觸發 + 渲染)                   │
│  - 接收 User 操作                                     │
│  - 將 User 意圖轉給 Agent                             │
│  - 收到 Contract 後無腦渲染                           │
│  - 擁有 ontology 整合                                 │
└─────────────────────┬───────────────────────────────┘
                      │  共同語言 (AIOps Report Contract)
┌─────────────────────▼───────────────────────────────┐
│  Layer 2: aiops-contract  (獨立 Package)             │
│  - 雙方的共同語言，誰都不擁有它                        │
│  - Python package + TypeScript package               │
│  - Vega-Lite extended with AIOps domain schema       │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│  Layer 3: aiops-agent  (推理 + 決策微服務)            │
│  - 完全不知道 UI 的存在                               │
│  - 只透過 MCP/Skill 與外界互動                        │
│  - 輸出 AIOps Report Contract                        │
└─────────────────────────────────────────────────────┘
```

---

## 5 個 Project 與職責

| Project | 職責 | 技術棧 | 依賴 |
|---|---|---|---|
| `aiops-contract` | 共同語言 schema 定義 | Python + TypeScript | 無 |
| `aiops-app` | AIOps 應用，渲染，擁有 ontology 整合 | Next.js (TypeScript) | aiops-contract |
| `ontology` | AIOps 的資料服務 | Python (FastAPI) | 無 |
| `aiops-agent` | AI 推理微服務，只有 MCP/Skill | Python (FastAPI) | aiops-contract |
| `ontology-simulator` | Dev 用，mirror ontology 介面 | Python (FastAPI) | ontology (介面) |

---

## 依賴關係圖

```
aiops-contract (共同語言，無依賴)
      │
      ├──────────────────────────────┐
      ▼                              ▼
aiops-agent                      aiops-app
(只有 MCP/Skill)                  (應用 + 渲染)
      │                              │
      │  呼叫 MCP                     │ 擁有
      └──── MCP catalog ◀────────── ontology
                                     │
                            dev mirrors│
                          ontology-simulator
```

**核心原則：Agent 永遠不直接碰 ontology。** ontology 是 AIOps 的內部資產，AIOps 決定哪些能力包成 MCP 暴露給 Agent。

---

## 建置順序與原因

```
1. aiops-contract      ← 語言先定義，其他都依賴它
2. aiops-app           ← 建好 AIOps 的能力邊界與 MCP catalog
3. ontology            ← app 的資料層
4. aiops-agent         ← 此時有真實 MCP 可對接，不對空氣寫
5. ontology-simulator  ← dev 工具最後
```

**原因：** Agent 是在已知 AIOps 能力的前提下建的，MCP catalog 才是真實可用的，避免「Agent 先建好，AIOps 後來不長那樣」的耦合風險。

---

## AIOps MCP 的兩種類型

| 類型 | 行為 | 範例 |
|---|---|---|
| **Data MCP** | Agent 呼叫 → 拿到資料 → 繼續推理 | `get_dc_timeseries`, `get_event_log` |
| **Handoff MCP** | Agent 呼叫 → AIOps 接手 → User 直接與 AIOps 互動 | `open_lot_trace`, `open_drill_down` |

Handoff MCP 呼叫後 Agent 不等結果，直接完成這條執行線。

---

## Package 發布策略

- **Pre-production：** local path install（`pip install -e ../aiops-contract` / `npm link`）
- **Production：** 穩定後發布至 private PyPI + private npm registry
- **版本管理：** production 前不強制 semantic versioning

---

## 架構決策記錄 (ADR)

| # | 決策 | 原因 |
|---|---|---|
| ADR-01 | Contract 作為獨立 project | 避免 Agent 與 AIOps 互相依賴，任何前端只要實作 Contract 就能接 Agent |
| ADR-02 | Agent 只有 MCP/Skill，不直接碰 ontology | ontology 是 AIOps 的內部資產，Agent 不應知道它的存在 |
| ADR-03 | Rendering standard 採用 Vega-Lite extended | LLM 生成 Vega-Lite 能力強；extend 自訂 type 解決 AIOps domain 特有需求 |
| ADR-04 | 前端統一 Next.js | ontology-simulator 已用 Next.js，TypeScript types 可直接共用 |
| ADR-05 | 5 個獨立 repo，不用 monorepo | 真正的微服務邊界；pre-production 用 local path install 降低 overhead |
| ADR-06 | 先建 App 再建 Agent | Agent 建立時有真實 MCP catalog 可對接 |
| ADR-07 | MCP/Skill 是 domain knowledge，不是 Agent 的 | MCP/Skill 由 domain expert 在 AIOps 定義，Agent 只有「使用它們的能力」，不擁有它們的定義。Agent 可以被替換（Claude → GPT → 自建模型），MCP/Skill catalog 不受影響。同一個 Agent 換一套 catalog 就能服務不同 domain。 |
| ADR-08 | Agent 不 hardcode 任何 MCP/Skill 名稱 | 所有 MCP/Skill 從 AIOps catalog API 動態載入，Agent 程式碼內不能出現任何 domain-specific 的工具名稱或邏輯 |

---

## AIOps App 功能全景

`aiops-app` 有兩個面向，都在同一個 project：

### User 面（已建）
- Chat UI + Agent Console（S0–S6 stage 追蹤、HITL、token 計數）
- ContractRenderer（vega-lite、kpi-card、evidence chain、suggested actions）

### Admin/Expert 面（待建，從原系統 migrate）
| 功能 | 說明 | 原系統對應 |
|---|---|---|
| MCP Builder | 定義 AIOps 暴露給 Agent 的 MCP（資料源、processing script、參數） | `app.js` MCP Builder tab |
| Skill Builder | 定義診斷邏輯（Event → MCP → 結論規則） | `app.js` Skill Builder tab |
| Data Subject 管理 | 定義資料源與 API 連線 | `app.js` Data Subject tab |
| Event Type Builder | 定義異常事件類型與屬性 | `app.js` Event Type tab |
| 設定 / Soul Prompt | Agent 推理個性設定（屬於 aiops-agent，從 aiops-app 提供 UI） | `app.js` Settings tab |

**MCP Registry 的資料流：**
```
Expert 在 MCP Builder 建立 MCP
    │
    ▼
MCP Registry（aiops-app DB）
    │
    │  Agent S1 每次對話時 pull
    ▼
GET /api/mcp-catalog
    │
    ▼
Agent system prompt（動態注入，不 hardcode）
```

---

*最後更新：2026-03-21*
