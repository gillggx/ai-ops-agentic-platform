# Spec: 9-Stage Data Pipeline Architecture + Console Redesign

**Version:** 2.0
**Date:** 2026-04-14
**Author:** Gill (Architecture) + Claude (Implementation)
**Status:** Draft — 待確認後開始開發

---

## 1. 動機

### 1.1 現有問題

`execute_analysis` 是一個黑盒 mega-tool — 內部跑了一個完整的 sub-pipeline（LLM code gen → sandbox execute → chart middleware），跟我們設計的多 stage pipeline 互斥：

```
現狀：
  LLM Planning → query_data(撈資料) → execute_analysis(撈資料+寫code+執行+畫圖)
                                        ↑ 這裡面又跑了一個完整 pipeline
                                        ↑ 失敗就重試 → 10 次 loop
```

### 1.2 目標架構

每個 stage 職責單一、input/output 明確，由 LangGraph 控制流程：

```
目標：
  Stage 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9
  每一步都可以在 Console 看到做了什麼
  Stage 3~6 = Data Pipeline = 可存成 Skill
```

---

## 2. 九個 Stage 定義

### Stage 1: Context Load
**誰做：** 系統（純 Python，無 LLM）
**Input：** user_message, session_id
**Output：** system_prompt（含 soul prompt + MCP catalog + skill catalog + memory）

| Console 顯示 | 展開後細節 |
|-------------|----------|
| 📦 Context Load ✅ 0.3s | RAG Memory: 2 條（含 id + 摘要 + confidence）|
| | History: 3 輪 |
| | Skill Catalog: 12 My Skills |
| | MCP Catalog: 4 system MCPs |

---

### Stage 2: LLM Planning
**誰做：** LLM
**Input：** system_prompt + user_message
**Output：** plan（要做什麼 + 需要什麼資料 + 怎麼處理 + 怎麼呈現）

LLM 規劃整個 data pipeline：

```json
{
  "intent": "檢查 STEP_007 的 SPC charts 跟 APC rf_power_bias 的線性回歸",
  "data_retrieval": {
    "mcp": "get_process_info",
    "params": {"step": "STEP_007"}
  },
  "data_transform": {
    "description": "從 SPC 取 5 種 chart value，從 APC 取 rf_power_bias，by eventTime join"
  },
  "compute": {
    "description": "對每種 SPC chart type vs rf_power_bias 做線性回歸，計算 R²",
    "type": "linear_regression"
  },
  "presentation": {
    "chart_type": "scatter",
    "group_by": "chart_type",
    "show_regression_line": true,
    "show_r_squared": true
  }
}
```

| Console 顯示 | 展開後細節 |
|-------------|----------|
| 🧠 Planning ✅ 1.2s | Input tokens: 23,686 |
| | Plan: |
| | 　Data: get_process_info(step=STEP_007) |
| | 　Transform: SPC 5 charts + APC rf_power_bias, join by eventTime |
| | 　Compute: linear regression, R² per chart_type |
| | 　Present: scatter plot with regression line |

---

### Stage 3: Data Retrieval
**誰做：** 系統（呼叫 MCP API，無 LLM）
**Input：** plan.data_retrieval
**Output：** raw_data（巢狀 ontology JSON）

```
呼叫 get_process_info(step=STEP_007)
→ 128 events, 每筆含 SPC/APC/DC/RECIPE/FDC/EC nested objects
```

| Console 顯示 | 展開後細節 |
|-------------|----------|
| 📡 Data Retrieval ✅ 0.8s | MCP: get_process_info |
| | Params: step=STEP_007, since=24h (default) |
| | Response: 128 events |
| | Time range: 2026-04-13 18:00 ~ 2026-04-14 18:00 |

---

### Stage 4: Data Transform
**誰做：** LLM 生成 code → Sandbox 執行（看到 raw data sample 後決定怎麼處理）
**Input：** raw_data + plan.data_transform
**Output：** processed_data（扁平化、篩選、join 後的乾淨 dataset）

