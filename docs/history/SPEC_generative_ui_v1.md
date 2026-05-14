# Spec: Generative UI Architecture — 從「LLM 寫 Code 畫圖」到「後端扁平化 + 前端互動探索」

**Version:** 1.0
**Date:** 2026-04-14
**Author:** Gill (Product) + Claude (Architecture)
**Status:** Draft — 評估 Spec，待確認後進入 Execution Plan

---

## 1. 問題陳述

### 1.1 現狀

目前 Copilot 的圖表產出依賴 LLM 在多個環節做正確的事：

```
User 問問題
  → LLM 選工具 (execute_skill / execute_mcp / execute_analysis)
    → 如果選 execute_analysis:
      → LLM 決定用哪個 MCP
      → LLM 生成 Python code
      → LLM 填寫 output_schema (type=spc_chart, x_key, y_key...)
      → chart_middleware 根據 output_schema 生成 chart DSL
      → 前端渲染
```

**每一步都可能出錯：**

| 環節 | 出錯方式 | 實測頻率 |
|------|---------|---------|
| 選工具 | 該用 analysis 卻用了 mcp（不出圖） | ~30% |
| 選 Skill | 選到功能相似但不完全匹配的 skill | ~20% |
| 寫 code | output 格式不對（dict vs list） | ~15% |
| 填 output_schema | type 或 key 填錯 → charts=0 | ~10% |
| 幻覺 | 說「圖表已渲染」但實際沒有 | ~20% |

**Baseline 測試結果（2026-04-14，30 cases）：**
- 圖表類 cases：60% 準確率
- 文字類 cases：87% 準確率
- 圖表失敗的 root cause 全部是 LLM 在上述環節出錯

### 1.2 舊版為什麼好

舊版（`/workspace/fastapi_backend_service`）的架構：

```
Skill 明確綁定 mcp_ids → 不需要 LLM 選
MCP 自帶 ui_render_config → chart 配置是靜態的
_auto_chart() 從 dataset + config 生成 Plotly → 不經 LLM
llm_readable_data / ui_render_payload 嚴格分離 → LLM 不碰 chart
```

**核心原則：LLM 只做「診斷推理」和「意圖宣告」，不碰資料格式和圖表渲染。**

### 1.3 目標

將架構從「LLM 動態寫 Code 畫圖」轉移為「後端資料扁平化 + 前端 Generative UI」，使得：

1. **圖表 100% 可靠** — 不依賴 LLM 寫對 code / output_schema
2. **零延遲切換** — 使用者可在前端直接切換維度（SPC→APC→DC），不需重新問 Agent
3. **LLM 專注推理** — 只做意圖理解和診斷分析，不管資料格式和渲染

---

## 2. 架構設計

### 2.1 Data Pipeline 總覽

```
User 問問題
  → [Node 1] Intent Understanding — LLM 理解需求
  → [Node 2] Data Retrieval — 呼叫 MCP 撈 raw data
  → [Node 3] Data Flattening — 純 Python，無 LLM，拆解巢狀 JSON
  → [Node 4] Visualization Intent — LLM 宣告「要看什麼」(UI Config JSON)
  → [Node 5] Data Diagnosis — LLM 讀扁平資料，做異常判斷
  → [Node 6] Response & Render — SSE 推送文字 + UI Config 到前端
  → Frontend ChartExplorer 渲染 — 使用者可自由切換維度
```

### 2.2 各節點詳細設計

#### Node 1: Intent Understanding（現有 `llm_call`）

**Input:** user_message + context
**Output:** tool_calls（決定要做什麼）

LLM 的決策簡化為兩條路：
- 有現成 Skill **完全匹配** → `execute_skill`
- 其他所有情況 → 進入 Data Pipeline（Node 2~6）

**關鍵改變：** 不再有 execute_mcp 和 execute_analysis 的三選一困境。LLM 只需決定「要查什麼資料」。

#### Node 2: Data Retrieval（現有 `tool_execute` 的 MCP 部分）

**Input:** LLM 指定的查詢意圖（equipment_id, step, since 等）
**Output:** raw ontology JSON（巢狀結構）

```python
# LLM 只需輸出查詢意圖：
{
  "action": "query",
  "data_source": "get_process_info",
  "params": {"equipment_id": "EQP-01", "step": "STEP_001", "since": "24h"}
}
```

後端自動呼叫對應的 MCP，不需要 LLM 呼叫 `execute_mcp` tool。

#### Node 3: Data Flattening（全新節點，純 Python，無 LLM）

**Input:** raw ontology JSON（`{total, events: [{SPC: {charts: {...}}, APC: {parameters: {...}}, ...}]}`）
**Output:** 6 個扁平化 dataset + metadata

