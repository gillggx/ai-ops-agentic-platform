# Phase 12 — Candidate Skill Catalog

> **2026-05-10 update** · Phase 11 v6 cleanup — the Skill Library is the
> single authoring entry point. Pipeline Builder is no longer linked from
> the main nav; users reach it through Skill → Build/Refine. Direct hits
> to `/admin/pipeline-builder` redirect to `/skills`. Legacy free-standing
> pipelines + auto_patrols + auto_check_triggers are dropped by V26.



20 candidate Skills designed against the current simulator data model
(Phase 12). Each skill maps to a real `event_type` we emit or a cron
schedule, exercises a different chart type, and references concrete
tables / fields available today.

> **Author 2026-05-10** · derived from `ontology_simulator/app/services/*`
> + `event_types` seed (V24/V25) + chamber dimension + parameter audit log.

---

## Available simulator data (recap)

| Layer | Surface | Volume |
|---|---|---|
| DC sensors | `object_snapshots` `objectName='DC'` | ~120 sensors / process / chamber |
| SPC charts | `object_snapshots` `objectName='SPC'` | 12 charts / process; `is_ooc` per chart |
| EC constants | `object_snapshots` `objectName='EC'` | 50 constants / process / chamber, 7 are PM counters |
| FDC | `object_snapshots` `objectName='FDC'` | 30 fault codes (`FDC_<area>_<code>`) |
| APC | `object_snapshots` `objectName='APC'` | 20 params, 5 active (with self-correct) |
| Recipe | `object_snapshots` `objectName='RECIPE'` | 20 recipes, version bumps tracked |
| Audit log | `parameter_audit_log` | APC auto-correct + recipe bump + engineer override |
| Alarms | `alarms` | ack/dispose lifecycle (Phase 12) |
| Chambers | `chamberID` on every snapshot/event | 4 per tool (CH-1..CH-4), random per process |
| Lot type | `lot_type` on events + lots | `production` (k=1.5σ) / `monitor` (k=2.0σ, sparse step subset) |

## Registered system events (`event_types`)

`OOC` · `FDC_FAULT` · `FDC_WARNING` · `PM_START` · `PM_DONE`
`EQUIPMENT_HOLD` · `RECIPE_VERSION_BUMP` · `APC_AUTO_CORRECT`
`ENGINEER_OVERRIDE` · `MONITOR_LOT_RUN` · `ALARM_RAISED`

---

## A. OCAP / SPC OOC investigation (event-triggered)

| # | Skill | Trigger | C1 confirm | Checklist | Chart |
|---|---|---|---|---|---|
| 1 | **OCAP 5-in-3-out** | `OOC` | 近 5 lot OOC ≥ 3 才繼續 | ① OOC 趨勢 ② 違規 chart 排名 ③ 對應 APC 變更 audit | line + bar Pareto + timeline |
| 2 | **Chamber match (event)** | `OOC` | 觸發 chamber vs 兄弟差距 > 2σ | ① 4-chamber 同 chart 線圖 ② boxplot 比對 | 4-line + box plot |
| 3 | **跨機台同站點 drift** | `OOC` | 同站點 ≥ 2 台同時 OOC | ① 同 chart 跨 tool 趨勢 ② 站點 fanout heatmap | line + heatmap (tool × hour) |
| 4 | **Drift accumulation 倒推** | `OOC` | 違規 chart 在 OOC 前 5 step 已有 drift | ① 30-step LOESS 趨勢 ② drift slope by step | line + scatter w/ regression |

## B. FDC fault analysis (event-triggered)

| # | Skill | Trigger | C1 confirm | Checklist | Chart |
|---|---|---|---|---|---|
| 5 | **Fault code Pareto** | `FDC_FAULT` | 同 fault_code 24h ≥ 3 次 | ① fault_code 排名 ② contributing_sensors 堆疊 | horizontal Pareto + stacked bar |
| 6 | **Multi-sensor 早期警告** | `FDC_WARNING` | WARN 連 5 process | ① 30 個 warning sensor radar ② 共現矩陣 | radar + correlation heatmap |
| 7 | **FDC vs SPC 一致性** | `FDC_FAULT` | FAULT 但 SPC PASS（罕見） | ① FAULT-without-OOC 列表 ② sensor 落在哪 | table + scatter |

## C. EC equipment constants & PM management

| # | Skill | Trigger | C1 confirm | Checklist | Chart |
|---|---|---|---|---|---|
| 8 | **EC counter saturation** | cron 每 4h | 任一 counter / `alert_at` > 80% | ① 7 個 counter 進度條 ② 預估剩餘 wafer | progress matrix + bar |
| 9 | **Pre-PM 抽屜** | `PM_START` | 跑此 skill 一定走 | ① RF 群組 drift % ② Vacuum 群組 ③ Thermal 群組 | grouped bar (3 panels) |
| 10 | **Post-PM 驗收** | `PM_DONE` | recalibration 後跑滿 5 lot | ① 5 個 SPC sensor pre/post 對比 ② boxplot | dual line + box plot |
| 11 | **PM 週期穩定度** | cron 每日 06:00 | 非首次跑 | ① 各 tool PM 間隔 days ② 趨勢是否縮短 | line per tool + slope |

## D. Recipe / APC change attribution

