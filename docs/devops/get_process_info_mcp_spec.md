# `get_process_info` — Process Info MCP 資料供應規格 (DevOps)

> 給 DevOps 對接 production ontology 用。本文是 **單一 MCP**（`get_process_info`）
> 的完整 input / output 契約，以及 production 端**該提供的資料**。
>
> 設計原則：用最簡單的三個維度 — **站點 (`step`) / 批次 (`lotID`) / 機台 (`toolID`)**
> — 三選一即可查，**一次呼叫就回傳該 process 的所有相關物件**（SPC / APC / DC /
> RECIPE / FDC / EC），下游 pipeline 不需要再呼叫其他 MCP 補資料。
>
> 來源：本規格從現行系統的 `mcp_definitions.get_process_info`（description +
> input_schema + api_config）與 reference 實作（`ontology_simulator`
> `/process/info`）整理而來，與線上行為一致。

---

## 1. HTTP 契約

| 項目 | 值 |
|---|---|
| Method | `GET` |
| Path | `/api/v1/process/info` |
| Auth | 由 `api_config.headers` 注入（`${ENV}` 插值，例如 `Authorization: Bearer ${PROCESS_API_TOKEN}`） |
| Content-Type (回應) | `application/json` |

> MCP 設定裡的 `endpoint_url` 指向此 path（reference 環境為
> `http://localhost:8012/api/v1/process/info`）。Production 換成貴司 ontology
> 服務的 base URL 即可，**path 與參數契約必須一致**。

---

## 2. Input（query parameters）

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `toolID` | string | 三選一* | 機台 ID，e.g. `EQP-01` |
| `lotID` | string | 三選一* | 批次 ID，e.g. `LOT-0001` |
| `step` | string | 三選一* | 站點代碼，e.g. `STEP_020`（**伺服器端會轉大寫比對**） |
| `objectName` | string | 否 | 物件篩選：`SPC` \| `APC` \| `DC` \| `RECIPE` \| `FDC` \| `EC`。**不帶 = 回傳全部物件** |
| `since` | string | 否 | 時間窗：`24h` \| `7d` \| `30d`。不帶時預設不限（reference 行為：以 `limit` 取最近 N 筆） |
| `limit` | integer | 否 | 回傳最近 N 筆 events，範圍 `1~500`，預設 `50`。查「最近 N 次 process」用此欄位 |
| `eventTime` | string (ISO8601) | 否 | 精確定位某一次 process |

\* **`toolID` / `lotID` / `step` 至少帶一個**，三者皆空 → 回 **HTTP 400**
（`"Must provide toolID, lotID, or step (at least one)"`）。

**相容性要求（production 必須支援）：**
- **snake_case 別名**：同時接受 `tool_id` / `lot_id` / `object_name`
  （與 camelCase 等義；camelCase 優先）。
- **`toolID=ALL` sentinel**：值為 `ALL`（不分大小寫）代表「全機台」→ 通過必填
  檢查但**不對 toolID 過濾**（`lotID` / `step` 沒有此設計）。

---

## 3. Output（回應結構）

頂層：

```jsonc
{
  "total": 2,                 // events 筆數
  "events": [ { /* 見下 */ } ] // 已按 eventTime DESC 排序
}
```

每一筆 event row = **5 個固定平面欄位** + **依 objectName 掛上的 nested 物件**：

```jsonc
{
  "eventTime": "2026-06-15T08:30:00",   // ISO8601
  "lotID": "LOT-0001",
  "toolID": "EQP-01",
  "step": "STEP_020",
  "spc_status": "PASS",                  // 'PASS' | 'OOC'（process 級 OOC 標記）

  // 以下物件：不帶 objectName 時全回；帶 objectName 時只回該一種
  "SPC":    { ... },
  "APC":    { ... },
  "DC":     { ... },
  "RECIPE": { ... },
  "FDC":    { ... },
  "EC":     { ... }
}
```

**規則：**
- 欄位一律 **camelCase**。
- `events` 依 `eventTime` **由新到舊（DESC）**排序。
- nested 物件的 key 就是 `objectName`（`SPC` / `APC` / `DC` / `RECIPE` / `FDC` / `EC`）。
- nested 物件內**不要**重複 `eventTime` / `lotID` / `toolID` / `step` / `objectName`
  （這些是 join key，掛上去前要移除）。

---

## 4. 各 nested 物件該提供的資料

DevOps 需確保 production 端每個 process event 對應的物件快照含以下欄位。

### 4.1 `SPC`（統計製程管制）
```jsonc
"SPC": {
  "spc_status": "PASS",        // 同 event 級 spc_status
  "charts": {
    "xbar_chart": { "value": 12.3, "ucl": 15.0, "lcl": 9.0, "is_ooc": false },
    "r_chart":    { "value": ..., "ucl": ..., "lcl": ..., "is_ooc": ... },
    "s_chart":    { ... },
    "p_chart":    { ... },
    "c_chart":    { ... }
    // 其餘 chart type 視製程而定
  }
}
```
- 每個 chart 至少含 `value` / `ucl` / `lcl` / `is_ooc`（chart 層級 OOC 旗標）。

