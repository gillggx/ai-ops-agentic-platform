# SPEC: Alarm Center Redesign — Tier 1 + Tier 2

- Status: **Approved** (2026-05-01)
- Author: gill + Claude (Tech Lead)
- Date: 2026-04-30 draft → 2026-05-01 approved
- Supersedes: 無（首版；目前 `aiops-app/src/app/alarms/page.tsx` 為待重構對象）
- Related: `/Users/gill/Downloads/alarm center sample/` (Claude-generated design study)

---

## 1. Context & Objective

### 痛點（現狀）

`aiops-app/src/app/alarms/page.tsx` 目前是「平鋪 alarm list」：
1. **重複噪音** — 同一台 EQP 在短時間內連續 OOC，會產生 N 個獨立 alarm row，操作員每筆都要點開判讀，無法一眼看出是同一根 chamber drift。
2. **刺眼紅** — severity = high 直接整片飽和紅，看 5 分鐘眼睛就累；無法在視覺上分出「重大、中度、可後處理」的層次。
3. **缺優先序** — 50+ alarm 並列，沒有「先處理哪個」的引導；rootcause confidence、affected lots、最近活躍度都沒有曝光。
4. **單機台視角缺失** — 操作員心裡的單位是「EQP-03 出狀況」而非「alarm #254」，現在 UI 是 alarm-centric 不是 tool-centric。
5. **AI 戰況不可見** — Auto-Patrol/Auto-Check 後台跑了什麼、跑得多快、有沒有掉，操作員不知道。

### Objective

把 Alarm Center 從「list of alarm rows」重構成「tool-cluster + 三窗格 cockpit」：

- **Tier 1（核心）**：3-pane layout（Cluster List / Detail / AI Copilot）、alarm clustering、OKLCH 柔和配色、ClusterCard with sparkline、頂部「AI 戰況」strip。
- **Tier 2（增強）**：KPI cards（active alarms / open clusters / MTTR / health score）、Copilot panel 中嵌入該 cluster 的 plan + 行動按鈕（Acknowledge / Hold / Dispatch — Hold/Dispatch 先暫禁；參見 §6 Risks）。

### 不在本 Spec 範圍

- **Tier 3 deferred**：Floor Map（30-tool grid）、Triage Lanes 三階段視圖、Tweaks panel、Pipeline Run 詳細頁。
- **MES/派工整合**：Hold/Dispatch 真正觸發外部系統；本 spec 僅佔位 UI。
- **rootcause confidence model**：本 spec 不訓練模型；若資料不存在則 UI 顯示 "—"。

---

## 2. Architecture & Design

### 2.1 資料模型

**現有不動**：`alarms` table、`AlarmEntity`、`AlarmEnrichmentService` 維持。

**新增（純衍生，無 schema migration）**：
所有 cluster / KPI 都從現有 `alarms` 表即時聚合，**不**新建 `alarm_clusters` 表（避免雙寫一致性問題；Tier 1 數量級 < 1k alarm，groupBy 在 DB 端 < 50ms）。

### 2.2 Backend — 新 API

#### `GET /api/v1/alarms/clusters?since=24h&status=active`

聚合規則（v1 — 已對齊）：
- **Cluster key**：`equipment_id`（同一台機台 = 一個 cluster，不再依 trigger_event 細分）
- **Time bucket**：since 參數內的所有 alarm 歸入同一 cluster
- **Sparkline**：將 since 區間切 10 等份 bucket，每 bucket 計數 → `int[10]`
- **Severity rollup**：取 cluster 內 max severity（high > medium > low）
- **first_at / last_at**：cluster 內 min/max event_time
- **count / open_count / ack_count**：依 status 分組
- **affected_lots**：cluster 內 distinct `lot_id` 數量
- **rootcause_confidence**：v1 留 `null`（資料尚未產生，UI 顯示 "—"）
- **cause**：v1 從 `trigger_event` 直接 mapping（e.g. `spc.ooc` → "SPC drift"）；無模型推論
- **assignee**：v1 留 `null`（無 assignee 欄位，未來補 user-alarm relation table）

回傳 schema：

