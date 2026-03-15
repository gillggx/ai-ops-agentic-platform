# Agentic OS v2.2 — Final Implementation Spec

**完成日期：** 2026-03-14
**狀態：** ✅ COMPLETE（含 Post-Release UI Refinements）

---

## 1. 本版本交付範圍

v2.2 將 Ontology Simulator 從「製程模擬工具」升級為「工廠級資料服務平台（Data Service Platform）」，對外暴露結構化的 Data Services API，並以 Triple-Trace Nexus UI 作為視覺化展示層。

Post-release refinements（同日完成）：
- Nexus UI 整合進 MES Simulator 主頁（移除獨立入口），以 TOPOLOGY / NEXUS tab 切換
- 拓樸圖邊線語意修正為正確的設備中心關係
- `context/query` API 修正 LIVE 模式下 LOT/TOOL 查詢不需要 anchor event

---

## 2. 架構概覽

```
┌─────────────────────────────────────────────────────────┐
│  FastAPI Backend (port 8000)                            │
│  SPA → Sidebar "MES 即時模擬器"                          │
│    └─ iframe (/simulator/)                              │
│         └─ Dashboard: [TOPOLOGY tab] / [NEXUS tab]      │
└─────────────────────────────────────────────────────────┘
                          ↓ Nginx proxy
┌─────────────────────────────────────────────────────────┐
│  OntologySimulator (port 8001)                          │
│                                                         │
│  /api/v1/  — 既有端點（events, context, audit...）        │
│  /api/v2/ontology/  — 新增 Data Services API            │
│                                                         │
│  MongoDB ← MES Simulator (10 tools × 100 lots)         │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 新增後端 API（/api/v2/ontology/）

### 3.1 GET /api/v2/ontology/context

**Graph Context Service — Use Case 1: SPC OOC 根因展開**

| 參數 | 說明 |
|------|------|
| `lot_id` | Lot ID，例如 LOT-0007 |
| `step` | Step ID，例如 STEP_048 |
| `ooc_only` | true = 只取 OOC 事件（選填，預設 false）|

回傳結構：
```json
{
  "root":   { "lot_id", "step", "event_id", "event_time", "spc_status", "recipe_id", "apc_id", "tool_id" },
  "tool":   { "tool_id", "status" },
  "recipe": { "objectName", "parameters": { 20 params }, ... },
  "apc":    { "objectName", "parameters": { 20 params }, ... },
  "dc":     { "objectName", "parameters": { 30 sensors }, ... },
  "spc":    { "objectName", "spc_status", ... }
}
```

任一節點缺失時附加 `"orphan": true` 旗標。

---

### 3.2 GET /api/v2/ontology/fanout/{event_id}

**Ontology Audit Service — 單一事件扇出追蹤**

給定 MongoDB ObjectId，追蹤該事件產生的 4 條子系統連結：

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

`orphan: true` = 該連結斷裂（Sankey 紅色火花觸發條件）。

---

### 3.3 GET /api/v2/ontology/orphans

**Orphan Scanner — 孤兒偵測**

| 參數 | 說明 |
|------|------|
| `limit` | 最多回傳幾個孤兒事件（1-500，預設 50）|

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

---

### 3.4 GET /api/v1/context/query（修正）

**LIVE 模式 LOT / TOOL 查詢修正**

原實作對所有 objectName 都先做 anchor event 查找，導致 LIVE 模式下（步驟進行中、尚未寫入 TOOL_EVENT）點擊 LOT / TOOL 節點報 404。

修正邏輯：
- `objectName=LOT` → 直接查 `lots` master collection，不需 anchor event
- `objectName=TOOL` → 直接查 `tools` master collection，不需 anchor event
- `objectName=APC/RECIPE/DC/SPC` → 仍需 anchor event（快照在步驟完成時才寫入）

---

## 4. Triple-Trace Nexus UI

### 4.1 整合位置（Post-Release 更新）

Nexus UI **整合進 MES Simulator 主頁**（`/simulator/`），不再作為獨立頁面：

```
FastAPI SPA Sidebar → MES 即時模擬器 → /simulator/ → Dashboard
  ┌─────────────────────────────────────────────────────┐
  │  [TOPOLOGY]  [⬡ NEXUS]  ← 中間面板 tab 切換         │
  ├────────────────┬────────────────────────────────────┤
  │ TOPOLOGY tab   │  NEXUS tab                         │
  │                │                                    │
  │ Context        │  Ontology Fan-out header           │
  │ Topology SVG   │  ┌─────────────────────────────┐  │
  │ (設備中心拓樸) │  │  Sankey (dark, 260px)       │  │
  │                │  └─────────────────────────────┘  │
  │                │  Compression Ratio bars (2×2 grid) │
  └────────────────┴────────────────────────────────────┘
```

`/simulator/nexus/` 靜態頁面仍存在（Next.js build 產出），但 FastAPI SPA sidebar 的獨立 Nexus 入口已移除。

### 4.2 Context Topology — 正確邊線語意

設備中心關係（Equipment-centric）：

| 邊線 | 語意 |
|------|------|
| TOOL → RECIPE | 設備載入此配方 |
| TOOL → LOT | 設備正在處理此 WIP |
| LOT → APC | per-lot APC 調整快照 |
| LOT → DC | per-lot 感測器資料收集 |
| LOT → SPC | per-lot SPC 量測結果 |

### 4.3 Sankey 節點配色

| 節點 | 顏色 |
|------|------|
| Process Events | Violet `#7c3aed` |
| APC Index / Objects | Teal `#0d9488` / `#5eead4` |
| DC Index / Objects | Indigo `#4f46e5` / `#a5b4fc` |
| SPC Index / Objects | Amber `#d97706` / `#fcd34d` |
| RECIPE Index / Objects | Sky `#0284c7` / `#7dd3fc` |
| ⚡ Orphan | Red `#dc2626` |

