# Phase 9 — Agent-Authored Rules

**Codename**: 對話即規則 (Rule-as-Spec)
**Status**: design draft — 2026-05-08
**Predecessor**: Phase 8-A-1d (chat + build native in sidecar, 2026-04-25)
**Author**: gill + Claude (Opus 4.7)

---

## TL;DR

> **The agent specs rules at design-time. Deterministic code runs them at runtime.**

The chat agent stops being a per-request inference loop and starts being a
**rule author**. Output of a chat session is no longer just an answer; it is
optionally a **Rule Artifact** — a stored (pipeline + schedule + channel +
owner) tuple — that the existing pipeline executor + Java cron run on its
own thereafter, with **zero LLM in the runtime hot path**.

This is the same architectural principle as `feedback_flow_in_graph_not_prompt`
(graph nodes, not LLM, decide flow) extended one floor up: **rules, not LLM,
decide runtime behaviour**. LLM is constrained to the spec-creation moment.

## Why now

Chat answers today are ephemeral — the user gets the analysis, but the
analysis doesn't *persist as something runnable*. Each "tomorrow morning
let me see this again" or "every Monday top-5 OOC" becomes a manual
re-prompt or a builder-mode session. Three concrete scenarios from the
2026-05-08 design discussion all hit the same wall, and they all share the
same fix.

### Cost / reliability also push this way

- LLM cost: a daily 7:30 briefing × 7 days × 10 PEs × Sonnet pricing dwarfs
  the equivalent code-run cost by ~100×. Specifying once is ~free per fire.
- Determinism: cron-fired pipelines have repeatable output; LLM-fired
  briefings drift between runs and are hard to debug.
- Auditability: a Rule Artifact in DB can be diffed, exported, shared — a
  prompt session cannot.

## Architectural principle

```
                Design-time (LLM-in-loop, rare, expensive)
        ┌─────────────────────────────────────────────────┐
        │  user (NL)                                       │
        │     ↓                                            │
        │  chat agent                                      │
        │     ↓ (proposes)                                 │
        │  Rule Artifact = {                               │
        │    trigger:  cron | event | manual,              │
        │    pipeline: PipelineJSON,                       │
        │    channel:  in-app | email | push | slack,      │
        │    owner:    user_id,                            │
        │    kind:     personal_briefing | weekly_report   │
        │              | saved_query | watch_rule          │
        │  }                                               │
        │     ↓ (user confirms)                            │
        │  DB write                                        │
        └─────────────────────────────────────────────────┘
                              ↓
                Runtime (zero LLM, deterministic, cheap)
        ┌─────────────────────────────────────────────────┐
        │  Java AutoPatrolScheduler                        │
        │     ↓ (cron tick OR event match)                 │
        │  sidecar PipelineExecutor                        │
        │     ↓ (block DAG runs against MCPs)              │
        │  result rows / chart spec / alert payload        │
        │     ↓                                            │
        │  NotificationDispatch service                    │
        │     ↓                                            │
        │  user's chosen channel                           │
        └─────────────────────────────────────────────────┘
```

