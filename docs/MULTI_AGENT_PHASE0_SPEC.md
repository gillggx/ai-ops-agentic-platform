# Multi-Agent Phase 0 — Build-Plane 角色化重構 Tech Spec

> Draft · 2026-07-02。承接 `AGENT_HARNESS_DESIGN.html` / `MULTI_AGENT_ARCHITECTURE.html`。
> 決策前提:D1 = 結構重構先;D2 = 監控平面納入本 effort（Phase 1）。

---

## 1. Context & Objective

**現況**:builder 是單一 LangGraph、單一 LLM（GLM-5.2）、單一 prompt 語境。
`goal_plan` / `agentic_phase_loop` / `phase_verifier` / `phase_revise` 雖已是 graph
node，但共用同一份巨型 prompt、同一個 context、同一個模型 —— 改一條 planning 規則
可能誤傷 execution 行為。

**目標（Phase 0）**:把 build 平面拆成 **Planner / Builder / Repair** 三個
role agent，各自有獨立的 prompt / model / tools / context view，達到:
- 關注點分離、每個 agent prompt 小而單一職責
- 每個 agent 可獨立單測（state-in → patch-out）
- 改一個關注點只動一個 agent，ownership 清楚
- 把後續 memory / feedback / Supervisor 要插的「縫」先鋪好

**非目標（Phase 0 明確不做）**:
- 不加 memory / feedback channel / Supervisor（Phase 2+）
- 不動監控平面（Phase 1）
- **不改任何行為** —— 這是純重構

---

## 2. Architecture & Design

### Agent 契約（maintainability 骨幹）
```
Agent = (
  system_prompt,          # 只屬於這個角色，單一職責
  model_cfg,              # 哪個模型 / reasoning effort（未來 tier-router 改這裡）
  allowed_tools,          # 工具白名單
  state_view(state)->view,# 這 agent 讀 state 的哪一塊（compact view）
  run(view)->patch,       # 回寫 state 的哪一塊
)
```
- **graph 仍是 supervisor**（deterministic 路由）;agent 只在 node 內做窄推理。
- agent 之間**只透過共用 state（canvas + phases + exec_trace）溝通**（現況已然），
  不做 agent-to-agent 自由對話、不引入 supervisor-LLM。

### 三 agent 對應現有 node（沿用邊界，爆炸半徑最小）
| Agent | 對應現 node | 職責 |
|---|---|---|
| **PlannerAgent** | `goal_plan` | 意圖 → phases |
| **BuilderAgent** | `agentic_phase_loop` | 每 phase 選 block / 接線 / 設參 |
| **RepairAgent** | `phase_revise` | 卡住自省 + 替代策略 |
| （不動）Verifier | `phase_verifier` | **維持 deterministic node，不 agent 化** |

### Registry module（maintainability 兌現點）
三個 agent 的 `system_prompt / model_cfg / allowed_tools` 集中到**一個 registry
模組**（single source）。改一個 agent 的 prompt / 模型 / 工具 = 只改這一處。

---

## 3. Step-by-Step Execution Plan

每步 = 一個小 PR，**SLASH-17 當回歸閘**，可獨立 review / rollback。

1. **加 `Agent` base + registry skeleton** —— 只有抽象與空殼，不接線、不改行為。
2. **`goal_plan` → 委派 `PlannerAgent`** —— node 改成呼叫 agent;跑 SLASH-17 = baseline。
3. **`agentic_phase_loop` → `BuilderAgent`** —— SLASH-17 回歸。
4. **`phase_revise` → `RepairAgent`** —— SLASH-17 回歸。
5. **集中 config 到 registry** —— 把散落的 prompt / model / tool 常數收攏。
6. **全套 SLASH-17 回歸驗收** —— strict 品質、成本、cache 命中率三項齊看。

---

## 4. Edge Cases & Risks

- **Prompt-cache prefix 變動**:拆 prompt 會改變 cache 斷點 → 每步驗 `cache_read`
  仍維持 **40–58%**，否則成本回歸（這是我們剛量過、最在意的成本槓桿）。
- **Token 爆量**:agent 交接必須重用既有 compact state view（canvas_diff 等），
  不可重新展開整份 context。
- **不可退回 supervisor-LLM**、**Verifier 不 agent 化** —— 守住 flow-in-graph。
- **v27 legacy path** 維持現狀（fallback），不一併遷移，降風險。
- **驗收 = 零回歸**:SLASH-17 品質 / 成本 / cache 任一退步就不 merge。

---

## Roadmap（Phase 0 之後）

| Phase | 內容 | 依賴 |
|---|---|---|
| **0** | build 平面 3-agent 重構（本 Spec） | — |
| **1** | **監控平面納入**:4 個 monitor agent 當 requester 接進 Planner | Phase 0 |
| 2 | Episode / feedback channel + self-vs-user divergence（C#1+#2） | — |
| 3 | agent_knowledge 加 `class` 欄 + `block_doc_memos` 表 | 2 |
| 4 | Planner fast-path 寫入 / Builder 文件備忘 / Repair correction | 3 |
| 5 | Supervisor 週期蒸餾 + curation（含 prune） | 4 |

### Phase 1 待決子問題（不阻擋 Phase 0）
監控觸發時,monitor agent 要:
- **(a) 跑既有 canned patrol**（skills_v2,低工、快落地）,還是
- **(b) 命令 Planner 動態建診斷 pipeline**（全願景、agentic,工較大）?

這個 fork 等 Phase 0 完成、進 Phase 1 時再拍板。

---

**簽收**:這份 Phase 0 Spec 是否符合預期?確認無誤請回覆「**開始開發**」,我就
從 Step 1（`Agent` base + registry skeleton）開始,每步跑 SLASH-17 驗零回歸。