流程：
1. 系統先做基礎 flatten（6 個 flat dataset — 確定性，不需要 LLM）
2. LLM 看到 flat data 的 sample（3 rows per dataset）+ plan.data_transform
3. LLM 生成 transform code（例如：filter xbar + join apc by eventTime）
4. Sandbox 執行 code，輸入 _flat_data，輸出 processed_data

```python
# LLM 生成的 transform code 範例：
spc = [r for r in _flat_data['spc_data'] if r['chart_type'] == 'xbar_chart']
apc = [r for r in _flat_data['apc_data'] if r['param_name'] == 'rf_power_bias']

# Join by eventTime
from collections import defaultdict
apc_by_time = {r['eventTime']: r['value'] for r in apc}
joined = []
for r in spc:
    if r['eventTime'] in apc_by_time:
        joined.append({
            'eventTime': r['eventTime'],
            'xbar_value': r['value'],
            'rf_power_bias': apc_by_time[r['eventTime']],
            'chart_type': r['chart_type'],
            'is_ooc': r['is_ooc'],
        })

_processed_data = joined
```

| Console 顯示 | 展開後細節 |
|-------------|----------|
| 🔄 Data Transform ✅ 2.1s | Base flatten: 6 datasets |
| | 　spc_data: 640 rows |
| | 　apc_data: 2560 rows |
| | 　(其他 4 個...) |
| | Custom transform: filter xbar + join APC |
| | Output: 128 joined rows |
| | 📋 Code（可展開看 Python code）|

---

### Stage 5: Compute（可選）
**誰做：** LLM 生成 code → Sandbox 執行
**Input：** processed_data + plan.compute
**Output：** compute_results（數值結果：R², p-value, OOC count 等）

只在需要統計運算時觸發。簡單查看（「看 SPC trend」）跳過此 stage。

```python
# LLM 生成的 compute code 範例：
import numpy as np

results = []
for chart_type in set(r['chart_type'] for r in _processed_data):
    subset = [r for r in _processed_data if r['chart_type'] == chart_type]
    x = np.array([r['rf_power_bias'] for r in subset])
    y = np.array([r['xbar_value'] for r in subset])
    
    if len(x) >= 3:
        slope, intercept = np.polyfit(x, y, 1)
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        results.append({
            'chart_type': chart_type,
            'r_squared': round(r_squared, 4),
            'slope': round(slope, 6),
            'intercept': round(intercept, 4),
            'sample_count': len(x),
        })

_compute_results = results
```

| Console 顯示 | 展開後細節 |
|-------------|----------|
| 🔬 Compute ✅ 0.5s | Type: linear_regression |
| | Input: 128 joined rows |
| | Results: |
| | 　xbar_chart: R²=0.23, slope=0.0012 |
| | 　r_chart: R²=0.08, slope=-0.0003 |
| | 　s_chart: R²=0.15, slope=0.0008 |
| | 　(其他...) |
| | 📋 Code（可展開看 Python code）|

---

### Stage 6: Presentation
**誰做：** LLM 宣告 UI Config → 前端 ChartExplorer/DataExplorer 渲染
**Input：** processed_data + compute_results + plan.presentation
**Output：** UI Config JSON + 資料推送到前端

LLM 不畫圖。它只宣告要怎麼呈現：

```json
{
  "ui_component": "DataExplorer",
  "query_info": {
    "mcp": "get_process_info",
    "params": {"step": "STEP_007"},
    "result_summary": "128 events, 22 OOC (17.2%)"
  },
  "datasets": {
    "processed_data": [...128 rows...],
    "compute_results": [...5 rows...]
  },
  "initial_view": {
    "data_source": "processed_data",
    "chart_type": "scatter",
    "x_axis": "rf_power_bias",
    "y_axis": "xbar_value",
    "group_by": "chart_type",
    "regression_line": true,
    "annotations": [
      {"text": "R²=0.23", "position": "top-right"}
    ]
  },
  "available_views": ["processed_data", "compute_results", "spc_data", "apc_data"]
}
```

