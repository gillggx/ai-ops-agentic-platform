# AIOps — Product Spec

_Last updated: 2026-03-21_

---

## 1. System Overview

AIOps 是一套針對半導體製程的 AI 輔助運營平台，整合真實 OntologySimulator（10 台設備、MongoDB、5~8 min/step）作為資料來源，
透過 Next.js 前端、FastAPI AI Agent 提供：

- 設備即時監控（Overview）
- 事件紀錄與診斷（Events）
- 製程本體論拓撲視圖（Topology Canvas）
- AI Co-Pilot（chat + SSE streaming + contract card）

---

## 2. Architecture

```
Browser (Next.js :3000)
  ├── /                  → Overview Dashboard (equipment grid + KPI)
  ├── /events            → Event log (all 10 EQPs, filter by severity/equipment)
  ├── /topology?lot=...  → Ontology Topology Canvas
  └── /admin             → MCP / Skill builder

Next.js API Routes (/api/...)
  ├── /api/ontology/[...path]  → Ontology Adapter (proxies to OntologySimulator)
  └── /api/agent/chat          → AI Agent (proxies to FastAPI :8001, SSE stream)

FastAPI AI Agent (:8001)
  └── tool_dispatcher.py  → MCP → OntologySimulator API mapping

OntologySimulator (:8012)  ← MongoDB semiconductor_sim
  ├── /api/v1/tools            → 10 equipment current status
  ├── /api/v1/lots             → 20 lots (Processing / Waiting / Finished)
  ├── /api/v1/events           → process events (lotID / toolID filter)
  ├── /api/v1/analytics/history → object snapshots (DC / SPC / APC / RECIPE)
  └── /api/v1/context/query    → Time-Machine: fetch object state at given eventTime
```

---

## 3. Data Model — OntologySimulator Event

Each process step produces one event document (stored in MongoDB `events` collection):

```json
{
  "eventTime":     "2026-03-21T10:12:46Z",
  "lotID":         "LOT-0005",
  "toolID":        "EQP-08",
  "step":          "STEP_001",
  "recipeID":      "RCP-015",
  "apcID":         "APC-072",
  "dcSnapshotId":  "<ObjectId>",
  "spcSnapshotId": "<ObjectId>",
  "spc_status":    "OOC",
  "eventType":     "LOT_EVENT"
}
```

Object types per event:

| Object  | Storage              | Key Fields                                      |
|---------|----------------------|-------------------------------------------------|
| DC      | object_snapshots     | `parameters: {sensor_01..sensor_30: number}`   |
| SPC     | object_snapshots     | `charts: {xbar/r/s/p/c: {value,ucl,lcl}}`, `spc_status` |
| APC     | object_snapshots     | `parameters: {etch_time_offset, rf_power_bias, ...}` |
| RECIPE  | object_snapshots     | `parameters: {step_time, rf_power, ...}`        |
| TOOL    | tools collection     | `tool_id`, `status`, `current_lot`              |
| LOT     | lots collection      | `lot_id`, `status`, `current_step`              |

---

## 4. Feature Spec — Ontology Topology Canvas

### 4.1 核心概念

Topology Canvas 以**任意物件為中心**，展示它在某次製程事件中與其他物件的關係。

- **中心節點**：使用者選定的物件（LOT / TOOL / RECIPE / APC）
- **周邊節點**：該製程事件中所有相關物件（固定展示：LOT、TOOL、RECIPE、APC、DC、SPC）
- **底部 Timeline**：該物件所有歷史製程事件，點選後 topology 更新至該 snapshot

### 4.2 頁面佈局（Light Mode）

```
┌──────────────────────────────────────────────────────────────┐
│  Topbar (existing light topbar with nav)                      │
├──────────────┬───────────────────────────────────────────────┤
│ Left sidebar │  Topology Canvas (SVG, light bg)              │
│ (240px)      │                                               │
│  Object Type │   [TOOL] ─ ─ [CENTER] ─ ─ [RECIPE]          │
│  ○ LOT       │   [DC]  ─ ─     ○     ─ ─ [APC]             │
│  ○ TOOL      │   [SPC] ─ ─              ─ ─ ...             │
│  ○ RECIPE    │                                               │
│  ○ APC       │   (click node → right side detail panel)      │
│              ├───────────────────────────────────────────────┤
│  Object List │  Timeline (past events for selected object)   │
│  LOT-0001    │  ──●──────────────────────────────────●──    │
│  LOT-0002 ●  │    ○ Start  ─ OOC End  ─ Pass End            │
│  ...         │                                               │
└──────────────┴───────────────────────────────────────────────┘
```

### 4.3 Left Sidebar

**Object Type 選擇**（radio/tab 形式）:

| Type      | 資料來源                         | 支援 |
|-----------|----------------------------------|------|
| LOT       | `GET /api/ontology/lots`         | ✅   |
| TOOL      | `GET /api/ontology/equipment`    | ✅   |
| RECIPE    | 從 recent events 推導            | 🔜   |
| APC       | 從 recent events 推導            | 🔜   |

**Object List**:
- 每筆顯示 ID + 狀態 badge
- 點擊 → 觸發 topology 更新（抓最新一次 event）
- 正在 Processing / Running 的物件優先排序

### 4.4 Topology Canvas 節點規格（Light Mode）

