# Spec: Console Redesign + Data Explorer 位置調整

**Version:** 1.0
**Date:** 2026-04-14
**Author:** Gill + Claude
**Status:** Draft

---

## 1. 問題陳述

### 1.1 Console 的 Stage 已過時

現在 Console 顯示 Stage 1~6，但跟新的 Generative UI pipeline 不對應：

```
現在的 Console：
● Stage 1  ● Stage 3  ● Stage 4  ● Stage 5  ● Stage 6
  (context)  (tool)     (synth)    (critique)  (memory)

實際 pipeline：
  Context → Plan → Data Retrieval → Flatten → Viz Config → Diagnosis → Synthesis → Critique → Memory
```

使用者看到「Stage 3」不知道是在撈資料還是在做分析。

### 1.2 Console 缺少細節

目前只有一行 log，例如：
```
🔧 query_data(data_source=get_process_info, params={step: STEP_001})
✅ get_process_info
📊 Data flattened: 28 events, 6 datasets
```

PE 想知道更多：
- 撈了什麼資料？查詢條件是什麼？
- Flatten 後各 dataset 有幾筆？
- LLM 做了什麼判斷？
- Memory 寫了什麼？

### 1.3 Data Explorer 位置錯誤

ChartExplorer 目前渲染在 copilot 右側（360px 寬），太窄。應該在中央 AnalysisPanel。

### 1.4 Memory 功能不透明

Memory 機制在背景運作，使用者完全不知道：
- 有沒有從記憶中找到相關經驗
- Agent 有沒有根據過去經驗調整行為
- 這次對話有沒有產生新記憶

---

## 2. Console 重新設計

### 2.1 Pipeline Steps（取代 Stage 1~6）

每個 step 是一個可收合的 card：

```
┌─ 📦 Context Load                                    ✅ 0.3s
│  (點擊展開)
│  RAG Memory: 2 條相關經驗
│    [mem:15] 「EQP-01 STEP_001 OOC 時優先查 APC drift」 confidence: 7/10
│    [mem:23] 「STEP_001 xbar 異常常見原因是 chamber pressure」 confidence: 5/10
│  History: 3 輪對話
│  Skill Catalog: 44 skills
│  MCP Catalog: 4 system MCPs
└──

┌─ 🧠 LLM Planning                                    ✅ 1.2s
│  (點擊展開)
│  Input tokens: 22,001
│  Plan:
│    Step 1: query_data(get_process_info, step=STEP_001)
│    Step 2: 分析 APC etch_time_offset 趨勢
│  Tool chosen: query_data
│  Visualization: apc_data (filter: etch_time_offset)
└──

┌─ 📡 Data Retrieval                                   ✅ 0.8s
│  (點擊展開)
│  MCP: get_process_info
│  Params: step=STEP_001, since=24h
│  Response: 28 events
└──

┌─ 🔄 Data Flatten                                     ✅ 0.1s
│  (點擊展開)
│  Input: 28 raw events (nested JSON)
│  Output:
│    spc_data:    140 rows (5 chart types × 28 events)
│    apc_data:    560 rows (20 params × 28 events)
│    dc_data:     840 rows (30 sensors × 28 events)
│    recipe_data: 560 rows
│    fdc_data:    28 rows
│    ec_data:     224 rows (8 constants × 28 events)
│  OOC: 5/28 (17.86%)
│  Top OOC: EQP-01(2), EQP-03(1), EQP-04(1), EQP-05(1)
└──

┌─ 📊 Visualization Config                             ✅ —
│  (點擊展開)
│  Component: ChartExplorer
│  Initial view: apc_data
│  Filter: param_name = etch_time_offset
│  Available: SPC, APC, DC, Recipe, FDC, EC
└──

┌─ 💬 Synthesis                                        ✅ 2.1s
│  (點擊展開)
│  Input tokens: 23,833
│  Output: 580 chars
│  Contract: NO (文字回答 + ChartExplorer)
└──

┌─ 🔍 Self-Critique                                    ✅ 0.5s
│  (點擊展開)
│  Status: PASS
│  Verified: 3 data points checked
│  Issues: 0
└──

┌─ 💡 Memory Lifecycle                                 ✅ 0.3s
│  (點擊展開)
│  Retrieved: 2 memories cited
│  Feedback: [mem:15] +1 success (confidence: 7→8)
│  New memory: 「STEP_001 APC etch_time_offset 查詢用 query_data + apc_data filter」
│  Status: SCHEDULED (background write)
└──
```

### 2.2 收合/展開行為

- **預設收合** — 只看到 icon + 標題 + 狀態 + 耗時
- **點擊展開** — 看到完整細節
- **錯誤時自動展開** — 如果某步出錯，自動展開顯示錯誤詳情
- **Running 時顯示動畫** — 當前正在執行的 step 有 spinner

### 2.3 SSE Event 對應

| Pipeline Step | SSE Event(s) | 展開內容來源 |
|---------------|-------------|------------|
| Context Load | `context_load` | ev.rag_hits, ev.history_turns, ev.cache_blocks |
| LLM Planning | `llm_usage` + `plan` | ev.input_tokens, ev.text |
| Data Retrieval | `tool_start` + `tool_done` (query_data) | ev.input, ev.result_summary |
| Data Flatten | `flat_data` | ev.metadata (dataset_sizes, ooc stats) |
| Viz Config | `ui_config` | ev.config |
| Synthesis | `synthesis` | ev.text length, ev.contract |
| Self-Critique | `reflection_pass` or `reflection_amendment` | ev.issues |
| Memory | `memory_write` | ev.content, ev.memory_type |

