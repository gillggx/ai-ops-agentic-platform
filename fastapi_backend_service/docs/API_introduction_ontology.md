# OntologySimulator v2 API — System MCP 使用手冊

> Simulator 環境：20 批次（LOT-0001 ～ LOT-0020）、10 台機台（EQP-01 ～ EQP-10）、100 個步驟（STEP_001 ～ STEP_100）
> Base URL：`http://localhost:8001/api/v2/ontology`
> 所有時間欄位格式：ISO 8601，e.g. `2026-03-15T05:55:16Z`

---

## 資料模型說明

每一次製程（一個 lot 在一台機台跑一個 step）會產生 **兩個事件**：

| 事件 | 時機 | 掛載物件 |
|------|------|---------|
| ProcessStart | 製程開始 | Recipe 快照、APC 參數快照 |
| ProcessEnd | 製程結束 | DC 量測值快照、SPC 結果快照 |

所有 API 都會自動將這兩個事件合併，對外呈現為「一次製程」。

---

## 1. `get_process_context` — 製程現場完整快照

**用途**：給定 lot_id + step，還原當下的完整製程情境（Recipe + APC + DC + SPC 一次全拿）。
**端點**：`GET /context?lot_id=&step=`
**最佳使用時機**：已從 trajectory 取得 lot_id + step，需要展開細節時。

### 參數

| 參數 | 必填 | 說明 |
|------|------|------|
| `lot_id` | ✅ | 批次 ID，e.g. `LOT-0002` |
| `step` | ✅ | 步驟代碼，e.g. `STEP_006` |
| `event_time` | ❌ | ProcessStart 時間（ISO8601），用於同一批次同一步驟有多次 cycle 時鎖定特定一次 |

### 回傳結構

```
{
  root:    { lot_id, step, process_status, in_progress, spc_status, recipe_id, apc_id, tool_id, start_time, end_time }
  tool:    { tool_id, status }
  recipe:  { objectID, parameters: { etch_time_s, target_thickness_nm, ... } }
  apc:     { objectID, parameters: { rf_power_bias, model_intercept, ... } }
  dc:      { objectID, parameters: { chamber_pressure, rf_forward_power, ... } }  ← ProcessEnd 才有
  spc:     { charts: { xbar_chart: {value, ucl, lcl}, ... }, spc_status }          ← ProcessEnd 才有
  summary: "一句 LLM 可直接引用的摘要"
}
```

> `root.in_progress = true` 表示步驟進行中，dc / spc 為 null。
> `root.spc_status = "OOC"` 是最重要的異常信號。

### Sample — LOT-0002 STEP_006（OOC 案例）

```json
{
  "root": {
    "lot_id": "LOT-0002",
    "step": "STEP_006",
    "process_status": "ProcessEnd",
    "in_progress": false,
    "spc_status": "OOC",
    "recipe_id": "RCP-001",
    "apc_id": "APC-006",
    "tool_id": "EQP-09",
    "start_time": "2026-03-15T05:58:15.596000Z",
    "event_time": "2026-03-15T05:58:49.987000Z"
  },
  "recipe": {
    "objectID": "RCP-001",
    "parameters": {
      "etch_time_s": 26.5511,
      "target_thickness_nm": 53.9051,
      "etch_rate_nm_per_s": 1.32,
      "cd_bias_nm": 1.7141,
      "process_pressure_mtorr": 16.7033,
      "source_power_w": 1533.7341,
      "bias_power_w": 372.3853,
      "cf4_setpoint_sccm": 49.9629,
      "o2_setpoint_sccm": 11.0886
    }
  },
  "apc": {
    "objectID": "APC-006",
    "parameters": {
      "rf_power_bias": 0.915354,
      "model_intercept": 0.385845,
      "etch_time_offset": 0.030775,
      "gas_flow_comp": 1.431836,
      "target_cd_nm": 48.480599,
      "model_r2_score": 0.782417,
      "stability_index": 0.962833
    }
  },
  "dc": {
    "objectID": "DC-LOT-0002-STEP_006-20260315055849987804",
    "parameters": {
      "chamber_pressure": 18.2522,
      "rf_forward_power": 1561.3306,
      "bias_voltage_v": 849.7714,
      "esc_zone1_temp": 60.118,
      "cf4_flow_sccm": 49.8257,
      "o2_flow_sccm": 10.0666,
      "throttle_position_pct": 56.3834
    }
  },
  "spc": {
    "spc_status": "OOC",
    "charts": {
      "xbar_chart": { "value": 18.2522, "ucl": 17.5, "lcl": 12.5 },
      "r_chart":    { "value": 849.7714, "ucl": 880.0, "lcl": 820.0 },
      "s_chart":    { "value": 60.118, "ucl": 62.5, "lcl": 57.5 }
    }
  },
  "summary": "[LOT-0002 @ EQP-09 STEP_006 | 2026-03-15 05:58:49 | Complete] | Recipe: RCP-001 | APC: APC-006 bias=0.9154 | DC: ProcessEnd | SPC: OOC"
}
```

