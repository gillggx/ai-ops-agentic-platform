# OntologySimulator — Full API Reference

**Base URL（本機）：** `http://localhost:8001`
**版本：** v2.3（兩事件模型 ProcessStart / ProcessEnd）
**最後更新：** 2026-03-15

---

## 目錄

| 群組 | 端點數 | 說明 |
|------|--------|------|
| [V2 — 圖譜查詢](#v2-圖譜查詢) | 8 | 本體論上下文、軌跡、歷史、索引 |
| [V1 — 時光機查詢](#v1-時光機查詢) | 3 | 任意時刻快照、分析歷史 |
| [V1 — 監控](#v1-監控) | 5 | 狀態、Lot/Tool 清單、Events、Audit |
| [建議新增](#建議新增) | 5 | 尚未實作但已規劃 |

---

## 兩事件模型說明

每個 `(lot, tool, step)` 組合產生 **2 個事件**：

| 事件 | `process_status` | 捕獲對象 | 說明 |
|------|-----------------|---------|------|
| ProcessStart (t0) | `"ProcessStart"` | RECIPE + APC | 加工前配方載入 |
| ProcessEnd (t1) | `"ProcessEnd"` | DC + SPC | 加工後量測結果 |

查詢時預設回傳 `ProcessEnd`（含完整 4 對象）。指定 `process_status=ProcessStart` 只回傳 RECIPE + APC。

---

## V2 圖譜查詢

**Prefix：** `/api/v2/ontology`

---

### 1. `GET /api/v2/ontology/context`

**製程上下文查詢（最核心）**

給定 `(lot_id, step)`，一次展開所有關聯節點：Tool / Recipe / APC / DC / SPC。

**Query 參數：**

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `lot_id` | string | ✅ | e.g. `LOT-0007` |
| `step` | string | ✅ | e.g. `STEP_045` |
| `process_status` | string | ❌ | `ProcessStart`（只 Recipe+APC）或 `ProcessEnd`（全部，預設）|
| `ooc_only` | bool | ❌ | `true` = 只取有 OOC 的事件（預設 `false`）|

**回傳：**
```json
{
  "root": {
    "lot_id": "LOT-0007",
    "step": "STEP_045",
    "event_id": "...",
    "process_status": "ProcessEnd",
    "event_time": "2026-03-15T06:10:00",
    "start_time": "2026-03-15T06:09:00",
    "spc_status": "OOC",
    "recipe_id": "RCP-007",
    "apc_id": "APC-045",
    "tool_id": "EQP-03"
  },
  "tool":   { "tool_id": "EQP-03", "status": "Busy" },
  "recipe": { "objectID": "RCP-007", "objectName": "RECIPE", "parameters": { "etch_time_s": 30.5, ... } },
  "apc":    { "objectID": "APC-045", "objectName": "APC", "mode": "Run-to-Run", "parameters": { "etch_time_offset": 0.042, ... } },
  "dc":     { "objectID": "DC-LOT-0007-STEP_045-...", "objectName": "DC", "parameters": { "chamber_pressure": 15.2, ... } },
  "spc":    { "objectID": "SPC-LOT-0007-STEP_045-...", "objectName": "SPC", "spc_status": "OOC",
              "charts": { "xbar_chart": { "value": 18.1, "ucl": 17.5, "lcl": 12.5 }, ... } }
}
```

`process_status=ProcessStart` 時，`dc` 和 `spc` 欄位為 `null`（尚未量測）。
任一子節點遺失時附加 `"orphan": true`。

**範例：**
```
GET /api/v2/ontology/context?lot_id=LOT-0001&step=STEP_004
GET /api/v2/ontology/context?lot_id=LOT-0001&step=STEP_004&process_status=ProcessStart
GET /api/v2/ontology/context?lot_id=LOT-0001&step=STEP_004&ooc_only=true
```

---

### 2. `GET /api/v2/ontology/trajectory/lot/{lot_id}`

**Lot 製程軌跡**

按時間順序列出該 Lot 經過的所有 Step，每步合併 ProcessStart + ProcessEnd 資訊。

**路徑參數：** `lot_id` — e.g. `LOT-0007`

**回傳：**
```json
{
  "lot_id": "LOT-0007",
  "total_steps": 63,
  "steps": [
    {
      "step": "STEP_001",
      "tool_id": "EQP-09",
      "start_time": "2026-03-15T05:00:00",
      "end_time": "2026-03-15T05:00:45",
      "recipe_id": "RCP-001",
      "apc_id": "APC-001",
      "spc_status": "PASS",
      "dc_snapshot_id": "...",
      "spc_snapshot_id": "..."
    },
    {
      "step": "STEP_002",
      "tool_id": "EQP-04",
      "start_time": "2026-03-15T05:02:00",
      "end_time": null,
      "spc_status": null
    }
  ]
}
```

`end_time: null` 表示該步驟仍在加工中（⏳ in-progress）。

**範例：**
```
GET /api/v2/ontology/trajectory/lot/LOT-0007
```

---

### 3. `GET /api/v2/ontology/trajectory/tool/{tool_id}`

**設備作業歷史**

按時間順序列出該設備處理的所有批次，合併 ProcessStart + ProcessEnd。

**路徑參數：** `tool_id` — e.g. `EQP-03`

**Query 參數：**

| 參數 | 型別 | 說明 |
|------|------|------|
| `limit` | int | 最多回傳幾批（1–1000，預設 200）|
| `include_state_events` | bool | 是否含 HOLD / RELEASE 狀態事件（預設 false）|

**回傳：**
```json
{
  "tool_id": "EQP-03",
  "tool_info": { "tool_id": "EQP-03", "status": "Busy" },
  "total_batches": 150,
  "batches": [
    {
      "lot_id": "LOT-0007",
      "step": "STEP_045",
      "start_time": "2026-03-15T06:09:00",
      "end_time": "2026-03-15T06:10:00",
      "recipe_id": "RCP-007",
      "apc_id": "APC-045",
      "spc_status": "OOC",
      "dc_snapshot_id": "...",
      "spc_snapshot_id": "..."
    }
  ]
}
```

**範例：**
```
GET /api/v2/ontology/trajectory/tool/EQP-03?limit=50
GET /api/v2/ontology/trajectory/tool/EQP-03?include_state_events=true
```

---

### 4. `GET /api/v2/ontology/history/{object_type}/{object_id}`

**對象參數歷史（趨勢分析）**

取得單一對象隨時間的所有快照，用於參數漂移分析與趨勢圖。

**路徑參數：**

| 參數 | 值 |
|------|----|
| `object_type` | `APC` \| `RECIPE` \| `DC` \| `SPC` |
| `object_id` | e.g. `APC-045`, `RCP-007`, `DC-LOT-0007-STEP_045-...` |

**Query 參數：**

| 參數 | 型別 | 說明 |
|------|------|------|
| `limit` | int | 最多回傳幾筆（1–1000，預設 200）|

**回傳：**
```json
{
  "object_type": "APC",
  "object_id": "APC-045",
  "total_records": 150,
  "history": [
    {
      "snapshot_id": "...",
      "process_status": "ProcessStart",
      "event_time": "2026-03-15T06:09:00",
      "lot_id": "LOT-0007",
      "tool_id": "EQP-03",
      "step": "STEP_045",
      "spc_status": "OOC",
      "parameters": {
        "etch_time_offset": 0.042,
        "rf_power_bias": 1.02,
        "model_r2_score": 0.94
      }
    }
  ]
}
```

**APC 用途：** 觀察 `etch_time_offset`、`ff_correction` 等控制參數的逐步漂移趨勢。
**DC 用途：** 觀察 30 個感測器的時序讀數，辨識系統性偏移。

**範例：**
```
GET /api/v2/ontology/history/APC/APC-045?limit=100
GET /api/v2/ontology/history/DC/DC-LOT-0007-STEP_045-20260315061000000000?limit=50
```

---

### 5. `GET /api/v2/ontology/indices/{object_type}`

**對象索引瀏覽器**

列出指定子系統的最新 N 筆快照索引（含完整 payload），可依 OOC 狀態篩選。

**路徑參數：** `object_type` — `APC` | `RECIPE` | `DC` | `SPC`

**Query 參數：**

| 參數 | 型別 | 說明 |
|------|------|------|
| `limit` | int | 1–200，預設 50 |
| `status` | string | 篩選 `spc_status`，e.g. `OOC` 只看異常 |
| `process_status` | string | `ProcessStart` 或 `ProcessEnd` |

**回傳：**
```json
{
  "object_type": "SPC",
  "count": 12,
  "records": [
    {
      "index_id": "...",
      "object_id": "SPC-LOT-0007-STEP_045-...",
      "process_status": "ProcessEnd",
      "event_time": "2026-03-15T06:10:00",
      "lot_id": "LOT-0007",
      "tool_id": "EQP-03",
      "step": "STEP_045",
      "payload": {
        "spc_status": "OOC",
        "charts": { "xbar_chart": { "value": 18.1, "ucl": 17.5, "lcl": 12.5 }, ... }
      }
    }
  ]
}
```

**常用查詢：** `?object_type=SPC&status=OOC` — 取得目前所有 OOC 事件清單（Watchlist 用）。

**範例：**
```
GET /api/v2/ontology/indices/SPC?status=OOC&limit=20
GET /api/v2/ontology/indices/APC?process_status=ProcessStart&limit=50
```

---

### 6. `GET /api/v2/ontology/fanout/{event_id}`

**事件扇出追蹤（Sankey 圖用）**

給定 MongoDB ObjectId，展開該事件所有子系統連結，用於 Sankey 圖渲染或 RCA 深挖。

**路徑參數：** `event_id` — MongoDB ObjectId 字串

**回傳：**
```json
{
  "event_id": "...",
  "eventTime": "2026-03-15T06:10:00",
  "eventType": "TOOL_EVENT",
  "process_status": "ProcessEnd",
  "lotID": "LOT-0007",
  "toolID": "EQP-03",
  "step": "STEP_045",
  "spc_status": "OOC",
  "subsystems": {
    "APC":    { "object_id": "APC-045", "snapshot_id": "...", "snapshot_exists": true, "master_exists": true, "orphan": false, "parameters": { ... } },
    "RECIPE": { "object_id": "RCP-007", "snapshot_id": "...", "snapshot_exists": true, "master_exists": true, "orphan": false, "parameters": { ... } },
    "DC":     { "object_id": "DC-...", "snapshot_id": "...", "snapshot_exists": true, "master_exists": null, "orphan": false, "sensor_count": 30 },
    "SPC":    { "object_id": "SPC-...", "snapshot_id": "...", "snapshot_exists": true, "master_exists": null, "orphan": false, "spc_status": "OOC" }
  }
}
```

`orphan: true` = 快照遺失（Sankey 紅色火花觸發條件）。

---

### 7. `GET /api/v2/ontology/orphans`

**孤兒偵測**

找出「索引存在但 Snapshot 文件遺失」的孤兒記錄，用於資料品質監控。

**Query 參數：** `limit` int（1–500，預設 50）

**回傳：**
```json
{
  "total_orphans": 0,
  "orphans": [
    {
      "event_id": "...",
      "eventTime": "...",
      "process_status": "ProcessEnd",
      "lotID": "...", "toolID": "...", "step": "...",
      "broken_links": [{ "subsystem": "DC", "missing_id": "..." }]
    }
  ]
}
```

健康系統回傳 `total_orphans: 0`。

---

### 8. `GET /api/v2/ontology/enumerate`

**枚舉可用 ID**

回傳所有合法的 Lot / Tool / Step ID，供 UI 下拉選單使用。

**回傳：**
```json
{
  "lot_ids":  ["LOT-0001", "LOT-0002", ..., "LOT-0020"],
  "tool_ids": ["EQP-01", "EQP-02", ..., "EQP-10"],
  "steps":    ["STEP_001", "STEP_002", ..., "STEP_100"]
}
```

---

## V1 時光機查詢

**Prefix：** `/api/v1`

---

### 9. `GET /api/v1/context/query`

**時光機快照查詢**

給定任意 `eventTime`，回傳當時有效的對象快照。APC/RECIPE 依事件時間找最近版本；DC/SPC 找最近 ProcessEnd 快照（不受 eventTime 限制）。

**Query 參數：**

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `eventTime` | ISO8601 datetime | ✅ | 參考時間，e.g. `2026-03-15T06:00:00` |
| `step` | string | ✅ | e.g. `STEP_045` |
| `targetID` | string | ✅ | Lot ID 或 Tool ID 或 Object ID |
| `objectName` | string | ✅ | `APC` \| `RECIPE` \| `DC` \| `SPC` \| `LOT` \| `TOOL` |

**行為差異：**

| objectName | 查詢邏輯 |
|------------|---------|
| `LOT` / `TOOL` | 回傳即時 master state（不受時間限制）|
| `DC` / `SPC` | 找最近 ProcessEnd 事件（忽略 eventTime，因為 DC/SPC 只在 ProcessEnd 存在）|
| `APC` / `RECIPE` | Time-Machine：找 `eventTime ≤ 請求時間` 的最新快照 |

**範例：**
```
GET /api/v1/context/query?targetID=LOT-0007&step=STEP_045&objectName=SPC&eventTime=2026-03-15T06:00:00
GET /api/v1/context/query?targetID=EQP-03&step=STEP_045&objectName=APC&eventTime=2026-03-15T05:30:00
GET /api/v1/context/query?targetID=LOT-0007&step=STEP_045&objectName=LOT&eventTime=2026-03-15T06:00:00
```

---

### 10. `GET /api/v1/analytics/history`

**參數趨勢歷史**

依 targetID 取得指定對象類型的時序快照，最舊優先，適合折線圖渲染。

**Query 參數：**

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `targetID` | string | ✅ | `LOT-xxxx`（按 Lot）、`EQP-xx`（按 Tool）、`APC-xxx`（按對象 ID）|
| `objectName` | string | ✅ | `APC` \| `RECIPE` \| `DC` \| `SPC` |
| `limit` | int | ❌ | 1–500，預設 50 |
| `step` | string | ❌ | 指定步驟篩選，e.g. `STEP_045` |

**回傳：** 陣列，時序升序（最舊優先）。

**範例：**
```
GET /api/v1/analytics/history?targetID=EQP-03&objectName=DC&limit=100&step=STEP_045
GET /api/v1/analytics/history?targetID=LOT-0007&objectName=APC&limit=50
```

---

## V1 監控

---

### 11. `GET /api/v1/status`

**模擬狀態摘要**

```json
{
  "lots":  { "Waiting": 15, "Processing": 5 },
  "tools": { "Idle": 5, "Busy": 5 },
  "total_events": 132,
  "total_snapshots": 132
}
```

---

### 12. `GET /api/v1/lots`

**Lot 清單**

**Query 參數：** `status` string（`Waiting` \| `Processing` \| `Finished`，選填）

**回傳：** `[{ "lot_id", "current_step", "status", "cycle" }, ...]`

---

### 13. `GET /api/v1/tools`

**Tool 清單**

**回傳：** `[{ "tool_id", "status" }, ...]`

---

### 14. `GET /api/v1/events`

**事件時間線**

**Query 參數：** `toolID` string（選填）、`lotID` string（選填）、`limit` int（1–500，預設 50）

**回傳（最新優先）：**
```json
[
  {
    "eventTime": "2026-03-15T06:10:00",
    "eventType": "TOOL_EVENT",
    "status": "ProcessEnd",
    "lotID": "LOT-0007",
    "toolID": "EQP-03",
    "step": "STEP_045",
    "apcID": "APC-045",
    "recipeID": "RCP-007",
    "dcSnapshotId": "...",
    "spcSnapshotId": "...",
    "spc_status": "OOC"
  }
]
```

---

### 15. `POST /api/v1/tools/{tool_id}/acknowledge`

**設備 HOLD 確認**

解除機台 HOLD 狀態（模擬工程師點擊確認）。

**路徑參數：** `tool_id` — e.g. `EQP-03`

**回傳：** `{ "tool_id": "EQP-03", "released": true }`

---

### 16. `GET /api/v1/audit`

**資料稽核報告**

回傳各子系統的索引壓縮率、最新/最舊時間戳，以及 master 資料筆數。

```json
{
  "subsystems": {
    "APC":    { "index_entries": 850, "distinct_objects": 100, "compression_ratio": 8.5, "newest_event_time": "...", "oldest_event_time": "..." },
    "RECIPE": { "index_entries": 850, "distinct_objects": 20,  "compression_ratio": 42.5, ... },
    "DC":     { "index_entries": 430, "distinct_objects": 430, "compression_ratio": 1.0, ... },
    "SPC":    { "index_entries": 430, "distinct_objects": 430, "compression_ratio": 1.0, ... }
  },
  "event_fanout": { "TOOL_EVENT": 430, "LOT_EVENT": 430 },
  "master_data": { "recipe_versions": 20, "apc_models": 100, "lots": 20, "tools": 10 }
}
```

`compression_ratio` 說明：RECIPE 42.5x 意味著 20 個配方版本被引用了 850 次 — 每次製程都建立索引，但實際存儲只有 20 筆。

---

## 建議新增

以下端點尚未實作，但對 AI Agent 診斷場景具有高價值：

---

### A. `GET /api/v2/ontology/stats/ooc`

**OOC 統計摘要**

按時間窗口、機台、步驟聚合 OOC 比率，供 Watchlist 儀表板使用。

**建議 Query 參數：**

| 參數 | 型別 | 說明 |
|------|------|------|
| `tool_id` | string | 選填，篩選特定機台 |
| `step` | string | 選填，篩選特定步驟 |
| `window` | string | `1h` \| `8h` \| `24h`（預設 `24h`）|

**建議回傳：**
```json
{
  "window": "24h",
  "total_runs": 430,
  "total_ooc": 98,
  "ooc_rate_pct": 22.8,
  "by_tool": {
    "EQP-03": { "runs": 45, "ooc": 12, "ooc_rate_pct": 26.7 }
  },
  "by_step": {
    "STEP_045": { "runs": 20, "ooc": 8, "ooc_rate_pct": 40.0 }
  },
  "trending_chart": [
    { "sensor": "rf_forward_power", "breach_count": 42 },
    { "sensor": "chamber_pressure", "breach_count": 28 }
  ]
}
```

---

### B. `GET /api/v2/ontology/compare/tools`

**多機台同步驟比較**

在相同步驟下比較多台設備的 DC 感測器 / SPC 圖表，找出異常機台。

**建議 Query 參數：**

| 參數 | 型別 | 說明 |
|------|------|------|
| `step` | string | ✅ 目標步驟 |
| `limit_per_tool` | int | 每台機台取最近 N 筆平均（預設 10）|

**回傳**：各機台的感測器均值 + 標準差，標記偏離 fleet mean > 2σ 的機台。

---

### C. `GET /api/v2/ontology/compare/lots`

**Lot 間比較（Golden Lot 對照）**

比較兩個 Lot 在相同 Step 的快照差異，識別 recipe / APC / DC 異常。

**建議 Query 參數：**

| 參數 | 型別 | 說明 |
|------|------|------|
| `lot_id_a` | string | ✅ 目標 Lot（e.g. OOC Lot）|
| `lot_id_b` | string | ✅ 參考 Lot（e.g. Golden Lot）|
| `step` | string | ✅ 比較步驟 |

**回傳**：每個對象的參數 diff（`a_value`, `b_value`, `delta`, `delta_pct`）。

---

### D. `GET /api/v2/ontology/drift/{apc_id}`

**APC 漂移趨勢分析**

追蹤特定 APC 模型的控制參數隨運行次數的累積漂移。

**建議 Query 參數：** `limit` int（最近 N 次運行）

**回傳**：`etch_time_offset`、`ff_correction`、`model_r2_score` 等關鍵參數的時序 + drift_rate（每步驟平均漂移量）。

---

### E. `GET /api/v2/ontology/lot/{lot_id}/ooc_summary`

**Lot OOC 步驟摘要**

快速列出該 Lot 哪些步驟發生 OOC，以及觸發的 SPC 圖表，供快速篩選。

**回傳：**
```json
{
  "lot_id": "LOT-0007",
  "total_steps_completed": 63,
  "ooc_steps": [
    {
      "step": "STEP_045",
      "tool_id": "EQP-03",
      "event_time": "2026-03-15T06:10:00",
      "breached_charts": ["xbar_chart", "r_chart"],
      "breached_sensors": ["chamber_pressure", "bias_voltage_v"]
    }
  ]
}
```

---

## 物件參數速查表

### Recipe 參數（20 個）
| 欄位 | 單位 | 說明 |
|------|------|------|
| `etch_time_s` | s | 蝕刻時間 |
| `target_thickness_nm` | nm | 目標膜厚 |
| `etch_rate_nm_per_s` | nm/s | 蝕刻速率 |
| `cd_bias_nm` | nm | CD 偏移 |
| `over_etch_pct` | % | 過蝕刻 |
| `process_pressure_mtorr` | mTorr | 製程壓力 |
| `base_pressure_mtorr` | mTorr | 基礎壓力 |
| `chamber_temp_c` | °C | 腔體溫度 |
| `wall_temp_c` | °C | 腔壁溫度 |
| `cf4_setpoint_sccm` | sccm | CF4 設定 |
| `o2_setpoint_sccm` | sccm | O2 設定 |
| `ar_setpoint_sccm` | sccm | Ar 設定 |
| `he_setpoint_sccm` | sccm | He 設定 |
| `source_power_w` | W | 射頻源功率 |
| `bias_power_w` | W | 偏壓功率 |
| `source_freq_mhz` | MHz | 源頻率 |
| `bias_freq_khz` | kHz | 偏壓頻率 |
| `epd_threshold_au` | AU | 終點偵測閾值 |
| `min_etch_time_s` | s | 最小蝕刻時間 |
| `max_etch_time_s` | s | 最大蝕刻時間 |

### APC 參數（20 個）
| 欄位 | 單位 | 說明 |
|------|------|------|
| `etch_time_offset` | s | 蝕刻時間補正 |
| `rf_power_bias` | — | RF 功率偏置 |
| `gas_flow_comp` | sccm | 氣體流量補償 |
| `model_intercept` | — | 模型截距 |
| `target_cd_nm` | nm | 目標 CD |
| `target_epd_s` | s | 目標 EPD 時間 |
| `etch_rate_pred` | nm/min | 預測蝕刻速率 |
| `uniformity_pct` | % | 均勻度 |
| `ff_correction` | — | 前饋修正 |
| `ff_weight` | — | 前饋權重 |
| `ff_alpha` | — | 前饋學習率 |
| `lot_weight` | — | Lot 權重 |
| `fb_correction` | — | 回授修正 |
| `fb_alpha` | — | 回授學習率 |
| `model_r2_score` | — | 模型 R² |
| `stability_index` | — | 穩定性指標 |
| `prediction_error_nm` | nm | 預測誤差 |
| `convergence_idx` | — | 收斂指標 |
| `reg_lambda` | — | 正則化 λ |
| `response_factor` | — | 響應因子 |

### SPC 控制圖規格（5 個）
| 圖表 | 監控感測器 | LCL | UCL | 單位 |
|------|-----------|-----|-----|------|
| `xbar_chart` | `chamber_pressure` | 12.5 | 17.5 | mTorr |
| `r_chart` | `bias_voltage_v` | 820 | 880 | V |
| `s_chart` | `esc_zone1_temp` | 57.5 | 62.5 | °C |
| `p_chart` | `cf4_flow_sccm` | 44 | 56 | sccm |
| `c_chart` | `rf_forward_power` | 1430 | 1570 | W |

---

## 版本歷史

| 版本 | 日期 | 新增 |
|------|------|------|
| v2.0 | 2026-02 | 初始 v2 API（context, fanout, orphans）|
| v2.1 | 2026-02 | trajectory/lot, indices |
| v2.2 | 2026-03 | trajectory/tool, history, enumerate |
| **v2.3** | **2026-03-15** | **兩事件模型：ProcessStart/ProcessEnd split；`process_status` 參數；`start_time` 欄位；v1 DC/SPC fix** |