```python
class FlattenedData:
    spc_data: List[Dict]     # [{eventTime, chart_type, value, ucl, lcl, is_ooc, toolID, lotID, step}]
    apc_data: List[Dict]     # [{eventTime, param_name, value, toolID, step}]
    dc_data: List[Dict]      # [{eventTime, sensor_name, value, toolID, step}]
    recipe_data: List[Dict]  # [{eventTime, recipe_version, param_name, value, toolID, step}]
    fdc_data: List[Dict]     # [{eventTime, classification, fault_code, confidence, toolID, step}]
    ec_data: List[Dict]      # [{eventTime, constant_name, value, nominal, deviation_pct, status}]
    
    metadata: Dict           # {total_events, ooc_count, ooc_rate, time_range, equipment_list, step_list}
```

**實作來源：** 現有 `render_intent_classifier.py` 的 `spc_flatten`, `apc_flatten_multiline`, `dc_flatten_multiline` 等 transform functions，獨立成 `data_flattener.py` service。

**關鍵原則：**
- 純 Python，零 LLM 介入
- 確定性 — 同樣的 input 永遠產生同樣的 output
- 所有 flatten 在這一步完成，後續節點只讀扁平資料

#### Node 4: Visualization Intent（全新節點）

**Input:** user_message + flattened_data.metadata
**Output:** UI Configuration JSON

LLM 不寫 code、不定義 output_schema、不選 chart type。它只宣告**使用者想看什麼**：

```json
{
  "ui_component": "ChartExplorer",
  "initial_view": {
    "data_source": "spc_data",
    "chart_type": "line",
    "x_axis": "eventTime",
    "y_axis": "value",
    "group_by": "chart_type",
    "filter": {"chart_type": "xbar_chart"},
    "highlight": {"field": "is_ooc", "value": true, "color": "red"},
    "control_lines": [
      {"field": "ucl", "style": "dashed", "color": "red", "label": "UCL"},
      {"field": "lcl", "style": "dashed", "color": "red", "label": "LCL"}
    ]
  },
  "available_views": ["spc_data", "apc_data", "dc_data", "recipe_data", "fdc_data", "ec_data"]
}
```

**如果使用者只問文字（「今天有什麼異常」）：**

```json
{
  "ui_component": "TextOnly",
  "show_data_explorer": false
}
```

**如果使用者問判斷型問題（「有沒有 OOC」）：**

```json
{
  "ui_component": "DiagnosisReport",
  "show_data_explorer": true,
  "initial_view": { ... }
}
```

**UI Config JSON Schema 設計原則：**
- 欄位名稱必須是 flattened_data 裡有的 key — LLM 看得到 metadata 裡的欄位清單
- chart_type 只有固定幾種：`line`, `bar`, `scatter`, `spc`（帶 control lines）
- filter / group_by 的值必須是 metadata 裡列出的 enum

#### Node 5: Data Diagnosis（現有 `synthesis` 的分析部分）

**Input:** user_message + flattened_data + metadata
**Output:** 診斷文字

LLM 讀扁平化資料（不是 raw ontology JSON），專注回答：
- OOC 統計和分佈
- 異常根因推論
- 建議動作

**不做的事：** 不寫 code、不定義 chart、不選 MCP。

**LLM 看到的資料範例：**
```
═══ DATA OVERVIEW ═══
total_events: 200, ooc_count: 33, ooc_rate: 16.5%
ooc_by_step: STEP_001:16, STEP_004:6, STEP_003:5
ooc_by_tool: EQP-09:8, EQP-01:7, EQP-03:6
═════════════════════

spc_data sample (first 5 of 1000):
  {eventTime: "2026-04-14T10:00", chart_type: "xbar_chart", value: 1523, ucl: 1570, lcl: 1430, is_ooc: false, toolID: "EQP-01", step: "STEP_001"}
  ...

apc_data sample (first 5 of 4000):
  {eventTime: "2026-04-14T10:00", param_name: "etch_time_offset", value: 0.048, toolID: "EQP-01", step: "STEP_001"}
  ...
```

#### Node 6: Response & Render（擴充現有 `adapter`）

**SSE 推送兩種 payload：**

```javascript
// 1. 文字回答
{"type": "synthesis", "text": "EQP-01 STEP_001 OOC 率 16.5%，主因是..."}

// 2. UI Configuration（前端收到後渲染 ChartExplorer）
{"type": "ui_config", "config": { ... UI Config JSON ... }}

// 3. 扁平化資料（前端快取）
{"type": "flat_data", "spc_data": [...], "apc_data": [...], "metadata": {...}}
```

前端收到後：
- `synthesis` → 顯示在 Copilot 右側
- `ui_config` → 初始化 ChartExplorer 在中央面板
- `flat_data` → 存入 Context/State，供 ChartExplorer 零延遲切換