---

## 2. `get_lot_trajectory` — 批次製程路徑

**用途**：查詢一個批次走過的所有步驟序列，每步驟一筆（已合併 ProcessStart + ProcessEnd）。
**端點**：`GET /trajectory/lot/{lot_id}`

### 參數

| 參數 | 必填 | 說明 |
|------|------|------|
| `lot_id` | ✅ | 批次 ID，e.g. `LOT-0002` |
| `start_time` | ❌ | 時間窗口起始（ISO8601） |
| `end_time` | ❌ | 時間窗口結束（ISO8601） |
| `limit` | ❌ | 回傳步驟數上限（預設 500） |

### 回傳結構

```
{
  lot_id:      "LOT-0002",
  total_steps: 5,
  steps: [
    {
      step, tool_id, start_time, end_time,
      recipe_id, apc_id,
      spc_status,           ← "PASS" / "OOC" / null（進行中）
      dc_snapshot_id,       ← 帶入 get_process_context 用
      spc_snapshot_id
    },
    ...
  ]
}
```

### Sample — LOT-0002（含兩個 OOC 步驟）

```json
{
  "lot_id": "LOT-0002",
  "total_steps": 5,
  "steps": [
    {
      "step": "STEP_004", "tool_id": "EQP-06",
      "start_time": "2026-03-15T05:55:16Z", "end_time": "2026-03-15T05:55:55Z",
      "recipe_id": "RCP-005", "apc_id": "APC-004",
      "spc_status": "PASS"
    },
    {
      "step": "STEP_005", "tool_id": "EQP-09",
      "start_time": "2026-03-15T05:57:35Z", "end_time": "2026-03-15T05:58:15Z",
      "recipe_id": "RCP-019", "apc_id": "APC-005",
      "spc_status": "PASS"
    },
    {
      "step": "STEP_006", "tool_id": "EQP-09",
      "start_time": "2026-03-15T05:58:15Z", "end_time": "2026-03-15T05:58:49Z",
      "recipe_id": "RCP-001", "apc_id": "APC-006",
      "spc_status": "OOC"
    },
    {
      "step": "STEP_007", "tool_id": "EQP-09",
      "start_time": "2026-03-15T05:58:49Z", "end_time": "2026-03-15T05:59:38Z",
      "recipe_id": "RCP-019", "apc_id": "APC-007",
      "spc_status": "OOC"
    },
    {
      "step": "STEP_008", "tool_id": "EQP-09",
      "start_time": "2026-03-15T05:59:38Z", "end_time": null,
      "recipe_id": "RCP-003", "apc_id": "APC-008",
      "spc_status": null
    }
  ]
}
```

> STEP_006、STEP_007 連續 OOC，STEP_008 進行中（`end_time = null`，`spc_status = null`）

---

## 3. `get_tool_trajectory` — 機台批次履歷

**用途**：查詢一台機台處理過的所有批次，每筆代表「此機台處理某批次某步驟」一次完整 run。
**端點**：`GET /trajectory/tool/{tool_id}`

### 參數

| 參數 | 必填 | 說明 |
|------|------|------|
| `tool_id` | ✅ | 機台 ID，e.g. `EQP-01` |
| `start_time` | ❌ | 時間窗口起始（ISO8601） |
| `end_time` | ❌ | 時間窗口結束（ISO8601） |
| `limit` | ❌ | 回傳批次數上限（預設 200） |

### 回傳結構

```
{
  tool_id: "EQP-01",
  tool_info: { tool_id, status },
  total_batches: N,
  batches: [
    { lot_id, step, start_time, end_time, recipe_id, apc_id, spc_status, dc_snapshot_id, spc_snapshot_id },
    ...
  ]
}
```

