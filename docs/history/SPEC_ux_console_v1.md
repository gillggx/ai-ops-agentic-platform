# Spec: Console Pipeline Cards + Alarm Center UX 降噪 + Summary 修復

**Version:** 1.0
**Date:** 2026-04-15
**Author:** Gill + Gemini (UX) + Claude (Architecture)
**Status:** Draft

---

## 1. Console Collapsible Pipeline Cards

### 1.1 現狀
Console tab 是一個 flat log list（icon + text），沒有結構。使用者看到：
```
📦 CTX | RAG 記憶: 0 條 | 歷史: 0 輪
🧠 Planning ✅ 1.2s — ...
📡 Data Retrieval ✅ 0.8s — get_process_info(step=STEP_001) → 200 events
🔄 Data Transform ✅ 0.1s — Base: spc_data=1000, apc_data=4000...
📊 Presentation ✅ — DataExplorer: spc_data (line)
💬 Synthesis ✅ 1.8s
```

### 1.2 目標
改為 **可收合的 card list**，每個 card 對應一個 pipeline stage：

```
┌─────────────────────────────────────────────────────┐
│ 📦 Context Load                          ✅ 0.3s   │
│   RAG: 0 條 | History: 0 輪                        │
├─────────────────────────────────────────────────────┤
│ 🧠 Planning                             ✅ 1.2s   │
│   → get_process_info(step=STEP_001)                │
│   → presentation: spc_data                          │
│   [▶ 展開 plan JSON]                                │
├─────────────────────────────────────────────────────┤
│ 📡 Data Retrieval                        ✅ 0.8s   │
│   MCP: get_process_info | step=STEP_001            │
│   200 events | 24h                                  │
├─────────────────────────────────────────────────────┤
│ 🔄 Data Transform                        ✅ 0.1s   │
│   spc=1000 apc=4000 dc=6000 recipe=4000            │
│   [▶ 展開 code]                                     │
├─────────────────────────────────────────────────────┤
│ 🔬 Compute                              ⏭️ skip   │
├─────────────────────────────────────────────────────┤
│ 📊 Presentation                          ✅        │
│   DataExplorer: spc_data (line)                     │
├─────────────────────────────────────────────────────┤
│ 💬 Synthesis                             ✅ 1.8s   │
│   269 chars                                         │
├─────────────────────────────────────────────────────┤
│ 🔍 Self-Critique                         ✅ PASS   │
├─────────────────────────────────────────────────────┤
│ 💡 Memory                               ✅ 0.3s   │
│   +0 learned                                        │
├─────────────────────────────────────────────────────┤
│ Total: 4.5s | LLM: 2 calls | Tokens: 42k          │
└─────────────────────────────────────────────────────┘
```

### 1.3 Card 行為

| 狀態 | 圖示 | 背景 | 行為 |
|------|------|------|------|
| Pending | ⚪ | — | 灰色，等待中 |
| Running | 🟡 | — | 黃色 + subtle pulse |
| Complete | 🟢 | — | 綠色，可點擊展開 |
| Skipped | ⚪ | — | 灰色 + ⏭️，一行 |
| Error | 🔴 | 淺紅底 | 紅色，自動展開 |

### 1.4 展開內容

| Stage | 收合顯示 | 展開內容 |
|-------|---------|---------|
| Context | RAG 條數 + History 輪數 | Memory hits（id + summary + confidence）|
| Planning | 查詢條件 + presentation | Plan JSON（formatted）|
| Retrieval | MCP + params + event count | Response time + time range |
| Transform | Dataset sizes | Custom transform code（syntax highlight）|
| Compute | Type + result count | Code + results table |
| Presentation | Component + initial view | UI Config JSON |
| Synthesis | Char count | Token usage |
| Critique | PASS/FAIL | Issues list |
| Memory | Learned count | New memory content |

### 1.5 底部統計欄

```
Total: 4.5s | LLM: 2 calls | Tokens: 42,340 (in: 40k, out: 2.3k)
```

### 1.6 實作方式

**不需要新 SSE events** — 所有資訊已在現有 events 裡：

| SSE Event | → Card |
|-----------|--------|
| `stage_update(stage=1)` | Context card |
| `plan` + `llm_usage` | Planning card |
| `pipeline_stage(stage=3)` | Retrieval card |
| `pipeline_stage(stage=4)` | Transform card |
| `pipeline_stage(stage=5)` | Compute card |
| `pipeline_stage(stage=6)` | Presentation card |
| `synthesis` | Synthesis card |
| `reflection_pass/amendment` | Critique card |
| `memory_write` | Memory card |

前端改動：AICopilot Console tab 從 `logs: LogEntry[]` 改為 `pipelineCards: PipelineCard[]`。

```typescript
interface PipelineCard {
  stage: number;
  name: string;
  icon: string;
  status: "pending" | "running" | "complete" | "skipped" | "error";
  elapsed?: number;
  summary: string;
  detail?: Record<string, unknown>;  // 展開後顯示
  expanded: boolean;
}
```

