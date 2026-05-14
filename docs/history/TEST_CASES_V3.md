# Pipeline Builder — Test Cases V3

**Date:** 2026-04-18
**Purpose:** 驗證 Phase α/β/γ/δ 完成後的 23-block 積木組合能力
**Scope:** 原 V2 的 20 cases（Agent 路徑）+ 新 24 cases（新積木 + 進階組合）= **44 cases**

---

## 符號說明

| 符號 | 意義 |
|---|---|
| 🟢 | **JSON TC** — 直接構造 pipeline_json 測試，CI 可跑 |
| 🤖 | **Agent TC** — 需真 LLM（`ANTHROPIC_LIVE=1`）驗 prompt 收斂 |
| 📊 | 預期開 DataExplorer / Results panel |
| 💬 | 預期 Copilot 文字回答 |
| ❓ | Agent 應反問（缺資訊） |
| 🚫 | 系統無法，應誠實說「目前無法」 |

---

## Section 1 — Baseline（沿襲 V2 的 20 cases）

Baseline 聚焦 **Agent 能否用新積木庫正確建出合理 pipeline**。這些沿用 V2 的 prompt，重點在 Agent 路徑的覆蓋率提升（V2 17/20 pass）。

| # | Prompt | 類型 | 預期（新積木視角） |
|---|---|---|---|
| TC01 | EQP-01 的 APC etch_time_offset 趨勢 | 🤖📊 | `process_history → chart(y=apc_etch_time_offset)` |
| TC02 | STEP_001 的 xbar_chart trend chart | 🤖📊 | `process_history → chart(SPC 模式, ucl_column=...)` |
| TC03 | EQP-05 列出 OOC 站點和 SPC charts | 🤖📊💬 | `process_history → filter(OOC) → groupby_agg(step,count) → chart(bar)` |
| TC04 | 比較 EQP-01 和 EQP-02 的 SPC xbar 趨勢 | 🤖📊 | 分兩次抓 → **`block_union`** → `chart(color=toolID)` |
| TC05 | 我想看 EQP-02 今天的製程資訊 | 🤖📊 | `process_history(time_range=24h) → chart` |
| TC06 | 目前有哪些機台 | 🤖💬 | **`block_mcp_call`**(list_tools) — 改用通用 wrapper，不再 ❓ |
| TC07 | 10 個機台今天有多少 OOC | 🤖💬 | `process_history → filter(OOC) → groupby_agg(toolID,count) → sort(desc)` |
| TC08 | EQP-01 最近有沒有 OOC | 🤖💬 | `process_history → filter(OOC)` → count |
| TC09 | 今天有什麼異常嗎 | 🤖💬 | `process_history(24h) → filter(OOC) → groupby_agg` |
| TC10 | EQP-03 剛 OOC 了幫我看一下 | 🤖📊💬 | `process_history → chart(SPC 模式)` |
| TC11 | 為什麼這台一直 OOC | 🤖❓ | 缺機台 ID → 反問 |
| TC12 | 為什麼 EQP-01 的 OOC 比 EQP-02 高這麼多 | 🤖💬 | `process_history → groupby_agg → sort`；誠實承認統計≠根因 |
| TC13 | 哪台機台最需要關注 | 🤖💬 | **`block_sort`** top-N |
| TC14 | 今天有沒有需要停機檢查的 | 🤖🚫💬 | 沒有 PM schedule MCP — 誠實說無法 |
| TC15 | STEP_001 7 天 SPC all charts | 🤖📊 | `process_history(7d) → 5 個 chart 或 unpivot` |
| TC16 | EQP-07 xbar + APC rf_power_bias 同張圖 | 🤖📊 | `chart(y="spc_xbar...", y_secondary=["apc_rf..."])` — **Phase α 雙軸** |
| TC17 | STEP_001 多 APC params trend | 🤖📊 | 多個 chart node 或 unpivot |
| TC18 | STEP_007 所有 SPC charts + 5 點 2 OOC check | 🤖📊💬 | `unpivot → rolling_window(is_ooc, sum, 5) → threshold(>=2)` |
| TC19 | STEP_007 SPC vs APC rf_power_bias 線性回歸 R² | 🤖📊💬 | **`unpivot → linear_regression(group_by=chart_type) → chart(bar,y=r_squared)`** |
| TC20 | STEP_001 xbar 常態分布 + 1~4σ 標記 | 🤖📊💬 | **`histogram`** + `chart(bar, SPC 模式含多 σ)` |

**V3 期望：**
- TC06 從 🚫 轉成 可做 — 有 `block_mcp_call`
- TC13 從「Agent 亂建」變成 `sort` 一步到位
- TC16 雙軸化 — Phase α chart 擴充
- TC18/19/20 有對應積木 — 之前 V2 辦不到

---

## Section 2 — 新積木 × 24 case

