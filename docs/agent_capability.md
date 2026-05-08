# Chat Mode AI Agent — Capability Map (2026-05-08)

> Living doc. Captures the use cases the chat-mode agent could serve, what
> is already wired up, and what is still gap. Updated as we pick items off
> for design / build. The primary endpoint is `/internal/agent/chat` →
> `agent_orchestrator_v2` (LangGraph) running inside the python sidecar.
>
> **🛠 2026-05-08 update**: items marked **[Phase 9]** below are folded into
> the Agent-Authored Rules design. See
> [PHASE_9_AGENT_AUTHORED_RULES.md](PHASE_9_AGENT_AUTHORED_RULES.md) for the
> architectural thesis ("agent specs rules at design-time, code runs them
> at runtime") and build sequence. Overall AIOps phase status lives in
> [AIOPS_ROADMAP.md](AIOPS_ROADMAP.md).

## Use case map

### A. Read-only intelligence

| ID | Use case | Example | Status |
|----|---|---|---|
| A1 | 直接資料查詢 | 「list 機台」「LOT-0013 在哪」 | ✅ done — runs through `block_list_objects` / `block_mcp_call` |
| A2 | 歷史時段比較 | 「今天 OOC 數 vs 昨天」「上週 vs 本週」 | ❌ gap — needs a time-bisect wrapper that splits the query and diffs |
| A3 | 跨物件 reverse lookup | 「APC-007 上週影響過哪些 lot」 | ⚠️ partial — works via builder but no chat-native shortcut |
| A4 | 異常 RCA / 為什麼 | 「為什麼 EQP-03 一直 alarm」 | ✅ done via tool-use loop; quality dependent on prompt |
| A5 | 自然語言 briefing | 「今天廠區重點」「過夜事件摘要」 | ⚠️ partial — `/briefing/sse` endpoint exists but no chat hook **[Phase 9-A — `personal_briefing` rule kind]** |

### B. Action / write operations (none in production yet)

| ID | Use case | Example | Risk |
|----|---|---|---|
| B1 | Acknowledge alarm / hold | 「ack 掉 EQP-05 hold」 | medium — needs audit log + confirm dialog |
| B2 | Pause / resume patrol | 「patrol 3 停掉」「重新開」 | low–medium |
| B3 | Save chat result as skill | 「把這個分析存成 skill 叫 daily_ooc_check」 | low — high-value chat→artifact path ⭐ **[Phase 9-B/9-C]** |
| B4 | Schedule / subscribe | 「每天 8 點 send overnight OOC 統計」 | low — wraps cron-trigger **[Phase 9-A/9-B]** |
| B5 | Build alarm rule | 「EQP-03 連 3 次 OOC 就告警」 | medium — better routed through builder spec |

### C. Conversational / learning

| ID | Use case | Status |
|----|---|---|
| C1 | 知識問答（OOC 是什麼 / Cpk 怎麼算） | ✅ knowledge bucket added 2026-05-02 |
| C2 | Skill discovery (「有哪些 skill 可以分析 APC drift」) | ❌ gap — needs skill-search tool over `skill_definitions` |
| C3 | 多輪 drilling (「show EQP-03」→「上週呢」→「換 EQP-04」) | ⚠️ partial — context threading is ad-hoc |
| C4 | Skill 組合 (「先跑 X 再丟 Y」) | ❌ gap — would need a runtime DAG composer |
| C5 | Explain my pipeline (「我這個 pipeline 在做什麼」) | ❌ gap |

## User's requested cases (P0 — currently in scope)

1. **Skill 執行（補強）** — already routed through `invoke_published_skill` tool. Open questions:
   - Skill not found → say no / suggest similar / auto-fallback to case 2?
   - Skill has required params → how does the agent ask user to fill (intent_completeness gate already does some of this).
2. **Chat → builder bridge** — currently chat does *not* hand off to builder; user has to switch mode manually. Open questions:
   - UX: jump to builder pre-filled vs run-in-chat-then-publish?
   - Trigger: user says "幫我建" vs agent auto-detects "no skill matches"?

## Recommendation (next session)

Pair P0 with two P1 items that share a spec generator:
- P0 case 2 (chat→builder bridge): chat agent emits a pipeline spec when no skill matches, user clicks → builder pre-filled
- P1 B3 (save chat as skill): chat agent reaches the answer in-chat, then offers "save as skill", same spec generator emits a publishable skill definition

These two are conceptually the same path's two endpoints (mid-task spec vs post-task spec), so building a single `propose_pipeline_or_skill` tool covers both.

## Architecture & boundaries (reminder, do not break)

- Chat orchestrator runs in **sidecar** (`agent_orchestrator_v2`). Never put new flow logic in the system prompt — wire it as graph nodes (see `feedback_flow_in_graph_not_prompt`).
- Read MCP / Skill / Block descriptions from DB at request time. No hardcoded usage notes in prompts.
- Builder mode lives at `/internal/agent/build` (Glass Box loop + Block Advisor graph). The chat→builder bridge is a *handoff*, not a merge — keep them as separate stacks, just make the intent transfer explicit.

## History

- 2026-05-08 — first draft, scoped from chat with user; P0 = user's two; P1 added by agent for review.
- 2026-05-08 (later) — user pivoted the framing from "what can the agent do" to **user-scenario** thinking (4 scenarios: shift handoff / weekly report / drilling / incident RCA). User added the architectural constraint **"agent generates rules, code runs them"** — agent must NOT be in the runtime hot path, only at spec-creation time. This crystallised into [PHASE_9_AGENT_AUTHORED_RULES.md](PHASE_9_AGENT_AUTHORED_RULES.md).