**中心節點**
- 圓形，直徑 80px
- 背景: `#ffffff`，邊框: `2px solid #2b6cb0`，`box-shadow: 0 0 0 6px #ebf4ff`
- 上方小標：物件類型（`LOT` / `TOOL` etc.）
- 中央：物件 ID（monospace，深色）
- 下方小標：步驟或狀態摘要

**周邊節點 (Rect cards)**
- 尺寸: 160 × 64px，rounded 8px
- 背景: `#ffffff`，邊框: `1px solid #e2e8f0`，左邊框 4px 彩色
- 陰影: `0 1px 3px #0000001a`
- 第一行: 類型標籤（彩色，11px，monospace，uppercase）
- 第二行: 物件 ID（`#1a202c`，monospace）
- 第三行: 狀態摘要（彩色小字）

節點顏色:

| 節點      | 顏色 (accent)  | 說明                         |
|-----------|---------------|------------------------------|
| LOT       | `#2b6cb0`     | 僅當 center 非 LOT 時顯示     |
| TOOL      | `#e53e3e`     | 永遠顯示                      |
| RECIPE    | `#2c7a7b`     | 永遠顯示                      |
| APC       | `#b83280`     | 永遠顯示                      |
| DC        | `#276749`     | 永遠顯示（30 sensors）        |
| SPC       | `#276749`(PASS) / `#c53030`(OOC) | 永遠顯示 |

**連線**: SVG `<line>`，`strokeDasharray="5 4"`，顏色 `#cbd5e0`

### 4.5 Detail Panel（點擊節點後，canvas 右側展開）

| 節點      | 顯示內容                                                  |
|-----------|----------------------------------------------------------|
| TOOL      | tool_id、status badge、current lot                       |
| DC        | 30 個 sensor 數值表（2~3 columns grid）                  |
| SPC       | 5 張 chart（xbar/r/s/p/c），每張 value bar + PASS/OOC   |
| APC       | parameter 清單（drift 後的值）                           |
| RECIPE    | recipe ID + parameters                                   |
| LOT       | lot_id、status、current_step                             |

### 4.6 底部 Timeline

- X 軸: 時間（所選物件的所有歷史事件，最多 200 筆）
- Tick mark 顏色:
  - 紅色: `spc_status === "OOC"`
  - 綠色: `spc_status === "PASS"`
  - 灰色: 其他
- 藍色豎線標記目前選中 event
- 點選 tick → topology 更新為該事件的 snapshot
- Context bar: `{TYPE} {ID} · {N} events · {X} OOC`

### 4.7 URL Schema

| 選擇                        | URL                                                          |
|-----------------------------|--------------------------------------------------------------|
| LOT 視角（預設最新事件）     | `/topology?type=lot&id=LOT-0005`                            |
| TOOL 視角（預設最新事件）    | `/topology?type=tool&id=EQP-06`                             |
| 指定歷史事件                 | `/topology?type=lot&id=LOT-0005&step=STEP_001&eventTime=...` |

---

## 5. Feature Spec — Overview Dashboard

### 5.1 Layout

3 欄：左 (220px equipment nav) | 中 (main) | 右 (360px AI co-pilot)

### 5.2 KPI Cards

| Card         | 資料來源                    |
|--------------|----------------------------|
| 稼動率       | running / total × 100%     |
| 執行中設備   | status = running count     |
| 警報/停機    | alarm + down count         |
| 維護中       | maintenance count          |

### 5.3 Equipment Grid

- 每台設備一張卡片
- 狀態色圈 + 名稱 + ID + status badge
- 點擊 → 進入 EquipmentDetail（DC timeseries chart + events）
- 「診斷」按鈕 → 送訊息給 AICopilot

---

## 6. API Adapter Routes (`/api/ontology/...`)

| Route                                             | 對應 OntologySimulator API                                       |
|---------------------------------------------------|------------------------------------------------------------------|
| `GET /equipment`                                  | `GET /api/v1/tools`                                              |
| `GET /equipment/:id`                              | `GET /api/v1/tools` (filter by tool_id)                         |
| `GET /equipment/:id/dc/timeseries?parameter=...`  | `GET /api/v1/analytics/history?targetID=&objectName=DC`          |
| `GET /events?equipment_id=&lot_id=&limit=`        | `GET /api/v1/events?toolID=|lotID=`                              |
| `GET /lots`                                       | `GET /api/v1/lots`                                               |
| `GET /lots/:id/objects?objectName=&step=`         | `GET /api/v1/analytics/history?targetID=&objectName=&step=`      |
| `GET /topology?lot=&step=&eventTime=`             | `GET /api/v1/context/query` × 4 (DC/SPC/APC/RECIPE in parallel) |

---

## 7. Tech Stack

| Layer     | Choice                  | Notes                                 |
|-----------|-------------------------|---------------------------------------|
| Frontend  | Next.js 15 (App Router) | TypeScript, inline styles             |
| Charts    | Vega-Lite (react-vega)  | DC timeseries, SPC control chart      |
| AI Stream | SSE (fetch + ReadableStream) | Agent → AICopilot streaming         |
| DB        | MongoDB (via OntologySimulator) | No direct access from frontend  |
| Agent     | FastAPI + Claude Haiku  | Tool calls → OntologySimulator        |

---

## 8. Environment Variables

```bash
# .env.local
AGENT_BASE_URL=http://localhost:8001
ONTOLOGY_BASE_URL=http://localhost:8012
```