| Console 顯示 | 展開後細節 |
|-------------|----------|
| 📊 Presentation ✅ — | Component: DataExplorer |
| | Initial view: scatter (rf_power_bias vs xbar_value) |
| | Group by: chart_type (5 groups) |
| | Regression line: enabled |
| | Available datasets: processed_data, compute_results, spc_data, apc_data |

前端收到後：
- 中央 DataExplorer 顯示 scatter plot + regression line
- 使用者可自由切換 chart_type、改 x/y 軸、看 compute_results table

---

### Stage 7: Synthesis
**誰做：** LLM
**Input：** compute_results + metadata + user_message
**Output：** 文字結論

LLM 只做文字回答 — 根據 compute_results 寫結論：

```
STEP_007 的 SPC 5 種管制圖與 APC rf_power_bias 的線性回歸分析：

| Chart Type | R² | 相關性 |
|-----------|-----|-------|
| xbar_chart | 0.23 | 弱正相關 |
| r_chart | 0.08 | 無顯著相關 |
| s_chart | 0.15 | 弱正相關 |
| p_chart | 0.31 | 中度正相關 ⚠️ |
| c_chart | 0.05 | 無顯著相關 |

結論：p_chart 與 rf_power_bias 有最高的相關性（R²=0.31），
建議重點監控 APC 的 rf_power_bias 偏移對 p_chart 的影響。
```

| Console 顯示 | 展開後細節 |
|-------------|----------|
| 💬 Synthesis ✅ 1.8s | Input tokens: 25,848 |
| | Output: 320 chars |
| | Contract: NO（DataExplorer 已在 Stage 6 渲染） |

---

### Stage 8: Self-Critique
**誰做：** LLM
**Input：** synthesis text + tool results
**Output：** pass / amendment

| Console 顯示 | 展開後細節 |
|-------------|----------|
| 🔍 Self-Critique ✅ 0.5s | Status: PASS |
| | Verified: R² values match compute_results |
| | Issues: 0 |

---

### Stage 9: Memory Lifecycle
**誰做：** 系統 + LLM（背景）
**Input：** 整個 pipeline 的 context
**Output：** memory write（如果有學到新東西）

| Console 顯示 | 展開後細節 |
|-------------|----------|
| 💡 Memory ✅ 0.3s | Retrieved: 1 memory cited |
| | 　[mem:15] confidence 7→8 (+1 success) |
| | New memory: 「STEP_007 SPC vs APC 回歸用 scatter + R²」 |
| | Status: SCHEDULED |

---

## 3. Console UI 設計

### 3.1 整體布局

Console 從現有的 flat log list 改為 **pipeline steps card list**：

```
┌─ Console ────────────────────────────────────┐
│                                               │
│  📦 Context Load                    ✅ 0.3s  │
│  ─────────────────────────────────────────── │
│  🧠 Planning                       ✅ 1.2s  │
│  ─────────────────────────────────────────── │
│  📡 Data Retrieval                  ✅ 0.8s  │
│    get_process_info(step=STEP_007)           │
│    128 events                                │
│  ─────────────────────────────────────────── │
│  🔄 Data Transform                  ✅ 2.1s  │
│    6 datasets → filter + join → 128 rows     │
│    [▶ 展開 code]                              │
│  ─────────────────────────────────────────── │
│  🔬 Compute                         ✅ 0.5s  │
│    linear_regression → 5 results             │
│    [▶ 展開 code]  [▶ 展開 results]           │
│  ─────────────────────────────────────────── │
│  📊 Presentation                    ✅ —     │
│    DataExplorer: scatter (5 groups)          │
│  ─────────────────────────────────────────── │
│  💬 Synthesis                       ✅ 1.8s  │
│    320 chars                                 │
│  ─────────────────────────────────────────── │
│  🔍 Self-Critique                   ✅ PASS  │
│  ─────────────────────────────────────────── │
│  💡 Memory                          ✅ 0.3s  │
│    +1 learned, 1 cited                       │
│                                               │
│  Total: 7.0s | LLM: 3 calls | Tokens: 52k   │
└───────────────────────────────────────────────┘
```

### 3.2 Card 狀態

