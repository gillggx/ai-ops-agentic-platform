# Pipeline Builder — 全 Prompt Inventory + Necessity Audit

**Date:** 2026-05-18
**Purpose:** 盤點 Chat → Builder Pipeline flow 沿路所有 LLM prompt，逐個檢視是否必要、可否合併、是否該刪。

---

## 1. 全 Flow Overview

```
USER MSG (browser → /api/agent/chat → /internal/agent/chat)
  │
  ▼
┌─────────────────────────────────────────┐
│ Chat Orchestrator (agent_orchestrator_v2)│
│  ├─ #C1 intent_classifier               │ Haiku, 1 per turn
│  ├─ #C2 intent_classifier_builder       │ Haiku, builder mode only
│  ├─ #C3 intent_completeness             │ Haiku/Sonnet, gate
│  ├─ #C4 llm_call (main agent)           │ Sonnet/Opus, MAIN COST
│  ├─ #C5 dimensional_clarifier (enrich)  │ Haiku, only on confirm card
│  ├─ #C6 self_critique                   │ Haiku, post-synthesis
│  ├─ #C7 summarize_history               │ Haiku, sliding window
│  └─ #C8 memory_abstraction              │ Haiku, post-turn background
└─────────────────────────────────────────┘
  │ (when LLM picks build_pipeline_live tool)
  ▼
┌─────────────────────────────────────────┐
│ Pipeline Builder Graph (graph_build)     │
│  Path A: v30 (CURRENT, default)          │
│   ├─ #B1 goal_plan                       │ Once/build (or per replan)
│   ├─ #B2 agentic_phase_loop              │ Per ReAct round (8 × N phases)
│   ├─ #B3 phase_verifier (inline judge)   │ Once per phase advance
│   └─ #B4 phase_revise                    │ On stuck (≤1 per phase)
│                                           │
│  Path B: v27 (LEGACY, dead on default)   │
│   ├─ #B5 plan (1-shot legacy)            │ dead
│   ├─ #B6 macro_plan                      │ dead
│   ├─ #B7 compile_chunk                   │ dead (called per macro step)
│   ├─ #B8 repair_plan                     │ dead
│   ├─ #B9 reflect_plan                    │ dead (reuses #B5 prompt!)
│   ├─ #B10 repair_op                      │ dead
│   └─ #B11 reflect_op                     │ dead
│                                           │
│  Shared:                                  │
│   └─ #B12 clarify_intent                 │ Both paths (G1 gate)
└─────────────────────────────────────────┘
  │ (Builder mode entry separately: /agent/build)
  ▼
┌─────────────────────────────────────────┐
│ Block Advisor (advisor/*)                │
│  ├─ #A1 classifier (6-bucket)            │ Per builder Q
│  ├─ #A2 extract_one (EXPLAIN)            │ When no block name in msg
│  ├─ #A3 extract_many (COMPARE)           │ When <2 blocks named
│  ├─ #A4 extract_usecase (RECOMMEND)      │ Always for recommend
│  ├─ #A5 synthesize EXPLAIN               │ Render block doc
│  ├─ #A6 synthesize COMPARE               │ A vs B table
│  ├─ #A7 synthesize RECOMMEND             │ Rank candidates
│  └─ #A8 synthesize KNOWLEDGE             │ Pure SPC/Cpk Q&A
└─────────────────────────────────────────┘

Briefing route (separate, not pipeline-builder):
  ├─ #X1 _SYSTEM_PROMPT + 5 user templates (fab/tool/alarm/fleet)
```

---

## 2. Chat Orchestrator (C1-C8)

| # | Name | File | Size | Trigger | Output | Model | Verdict |
|---|---|---|---|---|---|---|---|
| **C1** | `_CLASSIFIER_SYSTEM` | nodes/intent_classifier.py:41 | 2,300 | Every chat turn | JSON 5-bucket | haiku/300tok | **必要** — 路由不可缺 |
| **C2** | `_SYSTEM` (builder classifier) | nodes/intent_classifier_builder.py:54 | 3,400 | Builder mode turn | JSON 7-bucket | haiku/200tok | **必要** — Glass Box vs Advisor 分流 |
| **C3** | `_COMPLETENESS_SYSTEM` | nodes/intent_completeness.py:54 | 4,500 | clear_* intents | JSON `{complete, guess}` | haiku/600tok | **必要** — design_intent_confirm 卡片源 |
| **C4** | main llm_call | nodes/llm_call.py:213 | 25k+ (含 Soul + catalog + RAG) | 每 loop iter | tool_calls | sonnet/opus 8192tok | **核心** — agent 本體 |
| **C5** | `_ENRICH_SYSTEM` | dimensional_clarifier.py:253 | 1,200 | confirm card emit | JSON labels | haiku/800tok | **可砍** — pure 中文 localization；fallback dict 已存在 |
| **C6** | self-critique | nodes/self_critique.py:121 | 600 | post-synthesis (gated) | JSON `{pass, amended}` | haiku/800tok 12s | **可砍** — 已有 deterministic ID-check 一道，這是 second pass，命中率未驗証 |
| **C7** | `_summarize_history` | orchestrator.py:336 | 110 | history > 6 OR 50k tok | text | haiku/200tok | **有 bug 沒生效** — `self._llm` 不存在，每次 throw（被吃掉）|
| **C8** | `_ABSTRACTION_SYSTEM_PROMPT` | memory_abstraction.py:32 | 1,400 | post-turn 背景 | JSON `{intent, action}` | haiku/400tok | **保留** — Experience Memory 寫入用 |

