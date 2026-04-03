# OntologySimulator — API v2 Reference

**Base URL:** `http://localhost:8001`
**Prefix:** `/api/v2/ontology/`

---

## 1. GET /api/v2/ontology/context

**Graph Context Service — SPC OOC 根因展開**

給定一個 `(lot_id, step)` 組合，瞬間展開所有關聯節點，回傳一個巢狀 JSON，包含 Tool / Recipe / APC / DC / SPC 五個子系統的快照。

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `lot_id` | string | ✅ | Lot ID，e.g. `LOT-0007` |
| `step` | string | ✅ | Step ID，e.g. `STEP_045` |
| `ooc_only` | bool | ❌ | `true` = 只取 OOC 事件（預設 `false`）|

**回傳結構：**
```json
{
  "root":   { "lot_id", "step", "event_id", "event_time", "spc_status", "recipe_id", "apc_id", "tool_id" },
  "tool":   { "tool_id", "status" },
  "recipe": { "objectID", "objectName", "parameters": { 20 params } },
  "apc":    { "objectID", "objectName", "parameters": { 20 params } },
  "dc":     { "objectID", "objectName", "parameters": { 30 sensors } },
  "spc":    { "objectID", "objectName", "spc_status", ... }
}
```

任一子節點缺失時，該節點附加 `"orphan": true`。

**範例：**
```
GET /api/v2/ontology/context?lot_id=LOT-0001&step=STEP_004&ooc_only=true
```

---

## 2. GET /api/v2/ontology/fanout/{event_id}

**Ontology Audit Service — 單一事件扇出追蹤**

給定 MongoDB ObjectId，追蹤該事件產生的 4 條子系統連結，用於 Sankey 圖渲染。

| 路徑參數 | 說明 |
|----------|------|
| `event_id` | MongoDB ObjectId 字串 |

**回傳結構：**
```json
{
  "event_id": "...",
  "eventTime": "...",
  "lotID": "LOT-0007",
  "toolID": "EQP-08",
  "step": "STEP_048",
  "spc_status": "OOC",
  "subsystems": {
    "APC":    { "object_id", "snapshot_id", "snapshot_exists", "master_exists", "orphan", "parameters" },
    "RECIPE": { "object_id", "snapshot_id", "snapshot_exists", "master_exists", "orphan", "parameters" },
    "DC":     { "object_id", "snapshot_id", "snapshot_exists", "master_exists": null, "orphan", "sensor_count" },
    "SPC":    { "object_id", "snapshot_id", "snapshot_exists", "master_exists": null, "orphan", "spc_status" }
  }
}
```

`orphan: true` = 連結斷裂（Sankey 紅色火花的觸發條件）。

---

## 3. GET /api/v2/ontology/orphans

**Orphan Scanner — 孤兒偵測**

掃描最近事件，找出「索引存在但 Snapshot 文件遺失」的孤兒記錄。

| 參數 | 型別 | 說明 |
|------|------|------|
| `limit` | int | 最多回傳幾個孤兒事件（1–500，預設 50）|

**回傳結構：**
```json
{
  "total_orphans": 0,
  "orphans": [
    {
      "event_id": "...",
      "eventTime": "...",
      "lotID": "...",
      "toolID": "...",
      "step": "...",
      "broken_links": [{ "subsystem": "DC", "missing_id": "..." }]
    }
  ]
}
```

健康系統回傳 `total_orphans: 0`。

**範例：**
```
GET /api/v2/ontology/orphans?limit=20
```

---

## 4. GET /api/v2/ontology/trajectory/{lot_id}

**Lot-Centric Trace — 批次生命週期時間軸**

給定 Lot ID，按時間順序回傳它經歷的所有 Step，每筆含完整複合鍵。

| 路徑參數 | 說明 |
|----------|------|
| `lot_id` | Lot ID，e.g. `LOT-0007` |

**回傳結構：**
```json
{
  "lot_id": "LOT-0007",
  "total_steps": 63,
  "steps": [
    {
      "event_id": "...",
      "step": "STEP_001",
      "event_time": "2026-03-12T14:39:59Z",
      "tool_id": "EQP-09",
      "recipe_id": "RCP-001",
      "apc_id": "APC-001",
      "dc_snapshot_id": "...",
      "spc_snapshot_id": "...",
      "spc_status": "PASS"
    }
  ]
}
```

`spc_status` 為 `"OOC"` 時，UI 以橙色高亮該 Step。

**UI 使用位置：** TRACE 模式 → Timeline 旁「Lot Trace」子 tab

---

## 5. GET /api/v2/ontology/indices/{object_type}

**Object-Centric Index Explorer — 物件索引瀏覽器**

列出指定子系統物件的最新 N 筆快照索引（含完整 payload），按 eventTime 降序排列。

| 路徑參數 | 值 |
|----------|----|
| `object_type` | `APC` \| `RECIPE` \| `DC` \| `SPC` |

| 查詢參數 | 型別 | 說明 |
|----------|------|------|
| `limit` | int | 最多回傳幾筆（1–200，預設 50）|

**回傳結構：**
```json
{
  "object_type": "APC",
  "count": 50,
  "records": [
    {
      "index_id": "...",
      "object_id": "APC-042",
      "event_time": "2026-03-14T10:22:11Z",
      "lot_id": "LOT-0007",
      "tool_id": "EQP-05",
      "step": "STEP_042",
      "payload": {
        "objectName": "APC",
        "objectID": "APC-042",
        "parameters": { "param_01": 0.0341, "param_02": 1.012, ... }
      }
    }
  ]
}
```

`payload` 含完整快照，UI 點擊列即可直接渲染 JSON Inspector，無需第二次請求。

**UI 使用位置：** TRACE 模式 → Timeline 旁「Obj Index」子 tab

---

## v1 常用端點（參考）

| 端點 | 說明 |
|------|------|
| `GET /api/v1/status` | Simulator 狀態摘要 |
| `GET /api/v1/audit` | Sankey 圖所需的 Index/Object 計數與比率 |
| `GET /api/v1/events?toolID=EQP-01&limit=50` | 指定機台的事件列表 |
| `GET /api/v1/context/query?objectName=APC&targetID=APC-042&step=STEP_042&eventTime=...` | Time-Machine 查詢（APC/RECIPE/DC/SPC/LOT/TOOL）|
| `GET /api/v1/analytics/history?targetID=LOT-0007&objectName=APC&limit=50` | 歷史快照序列（用於趨勢圖）|

---

## 版本說明

| 版本 | 新增 |
|------|------|
| v2.2 | `/context`, `/fanout/{id}`, `/orphans` |
| v2.2.1 | `/trajectory/{lot_id}`, `/indices/{object_type}` |