> 結果按 `start_time` 倒序（最新在前）。

### Sample — EQP-01 最近 3 批

```json
{
  "tool_id": "EQP-01",
  "tool_info": { "tool_id": "EQP-01", "status": "Busy" },
  "total_batches": 3,
  "batches": [
    {
      "lot_id": "LOT-0018", "step": "STEP_002",
      "start_time": "2026-03-15T05:57:02Z", "end_time": "2026-03-15T06:57:44Z",
      "recipe_id": "RCP-007", "apc_id": "APC-002",
      "spc_status": "PASS"
    },
    {
      "lot_id": "LOT-0012", "step": "STEP_003",
      "start_time": "2026-03-15T05:56:15Z", "end_time": "2026-03-15T05:57:02Z",
      "recipe_id": "RCP-002", "apc_id": "APC-003",
      "spc_status": "PASS"
    },
    {
      "lot_id": "LOT-0005", "step": "STEP_004",
      "start_time": "2026-03-15T05:55:16Z", "end_time": "2026-03-15T05:56:15Z",
      "recipe_id": "RCP-005", "apc_id": "APC-004",
      "spc_status": "PASS"
    }
  ]
}
```

---

## 4. `get_tool_step_trajectory` — 機台 × 步驟交叉查詢

**用途**：查詢某台機台上，特定步驟跑過哪些批次，統計 OOC 率。
**端點**：`GET /trajectory/tool/{tool_id}/step/{step}`

### 參數

| 參數 | 必填 | 說明 |
|------|------|------|
| `tool_id` | ✅ | 機台 ID，e.g. `EQP-01` |
| `step` | ✅ | 步驟代碼，e.g. `STEP_002` |
| `start_time` | ❌ | 時間窗口起始（ISO8601） |
| `end_time` | ❌ | 時間窗口結束（ISO8601） |
| `limit` | ❌ | 回傳批次數上限（預設 200） |

### 回傳結構

```
{
  tool_id, step,
  total_batches: N,
  batches: [ { lot_id, start_time, end_time, recipe_id, apc_id, spc_status, dc_snapshot_id, spc_snapshot_id }, ... ],
  summary: "Tool EQP-01, Step STEP_002: 2 lot(s) found. OOC: 1 / 2."
}
```

> `summary` 直接含 OOC 統計，可直接引用。

### Sample — EQP-01 / STEP_002

```json
{
  "tool_id": "EQP-01",
  "step": "STEP_002",
  "total_batches": 2,
  "summary": "Tool EQP-01, Step STEP_002: 2 lot(s) found. OOC: 1 / 2.",
  "batches": [
    {
      "lot_id": "LOT-0019",
      "start_time": "2026-03-15T10:55:07Z", "end_time": "2026-03-15T10:55:54Z",
      "recipe_id": "RCP-013", "apc_id": "APC-002",
      "spc_status": "OOC"
    },
    {
      "lot_id": "LOT-0018",
      "start_time": "2026-03-15T05:57:02Z", "end_time": "2026-03-15T06:57:44Z",
      "recipe_id": "RCP-007", "apc_id": "APC-002",
      "spc_status": "PASS"
    }
  ]
}
```

---

## 5. `get_object_history` — 物件歷史快照序列

**用途**：查詢一個物件在不同時間點的參數快照，追蹤長期趨勢。
**端點**：`GET /history/{object_type}/{object_id}`

### 參數

| 參數 | 必填 | 說明 |
|------|------|------|
| `object_type` | ✅ | `APC` / `DC` / `SPC` / `RECIPE`（大寫） |
| `object_id` | ✅ | 物件 ID（見下方說明） |
| `start_time` | ❌ | 時間窗口起始（ISO8601） |
| `end_time` | ❌ | 時間窗口結束（ISO8601） |
| `limit` | ❌ | 回傳筆數上限（預設 200） |

### object_id 格式說明

| 類型 | object_id 格式 | 來源 | history 筆數 |
|------|----------------|------|-------------|
| APC | `APC-XXX`（e.g. `APC-005`） | `get_lot_trajectory` 的 `apc_id` | 多筆（同模型跨批次共用） |
| RECIPE | `RCP-XXX`（e.g. `RCP-001`） | `get_lot_trajectory` 的 `recipe_id` | 多筆 |
| DC | `DC-LOT-XXXX-STEP_XXX-timestamp` | `get_process_context` 的 `dc.objectID` | 通常 1 筆（唯一）|
| SPC | `SPC-LOT-XXXX-STEP_XXX-timestamp` | `get_process_context` 的 `spc.objectID` | 通常 1 筆（唯一）|

