# SPEC: Dashboard 設備總覽 重設計 — Phase 1 (Fleet Overview)

- Status: **Draft** (2026-05-01)
- Author: gill + Claude (Tech Lead)
- Reference: `/Users/gill/AIOps - Tool healthy check/HANDOFF.md`（Claude-generated 高保真原型）
- Replaces (partial): `aiops-app/src/app/dashboard/page.tsx` Mode A (FabHeatmap)

---

## 1. Context & Objective

### 痛點

`/dashboard`（無 `toolId` 時）目前只給「Tool × Step OOC heatmap」+ 一段 AI summary。痛點：
1. 操作員打開首頁要的是「**現在最該看哪台**」+「**為什麼**」，不是熱力圖座標
2. 排序資訊缺失 — 哪台 high / med / low 沒在主畫面講清楚
3. 沒有跨機台關聯（A 台 + B 台同 chamber group 一起壞 → 應合併呈現）
4. AI summary 只是一段文字，沒結構化「Top 3 該關心的事」

### Objective（Phase 1 範圍）

把首頁 `/dashboard`（無 toolId 時）改成 handoff 的 `fleet-merged.jsx` 形：

1. **AI Briefing hero**（接 chat agent SSE）— 整廠一句話講重點
2. **Top 3 Concerns 卡片**（rule-based v1）— 每張：嚴重度 / 信心 / 標題 / 證據 / 建議行動
3. **Ranked tool list**（依嚴重度排序）— sparkline + status dot + 5 個 metric 欄

**不在 Phase 1**：
- EQP detail（Phase 2 — `eqp-detail.jsx`）
- 製程溯源 3-tab 重構（Phase 3）
- 既有 `/dashboard?toolId=XX` 路徑保留**完全不動**（Mode B 6-tab + ProcessTracePanel 暫時不換）

---

## 2. Architecture & Design

### 2.1 Backend — 新 endpoint（4 條）

#### A. `GET /api/v1/fleet/equipment?since_hours=24`

| field | type | source |
|-------|------|--------|
| `id` | string | `equipment.id` |
| `name` | string | `equipment.name` |
| `health` | `"crit" \| "warn" \| "healthy"` | derived from `score` |
| `score` | int (0-100) | `100 − (oocCount*5 + alarms*3 + fdc*2)`, clamp [0,100] |
| `ooc` | float (%) | `oocCount / lots24h * 100` |
| `oocCount` | int | count(alarms WHERE trigger='spc.ooc' AND eq=this) since_hours |
| `alarms` | int | count(alarms WHERE status='active' AND eq=this) since_hours |
| `fdc` | int | count(alarms WHERE trigger LIKE 'fdc.%') since_hours（v1 留 0，simulator 沒 FDC alert）|
| `lots24h` | int | count(distinct lot_id from process_history) since_hours |
| `trend` | `"up" \| "down" \| "flat"` | `late=avg(hourly[16..23])`, `early=avg(hourly[0..7])`：late>early\*1.2 = down，late<early\*0.8 = up，否則 flat |
| `note` | string | 最近一筆 active alarm.title；無則空 |
| `hourly[24]` | float[] | per-hour OOC % bucket（24 個 bucket） |

**Sort：** `health` (crit→warn→healthy) → tie-break by `ooc` desc。

**Cache：** 60s server-side（fleet ranking 不需即時，避免 DB 重讀）。

#### B. `GET /api/v1/fleet/concerns?since_hours=24`

回傳 0–3 個 concern。**v1 純 rule-based**，rule list：

| rule_id | 觸發條件 | severity | confidence |
|---------|---------|----------|-----------|
| R1_critical_tool | 任一機台 `health="crit"` | crit | 1.0 |
| R2_rising_trend | `health="warn"` 且 `trend="down"` 且 `hourly[late]>5%` | warn | 0.85 |
| R3_cross_step_cluster | 同 step 在 ≥2 台機台都有 OOC | warn | 0.7 |

