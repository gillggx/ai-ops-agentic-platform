# ontology_simulator — Spec

**Date:** 2026-04-25
**HEAD:** 5114b9b
**Status:** Living Document（依 code 實況萃取）

---

## 1. 定位

半導體製程的 **資料模擬器**。在 dev / staging 環境中扮演真實 FAB ontology 的角色，提供：

- 合成製程資料（Lot 流轉、機台狀態、SPC/APC/DC/EC/FDC/RECIPE/OCAP 物件快照）
- 與 production ontology 完全一致的 API 介面（v1 + v2）
- 內建模擬引擎（lots state machine + OOC injection）
- NATS 事件發布（OOC → `aiops.events.ooc` subject）

**邊界：** 不知道 Agent 存在；不依賴 backend；純資料服務。
所有 System MCP 的 `endpoint_url` 指向這裡，production 切換只需改 `endpoint_url`，consumer 程式碼不變。

## 2. 技術棧

| Category | Tech | Version |
|---|---|---|
| Framework | FastAPI + Uvicorn | ≥0.135 / ≥0.41 |
| Database | MongoDB (motor async) | motor ≥3.7 |
| Message Bus | NATS（lazy import） | nats-py ≥2.6 |
| Frontend dashboard | Next.js（standalone export） | — |
| Python | Python 3.11+ | — |

## 3. 模組樹

```
ontology_simulator/
├── main.py                   FastAPI entrypoint + lifespan + WS /ws
├── config.py                 env vars + 模擬引擎參數
├── start.sh
├── requirements.txt          fastapi / motor / pymongo / nats-py
├── app/
│   ├── database.py           motor connect_and_init / disconnect
│   ├── api/
│   │   ├── routes.py         ★ v1 endpoints (979 LOC)
│   │   └── v2/routes.py      ★ v2 — 軌跡 / 索引 / search (1484 LOC)
│   ├── mes/
│   │   └── simulator.py      lot state machine + 排程 (201 LOC)
│   ├── services/             6 個物件 service：APC/DC/EC/FDC/RECIPE/SPC + OOC publisher
│   ├── agent/                station_agent.py（單機 agent 模擬）
│   └── ws/                   WebSocket manager（前端 dashboard 即時推 lots/tools 狀態）
├── frontend/                 獨立 Next.js dashboard（出 static export 給 nginx /simulator/）
├── tests/
└── verify_*.py               5 支 standalone scenario verifier（dual-track RCA / event fanout / etc.）
```

**Source LOC：** v1 routes 979 + v2 routes 1484 + services 720 + simulator 201 ≈ 3.4k LOC。

## 4. API Surface

### 4.1 v1（`/api/v1/*` — production-compatible）

| Method | Path | 說明 |
|---|---|---|
| GET | `/process/summary` | L1 — 聚合統計（OOC rates、tool breakdown、recent OOC events） |
| GET | `/process/info` | L2 — 範圍調查（objectName=SPC/DC/APC/RECIPE 切換） |
| GET | `/process/events` | 事件查詢（toolID / lotID / step / 時間區間） |
| GET | `/context/query` | 物件快照查詢（targetID + step + objectName + eventTime?） |
| POST | `/objects/query` | L3 — 物件參數時序（SPC param 短格式 → `charts.xbar_chart.value` 自動 normalize） |
| GET | `/object-info` | ⚠️ Deprecated — data IS the schema |
| GET | `/events` | ⚠️ Deprecated — 被 `/process/info` 取代 |
| GET | `/status` | 模擬器系統狀態 |
| GET | `/lots` | 批次列表（optional status filter） |
| GET | `/tools` | 機台列表 + 狀態 |
| POST | `/tools/{tool_id}/acknowledge` | Hold ack |
| GET | `/audit` | 模擬器內部 audit |
| POST | `/admin/reset-simulation` | 重設模擬狀態 |
| GET | `/analytics/{step-spc, step-dc, history}` | 分析 endpoint |

### 4.2 v2（`/api/v2/*` — 進階 trajectory + indices）

| Method | Path | 說明 |
|---|---|---|
| GET | `/fanout/{event_id}` | Event 影響範圍 |
| GET | `/orphans` | 沒對應 OOC 的孤兒事件 |
| GET | `/context` | v2 context query |
| GET | `/trajectory/lot/{lot_id}` | Lot 全站軌跡 |
| GET | `/trajectory/tool/{tool_id}[/step/{step}]` | Tool 軌跡 |
| GET | `/history/{object_type}/{object_id}` | 物件歷史 |
| GET | `/indices/{object_type}` | 物件索引 |
| GET | `/stats/baseline` | baseline 統計 |
| GET | `/timeseries/tool/{tool_id}/step/{step}` | 站點時序 |
| POST | `/search` | 跨物件 search |
| GET | `/enumerate` | 列舉可用 IDs |
| GET | `/tools/status` | 機台聚合狀態 |
| GET | `/equipment/{tool_id}/constants` | EC 物件 |
| GET | `/fdc/{tool_id}/uchart` | FDC u-chart |
| GET | `/ocap/{lot_id}/{step}` | OCAP 結果 |

### 4.3 WebSocket

- `WS /ws` — frontend dashboard 訂閱 lot / tool 狀態廣播

### 4.4 NATS Publish

| Subject | Trigger | Payload |
|---|---|---|
| `aiops.events.ooc` | SPC `is_ooc=true` 時自動發 | event payload（lazy import `nats`，連不上 silent degrade） |

⚠️ SPEC 2.0 寫的是 `fab.events.{eventType}`，實際 code 只發 `aiops.events.ooc` — 已修正。

## 5. MongoDB Collections