### Group A — Phase α (5)
| # | Scenario | 類型 | 關鍵積木 |
|---|---|---|---|
| TCα1 | STEP_001 xbar 常態 histogram bins=20 | 🟢🤖 | `histogram(bins=20)` → `chart(bar, x=bin_center, y=count)` |
| TCα2 | EQP-01 10 站 OOC 數 top-3 | 🟢🤖 | `groupby_agg + sort(desc, limit=3)` |
| TCα3 | 5 台機台 xbar 分布 boxplot | 🟢 | `chart(chart_type=boxplot, group_by=toolID, y=spc_xbar_chart_value)` |
| TCα4 | EQP-07 SPC xbar + APC rf_power_bias 雙軸 | 🟢🤖 | `chart(y="spc_xbar", y_secondary=["apc_rf_power_bias"])` |
| TCα5 | EQP-01 xbar vs APC rf_power_bias 線性回歸含 95% CI | 🟢🤖 | `linear_regression(x_column=apc_rf..., y_column=spc_xbar..., confidence=0.95)` — 驗 stats/data/ci 三 port |

### Group B — Phase β (7)
| # | Scenario | 類型 | 關鍵積木 |
|---|---|---|---|
| TCβ1 | STEP_007 5 種 SPC chart_type R² 一次出（unpivot + group_by）| 🟢🤖 | `unpivot → linear_regression(group_by=chart_type)` |
| TCβ2 | EQP-01 xbar Cpk（USL=115, LSL=85）全機台 | 🟢🤖 | `cpk(usl=115, lsl=85)` |
| TCβ3 | EQP-01 xbar Cpk per-step（group_by=step）| 🟢 | `cpk(group_by=step)` |
| TCβ4 | EQP-01 + EQP-02 union overlay xbar | 🟢 | `union(outer) → chart(color=toolID)` |
| TCβ5 | EQP-01 xbar Nelson R1..R8 全掃 | 🟢 | `weco_rules(rules=all-8)` |
| TCβ6 | 5 張 SPC chart WECO → `any_trigger` 聚合 → 單一 alert | 🟢🤖 | `any_trigger(OR 4) → alert`；evidence 含 `source_port` |
| TCβ7 | Union schema mismatch → intersect 模式 | 🟢 | `union(on_schema_mismatch=intersect)` 只保留共同欄 |

### Group C — Phase γ (7)
| # | Scenario | 類型 | 關鍵積木 |
|---|---|---|---|
| TCγ1 | 多 APC 參數 correlation heatmap | 🟢🤖 | `correlation(method=pearson) → chart(heatmap)` |
| TCγ2 | EQP-01 vs EQP-02 xbar 均值是否顯著不同（t-test）| 🟢 | `hypothesis_test(t_test, group=toolID)` |
| TCγ3 | 10 機台今日 OOC 是否獨立於機台（chi-square）| 🟢 | `hypothesis_test(chi_square, group=toolID, target=spc_status)` |
| TCγ4 | 5 個 step 的 xbar 均值是否顯著不同（ANOVA）| 🟢 | `hypothesis_test(anova, group=step)` |
| TCγ5 | EQP-01 xbar EWMA α=0.2 vs 原值 overlay | 🟢🤖 | `ewma → chart(y=[原值, ewma])` |
| TCγ6 | ANOVA k<3 groups → INVALID_INPUT | 🟢 | 預期錯誤 |
| TCγ7 | EWMA α=1.5 → INVALID_PARAM | 🟢 | 預期錯誤 |

### Group D — Phase δ (3)
| # | Scenario | 類型 | 關鍵積木 |
|---|---|---|---|
| TCδ1 | 呼叫 list_tools MCP → table | 🟢(mock)🤖 | `mcp_call(mcp_name=list_tools)` |
| TCδ2 | 呼叫不存在 MCP → MCP_NOT_FOUND | 🟢 | 預期錯誤 |
| TCδ3 | MCP 回傳 `{events: [...]}` → 自動 flatten | 🟢 | DataFrame 從 events 取 |

### Group E — 綜合 (2)
| # | Scenario | 類型 |
|---|---|---|
| TC-all-1 | 23 blocks 全部 schema 合法 + 有 examples 欄位（如 UX 做完）| 🟢 |
| TC-all-2 | 原 V2 20 cases 的 pipeline_json 直接表達率（不用 LLM）| 🟢 |

---

## 執行計劃

1. Section 2（Group A–E，共 24 case）先實作
   - 🟢 寫成 pytest integration file
   - 🤖 寫成 e2e `.spec.ts`，用 `ANTHROPIC_LIVE` env 閘門
2. Section 1 原 V2 的 20 case 保持在 Agent 驗證（🤖），但期待成功率從 17/20 提升
3. 最後跑 report — 統計 pass/fail/coverage

---

## 驗證結果格式（報告用）

```
| TC | 類型 | 狀態 | 備註 |
|---|---|---|---|
| TC01 | 🤖 | Manual pending | ANTHROPIC_LIVE 跑 |
| TCα1 | 🟢 | ✅ | bins=20, count sum = 原 rows |
...
```