```json
{
  "since": "24h",
  "as_of": "2026-04-30T14:18:00Z",
  "clusters": [
    {
      "cluster_id": "EQP-03",
      "equipment_id": "EQP-03",
      "bay": "A",
      "severity": "high",
      "title": "EQP-03 連續異常（5 種告警）",
      "trigger_events": ["spc.ooc", "particle.high"],
      "summary": "<derived from latest alarm summary>",
      "count": 15,
      "open_count": 15,
      "ack_count": 0,
      "first_at": "...",
      "last_at": "...",
      "spark": [3,5,4,7,8,11,10,14,13,15],
      "cause": "SPC drift",
      "affected_lots": 8,
      "rootcause_confidence": null,
      "alarm_ids": [254, 253, 252, ...]
    }
  ]
}
```

#### `GET /api/v1/alarms/kpis?since=24h`

```json
{
  "active_alarms": 47,
  "open_clusters": 8,
  "high_severity_count": 3,
  "mttr_minutes": 23,
  "auto_check_runs_last_hour": 12,
  "auto_check_avg_latency_s": 4.7,
  "health_score": 72
}
```

`mttr_minutes`：since 區間內 status=resolved 的 alarm 平均 (resolved_at − event_time) 分鐘數。
`health_score`：v1 用簡式 `100 − (high*5 + med*2 + low*1)`，clamp [0,100]。
`auto_check_*`：從 `pb_pipeline_runs` 讀 since 區間內 source pipeline.kind='auto_check' 的記錄。

#### Cluster 內 alarm list（重用現有 endpoint）

`GET /api/v1/alarms?ids=254,253,252` — 直接吃 alarm_ids 陣列；現有 endpoint 加 `ids` query param。

### 2.3 Frontend — 結構

```
src/app/alarms/page.tsx                  ← 入口，改為渲染 <AlarmCenterShell />
src/components/alarms/
  AlarmCenterShell.tsx                   ← 3-pane grid 容器 + KPI strip
  KpiStrip.tsx                           ← Tier 2: 上方 KPI cards
  PulseStrip.tsx                         ← Tier 1: AI 戰況橫條
  cluster-list/
    ClusterListPanel.tsx                 ← 左 pane（filter chips + ClusterCard 列表）
    ClusterCard.tsx                      ← 含 sparkline、severity tag、tool/cause/lots
    Sparkline.tsx                        ← 10-bucket SVG mini chart
  detail/
    ClusterDetailPanel.tsx               ← 中 pane（cluster 摘要 + alarm list + 既有 alarm tab UI）
    AlarmRow.tsx                         ← 從現有 page.tsx 拆出的 row 元件
  copilot/
    FocusedAgentPanel.tsx                ← 右 pane（cluster 焦點下的 AI plan + actions）
  shared/
    SeverityTag.tsx
    ToolChip.tsx
src/styles/alarm-center.css              ← OKLCH design tokens（從 sample 移植）
```

### 2.4 設計 Token (OKLCH)

從 `/Users/gill/Downloads/alarm center sample/styles.css` 移植，支援 light + dark：

```css
:root {
  --font-sans: 'Inter Tight', -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;
  --bg: oklch(99% 0.003 90);
  --surface: #ffffff;
  --border: oklch(92% 0.006 90);
  --text: oklch(22% 0.01 60);
  --text-2: oklch(45% 0.012 60);
  --high: oklch(58% 0.19 25);   /* 不再純飽和紅 */
  --med:  oklch(70% 0.14 70);
  --low:  oklch(60% 0.10 220);
  --accent: oklch(55% 0.13 265);
}
[data-theme="dark"] { /* 對應的 dark tokens */ }
```

字體用 Google Fonts CDN（Inter Tight + JetBrains Mono）載入。

### 2.5 Layout（Tier 1 + 2）

```
┌────────────────────────────────────────────────────────────────┐
│  [KPI STRIP]   active=47   open clusters=8   MTTR=23m   ...    │  Tier 2
├────────────────────────────────────────────────────────────────┤
│  [PULSE STRIP] AI 戰況: Auto-Check 12 runs/hr · avg 4.7s · ✓   │  Tier 1
├──────┬───────────────────┬──────────────────────┬──────────────┤
│ rail │  Cluster List     │  Cluster Detail      │ AI Copilot   │
│ 52px │  340px            │  flex                │ 360px        │
│      │                   │                      │              │
│  🔔  │  [Filter: high]   │  EQP-03 SPC OOC      │ Plan steps   │
│  🗺  │  ┌─────────────┐  │  ─ 15 alarms ─       │  ✓ 解析觸發   │
│  📊  │  │ EQP-03 high │  │  spark + summary     │  ✓ 比對 5 次  │
│      │  │ ▂▃▅▆▇█      │  │  affected lots: 8    │  ⏳ 比對 EQP-07│
│      │  │ 15 lots: 8  │  │                      │              │
│      │  └─────────────┘  │  Alarm rows (table)  │ [Ack] [Hold*]│
│      │  ...              │   #254 14:16:50 ...  │ [Dispatch*]  │
│      │                   │   #253 14:14:07 ...  │              │
└──────┴───────────────────┴──────────────────────┴──────────────┘
* Hold / Dispatch 為佔位（disabled + tooltip "MES 整合中"）
```