| 狀態 | 圖示 | 行為 |
|------|------|------|
| Pending | ⚪ 灰色 | 尚未開始 |
| Running | 🟡 黃色 + spinner | 正在執行 |
| Complete | 🟢 綠色 + ✅ | 完成，可展開 |
| Skipped | ⚪ 灰色 + ⏭️ | 不需要（如 Compute 跳過）|
| Error | 🔴 紅色 + ❌ | 失敗，自動展開 |

### 3.3 展開內容

每個 card 預設收合（一行摘要）。點擊展開後顯示：

| Stage | 展開內容 |
|-------|---------|
| Context Load | Memory hits + confidence、history turns、catalog sizes |
| Planning | Plan JSON（formatted）、token usage |
| Data Retrieval | MCP name + params、response size、time range |
| Data Transform | Base flatten sizes、custom code（syntax highlight）、output size |
| Compute | Compute type、input/output sizes、results table、code |
| Presentation | UI Config JSON、initial view 設定 |
| Synthesis | Token usage、output length |
| Self-Critique | Status、verified items、issues |
| Memory | Retrieved memories（id + summary + confidence）、new memory、feedback |

### 3.4 底部統計

```
Total: 7.0s | LLM calls: 3 | Tokens: 52,340 (in: 49k, out: 3.3k) | Data: 128 events
```

---

## 4. Skill 轉換

### 4.1 什麼可以存成 Skill

Stage 3~6 的參數 + code = 一個完整的 Data Pipeline Skill：

```yaml
Skill:
  name: "STEP_007 SPC vs APC rf_power_bias Linear Regression"
  data_retrieval:
    mcp: "get_process_info"
    params: {step: "STEP_007"}
  data_transform:
    code: "filter xbar + join APC rf_power_bias by eventTime"
  compute:
    code: "linear regression per chart_type, calc R²"
  presentation:
    chart_type: "scatter"
    x_axis: "rf_power_bias"
    y_axis: "xbar_value"
    group_by: "chart_type"
    regression_line: true
  input_schema:
    - {key: "step", type: "string", required: true}
  output_schema:
    - {key: "regression_results", type: "table"}
    - {key: "scatter_plot", type: "scatter_chart"}
```

### 4.2 Skill 執行

下次問同樣的問題：
1. LLM Planning 找到 Skill → `execute_skill(skill_id=X, params={step: "STEP_007"})`
2. 系統直接跑 Stage 3~6（不需要 LLM 重新規劃）
3. 結果進 Stage 7 Synthesis

### 4.3 Skill 升級路徑

```
Copilot 對話 → 「儲存為 My Skill」 → My Skill
My Skill → 綁 Event → Auto-Patrol（自動巡檢）
My Skill → 綁 Alarm → Diagnostic Rule（告警診斷）
```

---

## 5. Stage 4 & 5 的 Code Generation 策略

### 5.1 兩層處理

**Layer 1: 基礎 Flatten（確定性，不需要 LLM）**

```python
# 系統自動執行，每次都一樣
flat_data = data_flattener.flatten(raw_data)
# 產出 6 個標準 flat dataset: spc_data, apc_data, dc_data, recipe_data, fdc_data, ec_data
```

**Layer 2: Custom Transform（LLM 生成，根據需求不同）**

```python
# LLM 看到 flat_data sample 後生成
# Input: _flat_data (dict of 6 datasets)
# Output: _processed_data (list of dicts)
```

### 5.2 LLM 生成 Code 的 Context

LLM 在 Stage 4/5 生成 code 時，看到的是：

```
═══ AVAILABLE DATA ═══
_flat_data['spc_data'] (640 rows):
  sample: {"eventTime": "2026-04-14T10:00", "chart_type": "xbar_chart", "value": 15.6, "ucl": 17.5, "lcl": 12.5, "is_ooc": false, "toolID": "EQP-01", "step": "STEP_007"}

_flat_data['apc_data'] (2560 rows):
  sample: {"eventTime": "2026-04-14T10:00", "param_name": "rf_power_bias", "value": 0.95, "toolID": "EQP-01", "step": "STEP_007"}

(其他 4 個 dataset...)
═════════════════════

USER REQUEST: 對每種 SPC chart_type vs rf_power_bias 做線性回歸

TASK: 生成 Python code，從 _flat_data 提取所需資料，放入 _processed_data
可用模組: numpy, scipy.stats, collections
禁止: import requests, os, sys, matplotlib, plotly
```