### 2.3 前端 ChartExplorer 元件

```
┌──────────────────────────────────────────────┐
│ [SPC] [APC] [DC] [Recipe] [FDC] [EC]        │  ← data_source tabs
├──────────────────────────────────────────────┤
│ Chart Type: [Line ▼]  X: [eventTime ▼]       │
│ Y: [value ▼]  Group: [chart_type ▼]          │  ← control panel
│ Filter: [toolID: EQP-01 ▼] [step: ALL ▼]     │
├──────────────────────────────────────────────┤
│                                              │
│           📈 Interactive Chart               │  ← Plotly / Recharts
│           (hover, zoom, pan)                 │
│                                              │
├──────────────────────────────────────────────┤
│ 200 events · 33 OOC (16.5%) · 24h           │  ← status bar
└──────────────────────────────────────────────┘
```

**行為：**
- Agent 輸出的 `ui_config.initial_view` 決定初始狀態
- 使用者改 dropdown → 即時重繪（從前端 cache 讀資料）
- 零 API call、零 LLM call
- Tabs 切換也是零延遲（所有 6 種 flat data 已快取）

### 2.4 Sandbox 使用規範

| 允許 | 禁止 |
|------|------|
| 數值運算（mean, std, correlation） | import plotly / matplotlib / seaborn |
| 條件判斷（OOC count, threshold check） | 生成 chart spec / vega-lite / plotly JSON |
| 資料過濾 / 聚合 | 操作 UI / 呼叫外部 API |

Sandbox 的 output 只有：
- `_findings.condition_met` — bool
- `_findings.summary` — 文字
- `_findings.outputs` — 數值 / 表格（供 Diagnosis 節點讀取）

---

## 3. 與現有架構的對映

### 3.1 保留的

| 現有元件 | 角色 | 改變 |
|---------|------|------|
| LangGraph StateGraph | 狀態機框架 | 加新節點，不換框架 |
| load_context | Context 組裝 | 不變 |
| MCP definitions | 資料源定義 | 不變 |
| Skill definitions | 封裝好的 pipeline | 不變，skill-first 保留但降低優先 |
| self_critique | 反思檢查 | 不變 |
| memory_lifecycle | 記憶寫入 | 不變 |
| SSE adapter | 事件推送 | 擴充 ui_config + flat_data event types |

### 3.2 重構的

| 現有元件 | 改變 |
|---------|------|
| `render_intent_classifier.py` | transforms 搬到 `data_flattener.py`，classifier 角色由 Node 4 取代 |
| `chart_middleware.py` | **退役** — chart 生成移到前端 ChartExplorer |
| `render_card.py` execute_mcp 路徑 | 不再建 contract，改為推送 flat_data + ui_config |
| `tool_dispatcher.py` execute_analysis | 拆分：code 執行（sandbox）只做數值運算，chart 由前端處理 |
| `context_loader.py` routing rules | 大幅簡化 — 不再有三選一，只有「skill 或 pipeline」 |
| `ContractRenderer.tsx` | ChartExplorer 取代 chart DSL rendering |
| AICopilot chip buttons | ChartExplorer tabs 取代 |

### 3.3 新增的

| 新元件 | 職責 |
|-------|------|
| `data_flattener.py` | 純 Python，將巢狀 ontology JSON 拆為 6 個 flat dataset |
| `visualization_intent` node | LLM 宣告 UI Config JSON |
| `ChartExplorer.tsx` | 前端互動圖表探索器 |
| `FlatDataContext` | 前端 Context，快取 6 種 flat data |
| UI Config JSON schema | Agent ↔ Frontend 的圖表配置協議 |

---

## 4. LangGraph 節點重新設計

### 4.1 現有 vs 新版節點

```
現有：
  load_context → llm_call ⇄ tool_execute → synthesis → self_critique → memory_lifecycle

新版：
  load_context → llm_call → data_retrieval → data_flatten → viz_intent → diagnosis → synthesis → self_critique → memory_lifecycle
                    ↑              │
                    └── loop ──────┘ (如果需要更多資料)
```

### 4.2 工具定義簡化

**現有（3 個主要工具 + 多個輔助）：**
```
execute_skill, execute_mcp, execute_analysis,
list_skills, list_mcps, list_system_mcps,
draft_skill, draft_mcp, navigate, ...
```

**新版（2 個主要工具）：**
```
execute_skill  — 跑現成 Skill（完全匹配時）
query_data     — 宣告查詢意圖，後端自動呼叫 MCP + flatten
```

`execute_analysis` 的診斷功能保留在 Node 5 (Diagnosis)，但不再由 LLM 呼叫 — 系統自動在 pipeline 裡執行。