不需要新的 SSE events — 所有資訊已經在現有 events 裡。只需要前端把它們組織成 pipeline steps 而非 flat log。

---

## 3. Data Explorer 位置

### 3.1 從 Copilot 移到中央 AnalysisPanel

```
┌──────────┬──────────────────────────────────────┬───────────┐
│ Sidebar  │        Central Panel                  │  Copilot  │
│          │                                        │           │
│ 設備清單  │  ┌─ 查詢條件 ─────────────────────┐   │  對話     │
│          │  │ MCP: get_process_info          │   │           │
│          │  │ step=STEP_001, since=24h        │   │  Console  │
│          │  │ 結果: 28 events, 5 OOC (17.86%)│   │           │
│          │  └────────────────────────────────┘   │           │
│          │                                        │           │
│          │  ┌─ Data Explorer ────────────────┐   │           │
│          │  │ [SPC] [APC] [DC] [Recipe] ...  │   │           │
│          │  │ Filter: [etch_time_offset ▼]    │   │           │
│          │  │                                 │   │           │
│          │  │   📈 Interactive Chart          │   │           │
│          │  │                                 │   │           │
│          │  └────────────────────────────────┘   │           │
└──────────┴──────────────────────────────────────┴───────────┘
```

### 3.2 查詢條件面板

Data Explorer 上方顯示：

```
┌─────────────────────────────────────────────────┐
│ 📋 Query: get_process_info                       │
│ step=STEP_001 | since=24h | limit=50             │
│ ──────────────────────────────────────────────── │
│ Results: 28 events | 5 OOC (17.86%)              │
│ Tools: EQP-01~10 | Steps: STEP_001               │
│ Time range: 2026-04-13 18:00 ~ 2026-04-14 14:00  │
└─────────────────────────────────────────────────┘
```

### 3.3 觸發方式

- `query_data` + `visualization_hint` → 自動在中央開啟 Data Explorer
- `query_data` 不帶 hint → 不開 Data Explorer，只有文字
- `execute_skill` → 照舊的 Investigate Mode（Contract + Evidence Chain）
- 用戶點 copilot 的「查看資料」按鈕 → 也能手動開啟 Data Explorer

---

## 4. Memory 透明化

### 4.1 Console 中的 Memory 呈現

**Retrieval（Context Load 階段）：**
```
📦 Context Load
  RAG Memory: 2 條相關經驗
    🧠 [mem:15] 「EQP-01 STEP_001 OOC 時優先查 APC drift」
       confidence: 7/10 | used 3 times | last used 2h ago
    🧠 [mem:23] 「xbar 異常常見原因是 chamber pressure drift」
       confidence: 5/10 | used 1 time | last used 1d ago
```

**Write（Memory Lifecycle 階段）：**
```
💡 Memory Lifecycle
  Feedback: [mem:15] 被引用 → confidence +1 (7→8)
  New: 「STEP_001 查詢用 query_data + apc_data filter 可得到完整 APC 趨勢」
  Status: 已排程寫入
```

### 4.2 Memory 對使用者的價值

PE 可以從 Console 看到：
- **Agent 有沒有「記住」之前的經驗** — 「上次查 EQP-01 也是 APC 的問題」
- **經驗是否被正確使用** — confidence 分數反映可靠度
- **新的學習** — Agent 從這次對話學到了什麼

### 4.3 Memory 目前的限制

| 限制 | 說明 | 影響 |
|------|------|------|
| 工具數 >= 2 才寫入 | 單工具成功不學習 | 很多有價值的 query_data 經驗被跳過 |
| 抽象品質依賴 LLM | LLM 可能產生低品質摘要 | 部分記憶無用 |
| 無時間衰減 | 舊記憶永遠存在 | 資料庫膨脹 |
| 引用追蹤是軟約束 | Agent 可能不標記 `[memory:id]` | feedback 不準確 |

---

## 5. Execution Plan

| Priority | 項目 | 改動範圍 |
|----------|------|---------|
| **P0** | Data Explorer 移到中央 | AICopilot.tsx, AppShell.tsx, 新增 DataExplorerPanel |
| **P0** | 查詢條件面板 | DataExplorerPanel 新增 QuerySummary |
| **P1** | Console pipeline steps | AICopilot.tsx Console tab 重寫 |
| **P1** | 收合/展開 UI | PipelineStep component |
| **P2** | Memory 透明化 | Console 顯示 memory retrieval + write |
| **P3** | Memory 門檻降低 | memory_lifecycle.py 改 tools_used >= 1 |

---

## 6. 不改的

- LangGraph 圖拓撲不變（load_context → llm_call ⇄ tool_execute → synthesis → ...）
- SSE event types 不變（不需要新 events，只需要前端重新組織）
- Backend data_flattener 不變
- query_data tool 不變

---

*此 Spec 由 Gill 提出需求，Claude 進行設計。待確認後實施。*