行為：
- 點 ClusterCard → 中 pane 切到該 cluster 詳情 + 右 pane 載入該 cluster 的 AI plan
- 點 cluster 內 single alarm row → 中 pane 內展開該 alarm 的 trigger / diagnostic tabs（**現有 page.tsx tab UI 整段搬過來**）
- 預設選第一個 high-severity cluster
- 響應式：< 1280px 時右 pane 改成 modal，< 900px 時左 pane 改成 drawer

### 2.6 Cluster List filter 設計

頂部 chip rows：
- `severity`：全部 / high / med / low
- `status`：open / acknowledged / resolved
- `bay`：A / B / C / 全部（v1 從 `equipment_id` prefix 推；若沒對應就隱藏該 chip）

無 search box（v1 略，clusters 通常 < 20 個）。

### 2.7 AI Copilot Panel（右）— Tier 2 重點

當選定 cluster 時，右 pane 顯示：
1. **Plan 區**：從該 cluster 最近一個 alarm 的 `auto_check_runs[*]` 或 `findings.plan` 取出 step list（v1 直接讀現有 `auto_check_runs` 即可，不另外打 LLM）。
2. **Action 區**：只放 `[✓ Acknowledge cluster]` 一顆按鈕。點擊 → 對 cluster 內所有 `status=active` alarm batch 打 ack（後端新增 `POST /api/v1/alarms/cluster-ack { equipment_id }`，loop 已存在的 single-alarm ack 邏輯）。Hold / Dispatch 等 MES 整合再加，不放佔位。
3. **Cluster Summary**：affected lots / first seen / cause / confidence 一覽。

### 2.8 與現有功能相容

- `/alarms?id=254` deep link：自動找到該 alarm 所屬 cluster + open detail
- 現有 trigger / diagnostic tab UI（DataView table、charts、auto_check_runs 多卡）→ **整段保留**，只是裝載到 detail pane
- 現有 `alarms` 路由不換 URL；`page.tsx` 重構為 shell

---

## 3. Step-by-Step Execution Plan

### Phase A — Backend (1.5 day)
1. `AlarmController.listClusters(since, status)` + service 內 grouping logic（單 SQL groupBy）
2. `AlarmController.kpis(since)` — 單 SQL aggregation
3. 既有 list endpoint 加 `ids` query param 支援
4. 單元 / 整合測試（`AlarmClusterServiceTest`）

### Phase B — Frontend Layout + Tokens (1 day)
1. 移植 OKLCH tokens 到 `alarm-center.css`，引入 Inter Tight + JetBrains Mono
2. 建立 `AlarmCenterShell` 3-pane grid + KpiStrip + PulseStrip 骨架（先放 placeholder data）
3. 確認 light/dark 切換可用（沿用既有 next-themes / data-theme）

### Phase C — Cluster List + Card (1 day)
1. `Sparkline.tsx`（10-bucket SVG）
2. `ClusterCard.tsx`（severity bar + tool/cause/lots/sparkline）
3. `ClusterListPanel.tsx` + filter chips
4. wire `/api/v1/alarms/clusters` proxy route in `aiops-app/src/app/api/`

### Phase D — Detail Pane 整合 (1 day)
1. 從現有 `page.tsx` 抽出 alarm tab UI 為 `AlarmRow.tsx`（不動 tab logic，只是搬位置）
2. `ClusterDetailPanel.tsx` 顯示 cluster 摘要 + 該 cluster 的 alarm 列表
3. 點 alarm row → 內嵌展開 trigger/diagnostic（保留現有 `auto_check_runs` 多卡渲染）

### Phase E — Copilot Panel + KPIs (0.5 day)
1. `FocusedAgentPanel.tsx` 渲染 plan + actions（Hold/Dispatch disabled）
2. `KpiStrip.tsx` + `/api/v1/alarms/kpis` proxy
3. `PulseStrip.tsx`（auto_check 統計 strip）