**LLM 看到真實的 field names + data types，不需要猜。**

### 5.3 跳過策略

| 使用者需求 | Stage 4 | Stage 5 |
|-----------|---------|---------|
| 「看 SPC trend」 | Layer 1 only（基礎 flatten） | ⏭️ Skip |
| 「看 xbar + APC overlay」 | Layer 1 + Layer 2（join） | ⏭️ Skip |
| 「5 點有 2 點 OOC 嗎」 | Layer 1 only | ✅ OOC count check |
| 「回歸 R²」 | Layer 1 + Layer 2（join） | ✅ Linear regression |
| 「常態分佈 + sigma」 | Layer 1 only | ✅ Normal distribution stats |

---

## 6. SSE Event 對應

| Stage | SSE Event(s) | Payload |
|-------|-------------|---------|
| 1 Context Load | `context_load` | rag_hits, history_turns, cache_blocks |
| 2 Planning | `plan` + `llm_usage` | plan text/JSON, tokens |
| 3 Data Retrieval | `data_retrieval` | mcp, params, event_count, time_range |
| 4 Data Transform | `data_transform` | base_flatten_sizes, custom_code, output_size |
| 5 Compute | `compute_result` | type, results, code |
| 6 Presentation | `ui_config` + `flat_data` | UI Config JSON, processed datasets |
| 7 Synthesis | `synthesis` | text, token usage |
| 8 Self-Critique | `reflection_pass` / `reflection_amendment` | status, issues |
| 9 Memory | `memory_write` | retrieved, feedback, new_memory |

---

## 7. 與現有架構的關係

### 7.1 退役

| 元件 | 原因 |
|------|------|
| `execute_analysis` tool | 被 Stage 3~6 取代 |
| `execute_mcp` (LLM 直接呼叫) | 被 Stage 3 query_data 取代 |
| `chart_middleware.py` | 被 Stage 6 + 前端 ChartExplorer 取代 |
| `render_intent_classifier.py` | 被 Stage 4 基礎 flatten + Stage 6 取代 |
| `render_card.py` execute_mcp 路徑 | 被 Stage 3~6 pipeline 取代 |

### 7.2 保留

| 元件 | 角色 |
|------|------|
| LangGraph StateGraph | 狀態機框架（加新 stages） |
| `execute_skill` tool | Copilot 呼叫已存的 Skill |
| `skill_executor_service.py` | Skill 執行（DR/AP 走這條） |
| `data_flattener.py` | Stage 4 Layer 1 基礎 flatten |
| `ChartExplorer.tsx` + `DataExplorerPanel.tsx` | Stage 6 前端渲染 |

### 7.3 LLM Tool List 簡化

```
現在: query_data, execute_analysis, execute_skill, list_skills, draft_skill, ...
目標: execute_skill (唯一 tool — 因為 Stage 3~6 由 pipeline 自動執行)
```

LLM 在 Stage 2 Planning 時不選工具 — 它規劃 pipeline（要什麼資料、怎麼處理、怎麼呈現）。系統根據 plan 自動執行 Stage 3~6。

唯一例外：LLM 在 Planning 時發現 Skill Catalog 有完全匹配的 Skill → 直接 `execute_skill`，跳過 Stage 3~6。

---

## 8. Execution Plan