**Chat-side discussion 點**：
- C5 + C6 兩個 LLM call 是「裝飾性」（localization + 二級 audit）— 拿掉每 chat 省 ~1.5 LLM call
- C7 latent bug 確認，從未 fire 過 — 確認後可整段移除
- C3 跟 C2 + C1 加起來 = 每 chat 至少 **3 個 Haiku call before main agent**。可考慮合併（單一 classifier 直接 emit completeness 評估）

---

## 3. Pipeline Builder Graph (B1-B12)

### Live (v30) — 4 個

| # | Name | File | Size | Trigger | Output | Verdict |
|---|---|---|---|---|---|---|
| **B1** | `goal_plan._SYSTEM` | goal_plan.py:189 | **7,893** (今天 session 加得最肥) | Once per build / replan | JSON phases[] | **要瘦身**：今天 L1 spec 已寫，拿掉 case lists |
| **B2** | `agentic_phase_loop._SYSTEM` | agentic_phase_loop.py:45 | 2,429 (system) + 20-50k (user msg) | Each ReAct round (~ 8 × N phases) | tool_use | **必要核心** — 但 user_msg 太肥，已加 VERIFIER FEEDBACK + CONNECT OPTIONS 等 sections |
| **B3** | `phase_verifier` inline judge | phase_verifier.py:664 | 1,520 | Per phase advance (skip chart/verdict/alarm) | JSON `{match, reason}` | **可重做或拆**：L5 spec — per-kind judge functions 而非 1 個 generic |
| **B4** | `phase_revise._SYSTEM` | phase_revise.py:34 | 540 | Phase stuck (≤1 per phase) | JSON `{alternative}` | **必要** — 但與 B2 的 VERIFIER FEEDBACK 機制有重疊；可能可合併到 B2 prompt sections |

### Shared

| # | Name | File | Size | Trigger | Output | Verdict |
|---|---|---|---|---|---|---|
| **B12** | `clarify_intent._SYSTEM` | clarify_intent.py:37 | 2,819 | Once per build (gate) | JSON bullets[] | **架構問題**：跟 C3 intent_completeness 角色重疊；同樣是 user intent 確認 |

### Dead (v27, 沒人走) — 7 個

| # | Name | File | Size | Verdict |
|---|---|---|---|---|
| **B5** | `plan._SYSTEM` | plan.py:20 | 6,346 + catalog inject (10-60k) | **可刪** — v30 不走 |
| **B6** | `macro_plan._SYSTEM` | macro_plan.py:74 | 9,953 | **可刪** |
| **B7** | `compile_chunk._SYSTEM` | compile_chunk.py:91 | 2,386 | **可刪** |
| **B8** | `repair_plan._SYSTEM` | repair_plan.py:22 | 632 | **可刪** |
| **B9** | `reflect_plan` (reuses B5) | reflect_plan.py:36 | 2,415 + B5 | **可刪** — 是最大 effective prompt（含 catalog ~30k）|
| **B10** | `repair_op._SYSTEM` | repair_op.py:33 | 557 | **可刪** |
| **B11** | `reflect_op._SYSTEM` | reflect_op.py:50 | 967 | **可刪** |

**Builder-side discussion 點**：
- v27 路徑（B5-B11）7 個 prompt 是 dead code，總 prompt 字數 ~22k，graph_build 模組可大幅瘦身（這是 `project_v6_to_remove_list.md` 待辦的一部分）
- B3 inline judge 是**今天一整晚痛點集中地** — chart/verdict/alarm 各種 skip 都是它的旁路
- B12 clarify_intent 跟 C3 intent_completeness 是兩個獨立 intent gate；該不該保留兩道？

---

## 4. Block Advisor (A1-A8)