| Collection | 主要欄位 | 說明 |
|---|---|---|
| `lots` | `lotID, status, currentStep, recipe, route[]` | 批次狀態 |
| `tools` | `toolID, status, name, currentLot` | 機台狀態 |
| `events` | `eventTime, eventType, lotID, toolID, step, spc_status, recipeID, apcID, fdc_class` | 製程事件時間線 |
| `object_snapshots` | `eventTime, targetID, step, objectName, objectID, ...params` | 7 種物件快照（DC/SPC/APC/EC/RECIPE/FDC/OCAP） |

### object_snapshots 物件類型

| objectName | 主要欄位 | 模擬邏輯 |
|---|---|---|
| **DC** | `parameters.{30 sensors}` | Exponential drift + PM reset |
| **SPC** | `charts.{xbar,r,s,p,c}_chart{value,ucl,lcl,is_ooc}, spc_status` | 5 charts × 1 DC sensor |
| **APC** | `mode, parameters.{20}` (5 active + 15 passive) | active 50% self-correct；passive 自由飄；`model_r2` 隨 active drift 退化 |
| **RECIPE** | `recipe_version, parameters.{20}` | 10% 機率 version bump，key params ±offset |
| **FDC** | `classification, fault_code, confidence, contributing_sensors, description` | Rule-based: SPC OOC + DC drift → FAULT; APC 退化 → WARNING |
| **EC** | `constants.{8}` 各 `{value, nominal, tolerance_pct, deviation_pct, status, unit}` | 慢漂 + PM 校正，status: NORMAL/DRIFT/ALERT |
| **OCAP** | corrective action 結果 | 連續 OOC ≥ 3 自動觸發 |

## 6. 模擬引擎

### 6.1 Lot State Machine（[app/mes/simulator.py](ontology_simulator/app/mes/simulator.py)）

```
NEW → Processing → Waiting → Processing → ... → Finished
                     ↑                    │
                     └──── next step ─────┘
```

每個 step 產生：
1. `ProcessStart` event
2. 各物件 snapshot（DC → SPC → APC → EC → RECIPE → FDC → OCAP）
3. `ProcessEnd` event（含 `spc_status: PASS|OOC`）

### 6.2 並行控制

- `HEARTBEAT_MIN/MAX = 5/10s` — 心跳間隔
- `PROCESSING_MIN/MAX = 180/300s` — 處理時間
- `HOLD_PROBABILITY = 0.05` — 5% 機率機台 hold
- `RECYCLE_LOTS = true` — 跑完 route 重新投料

### 6.3 OOC 注入

- `OOC_PROBABILITY = 0.30` — 整體 OOC 機率
- `APC_DRIFT_RATIO = 0.05` — 每 process active param ±5% drift
- 連續 OOC 達閾值 → OCAP 觸發

## 7. Frontend Dashboard

`frontend/`（獨立 Next.js app）— 開發者觀察合成資料：
- Architecture View（系統 + 狀態摘要）
- Lots / Tools 列表 + 詳情
- Event Timeline
- Object Snapshots 瀏覽

deploy 時 `next export` → `frontend/out/`，nginx 用 alias `/simulator/` 餵 static。

## 8. Build / Deploy

- **Local：** `bash start.sh`（uvicorn `main:app --port 8012`）
- **Prod：** systemd unit [deploy/ontology-simulator.service](deploy/ontology-simulator.service)
  ```
  ExecStart=/opt/aiops/venv_ontology/bin/uvicorn main:app --host 127.0.0.1 --port 8012
  EnvironmentFile=/opt/aiops/ontology_simulator/.env
  ```

## 9. 環境變數

| Variable | Default | 說明 |
|---|---|---|
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB 連線 |
| `MONGODB_DB` | `semiconductor_sim` | DB name |
| `NATS_URL` | `nats://localhost:4222` | NATS server |
| `PORT` | `8001`（被 systemd 改成 `8012`） | API server |
| `TOTAL_LOTS` | `99999` | 模擬器初始 lot 數 |
| `HEARTBEAT_MIN/MAX` | `5/10` | 心跳間隔（秒） |
| `PROCESSING_MIN/MAX` | `180/300` | 處理時間（秒） |
| `HOLD_PROBABILITY` | `0.05` | hold 機率 |
| `OOC_PROBABILITY` | `0.30` | OOC 機率 |
| `APC_DRIFT_RATIO` | `0.05` | APC drift 幅度 |
| `RECYCLE_LOTS` | `true` | 跑完重投 |

## 10. 已知缺口

1. **`config.py` 預設 PORT=8001**，被 systemd unit 覆寫成 8012 — 容易誤導本地 dev
2. **NATS subject naming drift** — 舊 SPEC 寫 `fab.events.{type}`，現實只有 `aiops.events.ooc`
3. **5 支 verify_*.py 是 standalone script** — 沒接 pytest，難以 CI
4. **WebSocket manager 沒文件** — `app/ws/` 行為靠 frontend code 推
5. **沒 contract test against production ontology** — 「介面相同」純靠人工 review

## 11. 變更指南

- 新增 endpoint：先確認 production ontology 是否已有同名同 schema；不要創造 simulator-only API
- 改 object schema：DC/SPC/APC/RECIPE/FDC/EC 任何欄位都會被下游 backend 解析，請同步通知 fastapi_backend_service / python_ai_sidecar 的 MCP / Block 維護者
- NATS subject 變更：影響 `fastapi_backend_service/app/services/nats_subscriber_service.py` 的 Auto-Patrol 觸發邏輯
- 移除 deprecated endpoint（`/events`, `/object-info`）前先 grep 全 repo 確認沒人用
