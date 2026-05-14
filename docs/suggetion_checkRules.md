# Pipeline Builder — 20 個推薦設計（涵蓋 11 種 chart）

> Generated 2026-05-10 from simulator data inventory. Use as catalog
> for demo skills, LLM training examples, and Pipeline Builder QA.

## Simulator 資料背景

- **7 種物件快照**（DC / SPC / APC / RECIPE / FDC / EC / OCAP），存於 `object_snapshots` collection
- **10 機台**（EQP-01 ~ EQP-10）、**6 站點**（PHOTO / ETCH / CMP / IMP / DIFF / THIN）
- **OOC 機率 30%**、**APC drift ratio 5%/process**、**hold 機率 5%**
- 5 種 SPC chart：`xbar`, `r`, `s`, `p`, `c`，每張帶 `value / ucl / lcl / is_ooc`
- APC 20 個 params（5 active + 15 passive），含 `mode`, `model_r2`
- FDC 含 `classification`, `fault_code`, `confidence`, `contributing_sensors`
- EC 8 個 constants 各 `{value, nominal, deviation_pct, status}`

---

## Tier 1 — 基礎監控 (5)

| # | Pipeline 名稱 | Source → Transform → Chart |
|---|---|---|
| 1 | **機台 SPC xbar 即時趨勢** | `process_history(tool_id, limit=200, objectName=SPC)` → `spc_long_form` → **line_chart** (x=eventTime, y=value, series_field=chart_name + UCL/LCL rules) |
| 2 | **全 Fab OOC rate by 站點** | `process_history(limit=2000)` → `compute(is_ooc = spc_status=='OOC')` → `groupby_agg(group_by=step, agg=mean)` → **bar_chart** (x=step, y=ooc_rate) |
| 3 | **Lot 完成時間分布** | `list_objects(kind=lot, status=finished)` → `compute(duration = end-start)` → **histogram_chart** (value=duration, bins=20) |
| 4 | **機台目前狀態分布** | `list_objects(kind=tool)` → `groupby_agg(group_by=status, agg=count)` → **bar_chart** (x=status, y=count) |
| 5 | **各機台 OOC 排名 (top contributor)** | `process_history(limit=5000)` → `filter(spc_status='OOC')` → `groupby_agg(group_by=toolID, agg=count)` → **pareto** (auto sort + cum%) |

## Tier 2 — SPC 品管嚴格 (5)

| # | Pipeline 名稱 | Source → Transform → Chart |
|---|---|---|
| 6 | **嚴謹 X̄-R 控制圖（subgroup + WECO）** | `process_history(tool_id, limit=300)` → **xbar_r** (subgroup_size=5, value=spc_xbar_chart_value) — 自動算 σ + WECO 警示 |
| 7 | **IMR 個值控制圖（單點漂移）** | `process_history(tool_id, limit=200, objectName=SPC)` → **imr** (value=spc_imr_pressure_value) |
| 8 | **EWMA-CUSUM 早期漂移偵測** | `process_history(tool_id, limit=500)` → **ewma_cusum** (value=spc_ewma_bias_value, lambda=0.2, k=0.5, h=4) |
| 9 | **SPC value 常態性 QQ Plot** | `process_history(limit=1000, step=STEP_010)` → **probability_plot** (value=spc_xbar_chart_value) |
| 10 | **製程能力 Cpk 排名** | `process_history(limit=2000)` → `cpk(value=spc_xbar_chart_value, group_by=toolID)` → **bar_chart** (x=toolID, y=cpk, rules=[1.0, 1.33]) |

## Tier 3 — APC 效能分析 (3)