`execute_mcp` 降級為內部 API — 只在 Skill code 和 data_retrieval 節點內部使用，LLM 不直接呼叫。

---

## 5. 遷移策略

### 5.1 分階段實施

**Phase 1: Data Flattening Service（1-2 天）**
- 從 `render_intent_classifier.py` 提取 flatten functions → `data_flattener.py`
- 加入 metadata 生成（total_events, ooc_count, field_list 等）
- 單元測試：5 種 get_process_info response → 驗證 6 個 flat dataset

**Phase 2: UI Config JSON Schema + ChartExplorer 元件（2-3 天）**
- 定義 UI Config JSON schema（TypeScript + Python 雙語言）
- 實作 ChartExplorer.tsx（從 Dashboard 6-tab + SPCTab 演進）
- 控制面板：data_source tabs + chart_type + axis + filter dropdowns
- 驗證：手動傳 flat_data + ui_config → 圖表正確渲染 + 切換零延遲

**Phase 3: LangGraph Viz Intent Node（1-2 天）**
- 新增 `visualization_intent` node
- LLM prompt：給 metadata + user_message → 輸出 UI Config JSON
- 驗證：15 個 baseline test cases 的 ui_config 正確率

**Phase 4: SSE Adapter 擴充 + 前端整合（1-2 天）**
- adapter 推送 `ui_config` + `flat_data` SSE events
- Copilot 收到後初始化 ChartExplorer
- 驗證：end-to-end 30 test cases

**Phase 5: 退役 chart_middleware + 簡化 context_loader（1 天）**
- 移除 chart_middleware（前端 ChartExplorer 取代）
- 簡化 context_loader routing rules
- 移除 execute_mcp 從 LLM tool list

### 5.2 向後相容

| 功能 | 影響 | 處理 |
|------|------|------|
| Dashboard 6-tab | 已經是前端 cache | 遷移到 ChartExplorer，更互動 |
| Alarm Center DR charts | 走 skill_executor → chart_middleware | Phase 5 遷移到 ChartExplorer |
| Copilot chip buttons | 被 ChartExplorer 取代 | Phase 4 移除 |
| execute_analysis promote | 保留 — 但 promote 的是 diagnosis logic，不是 chart code | Phase 5 調整 |
| Auto-Patrol / DR skill code | 不影響 — skill 內部仍用 execute_mcp | 不變 |

---

## 6. 風險評估

| 風險 | 機率 | 影響 | 對策 |
|------|------|------|------|
| UI Config JSON schema 太複雜 → LLM 填錯 | 中 | 圖表初始狀態不對 | Schema 盡量簡單 + 前端容錯（有預設值） |
| 扁平化資料太大 → SSE 傳輸慢 | 低 | 首次載入延遲 | 只傳 metadata + 使用者點 tab 時 lazy load |
| ChartExplorer 互動性不足 | 低 | 使用者體驗差 | 從 Dashboard 6-tab 演進，已有基礎 |
| LLM 仍然嘗試寫 code 畫圖 | 中 | 走舊路徑 | 移除 execute_analysis 的 chart output + sandbox 禁止繪圖套件 |
| 現有 Skill 的 chart output 壞掉 | 中 | DR/AP 結果沒圖 | Phase 5 最後才退役 chart_middleware，確保新路徑穩定 |

---

## 7. 成功指標

| 指標 | 現狀 | 目標 |
|------|------|------|
| 圖表類 case 準確率 | 60% | 95%+ |
| 圖表首次出現延遲 | 5-30 秒（等 LLM 生成 code） | < 3 秒（pipeline 直出） |
| 維度切換延遲 | 需重新問 Agent（10-30 秒） | 0 秒（前端 cache） |
| LLM token 消耗 | 高（code generation + retry） | 減少 40%+（不寫 code） |
| Context loader rules 行數 | ~80 行 routing rules | < 20 行 |
| chart_middleware code | ~500 行 | 0（退役） |

---

## 8. 與 Skill Description Auto-gen Spec 的關係

`SPEC_skill_description_autogen.md` 裡的 Phase 3（自動生成 description）仍然有效 — Skill 的 description 品質決定 LLM 能不能正確匹配 skill。

但在 Generative UI 架構下，Skill matching 失敗的後果更小：
- 現在：選錯 skill → 錯誤的圖 / 沒有圖
- 新版：選錯 skill → 系統 fallback 到 data pipeline → 仍然能出圖

所以 skill description auto-gen 的**優先順序降低**，但仍建議做（改善 skill 命中率 → 減少 fallback → 更快）。

---

*此 Spec 由 Gill 提出架構方向，Claude 進行技術評估與細節設計。*
*待 Gill 確認後進入 Phase 1 實施。*