### Phase F — 整合測試 + Deploy (1 day)
1. 跑 `deploy/update.sh --force-rebuild`
2. 在 EC2 上實際操作：
   - 確認 cluster 數量 = `SELECT COUNT(DISTINCT (equipment_id, trigger_event))` from active alarms
   - 點 cluster → detail 顯示正確 alarm count
   - 點 alarm → diagnostic tab 顯示既有 auto_check_runs 卡（不破現有功能）
   - 切 light/dark theme
3. 跟 user 對齊「verify like a user」清單再宣告完工（記取 LESSONS_LEARNED theme 5）

**總工時估計：5 個工作日**（Tier 1 ≈ 3.5 day, Tier 2 ≈ 1.5 day）

---

## 4. Edge Cases & Risks

### 邊界
1. **0 個 active alarm** → 中 pane 顯示空狀態 "目前無告警"；右 pane 隱藏
2. **單 cluster 內 alarm > 100** → detail pane alarm list 用 virtualized scroll（或先 cap 50 + "查看更多"）
3. **alarm 沒有 `equipment_id`**（trigger_event 來源無 EQP 綁定）→ 歸到特殊 cluster `__unbound__`，列在最下方
4. **deep link `/alarms?id=X`** → 找不到對應 cluster 時 fallback 到 single-alarm legacy view（不破舊連結）
5. **dark mode contrast** → high-severity 在 dark 下用 `oklch(70% 0.20 25)` 較亮版本
6. **舊 alarm 沒 `acknowledged_by`** → Ack 按鈕仍可點；後台寫入時用 current user

### 風險
1. **Cluster grouping 語意不確定** — `(equipment_id, trigger_event)` 可能不是 user 心中的 cluster。**Mitigation**：v1 出貨後跟 user 對齊；若不對，改 grouping key 不影響 schema（純衍生）。
2. **rootcause_confidence 永遠 null** — UI 顯示 "—"，但 sample design 把它當核心。**Mitigation**：明確標 placeholder，等真有模型再上；UI 設計要能在沒 confidence 時 graceful。
3. **Hold / Dispatch 暫禁** — user 看到按鈕會以為能用。**Mitigation**：disabled + 明顯 tooltip "MES 整合中"，不要藏起來（保留視覺一致性）。
4. **既有 alarm UI users 中斷** — 大改版可能影響當下值班操作員。**Mitigation**：保留 `?legacy=1` query param 走舊版 fallback 兩週；deploy 後一週內 monitor 是否有 user 反映。
5. **KPI MTTR 計算不準** — `(resolved_at - event_time)` 含 alarm 在 queue 的時間，不是真實 MTTR。**Mitigation**：v1 註明 "TTR (event → resolved)" 而非 MTTR；後續若加 ack_at→resolved_at 再切換語意。
6. **OKLCH 老瀏覽器** — Safari < 15.4 不支援。**Mitigation**：postcss-oklab-function fallback 或直接要求 evergreen browser（user 已 Chrome）。
7. **效能** — 50 ClusterCard × sparkline SVG 不該是瓶頸；若上千 alarm，clustering SQL 加 index `(status, equipment_id, trigger_event, event_time)`。

### 不會做（YAGNI）
- 不引入 `alarm_clusters` 寫入表（Tier 1 數量級不需要）
- 不導入 Redux / Zustand（local component state 夠）
- 不 i18n 化（v1 中文 hardcode）
- 不寫 cluster 自動命名 LLM（v1 用 trigger_event mapping）
- 不放 Hold / Dispatch 佔位按鈕（user 決議：MES 整合前不出現）
- 不留 `?legacy=1` fallback（user 決議：直接切換）

---

## 5. Decisions（已對齊 — 2026-05-01）

| # | 問題 | Decision |
|---|------|----------|
| 1 | Cluster grouping key | **`equipment_id` only**（同台機所有 alarm 歸一群，不依 trigger_event 拆） |
| 2 | Bay 欄位來源 | **從 `equipment_id` prefix 推**：`EQP-01~10 → A`、`EQP-11~20 → B`、`EQP-21~30 → C` |
| 3 | Ack 作用範圍 | **Cluster 級 batch ack**：對 cluster 內所有 `status=active` alarm 一次寫入 |
| 4 | Hold / Dispatch 佔位 | **不做**（MES 整合前完全不出現按鈕） |
| 5 | Legacy fallback (`?legacy=1`) | **不需要**（直接切換到新版 UI） |

---

Spec 進入 **Approved**，下一步直接開工。