> ⚠️ DC/SPC 的 object_id 每次製程唯一，追蹤趨勢請改用 `get_tool_trajectory` + `get_process_context`。
> APC/RECIPE 才是此 API 的主要用途。

### 回傳結構

```
{
  object_type, object_id,
  total_records: N,
  history: [
    {
      snapshot_id, process_status,
      event_time, lot_id, tool_id, step,
      spc_status,
      parameters: { ... }
    },
    ...
  ]
}
```

### Sample — APC-005 歷史（3 筆，rf_power_bias 漂移趨勢）

```json
{
  "object_type": "APC",
  "object_id": "APC-005",
  "total_records": 3,
  "history": [
    {
      "event_time": "2026-03-15T10:52:51Z",
      "lot_id": "LOT-0006", "tool_id": "EQP-02", "step": "STEP_005",
      "spc_status": "PASS",
      "parameters": { "rf_power_bias": 1.216752, "model_r2_score": 0.926749, "stability_index": 0.856382 }
    },
    {
      "event_time": "2026-03-15T10:24:49Z",
      "lot_id": "LOT-0008", "tool_id": "EQP-02", "step": "STEP_005",
      "spc_status": "PASS",
      "parameters": { "rf_power_bias": 1.186751, "model_r2_score": 0.975117, "stability_index": 0.894534 }
    },
    {
      "event_time": "2026-03-15T10:23:25Z",
      "lot_id": "LOT-0006", "tool_id": "EQP-07", "step": "STEP_005",
      "spc_status": "PASS",
      "parameters": { "rf_power_bias": 1.156864, "model_r2_score": 0.929052, "stability_index": 0.878406 }
    }
  ]
}
```

---

## 6. `get_baseline_stats` — DC 參數基準統計

**用途**：計算某台機台歷史 DC 量測值的統計基準（mean / std / 3σ 控制限），用於判斷當前讀數是否異常。
**端點**：`GET /stats/baseline?tool_id=`

### 參數

| 參數 | 必填 | 說明 |
|------|------|------|
| `tool_id` | ✅ | 機台 ID，e.g. `EQP-01` |
| `recipe_id` | ❌ | 只統計使用此 Recipe 的批次，e.g. `RCP-013` |
| `start_time` | ❌ | 統計區間起始（ISO8601） |
| `end_time` | ❌ | 統計區間結束（ISO8601） |

### 回傳結構

```
{
  tool_id, sample_count, param_count,
  stats: {
    "參數名": { mean, std_dev, min, max, ucl_3sigma, lcl_3sigma },
    ...
  },
  summary: "Baseline stats for EQP-01: 20 samples, 30 DC parameters."
}
```

> 共 ~30 個 DC 參數，含腔體壓力、溫度、氣體流量、RF 功率等。

### Sample — EQP-01 基準（前 5 個參數）

```json
{
  "tool_id": "EQP-01",
  "sample_count": 20,
  "param_count": 30,
  "summary": "Baseline stats for EQP-01: 20 samples, 30 DC parameters. Use ucl_3sigma/lcl_3sigma to judge if current readings are anomalous.",
  "stats": {
    "chamber_pressure":     { "mean": 15.651, "std_dev": 1.744, "ucl_3sigma": 20.884, "lcl_3sigma": 10.419 },
    "foreline_pressure":    { "mean": 1.320,  "std_dev": 0.259, "ucl_3sigma": 2.097,  "lcl_3sigma": 0.543 },
    "loadlock_pressure":    { "mean": 0.053,  "std_dev": 0.016, "ucl_3sigma": 0.100,  "lcl_3sigma": 0.007 },
    "throttle_position_pct":{ "mean": 46.213, "std_dev": 10.974,"ucl_3sigma": 79.135, "lcl_3sigma": 13.292 },
    "rf_forward_power":     { "mean": 1498.5, "std_dev": 42.3,  "ucl_3sigma": 1625.4, "lcl_3sigma": 1371.6 }
  }
}
```

