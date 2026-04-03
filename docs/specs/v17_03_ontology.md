# Spec: ontology

> AIOps 的資料服務層 — 工廠語意資料的唯一來源

---

## Context & Objective

`ontology` 是 `aiops-app` 的內部資料服務，提供工廠語意資料（設備、批次、製程參數、事件）的查詢介面。

**核心原則：**
- ontology 是 AIOps 的內部資產，**Agent 不直接呼叫它**
- Agent 透過 AIOps 暴露的 MCP 間接取得 ontology 資料
- ontology-simulator 在開發環境 mirror 此服務的 API 介面

---

## Tech Stack

- **Framework:** Python (FastAPI)
- **資料存儲:** 依生產環境決定（SQL / time-series DB）
- **介面:** REST API

---

## Project Structure

```
ontology/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── equipment.py     ← 設備查詢
│   │       ├── dc_data.py       ← DC 時序資料
│   │       ├── events.py        ← 事件記錄
│   │       ├── lots.py          ← Lot 追蹤
│   │       └── spc.py           ← SPC 資料
│   ├── models/                  ← 資料模型
│   ├── services/                ← 業務邏輯
│   └── main.py
├── pyproject.toml
└── README.md
```

---

## API 介面（供 aiops-app 使用）

> 這些是 ontology 對 aiops-app 的內部 API，不對 Agent 暴露。

### 設備資料

```
GET  /api/v1/equipment/{equipment_id}/status
GET  /api/v1/equipment/list
GET  /api/v1/equipment/{equipment_id}/dc/timeseries
     ?param=Temperature&start=2026-03-21T00:00:00&end=2026-03-21T23:59:59
```

### 事件記錄

```
GET  /api/v1/events
     ?equipment_id=EQP-01&start=...&end=...
```

### Lot 追蹤

```
GET  /api/v1/lots/{lot_id}/trace
GET  /api/v1/lots/search?equipment_id=EQP-01&date=2026-03-21
```

### SPC 資料

```
GET  /api/v1/spc/{equipment_id}/{parameter}
     ?start=...&end=...
```

---

## 與 ontology-simulator 的關係

ontology-simulator 完整 mirror 上述 API 介面，使用模擬資料。
開發環境時，aiops-app 將 ontology base URL 指向 simulator（`http://localhost:8099`）。

**重要：** ontology 的 API 介面變更時，ontology-simulator 必須同步更新。

---

## 資料模型（核心概念）

```
Equipment (設備)
    ├── DC Parameters (量測參數時序)
    ├── Events (設備事件)
    └── Status (即時狀態)

Lot (批次)
    ├── Trace (在各設備的流轉記錄)
    └── Yield (良率資料)

SPC (Statistical Process Control)
    ├── Control Limits (UCL/LCL)
    └── OOC Events (超標事件)
```

---

## Edge Cases & Risks

| 風險 | 處理方式 |
|---|---|
| 查詢時間範圍過大 | API 強制限制最大時間範圍，回傳 400 |
| 設備 ID 不存在 | 回傳 404 |
| 資料庫連線失敗 | 回傳 503，aiops-app 顯示 data unavailable |

---

*最後更新：2026-03-21*