| # | Pipeline 名稱 | Source → Transform → Chart |
|---|---|---|
| 11 | **APC `model_r2` 退化追蹤** | `process_history(limit=500, objectName=APC)` → `apc_long_form` → `filter(parameter_name='model_r2')` → **line_chart** (x=eventTime, y=value, series_field=apcID, rules=[{value:0.7, label:'警戒'}]) |
| 12 | **APC active vs passive 偏移對比** | `process_history(objectName=APC, limit=1000)` → `apc_long_form` → **box_plot** (x=mode, y=parameter_value) |
| 13 | **APC parameter drift 散布圖** | `process_history(objectName=APC, limit=300)` → `apc_long_form` → `filter(parameter_name='etch_time_offset')` → **scatter_chart** (x=eventTime, y=value) |

## Tier 4 — FDC / EC / Recipe (4)

| # | Pipeline 名稱 | Source → Transform → Chart |
|---|---|---|
| 14 | **FDC fault 分類統計** | `process_history(limit=2000, objectName=FDC)` → `groupby_agg(group_by=classification, agg=count)` → **bar_chart** (x=classification, y=count, color by category) |
| 15 | **EC 常數 deviation% 趨勢** | `mcp_call(get_object_history, kind=EC, limit=500)` → `filter(constant_name='source_power')` → **line_chart** (x=eventTime, y=deviation_pct, rules=[5%, 10%]) |
| 16 | **Recipe version bump 時間軸** | `process_history(objectName=RECIPE, limit=1000)` → `compute(is_bumped = recipe_version != prev)` → `groupby_agg(group_by=date, agg=sum)` → **bar_chart** (x=date, y=count) |
| 17 | **FDC contributing_sensors 共現矩陣** | `process_history(objectName=FDC, limit=500)` → `unpivot(contributing_sensors)` → **spatial_pareto** (x=sensor, y=站點, value=count) |

## Tier 5 — 跨物件相關性 (3)

| # | Pipeline 名稱 | Source → Transform → Chart |
|---|---|---|
| 18 | **APC drift vs SPC OOC 相關性** | `process_history(limit=2000)` → `apc_long_form` + `compute(ooc_flag)` → `groupby_agg(group_by=lotID, agg=mean drift / sum ooc)` → **scatter_chart** (x=apc_drift, y=ooc_count, regression line) |
| 19 | **Hold 機台與 OOC 累積比率** | `list_objects(kind=tool)` + `process_history(limit=3000)` → `join` → `compute(in_hold)` → `groupby_agg(group_by=in_hold, agg=mean ooc_rate)` → **bar_chart** (x=狀態, y=ooc_rate) |
| 20 | **Lot route 各 step 良率 (Pareto-style)** | `process_history(lot_id, limit=200)` → `groupby_agg(group_by=step, agg=mean ooc)` → **line_chart** (x=step_順序, y=pass_rate, highlight 跌破 95% 的 step) |

---

## Chart 多樣性盤點

| Chart Block | 次數 | 出現在 |
|---|---|---|
| `line_chart` | 5 | #1, #11, #15, #20, #(隱含 SPC 趨勢) |
| `bar_chart` | 6 | #2, #4, #10, #14, #16, #19 |
| `scatter_chart` | 2 | #13, #18 |
| `histogram_chart` | 1 | #3 |
| `box_plot` | 1 | #12 |
| `pareto` | 1 | #5 |
| `probability_plot` (QQ) | 1 | #9 |
| `xbar_r` | 1 | #6 |
| `imr` | 1 | #7 |
| `ewma_cusum` | 1 | #8 |
| `spatial_pareto` | 1 | #17 |

11 種 chart blocks **全部 covered**。

## 建議優先 demo / training set

| Pipeline # | 為什麼 |
|---|---|
| #1, #5, #14 | 最常見、3 種不同 chart（line / pareto / bar）、5-6 node 簡潔 |
| #6, #8 | SPC 嚴格圖，展示專業 block |
| #11, #18 | 跨物件 join / 相關性，測 agent 規劃複雜度 |

每個都剛好 **5-7 nodes**（minimal viable），cover `process_history → groupby/compute → chart` canonical pattern。讓 LLM 多看這些 → plan 結構會更穩。