> 用法：取得 LOT-0002 STEP_006 的 `dc.parameters.chamber_pressure = 18.25`，對比此基準 `ucl_3sigma = 20.88`，判斷是否超出管制。

---

## 7. `search_ooc_events` — 跨批次 OOC 事件搜尋

**用途**：快速搜尋符合條件的 SPC 異常事件，支援機台 / 批次 / 步驟 / 時段多維過濾。
**端點**：`POST /search`（JSON body）
**⚠️ 注意**：此 MCP 使用 POST 方法，參數放在 JSON body，不是 URL query string。

### 參數（全部可選，全空回傳最新 50 筆）

| 參數 | 說明 |
|------|------|
| `tool_id` | 機台 ID，e.g. `EQP-01` |
| `lot_id` | 批次 ID，e.g. `LOT-0002` |
| `step` | 步驟代碼，e.g. `STEP_006` |
| `status` | SPC 狀態：`OOC` 或 `PASS` |
| `start_time` | 時間窗口起始（ISO8601） |
| `end_time` | 時間窗口結束（ISO8601） |
| `limit` | 回傳筆數上限（預設 50） |

### 回傳結構

```
{
  total, ooc_count, pass_count,
  summary: "Found 3 events matching query (3 OOC, 0 PASS). Filtered to tool=EQP-01.",
  events: [
    { event_id, lot_id, tool_id, step, spc_status, event_time, dc_snapshot_id, spc_snapshot_id },
    ...
  ]
}
```

> events 按 `event_time` 倒序（最新在前）。
> 拿到 event 後，用 `lot_id + step` 呼叫 `get_process_context` 展開完整細節。

### Sample — EQP-01 的 OOC 事件

Request body：
```json
{ "tool_id": "EQP-01", "status": "OOC", "limit": 3 }
```

Response：
```json
{
  "total": 3,
  "ooc_count": 3,
  "pass_count": 0,
  "summary": "Found 3 events matching query (3 OOC, 0 PASS). Filtered to tool=EQP-01.",
  "events": [
    {
      "lot_id": "LOT-0008", "tool_id": "EQP-01", "step": "STEP_023",
      "spc_status": "OOC", "event_time": "2026-03-15T11:06:31Z",
      "dc_snapshot_id": "69b692b77947a0455e667427"
    },
    {
      "lot_id": "LOT-0007", "tool_id": "EQP-01", "step": "STEP_058",
      "spc_status": "OOC", "event_time": "2026-03-15T11:02:06Z",
      "dc_snapshot_id": "69b691ae7947a0455e66732d"
    },
    {
      "lot_id": "LOT-0007", "tool_id": "EQP-01", "step": "STEP_057",
      "spc_status": "OOC", "event_time": "2026-03-15T11:01:28Z",
      "dc_snapshot_id": "69b691887947a0455e6672fd"
    }
  ]
}
```

---

## 典型診斷工作流程

### 情境 A：「EQP-01 最近怎麼了？」

```
1. search_ooc_events   { tool_id: "EQP-01", status: "OOC", limit: 10 }
   → 找出哪些批次、哪些步驟 OOC

2. get_tool_step_trajectory  { tool_id: "EQP-01", step: "STEP_023" }
   → 確認此步驟 OOC 率

3. get_process_context  { lot_id: "LOT-0008", step: "STEP_023" }
   → 展開完整 Recipe / APC / DC / SPC 細節

4. get_baseline_stats  { tool_id: "EQP-01" }
   → 建立 DC 基準，比對 step 3 的量測值
```

### 情境 B：「LOT-0002 這批貨哪裡出問題？」

```
1. get_lot_trajectory  { lot_id: "LOT-0002" }
   → 找出 spc_status = "OOC" 的步驟（STEP_006, STEP_007）

2. get_process_context  { lot_id: "LOT-0002", step: "STEP_006" }
   → 展開 OOC 步驟的完整快照，看 spc.charts 哪個超出控制限

3. get_object_history  { object_type: "APC", object_id: "APC-006" }
   → 追蹤此 APC 模型的歷史 rf_power_bias 漂移趨勢
```

### 情境 C：「APC-005 這個模型穩定嗎？」

```
1. get_object_history  { object_type: "APC", object_id: "APC-005", limit: 20 }
   → 取歷史快照，觀察 rf_power_bias / stability_index / model_r2_score 的趨勢
```