---

## 2. Alarm Center UX 降噪

### 2.1 現狀問題（Gemini 回饋）

1. **紅色過載** — 觸發原因、條件達成卡片全紅背景 + 紅色文字 → alarm fatigue
2. **雙層滾動條** — Master list 和 Detail 各自有滾動，外層也能滾 → 頁面跳動
3. **14 吋筆電空間不足** — AI 側邊欄佔 360px 固定

### 2.2 修改項目

#### A. 視覺降噪（優先）

**觸發原因 / 條件達成卡片：**
- 移除大面積紅色背景
- 改為白底 + 左邊線 `border-left: 4px solid #e53e3e`
- 文字改回標準深灰 `#2d3748`
- severity badge 保留紅色但縮小

```css
/* Before */
background: #fff5f5;
border: 1px solid #feb2b2;
color: #c53030;

/* After */
background: #fff;
border: 1px solid #e2e8f0;
border-left: 4px solid #e53e3e;
color: #2d3748;
```

**AI Synthesis 卡片：**
- 移除藍色漸層背景
- 改為白底 + 左邊線 `border-left: 4px solid #4299e1`

**DR Accordion：**
- ALERT 卡片：白底 + 左邊線紅色
- PASS 卡片：白底 + 左邊線綠色
- 移除全底色（目前 ALERT 是紅底）

#### B. 雙層滾動條修復

```tsx
// 外層
<div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>

// Master (左側告警清單)
<div style={{ width: "35%", height: "100%", overflowY: "auto" }}>

// Detail (右側診斷報告)
<div style={{ width: "65%", height: "100%", overflowY: "auto" }}>
```

確保只有 Master 和 Detail 各自滾動，外層 `overflow: hidden`。

#### C. AI 側邊欄改 Drawer（可選，較大改動）

**方案 A：側邊欄改為 Overlay Drawer**
- 預設隱藏，右下角浮動按鈕
- 點擊從右側滑出（`position: fixed, right: 0, width: 360px`）
- 半透明遮罩，點遮罩關閉

**方案 B：側邊欄可收合（較簡單）**
- 類似 AppShell sidebar 的收合功能
- 收合時只顯示 icon（48px 寬）
- Alarm 頁面預設收合 AI 側邊欄

**建議先做方案 B**（跟現有 sidebar 設計一致）。

### 2.3 影響的檔案

| 檔案 | 改動 |
|------|------|
| `aiops-app/src/app/alarms/page.tsx` | 視覺降噪 + 滾動條修復 |
| `aiops-app/src/components/operations/AlarmCenter.tsx` | DR accordion 顏色 |
| `aiops-app/src/components/operations/SkillOutputRenderer.tsx` | condition banner 顏色 |
| `aiops-app/src/components/shell/AppShell.tsx` | AI 側邊欄 Drawer/收合 |

---

## 3. TC06/07 Summary 修復

### 3.1 現狀
`get_process_summary` 回傳的不是 events（沒有 `{events: [...]}`），所以 data_flattener 回傳 `flat=0`。LLM 看到 0 events 就反問。

### 3.2 修法
在 `pipeline_executor.py` Stage 4，如果 MCP 不是 `get_process_info`（沒有 events），跳過 flatten，直接把 raw response 當作 `llm_summary`：

```python
if mcp_name in ("get_process_summary", "list_tools", "get_simulation_status"):
    # 非 events 型 MCP → 不做 flatten，直接給 LLM 看 raw JSON
    llm_summary = json.dumps(raw_result, ensure_ascii=False)[:6000]
    flat_data = None
    flat_metadata = {"total_events": 0, "available_datasets": []}
    # Skip Stage 4-6
```

這樣 LLM 拿到完整的 summary JSON（含 by_tool, by_step breakdown），可以直接回答，不會反問。

### 3.3 影響
- `pipeline_executor.py` — Stage 4 加判斷
- TC06（機台清單）、TC07（OOC 率）應該不再反問

---

## 4. Execution Plan

| Phase | 內容 | 預估 |
|-------|------|------|
| **Phase 1** | TC06/07 summary 修復 | 30 min |
| **Phase 2** | Alarm Center 視覺降噪 + 滾動條 | 2 hr |
| **Phase 3** | Console pipeline cards UI | 3 hr |
| **Phase 4** | AI 側邊欄收合（Alarm 頁面預設收合） | 1 hr |
| **Phase 5** | 驗證 20 test cases + Alarm 頁面 | 1 hr |

**Total: ~8 小時**

---

## 5. 不做的（排到下一輪）

| 項目 | 原因 |
|------|------|
| Resizable Panel（拖拽調整寬度）| 需要新 library，scope 大 |
| Playwright 截圖 | CI/CD 整合，非 UX 優先 |
| rem/clamp 流體化 | 全站重構，scope 太大 |
| Console code syntax highlight | 美化但非必要 |

---

*此 Spec 由 Gemini 提出 UX 需求，Gill 確認優先順序，Claude 進行技術設計。*
*待確認後開始實施。*