**Hard rule**: anything in the **Runtime** box must run without calling
Anthropic. If a rule needs LLM judgement at runtime (e.g. "summarize this
week"), the LLM call belongs *inside the pipeline* as an explicit `block_llm`
step — visible in the artifact, costed at spec-time, and replaceable.

## Rule Artifact — data model

Extends the existing `auto_patrol` table rather than introducing a new
top-level concept (auto_patrol already covers pipeline + cron + scope; we
only add personal-ownership + notification fields).

| field | type | source |
|---|---|---|
| `id` | bigint | existing |
| `name` | string | existing |
| `pipeline_id` | fk | existing |
| `schedule` | cron string | existing |
| `target_scope` | jsonb (all_equipment / specific / per_user) | existing — extend with `per_user` kind |
| `kind` | enum | existing — add `personal_briefing` / `weekly_report` / `saved_query` / `watch_rule` |
| `owner_user_id` | fk users.id | **NEW** — null for shared patrols, set for personal |
| `notification_channels` | jsonb (`[{type:"in_app"|"email"|"push", config:…}]`) | **NEW** |
| `notification_template` | string | **NEW** — message format ("EQP-{tool} OOC × {n} this week") |
| `last_dispatched_at` | timestamp | **NEW** — dedupe / status display |

### Rule kinds

| kind | trigger | example |
|---|---|---|
| `personal_briefing` | cron | "每天 7:30 過夜重點" (Scenario 1) |
| `weekly_report` | cron | "每週一 8:00 OOC top-5" (Scenario 3 / user's example) |
| `saved_query` | manual | "上次那個 EQP-07 drilling 結果" (Scenario 4) |
| `watch_rule` | event | "EQP-X 連 N 次 OOC 推播給我" (Phase 9-D, later) |
| `auto_patrol` | cron + event | existing alarm-generation patrol — unchanged |

## Three target scenarios (reproduced for context)

| # | persona | trigger | rule kind | channel |
|---|---|---|---|---|
| 1 | PE 早班接班 | cron `30 7 * * *` | `personal_briefing` | in-app banner |
| 3 | PE 主管週報 | cron `0 8 * * 1` | `weekly_report` | push + persisted |
| 4 | PE 探索 drilling | manual | `saved_query` | chat re-invoke |

Scenario 2 (incident RCA + ack alarm) is intentionally **out of scope** for
Phase 9 — it requires write operations + audit + 主動 push, which compounds
risk; revisit in Phase 10.

## Component inventory

| component | exists? | needed for Phase 9 |
|---|---|---|
| `auto_patrol` schema (cron + pipeline + scope) | ✅ | extend — see schema above |
| `AutoPatrolSchedulerService` (Java cron firing) | ✅ | reuse as-is |
| `PipelineExecutor` (sidecar, native blocks) | ✅ | reuse as-is |
| `pb_pipeline_runs` (execution history) | ✅ | reuse |
| User table + auth | ✅ (NextAuth + role hierarchy IT_ADMIN > PE > ON_DUTY) | reuse — `owner_user_id` FK |
| `NotificationDispatch` service | ❌ | **NEW** — start with in-app banner only |
| In-app banner UI | ❌ | **NEW** — top-of-page widget reading `notification_inbox` |
| `propose_personal_rule` agent tool | ❌ | **NEW** — spec generator in sidecar |
| Chat panel "store this as rule" button | ❌ | **NEW** — calls the same tool with the just-finished session as context |
| Rule management UI | ❌ | **NEW** — list / edit / pause / delete personal rules |

## Build order

### Phase 9-A — Schema + dispatch primitive (1 day)

- Migration `V20__personal_rule_fields.sql`: extend `auto_patrol` with
  `owner_user_id`, `notification_channels`, `notification_template`,
  `last_dispatched_at`
- New table `notification_inbox(id, user_id, rule_id, payload, read_at, created_at)`
- New service: `NotificationDispatch` (single method `dispatch(user_id, payload)`,
  v1 only writes to `notification_inbox`)
- Wire the existing `AutoPatrolExecutor` so when it runs a rule with
  `owner_user_id != null`, it dispatches the rendered result to the inbox

### Phase 9-B — Chat agent rule-author tool (2 days)

- New sidecar tool `propose_personal_rule(natural_language_request)` that:
  - asks for missing slots (schedule, channel) via existing
    `intent_completeness` gate pattern
  - composes a PipelineJSON via the same machinery the Glass Box builder
    uses, but headless (no canvas)
  - returns a Rule Artifact draft for user confirmation
  - on confirm, writes to `auto_patrol` + persists pipeline
- End-to-end test: user's example "每週一 8 點 OOC top-5" → fully wired rule
  → fires next Monday → inbox gets a row

### Phase 9-C — UI surfaces (1.5 days)

- In-app banner widget (top-right corner, like GitHub notifications)
- "/rules" page — list, pause, edit, delete personal rules
- Chat panel button: "save this analysis as a rule" — pre-fills the
  9-B tool with current chat context

### Phase 9-D — More channels + watch rules (later, optional for v0.9)

- Email channel (SES or smtp)
- Web push (service worker, PE 主管 mobile)
- `watch_rule` kind — event-triggered (alarm, OOC count threshold)

## Risks & open questions

| risk | mitigation |
|---|---|
| Agent generates a wrong / expensive pipeline | Show the proposed pipeline + preview run before confirm; user explicitly approves |
| Rule fires forever after employee leaves | `owner_user_id` FK + soft-pause when user inactive 30 days |
| Notification storm | `last_dispatched_at` + per-rule rate limit; banner inbox itself is rate-limited (dedupe identical payloads within 1h) |
| LLM hallucinates schedule ("twice a week" → wrong cron) | confirmation dialog shows human-readable schedule + cron string both |
| Cross-tenant leak | `owner_user_id` enforced at SQL level; banner inbox query always WHERE user_id=current |

### Open design questions

1. **Drift handling**: rule fires, blocks change schema in `pb_blocks` → does
   the rule auto-rewrite or fail? (Lean towards: fail loudly + ping owner.)
2. **Sharing**: can user A share a rule with user B? Phase 9 = no (personal
   only). Phase 10 = team-rules.
3. **Backfill**: when user creates a "weekly OOC" rule, do we run it once on
   last week's data so they see what it'll look like? (Yes — implicit in the
   confirm step.)

## Success metric

> By end of Phase 9, the user's example sentence — "每週一早 8 點自動分析上週
> 機台 OOC rate 並主動通知我" — is achievable end-to-end **inside the chat
> panel**, in under 2 minutes of dialogue, with zero builder-mode visit.

## Next step

Pick one scenario for the first Tech Spec. Recommendation: Scenario 3
(weekly report) — it exercises every layer (NL → schedule → pipeline →
channel) without the stateful complexity of `saved_query` or the timing
sensitivity of `personal_briefing`'s shift handoff.