| # | Skill | Trigger | C1 confirm | Checklist | Chart |
|---|---|---|---|---|---|
| 12 | **Recipe bump impact** | `RECIPE_VERSION_BUMP` | bump 後跑滿 10 lot | ① bump 前後 etch_rate ② SPC OOC 率對比 ③ 標記 vertical | dual-axis line + version markers |
| 13 | **APC 過度修正** | `APC_AUTO_CORRECT` | 同 APC 連 5 process 都 self-correct | ① 修正量 trend ② 修正方向是否震盪 | line + sign histogram |
| 14 | **工程師手動 override audit** | `ENGINEER_OVERRIDE` | 永遠跑 | ① 7d override timeline ② engineer × parameter heatmap ③ override 後 OOC 率 | timeline + heatmap + before/after bar |

## E. Chamber dimension (Phase 12)

| # | Skill | Trigger | C1 confirm | Checklist | Chart |
|---|---|---|---|---|---|
| 15 | **Chamber match daily** | cron 每日 08:00 | tool 啟用中 | ① 各 chamber σ 差異排名 ② 最差 tool 4-chamber 線圖 | bar + 4-line |
| 16 | **Chamber loading 不平均** | cron 每 4h | 24h 樣本 ≥ 50 | ① chamber processed count 條形 ② 是否某 chamber loading > 35% | bar + flag |

## F. Monitor lot QA

| # | Skill | Trigger | C1 confirm | Checklist | Chart |
|---|---|---|---|---|---|
| 17 | **Monitor vs Production drift** | `MONITOR_LOT_RUN` | 永遠跑 | ① monitor lot SPC vs production lot SPC 線圖 ② σ 差異趨勢 | overlay line + delta plot |
| 18 | **Monitor lot pass rate** | cron 每日 | 24h 內有 monitor 跑過 | ① pass rate per tool ② 7d 趨勢 | grouped bar + line |

## G. Alarm management

| # | Skill | Trigger | C1 confirm | Checklist | Chart |
|---|---|---|---|---|---|
| 19 | **Alarm disposition mix** | cron 每日 06:00 | 24h 有 ≥ 3 alarm | ① 4 disposition 比例堆疊 ② scrap 率是否異常 | stacked bar + threshold line |
| 20 | **Alarm response SLA** | cron 每週一 09:00 | 7d 樣本 | ① ack latency 直方圖 ② disposition latency 中位數 ③ 過長 outlier 列表 | histogram + box + table |

---

## Chart-type coverage (全部 18 種 + radar)

| Chart 類型 | 對應 Skill |
|---|---|
| line / multi-line | #1, #2, #3, #4, #10, #11, #12, #13, #15, #17, #18 |
| Pareto (sorted bar) | #5, #9, #11 |
| heatmap | #3, #6, #14 |
| scatter w/ regression | #4, #7 |
| box plot | #2, #10, #20 |
| stacked bar | #5, #19 |
| radar | #6 |
| histogram | #20 |
| dual-axis line + markers | #12 |
| progress / gauge matrix | #8 |
| timeline events | #1, #14 |
| correlation heatmap | #6 |
| grouped bar (multi-panel) | #9, #18 |

---

## 建議 PoC 前 5 條

優先做這 5 條，能 cover 80% trigger 類型 + 8 種以上 chart：

1. **#1 OCAP 5-in-3-out** — line + bar Pareto + timeline
2. **#15 Chamber match daily** — 4-line + bar
3. **#8 EC counter saturation** — progress matrix
4. **#12 Recipe bump impact** — dual-axis line + version markers
5. **#19 Alarm disposition mix** — stacked bar

---

## Sample input bindings per trigger type

當 `trigger_type=event` 時，pipeline input 自動從 event payload 拉
（V25 已 backfill `event_types.attributes`）：

```jsonc
// OOC payload                FDC_FAULT payload          PM_START payload
{ tool_id, lot_id, step,      { tool_id, lot_id, step,   { tool_id, reason }
  chamber_id, spc_chart,        chamber_id, fault_code,
  severity }                    contributing_sensors }

// RECIPE_VERSION_BUMP        APC_AUTO_CORRECT           ENGINEER_OVERRIDE
{ recipe_id, old_version,     { apc_id, parameter,       { object_name, object_id,
  new_version, changed_params } old_value, new_value,      parameter, old_value,
                                prev_spc_status }          new_value, engineer, reason }
```

當 `trigger_type=schedule` 時，input 來自 trigger.target：

| target.kind | input shape |
|---|---|
| `all` | `tool_id` (fanout 10 tools) |
| `tools` | `tool_id` (fanout selected) |
| `stations` | `station_id` (fanout selected) |

---

## Backed by which `object_snapshots` queries

| Skill | 主要查詢 |
|---|---|
| #1, #4 | `objectName='SPC'` time-window aggregation by `chart_id`, `is_ooc` |
| #2, #15 | `objectName='SPC'` GROUP BY `chamberID` |
| #3 | `objectName='SPC'` × event payload `step` GROUP BY `toolID` |
| #5–7 | `objectName='FDC'` GROUP BY `fault_code`, `contributing_sensors` |
| #8 | `objectName='EC'` filter `value/alert_at > threshold` |
| #9, #10, #11 | `objectName='EC'` + `tool_events.eventType IN (PM_*)` |
| #12 | `parameter_audit_log` `source='recipe_version_bump'` + SPC trend |
| #13 | `parameter_audit_log` `source='apc_auto_correct'` |
| #14 | `parameter_audit_log` `source LIKE 'engineer:*'` |
| #16 | `events.eventType='PROCESS_END'` GROUP BY `toolID, chamberID` |
| #17, #18 | `events` filter `lot_type='monitor'` |
| #19, #20 | `alarms` (Java DB) |