每個 concern shape：
```ts
{
  id: string; rule_id: string;
  severity: "crit" | "warn";
  confidence: number;        // 0..1
  title: string;             // 中文，動態填 tool/step
  detail: string;            // 中文，動態填數字
  tools: string[]; steps: string[];
  evidence: number;          // count of supporting alarms
  actions: string[];         // 1-3 條建議
}
```

最多回 3 個（嚴重度 + confidence 排序）。

#### C. `POST /api/v1/fleet/briefing/stream` — SSE

Hero 那段 narrative，串到既有 chat agent infra（**走目前 `/api/admin/briefing` 同款 SSE shape**，只是 scope 換成 `"fleet"` + body 帶聚合 stats）。

Backend 流程：
1. 收到 stats body
2. 組 prompt（含 fleet 聚合 + top 3 concerns 摘要）
3. 不開 tool call 模式 — 純 LLM `generate` 模式
4. SSE chunk 流文字回前端
5. 失敗時前端 fallback 到 rule-derived 一句話模板

#### D. `GET /api/v1/fleet/stats?since_hours=24`

幫 hero 右邊 metrics sidebar 用，避免前端自己算：
```json
{
  "fleet_ooc_rate": 5.32,    "ooc_events": 18,
  "total_events": 2971,      "fdc_alerts": 0,
  "open_alarms": 7,          "affected_lots": 31,
  "crit_count": 2,           "warn_count": 3,
  "as_of": "2026-05-01T..."
}
```

### 2.2 Frontend — 結構

```
src/styles/fleet-overview.css                   ← Inter + IBM Plex Mono + 設計 tokens
                                                   （palette per handoff: #b8392f/#b87a1f/#2f8a5b/#3a64b8）
src/components/fleet/
  FleetOverview.tsx                             ← 主 orchestrator，fetch 並組裝 3 區
  FleetBriefingHero.tsx                         ← 頂 hero（AI 文字 + 整體 metrics）
  TopConcernsRow.tsx                            ← 3 張 concern cards
  ToolList.tsx                                  ← ranked table
  primitives/
    Sparkline.tsx                               ← 從 charts.jsx 移植
    HourStrip.tsx                               ← 24 bar mini chart
    StatusDot.tsx, Pill.tsx, TrendArrow.tsx
```

`/dashboard/page.tsx` 改：
- 無 `toolId` → 渲染 `<FleetOverview />`（替代 `<FabHeatmap />`）
- 有 `toolId` → 完全不動，照舊跑既有 6-tab + ProcessTracePanel

### 2.3 設計細節

**Layout（grid）：**
```
┌──────────────────────────────────────────────────────────────────┐
│  [HERO]  AI Briefing 文字（左 1fr）  │  Fleet metrics（右 280px）│
├──────────────────────────────────────────────────────────────────┤
│  TOP 3 CONCERNS                                                   │
│  [card1]  [card2]  [card3]                                        │
├──────────────────────────────────────────────────────────────────┤
│  RANKED TOOL LIST                                                 │
│  # | EQP-XX  | Status | OOC% | 24h sparkline | events | AI sig | →│
│  ...                                                              │
└──────────────────────────────────────────────────────────────────┘
```

**Severity 視覺：** 採 handoff 規範
- 左側 3px stripe（crit=#b8392f / warn=#b87a1f / healthy=#2f8a5b）
- Pill + 彩色 mono 數字
- **不用紅色背景塞滿**

**Click 行為：**
- Tool row 點擊 → `router.push("/dashboard?toolId=EQP-XX")` 跳到既有 Mode B
- Concern card「下鑽」按鈕 → 同上 + URL 加 `?concern=cN` query

---

## 3. Step-by-Step Execution Plan（2-3 day）

### Day 1 — Backend

1. **AlarmRepository / EquipmentRepository** 加聚合 query：
   - `findHourlyOocBuckets(eqId, since)` → 24 個 float
   - `countActiveAlarmsByEquipment(since)` → Map<eq_id, int>