| # | Name | File | Size | Trigger | Output | Verdict |
|---|---|---|---|---|---|---|
| **A1** | `_SYSTEM` (advisor classifier) | classifier.py:29 | 2,650 | Per builder Q (regex bypass first) | JSON 6-bucket | **跟 C1/C2 高度重複** — 也是 intent classifier，bucket 不同。Mergeable |
| **A2** | `_EXTRACT_ONE_SYSTEM` | extract.py:44 | 450 | EXPLAIN, no block name | JSON `{block_name}` | **3 個 extract 可合 1** |
| **A3** | `_EXTRACT_MANY_SYSTEM` | extract.py:93 | 290 | COMPARE, <2 blocks | JSON `{block_names}` | 同上 |
| **A4** | `_EXTRACT_USECASE_SYSTEM` | extract.py:137 | 380 | RECOMMEND | JSON `{keywords}` | 同上 |
| **A5** | `_EXPLAIN_SYSTEM` | synthesize.py:51 | 780 | EXPLAIN render | markdown | **必要** |
| **A6** | `_COMPARE_SYSTEM` | synthesize.py:168 | 410 | COMPARE render | markdown | **必要** |
| **A7** | `_RECOMMEND_SYSTEM` | synthesize.py:215 | 600 | RECOMMEND render | markdown | **必要** |
| **A8** | `_KNOWLEDGE_SYSTEM` | synthesize.py:273 | 770 | KNOWLEDGE (no DB) | markdown | **必要** |

**Advisor-side discussion 點**：
- A2+A3+A4 三個 extractor 結構幾乎一樣，可合成 `extract(mode=one|many|usecase)`
- A5-A8 共用 preamble + rules，可抽公共 prefix
- **更高層問題**：A1 classifier 跟 C1/C2 是平行設計，重複；考慮一個 unified IntentClassifier helper

---

## 5. Briefing (X1) — 不在 pipeline builder flow 但同 LLM 池

| # | Name | File | Size | Purpose |
|---|---|---|---|---|
| X1 | `_SYSTEM_PROMPT` + 5 user templates | routers/briefing.py:125 + 33/64/81/93/105 | 160 system + ~250-640 user | Fab/tool/alarm/fleet 摘要 — 已 well-factored，沒 merge 空間 |

---

## 6. 必要性 — 我的初步看法

### 「絕對必要」(20 個 prompt 中的 ~8 個)
- C1 / C2 / C4 / C8 (chat orchestrator 核心)
- B1 / B2 (v30 builder 核心)
- A5-A8 (Advisor render — 各 bucket 都需要)

### 「可砍 / dead code」(7-9 個)
- **B5-B11**（v27 dead path 7 個）
- **C5**（dimensional_clarifier enrich — pure localization，fallback dict 已存在）
- **C6**（self_critique LLM 二級 audit — deterministic 一級已有）
- **C7**（summarize_history 有 bug 沒生效）

### 「結構性合併機會」
- **C1 + C2 + A1**：3 個 intent classifier 設計平行 — 一個 unified classifier 帶 mode 參數
- **C3 + B12**：兩個 intent gate（completeness + clarify）角色重疊
- **A2 + A3 + A4**：3 個 extractor 合 1
- **A5-A8**：4 個 synthesize prompt 共用前綴
- **B3 + B4**：phase_verifier judge + phase_revise 共用「卡了 → 怎辦」邏輯，可整合

### 「待重設計」(架構級)
- **B1 + B3**：plan 跟 verifier 之間 value_desc/expected 用法重疊。L3 spec — 拆 value_desc 為 user_desc + verifier_intent，或拿掉。
- **B3**：generic LLM-judge → per-kind judge functions (L5)
- **B1**：plan 自身 case rule 已多 — L1 spec 已寫 (今天的待辦)

---

## 7. 數字總結

| | 數量 | 累計字數 |
|---|---|---|
| 全部 prompts (Chat+Builder+Advisor+Briefing) | **25** | ~75,000 chars (含 catalog 插入更大)|
| Dead code (v27 builder) | **7** | ~22,000 chars |
| 純裝飾 / 可砍 | **2-3** | ~2,000 chars |
| 可合併重複 | **9** (3 classifier + 3 extractor + 4 synthesize 共抽公共) | ~3,000 chars 可省 |
| 真正核心 | **8** | ~40,000 chars |

**砍 dead + 砍裝飾 + 合併重複 → 25 → ~13 prompt，~75k → ~45k chars**。Maintenance burden 砍掉 ~40%。

---

## 8. 給 user 的 review questions

1. **C5/C6 兩個裝飾性 LLM call 是否該砍？**（localization + audit；省 1.5 chat call/turn）
2. **v27 dead path (B5-B11) 何時清？** 不影響 runtime 但 graph_build/ 模組會輕很多
3. **3 個 classifier (C1+C2+A1) 要不要合**？工程整潔但會動到多處
4. **C3 vs B12 兩道 intent gate 是必要還是冗餘？**
5. **B3 LLM-judge** 是今天痛點的 root — 要先做 L5（拆 per-kind judge）還是 L3（拆 value_desc）？

待你 review 後決定哪個方向先動。
