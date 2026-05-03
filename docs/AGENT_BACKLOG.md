# Agent Backlog

待辦的 agent 能力擴充方向。每項保留 spec / 範圍 / 預期工時 / 推薦順序。

最後更新：2026-05-03

---

## 目前 agent 已有的能力（基線）

- **Chat orchestrator (LangGraph)** — `/internal/agent/chat`
  - 7-bucket builder classifier（BUILD_NEW / BUILD_MODIFY / EXPLAIN / COMPARE / RECOMMEND / KNOWLEDGE / AMBIGUOUS）
  - 5-bucket chat classifier（clear_chart / clear_rca / clear_status / knowledge / vague）
  - intent_completeness gate
  - load_context（system prompt + skills + experience memory pgvector RAG）
  - llm_call ⇄ tool_execute 迴圈 + loop guard
  - synthesis → self_critique → memory_lifecycle
- **Glass Box (build orchestrator)** — `/internal/agent/build`
  - 27 BUILTIN_EXECUTORS + 18 chart blocks 在 sidecar in-process 跑
  - SPEC_glassbox_continuation paused-session 機制
  - Block Advisor graph（EXPLAIN / COMPARE / RECOMMEND / AMBIGUOUS）
- **客戶端**
  - AIAgentPanel（chat panel，認 advisor_answer / pb_pipeline / chart_intents 等 SSE event）
  - AgentBuilderPanel（builder canvas，Glass Box ops 即時繪 LiveCanvasOverlay）
  - 跨 surface ⌘K 命令面板 + tour onboarding

---

## 待辦項目（按推薦順序）

### ✅ E. Agent Eval Harness — 完成 + 上線（2026-05-03）

30 case / 6 suite，prod sidecar live run，baseline **26/30 pass (86.7%)**。
詳見 [tests/agent_eval/README.md](../tests/agent_eval/README.md)。

**4 個 baseline 失敗（real findings，待修）**：

1. **`builder_intent_7bucket :: recommend_001`** — 「我有 SPC data 想看異常點」 advisor 推薦回 `block_chart, block_process_history, block_spc_long_form`，**不是** SPC family（xbar_r/imr/ewma_cusum）。
   - **Cause**：legacy mega-block `block_chart` description 太廣，substring 分數仍勝過 dedicated SPC family（之前討論過）
   - **Fix**：`advisor.graph._score_block_for_keywords` 加 `status='deprecated'` 降權，~20 LOC

2. **`builder_intent_7bucket :: knowledge_001`** + `knowledge_no_tools` 的 2 case — concept 題（WECO 是什麼? Cpk 跟 Ppk 差在哪?）在 `/internal/agent/build` 被 advisor classifier 誤分為 EXPLAIN/COMPARE
   - **Cause**：advisor 的 5-bucket classifier (BUILD/EXPLAIN/COMPARE/RECOMMEND/AMBIGUOUS) **沒有 KNOWLEDGE 桶**；chat orchestrator 的 5-bucket 有。**兩個 classifier 不一致**。
   - **Fix**：`agent_builder.advisor.classifier` 加 KNOWLEDGE 桶 + advisor graph 路由 KNOWLEDGE → 直接 markdown 答（不查 Java blocks），~50 LOC

兩 fix 都 < 1 hr，下次 session 處理 → baseline 應升 100%。

---

### 🟡 B. Multi-session Investigation Continuity ★★☆

**痛點**：每次 chat 是冷啟動。PE 早上看 alarm，下午想 follow up 要重講脈絡。

**範圍**：
- DB：`agent_sessions` 加 `case_status` (open/resolved) + `parent_alarm_id` + `resolution_notes`
- Frontend：「我的 Cases」list view（左側 nav 加 entry），點開 reload 全部 chat history + 上下文
- 跟 chart catalog 整合：case 可掛 referenced chart_type / pipeline_id，user reopen 自動拉出來

**預期工時**：半週（DB schema + list UI + reload logic）

**做的時機**：E 上線後

---

### 🟢 A. Skill Marketplace（PE 自助 + thumbs feedback） ★★☆

**痛點**：agent 找得到 skill，但 PE/operator 看不到 skill registry 全貌；新 skill 是 Glass Box 建出來但沒人知道哪些常用。

**範圍**：
- `/knowledge/skills` 頁：列所有 published skill + 觸發條件 + 過去 30 天命中次數 + thumbs up/down
- DB：新 `skill_invocations` 統計表 + `skill_feedback` 表
- API：`/api/v1/skills/feedback` POST
- 反哺：feedback 數據加進 advisor RECOMMEND 排序（取代 naïve substring score）

**預期工時**：1-1.5 週

**做的時機**：下季 / 看 PE 反饋

---

### 🔵 C. Predictive Triggers（WECO Warning Preempt） ★★★ 戰略性

**痛點**：所有 trigger 都是「OOC 已發生 → 救火」。SPC 早期警訊（WECO R5/R7 = warning before OOC）沒有專屬 pipeline。

**範圍**：
- Event Poller 加 WECO warning event type（R5/R7 fired）
- DR pipeline 範本：early warning → 主動跑 root cause + 通知 PE
- 跟 18 chart blocks 的 SPC family（XbarR/IMR/EwmaCusum）整合 — 它們已有 WECO 計算

**預期工時**：1-2 週

**做的時機**：戰略性（這是「SPC 監控平台 → 真正的 AIOps 預警平台」的關鍵跨越）

---

### 🟣 D. External Integration（Slack / JIRA / Runbook） ★☆☆

**痛點**：agent 結論留在 chat panel，operator 下班沒看到；JIRA ticket 還是手動建。

**範圍**：
- MCP-style adapter for Slack / Teams / JIRA
- Agent 可 `notify_on_call(alarm_id, channel)` / `create_jira_ticket(summary, severity)`
- 也是 dogfood MCP 系統的好機會

**預期工時**：1-2 週（要看 IT 環境接得了哪些）

**做的時機**：要先確認商業 buy-in（Slack / Teams 客戶有沒有要求）

---

### ⚫ F. Adopt Claude Agent SDK ★☆☆

**範圍**：把自製 LangGraph + Glass Box loop 換成 Anthropic 官方 framework。

**為什麼不要先做**：
- 7-bucket classifier + advisor graph 剛上線、行為剛穩定
- 拆掉重做 = 沒帶來新功能、只是換實作
- **要先有 E（eval harness）才有 regression baseline 敢動**

**預期工時**：3-4 週（chat + builder 兩條都要重寫）

**做的時機**：E 落地後 + 確定要長期投資 AI 平台才考慮

---

## 已完成 — 不重複造（2026-04-25 ~ 05-03）

- ✅ 7-bucket builder classifier + advisor graph
- ✅ Block advisor (EXPLAIN/COMPARE/RECOMMEND/AMBIGUOUS) + Java search endpoint
- ✅ Chart catalog (/help/charts) + per-user theme preference
- ✅ Tour + cross-surface ⌘K palette
- ✅ block_chart 退役 + facet 功能升到 dedicated blocks
- ✅ 18 dedicated chart blocks SVG engine
- ✅ Pipeline Builder Stage 1-6 + Phase 8-A migration
- ✅ Java cutover v2（FASTAPI_BASE → :8002，shared-secret，bounded queries）
- ✅ Phase 8-A-1d :8001 fastapi-backend decommissioned
- ✅ OIDC + role hierarchy + role audit