### 4.2 `APC`（進階製程控制 / run-to-run）
```jsonc
"APC": {
  "objectID": "APC-009",       // ⚠ 必要：APC 模型 instance ID（user 在 TRACE view 看到的）
  "mode": "run_to_run",
  "parameters": {              // ~20 個補償參數
    "etch_time_offset": 0.12,
    "rf_power_bias": -3.5
    // ...
  }
}
```
- **`objectID` 必須提供**（e.g. `APC-009`）；「OOC count by APC instance」分析直接
  `groupby APC.objectID`。
- `parameters.*` 是 **raw measurement**，**不是** OOC marker（見 §5）。

### 4.3 `DC`（裝置常數 / 感測器）
```jsonc
"DC": {
  "chamberID": "CH-2",         // ⚠ DC 用 chamberID（不是 objectID）
  "parameters": {              // ~30 個感測器
    "chamber_pressure": 5.2,
    "rf_forward_power": 1500
    // ...
  }
}
```

### 4.4 `RECIPE`
```jsonc
"RECIPE": {
  "objectID": "RCP-001",
  "recipe_version": "v3",
  "parameters": {
    "etch_time_s": 60,
    "target_thickness_nm": 120
    // ...
  }
}
```

### 4.5 `FDC`（故障偵測與分類）
```jsonc
"FDC": {
  "objectID": "FDC-001",
  "classification": "NORMAL",  // 'NORMAL' | 'WARNING' | 'FAULT'
  "fault_code": null,
  "confidence": 0.98,
  "contributing_sensors": [ ... ],
  "description": "..."
}
```

### 4.6 `EC`（工程常數 / 偏差監控）
```jsonc
"EC": {
  "constants": {
    "rf_power_offset": {
      "value": 12.0, "nominal": 12.5, "tolerance_pct": 5,
      "deviation_pct": -4.0, "status": "OK", "unit": "W"
    }
    // ...
  }
}
```

---

## 5. 語義規則（DevOps 必須遵守）

1. **OOC 判定一律看 `spc_status`**（process 級，APC/SPC/FDC 共用同一欄位）：
   - `PASS` = 該 process 整體合格
   - `OOC` = 該 process 任一指標超管制 → **整筆 process 算 OOC**
2. **APC 沒有獨立 `is_ooc` 欄位**（不像 SPC `charts.<chart>.is_ooc`）。
   「APC OOC by parameter」= filter `spc_status=OOC` → groupby APC param；
   不可拿 `APC.parameters.value` 當 OOC marker。
3. **chart 層級 OOC** 才用 `SPC.charts.<chart>.is_ooc` 細分。
4. 物件 instance ID（`APC.objectID` / `RECIPE.objectID` / `DC.chamberID` /
   `FDC.objectID`）**必須回傳**，跨 instance 統計靠它 groupby。

---

## 6. 後端資料模型（建議）

reference 實作以兩個 collection join 而成，production 可比照：

- **`events`**：一筆 process event
  `{ eventTime, lotID, toolID, step, spc_status, fdc_classification }`
- **`object_snapshots`**：物件快照，join key = `(lotID, step, eventTime, objectName)`
  `{ lotID, step, eventTime, objectName, ...物件欄位 }`

**Join 邏輯**：對每筆符合 filter 的 event，用 `(lotID, step, eventTime)` 撈出對應
的所有 `object_snapshots`，依 `objectName` 掛到該 event row 上（移除 join key 後）。

---

## 7. 範例

**Request — 查 EQP-01 STEP_020 最近 50 筆（全物件）：**
```
GET /api/v1/process/info?toolID=EQP-01&step=STEP_020&limit=50
```

**Request — 查某 lot 全部物件做根因：**
```
GET /api/v1/process/info?lotID=LOT-0001
```

**Request — 只要 SPC、過去 7 天：**
```
GET /api/v1/process/info?toolID=EQP-01&step=STEP_020&objectName=SPC&since=7d
```

**Response（節錄）：**
```jsonc
{
  "total": 1,
  "events": [
    {
      "eventTime": "2026-06-15T08:30:00",
      "lotID": "LOT-0001", "toolID": "EQP-01", "step": "STEP_020",
      "spc_status": "OOC",
      "SPC": {
        "spc_status": "OOC",
        "charts": { "xbar_chart": { "value": 16.1, "ucl": 15.0, "lcl": 9.0, "is_ooc": true } }
      },
      "APC": { "objectID": "APC-009", "mode": "run_to_run", "parameters": { "etch_time_offset": 0.31 } }
    }
  ]
}
```

---

## 8. DevOps 對接檢核清單

- [ ] `GET /api/v1/process/info` 上線，接受 §2 全部 query params（含 snake_case 別名）。
- [ ] 三選一必填檢查 → 缺則 **400**。
- [ ] `toolID=ALL` 視為全機台、不過濾。
- [ ] 回應為 `{ total, events[] }`，events 依 `eventTime` DESC、欄位 camelCase。
- [ ] 每筆 event 含 5 個平面欄位 + 依 `objectName` 掛 nested 物件（§4 各物件欄位齊全，含 instance ID）。
- [ ] `spc_status` 值為 `'PASS' | 'OOC'`，且為唯一的 process 級 OOC 來源（§5）。
- [ ] Auth header 透過環境變數注入，不寫死於程式碼。