### 4.4 NexusCenter 組件（亮色主題）

`components/NexusCenter.tsx` — 嵌入 Dashboard 中間面板用：
- 顯示 Orphan 狀態 badge（綠色 ✓ No orphans / 紅色 ⚡ N orphans）
- Sankey 圖表（暗色容器內嵌，保持 ECharts 顏色正確性）
- 4 個子系統的 Index / Object bar + 壓縮比率數字
- 每 20 秒自動 refresh，來源：`/api/v1/audit` + `/api/v2/ontology/orphans`

---

## 5. FastAPI SPA 整合

### 目前整合方式
- **MES 即時模擬器** sidebar 按鈕（`nav-simulator`）→ iframe `/simulator/`
- Dashboard 中間面板提供 TOPOLOGY / NEXUS tab 切換
- 不再有獨立 `nav-ontology-nexus` 按鈕

---

## 6. 驗證腳本

```bash
cd ontology_simulator
python verify_data_services.py
```

4 個測試全部通過：
- TEST 1: Graph Context（OOC 事件展開，5 個節點全部 present）
- TEST 2: Fanout Trace（4 個子系統連結完整）
- TEST 3: Orphan Scanner（0 孤兒）
- TEST 4: Audit Sanity（RECIPE 36.6×、APC 13.6× 壓縮比）

---

## 7. 新增 / 修改檔案清單

### 新增
| 檔案 | 說明 |
|------|------|
| `app/api/v2/__init__.py` | v2 package |
| `app/api/v2/routes.py` | 3 個 v2 端點（context, fanout, orphans）|
| `components/nexus/SankeyFlow.tsx` | ECharts Sankey 組件（暗色主題）|
| `components/nexus/NexusView.tsx` | Triple-Trace 完整視圖（/nexus/ 頁面用）|
| `components/NexusCenter.tsx` | 亮色主題 Sankey + Ratio，嵌入 Dashboard 用 |
| `app/nexus/page.tsx` | Next.js /nexus 路由 |
| `verify_data_services.py` | 底層驗證腳本 |

### 修改
| 檔案 | 變更說明 |
|------|----------|
| `main.py`（ontology_simulator）| 掛載 router_v2 |
| `app/api/routes.py` | LOT/TOOL context/query 跳過 anchor event 檢查（LIVE 模式修正）|
| `package.json` | 新增 echarts、recharts 依賴 |
| `components/Dashboard.tsx` | 新增 `centerTab` state + TOPOLOGY/NEXUS tab 切換 |
| `components/TopologyView.tsx` | 邊線語意改為設備中心（TOOL→RECIPE, TOOL→LOT, LOT→APC/DC/SPC）|
| `static/index.html`（FastAPI）| 移除獨立 Ontology Nexus sidebar 按鈕與 view panel |
| `start.sh` | HTTP health check、lsof 語法修正（macOS 相容）|

---

## 8. 啟動方式

```bash
cd /path/to/fastapi_backend_service
./start.sh           # 完整建置（npm run build）+ 啟動兩個服務
./start.sh --no-build  # 跳過 Next.js build（已有 out/ 時）
```

服務就緒後：

| 入口 | URL |
|------|-----|
| FastAPI SPA（含 Nexus tab）| `http://localhost:8000` → Sidebar MES 模擬器 → NEXUS tab |
| Nexus 獨立頁面 | `http://localhost:8000/simulator/nexus/` |
| v2 API Docs | `http://localhost:8001/docs` → /api/v2/ontology/* |
| 孤兒掃描 | `http://localhost:8001/api/v2/ontology/orphans` |

---

## 9. 與 master_prod_spec_v2.2.md 對照

| 規格項目 | 狀態 |
|----------|------|
| Event Fan-out 底層（Tool/Lot Event × 4 子系統）| ✅ v1 已完成 |
| `GET /v2/ontology/fanout/{eventId}` | ✅ 完成 |
| `GET /v2/ontology/orphans` | ✅ 完成 |
| Graph Context Service（Use Case 1）| ✅ 完成 |
| Trajectory Trace Service | ✅ v1 /analytics/history 已支援 |
| Semantic Aggregation Service | 🔲 未實作（v2.3 規劃）|
| Sankey Diagram（Triple-Trace）| ✅ 完成（ECharts，整合入 Dashboard）|
| Event Timeline Inspector | ✅ 完成（Dashboard TRACE 模式 + RightInspector）|
| Object-Index Ratio Chart | ✅ 完成（NexusCenter 亮色主題）|
| verify_data_services.py | ✅ 完成，4/4 tests pass |
| Context Topology 邊線語意 | ✅ 修正為設備中心關係 |
| LIVE 模式 LOT/TOOL 查詢 | ✅ 修正（跳過 anchor event）|

**未實作項目（留待 v2.3）：**
- Semantic Aggregation Service（Use Cases 4, 6, 7, 10, 14, 18）
- 20 個 Use Cases 的完整 API coverage