2. 新 controller `FleetController`：4 個 endpoint
3. `FleetConcernRulesService`：3 條 rule + 模板字串
4. `FleetBriefingService`：複用既有 chat agent SSE（`/api/admin/briefing` 同 path 同 token），新 scope `fleet`
5. 單元測試（`FleetConcernRulesServiceTest` cover 3 條 rule）

### Day 2 — Frontend
6. `fleet-overview.css` 設計 token + 字型 lazy load（同 alarm-center）
7. Primitives（Sparkline / HourStrip / StatusDot / Pill / TrendArrow）— 純 SVG
8. `FleetBriefingHero` + SSE wiring
9. `TopConcernsRow` + `ToolList`
10. `FleetOverview` 串起來；page.tsx swap

### Day 3 — Deploy + Verify
11. `deploy/update.sh`
12. **Verify like a user**（記取 LESSONS_LEARNED theme 5）：
    - 開 `/dashboard` 無 `?toolId`：看到 hero + 3 cards + tool list
    - 確認 sparkline 不全 0
    - 確認 hero 文字流出（SSE working）
    - 點 tool row → 切到 `?toolId=XX` Mode B 不破
    - 確認 ranked sort 對：crit 在最上，OOC% tie-break 對

---

## 4. Edge Cases & Risks

### 邊界
1. **0 equipment 在 since 範圍** → fleet 表顯示「目前無資料」，hero / concerns 隱藏
2. **0 個 concern** → 整段 TOP 3 區塊隱藏，不留空殼
3. **SSE 失敗 / chat agent down** → fallback 到「整廠 N 個 alarm，最嚴重 EQP-XX」純模板
4. **某 tool 沒 process_history**（idle 機台）→ `lots24h=0`、`hourly` 全 0、healthy
5. **alarm 清得很乾淨後第一個 tool 仍標 crit** → 因為 score 是按 since 區間累計，不是即時；UI 註明「24h 內」

### 風險
1. **Rule 1 (R1) 直接抄 health=crit 等於跟 ToolList 重複**（同樣 tool 在 concerns + list 都出現）
   → **Mitigation**：list row 上 AI signal 欄如果該 tool 有 concern 就顯示 confidence；不互斥
2. **AI briefing 慢於 1.5s** → hero 顯示「AI 分析中…」spinner，避免空白
3. **score 公式跟 alarm-center health_score 不同步**（alarm-center 是整廠級，這裡是 per-tool）
   → 公式不同正確，但要在 spec 註明，未來改要兩邊一起改
4. **既有 Mode A 用戶突然看到全新 UI** → 不留 `?legacy=1`（之前 alarm-center 也沒留），但保留 git revert 路徑（單 commit 即可回滾）
5. **Sparkline render 性能**：10 機台 × 每個 24 bar SVG = 240 rect，可以接受；之後要 30 機台再考慮 canvas

### 不會做（YAGNI）
- 不引入 Plotly / D3 — 純 SVG
- 不存 `fleet_concerns` 寫入表（rule 即時跑 < 50ms）
- 不 i18n（per gill 決議）
- 不做 area 分組（per gill 決議）
- 不放 Hold / Dispatch placeholder（同 alarm-center 規範）

---

## 5. Decisions（已對齊）

| # | 問題 | 決議 |
|---|------|------|
| 1 | 目標頁 | `/dashboard`（無 toolId 模式 = Mode A） |
| 2 | Area 分組 | 不做 |
| 3 | AI briefing | 接 chat agent SSE（不寫死規則） |
| 4 | i18n 雙語 | 不做（zh only） |
| 5 | 既有 TopologyCanvas | Phase 3 整合進「製程溯源」3 sub-tab，不在 Phase 1 範圍 |

---

請問這份 Phase 1 Spec 是否符合預期？若確認無誤，請回覆「**開始開發**」。