| Phase | 內容 | 預估 |
|-------|------|------|
| **Phase 1** | Plan JSON schema + LLM planning prompt | 1 天 |
| **Phase 2** | LangGraph 新 nodes（data_retrieval, data_transform, compute, presentation） | 2 天 |
| **Phase 3** | Sandbox 讀 _flat_data + code gen for Stage 4/5 | 1 天 |
| **Phase 4** | Console UI 重寫（9 stages, collapsible cards） | 2 天 |
| **Phase 5** | SSE event 擴充 + DataExplorer 整合 | 1 天 |
| **Phase 6** | Skill 轉換（「儲存為 Skill」= save Stage 3~6） | 1 天 |
| **Phase 7** | 退役 execute_analysis + chart_middleware + render_intent_classifier | 1 天 |
| **Phase 8** | 20 test cases 驗證 + baseline 更新 | 1 天 |

**Total: ~10 天**

---

## 9. 驗證 Test Cases（20 cases）

### 簡單查看（Stage 3 + 4 Layer 1 + 6 + 7）

| # | Prompt | 預期 Pipeline |
|---|--------|-------------|
| 1 | EQP-01 的 APC etch_time_offset 趨勢 | Retrieve → Flatten → Present(apc trend) → Synthesis |
| 2 | STEP_001 的 xbar_chart trend | Retrieve → Flatten → Present(spc filter xbar) → Synthesis |
| 3 | EQP-05 列出 OOC 站點和 SPC charts | Retrieve → Flatten → Present(spc) → Synthesis(OOC 列表) |
| 4 | 我想看 EQP-02 今天的製程資訊 | Retrieve → Flatten → Synthesis(文字) |
| 5 | TC16: STEP_001 7 天 SPC all charts | Retrieve(since=7d) → Flatten → Present(spc all) → Synthesis |

### 純文字（Stage 3 + 7）

| # | Prompt | 預期 Pipeline |
|---|--------|-------------|
| 6 | 目前有哪些機台 | Retrieve(list_tools) → Synthesis(文字) |
| 7 | 全廠 OOC 率是多少 | Retrieve(summary) → Synthesis(文字) |
| 8 | EQP-01 最近有沒有 OOC | Retrieve(summary) → Synthesis(文字) |
| 9 | 今天有什麼異常嗎 | Retrieve(summary) → Synthesis(文字) |
| 10 | 今天有沒有需要停機檢查的 | Retrieve(summary) → Synthesis(文字) |

### 跨 Dataset（Stage 3 + 4 Layer 2 + 6 + 7）

| # | Prompt | 預期 Pipeline |
|---|--------|-------------|
| 11 | 比較 EQP-01 和 EQP-02 的 SPC xbar | Retrieve×2 → Flatten → Transform(merge by tool) → Present(overlay) → Synthesis |
| 12 | TC17: xbar + APC rf_power_bias 同張圖 | Retrieve → Flatten → Transform(join) → Present(overlay dual-axis) → Synthesis |
| 13 | TC18: 多 APC params trend | Retrieve → Flatten → Present(apc multi-param) → Synthesis |

### 統計計算（Stage 3 + 4 + 5 + 6 + 7）

| # | Prompt | 預期 Pipeline |
|---|--------|-------------|
| 14 | TC19: SPC charts + 5 點 2 OOC check | Retrieve → Flatten → Compute(OOC count per 5-window) → Present(spc + badge) → Synthesis |
| 15 | TC20: SPC vs APC 線性回歸 R² | Retrieve → Flatten → Transform(join) → Compute(regression) → Present(scatter + R²) → Synthesis |
| 16 | xbar 常態分佈 + 1~4σ 標記 | Retrieve → Flatten → Transform(filter xbar) → Compute(normal dist stats) → Present(histogram + sigma bands) → Synthesis |

### PE 產線情境

| # | Prompt | 預期 Pipeline |
|---|--------|-------------|
| 17 | EQP-03 剛 OOC 了幫我看一下 | Retrieve → Flatten → Present(spc all) → Synthesis(diagnosis) |
| 18 | 為什麼這台一直 OOC | 正確反問（缺機台） |
| 19 | 哪台機台最需要關注 | Retrieve(summary) → Synthesis(ranking) |
| 20 | 為什麼 EQP-01 的 OOC 比 EQP-02 高 | Retrieve(summary) → Synthesis(comparison) |

---

*此 Spec 由 Gill 提出架構方向，Claude 進行技術設計。*
*待確認後進入 Phase 1。*
