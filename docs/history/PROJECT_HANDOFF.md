# AIOps Platform — Project Handoff

**Last updated: 2026-05-24** · **Current phase: Java OOP refactor merged (PR #5) · post v30.23**

> 上次大改版是 2026-04-27 的 Phase 8 (Java cutover)。本次 handoff 覆蓋 Phase 8
> 之後的所有重大進展（v9–v19 + v30.x + Skill Catalog + Builder Block Advisor +
> Chart Engine overhaul + Object-native Pipeline + Self-correction loop + Tracer
> + Admin viewer + Build Traces UX + Dead-code purge + Java OOP refactor + JsonUtils
> 共用化 + pgvector write-path fix + 145 unit tests on backend).

---

## 1. Architecture (current)

EC2 single-host, systemd-managed. K8s migration planned but **not yet built** — see `docs/devOps_technique_guide_2.0.md` for K8s spec.

```
┌─────────────────────────────────────────────────────────────┐
│  aiops-app (Next.js 15 standalone)             :8000        │
│  • UI rendering + /api/* proxy routes only                  │
│  • Skill Builder + Chat panel + Admin pages                 │
│  • No business logic — proxies to Java :8002 / sidecar :8050│
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                                 ▼
┌──────────────────────┐         ┌─────────────────────────┐
│  java-backend        │         │  python_ai_sidecar      │
│  (Spring Boot 3.5.14)│         │  (FastAPI + LangGraph)  │
│  :8002 — sole DB     │         │  :8050 — agents + exec  │
│  • Auth (JWT/OIDC)   │         │  • Chat orchestrator v2 │
│  • PostgreSQL + pgvec│         │  • Glass Box builder    │
│  • Pipeline registry │         │  • Block Advisor        │
│  • Skill registry    │         │  • 56 block executors   │
│  • Alarm + role audit│         │  • Pipeline executor    │
│  • SSE stream proxy  │←JavaAPIClient ─→ Java :8002        │
│                      │         │  (sidecar never DB-direct)│
└──────────┬───────────┘         └──────────┬──────────────┘
           │                                │
           ▼                                ▼ (data fetch)
      PostgreSQL                ┌─────────────────────┐
                                │  ontology_simulator │
                                │  :8012              │
                                │  MongoDB + NATS     │
                                └─────────────────────┘
```

## 2. Stack versions (DevOps spec)

| Component | Target | Status on EC2 |
|---|---|---|
| Java | **Temurin 17** | ✓ (migrated from 21 on 2026-05-14) |
| Spring Boot | 3.5.14 | ✓ |
| Maven (NOT Gradle) | latest | ✓ |
| Python | 3.11 | ✓ |
| Node.js | 20.18 | ✓ |
| PostgreSQL | 17 + pgvector | ✓ |

Service ports: `8000` (app) · `8002` (java) · `8050` (sidecar) · `8012` (sim) · `:8001` decommissioned 2026-04-25.

K8s deployment: each container `EXPOSE 8080 → 80`, service-name routing. Not built yet — needs target env (GKE/EKS/self-hosted) decision first.

---

## 3. Phases since Phase 8 (chronological)

### Phase 9 — Self-correction loop (2026-05-13)
`inspect_execution` + `reflect_plan` nodes. After finalize runs dry-run, scan node_results for semantic issues; if issues + budget left, LLM rewrites plan. Status: ✓ shipped.

### Phase 10 — Builder graph v2 + Tracer + Admin viewer (2026-05-13/14)
`BuildTracer` opt-in writes per-build JSON to `/tmp/builder-traces/`. New admin page `/admin/build-traces` renders trace journey + LLM calls + node results + dry-run charts. Clear-all / Clear-24h+ buttons in sidebar. Status: ✓ shipped.

### Phase 11 — Skill terminator + skill_step_mode (2026-04-25)
Pipeline ending with `block_step_check` for SkillRunner pass/fail reads. Status: ✓ shipped.

### Phase 12 — Skill catalog (2026-05-10)
Skill definitions + UX for browsing/creating Skills. See `docs/SKILL_CATALOG_PHASE12.md`.

### Java OOP refactor (2026-05-23/24) — controller/service split + exception cleanup

Followed a DevOps audit flagging that the Java cutover left several god classes
mixing HTTP concerns with business logic. PR #5 (16 commits on `feat/java-oop-refactor`).

**Eight controller→service splits (P0)**:
| Phase | Target | LoC delta |
|---|---|---|
| P0-1 | SkillDocumentController | 826 → 188 (service 738) |
| P0-2 | PipelineController | 658 → 125 (service 543 + Dtos 91) |
| P0-3 | SkillRunnerService → 3 services | 893 → 270 (orchestrator) + 240 (`SkillStepExecutor`) + 460 (`SkillAlarmEmitter`) |
| P0-4 | FleetService → 3 services + façade | 959 → 70 façade + 354 (Roster) + 582 (EquipmentDetail) + 133 (`FleetSimulatorClient`) |
| P0-5 | AgentProxyController + shared utilities | 338 → 226 + new `SseEmitterBridge` + `RequestBodyAccess` (used by AgentProxy + Briefing + SkillDocument) |
| P0-6 | AgentKnowledgeController | 315 → 152 (service 280, 4 resource sections) |
| P0-7 | PipelineBuilderController | 252 → 137 (service 167) |
| P0-8 | InternalAgentKnowledgeController | 235 → 158 (service 167) |

**Bug surfaced + fixed by P0-6 smoke** (commit `e03020d`): pgvector ↔ Hibernate
write-path was rejecting INSERT/UPDATE on `agent_knowledge` + `agent_examples`
(`column embedding is of type vector but expression is of type character varying`).
Latent since the feature shipped — Frontend never created rows via Java, sidecar's
backfill used raw SQL. Fix: `@Column(insertable=false, updatable=false)` on the
embedding field + native `clearEmbedding(id)` for invalidation.

**P1 exception regime**: 52 `catch(Exception)` → 0 across 16 files.
- `JsonProcessingException` for mapper.read/write (~30 sites)
- `DateTimeParseException` for timestamp parse fallback chains (5)
- `NumberFormatException` for `Long.parseLong` / `Double.parseDouble` (1)
- `RuntimeException` for reactor block + JPA + fail-open guards (~17) — keeps the
  fail-open semantic but signals checked exceptions still bubble.

**P2 `JsonUtils` centralisation**: 6 duplicated JSON helpers (`parseJsonObject` /
`parseList` / `safeJson` / `asMap` patterns) across 4 services → 1 utility class
(4 static methods, ObjectMapper passed as first arg). Dropped 3 unused
`TypeReference` static fields after migration.

**P3 test coverage**: 4 new pure-Mockito test files, 145 tests pass (up from 65):
`JsonUtilsTest` (18) + `SkillDocumentServiceTest` (22) + `PipelineServiceTest`
(23) + `PipelineBuilderServiceTest` (11). Also patched 5 stale assertions in
`SkillAlarmEmitterTest` left over from earlier prod fixes (commits 405edd3 + ba26b6d).

**P4 layering docs**: 7 `package-info.java` files (skill / pipeline / fleet /
agentknowledge / agent / internal / common) document the controller↔service↔repo
boundary at each refactored package. Considered + rejected the full
`api → service` package move (high blast radius, no functional benefit — YAGNI).

Verification: every commit deployed to EC2; `mvn compile + test-compile` exit 0;
3 standard pipeline build cases (spc-trend / spc-multi-tool / spc-cusum) still
`finished` with 5-6 nodes in 60-130s — refactor 0-impact on build flow.

### v18 — Reject-and-ask loop + Intent bullets (2026-05-14)
Major build accuracy + UX upgrade. See section 4 below.

### v19 — Chat intent confirmation (2026-05-14)
v18 bullets extended to chat mode. See section 5 below.

### Phase 8-A-2 — Block panels SPC/APC (2026-05-14)
Composite blocks `block_spc_panel` + `block_apc_panel` — give `tool_id + step + chart_name + time_range` and they self-fetch + render. Replaces error-prone 4-block compositions that routinely collapsed to 1-point charts. Multi-machine comparison via `color_by='toolID'`. Green value / orange UCL/LCL defaults.

### v30 — Goal-Oriented ReAct Pipeline Builder (2026-05-16/17)

Replaces v27 `macro_plan + compile_chunk × N` with two-stage:
- `goal_plan_node` emits 5-7 intent-only phases (block-agnostic; `expected` ∈ raw_data/transform/scalar/verdict/chart/table/alarm)
- `agentic_phase_loop` runs a ReAct loop per phase (inspect_doc / add_node / connect / set_param / phase_complete) with `phase_verifier_node` + B2 LLM-judge gating advance

Canonical SPEC: [docs/spec_v30_react_pipeline_builder.md](./spec_v30_react_pipeline_builder.md).

Incremental updates this week:

- **v30.10 (2026-05-16) B2 LLM-judge** — verifier no longer accepts `covers+rows≥1` alone; an LLM judge checks `expected_output.value_desc` semantics with strict quantifier rules (「最後/last/first」→ must be rows==1; 「N 張/筆」→ rows≥N). Catches 假性 advance (e.g. 87 OOC rows passing a "last 1" phase).
- **v30.11 (2026-05-16) block_find + count_rows.covers + filter examples** — new `block_find` (filter + optional sort + take first/last/all/N) collapses the 3-step "find latest matching" pattern; `block_count_rows.covers=[scalar, transform]` so rule-based gate no longer blocks scalar phases; `block_filter` got an `examples[]` array (LLM learns shape from data); `block_sort` description tightened to cross-ref `block_find` for single-column 1-row cases. Flyway V47/V48 (manual psql on EC2 — Flyway disabled in prod).
- **v30.12 (2026-05-17) matched-only CONNECT OPTIONS view** — `agentic_phase_loop._build_canvas_diff_md` + `_build_observation_md` now surface a `== CONNECT OPTIONS for nX ==` section per node with un-connected input ports: lists ONLY type-compatible source ports across the pipeline; emits `[NO COMPATIBLE SOURCE]` + producer-block hints when none. Hypothesis-tested via `tools/trace_replay` (3 reps each at EQP-08 p5 r3): baseline 0/3 → matched-only 3/3 architecturally correct. E2e EQP-08 confirms LLM now picks Logic Node + port names 100% on first try; previous "from_port=verdict / to_port=data" hallucinations eliminated.

Trace tool: [tools/trace_replay/](../tools/trace_replay/) — controlled-variant LLM replay harness, new variants `inject_pipeline_lineage` + `inject_matched_connect_options`.

Open follow-ups (memory):
- `project_alarm_vs_display_decouple.md` — goal_plan should not mix alarm trigger + user presentation in one phase
- `project_rag_for_llm_lookups.md` — RAG tools (`query_blocks` / `query_columns` / `query_connectable_sources`) to replace push-everything catalog over time

### v30.10–v30.23 incremental ships (2026-05-16 → 2026-05-22)

12 increments since the first v30 ship. Most are LLM-prompt / verifier rule fixes
delivered as block-doc patches + Flyway migrations rather than graph rewrites
(per the "flow in graph, not prompt" principle the architectural shape stayed
stable).

- **v30.16+ block-doc patches** (`block_xbar_r` pre-aggregated value_column mode,
  `block_groupby_agg` param alignment with step_check + pandas, `block_ewma_cusum`
  schema accepts `target=null`, `block_spc_panel` 🚨 warns LLM not to pre-filter
  upstream + composite chart blocks). Each was a `V**.sql` migration applied
  manually on EC2 (Flyway disabled in prod).
- **v30.22 agent-driven verify** — LLM can emit `run_verifier` tool to verify a
  multi-block chain mid-phase, lets builder ship `> 2-node` phases without
  hitting the inspect/reflect loop on every step.
- **v30.23 covers gate behind feature flag** (default OFF) — verifier no longer
  auto-rejects on missing `produces.covers` declarations; logged-only until a
  real rule replaces it.
- **Tracer / Admin viewer iteration** — `inspect_block_doc` adds
  `section='summary'|'full'` (default lean) to cut tokens; trace truncation cap
  bumped 300→6000 chars; SSE param coercion fix so `phase_action.tool_args_raw`
  carries the actual values not the JSON-string; tool_use blocks stripped from
  assistant history when no dispatch happened (recovery from invalid LLM output);
  round budget 8 → 16 + doc-reread signal logged; Anthropic prompt cache on
  `agentic_phase_loop` cuts catalog tokens ~90%.
- **Verifier multi-terminal awareness** — when canvas has multiple terminal
  nodes, verifier picks the terminal matching `phase.expected` instead of the
  first one (was silently rejecting valid pipelines).
- **Builder Block Advisor v6.2/v6.3** — tool-using doc Q&A agent (advisor_v2)
  for EXPLAIN / COMPARE / RECOMMEND buckets so admin-edited
  `block_docs.markdown` surfaces in answers. KNOWLEDGE bucket added to
  classifier, deprecated blocks deprioritized. Eval baseline 26/30.

### Agent Knowledge V49/V50 + Slash-command audit V51/V52 (2026-05-21/23)

- **V49 `block_docs` table** — admin-editable markdown for block docs (Block
  Advisor's source). Read by `inspect_block_doc` + `/admin/block-docs` page.
- **V50 `agent_knowledge` seeds** — alarm scope + intent classification
  heuristics surfaced to plan_node as high-priority RAG bypass entries.
- **V51 `xbar_r` doc patch** — clarifies pre-aggregated `value_column` mode after
  the WECO X-bar/R agent picked the wrong shape repeatedly.
- **V52 `block_process_history` tool_id='ALL' sentinel** — fleet-wide queries
  no longer need to fan out across multiple `process_history` calls; sidecar
  expands ALL on the executor side.
- **Slash-command audit (2 reports)** — `docs/slash-command-audit-2026-05-21*.md`
  catalogue every slash command + its current routing; surfaced 4 stale commands
  removed in the dead-code purge.

### /system/monitor rewrite + Alarm UX 3-fix bundle (2026-05-22/23)

- **`/system/monitor` controller rewrite** (`046f85e`) — dropped stale
  `fastapi-backend:8001` entry (decommissioned 2026-04-25), added
  `aiops-java-scheduler:8003` + `aiops-app:8000`, replaced hardcoded "UP" with
  per-service `/health` probe (real status), dropped `fetchPollerStats()`
  (Python event poller is gone — Java scheduler owns event dispatch), extended
  `db_stats` to 15 tables (added `agent_knowledge`, `pb_blocks`, `block_docs`,
  `mcp_definitions`, `skill_runs`, `pb_pipeline_runs`).
- **Alarm UX 3-fix** (`ba26b6d` + `405edd3` + `79acbbe`):
  - data_views in `findings.outputs` were JSON-stringified in the UI as raw
    dumps; moved to `findings.step_details` (not iterated by RenderMiddleware)
    and AlarmEnrichmentService walks step_details to harvest into
    `trigger_data_views` → renders as proper DataViewTable.
  - `equipmentId` now falls back to evidence row's `toolID` when
    triggerPayload doesn't carry tool_id (cron/patrol skills); keeps alarms
    grouped per machine instead of dumping into a single "(any)" cluster.
  - Alarm summary leads with `confirm_check.description` (human-authored
    intent) before the machine-evaluated math, so oncall sees
    "條件: 5次中超過3次OOC" instead of just "Confirm: 1.0 ≥ 0.0".

### Dead-code purge (Tiers A/B/C + Round 1+2, 2026-05-23)

User feedback: post-cutover, multiple frontend pages + Java controllers were
still in the tree but unreachable. Purge removed:
- **Tier A** (4 pages) — triggers / published-skills / mcps / system-skills
- **Tier B** (7 pages + 31 alarm-center-beta assets) — auto-patrols /
  auto-check-rules / system aliases / dev / prototype / alarms-beta
- **Tier C** (5 orphan pages) — events / lots / event-types / automation /
  orphan mcps API proxy
- **Round 1+2 backend** — 8 Java controllers + 4 entity/repo chains
  (CronJob / DataSubject / MockDataSource / ScriptVersion) + 5 sidecar modules
  + 2 frontend proxies. ~14K LoC removed across frontend + backend.

---

## 4. v18 — Reject-and-ask loop + Intent bullets (shipped 2026-05-14 · historical)

### What changed
Builder graph used to silently fail when `macro_plan_node` LLM judged the prompt too_vague. v18:

1. `clarify_intent_node` → produces **intent bullets** (model's restatement of user's needs as 2-6 checkable points, each may have a chart preview from `block.examples`)
2. User confirms ✓ / rejects ✗ / edits each bullet
3. Confirmed bullets fold back into instruction as ground-truth → macro_plan
4. If macro_plan still says too_vague after retry → status=**refused** with friendly message (instead of silent fail)

Plus 4 new compile_chunk autofixes:
- `_force_skill_terminal` — skill_step_mode last step uses block_threshold → rewrite to block_step_check
- `_autocorrect_column_refs` — fuzzy match invented column names
- `_drop_unspecced_cpk` — block_cpk without usl/lsl → drop
- (existing 8 autofixes still active)

### Stability
Skill builder smoke 5/5 OK. Driver: `tooling/skill_builder_smoke.sh`, also `/tmp/driver_lastooc.py`.

### Files
- `python_ai_sidecar/agent_builder/graph_build/nodes/clarify_intent.py` — bullets generation + preview attachment
- `python_ai_sidecar/agent_builder/graph_build/nodes/macro_plan.py` — too_vague → needs_clarify routing
- `python_ai_sidecar/agent_builder/graph_build/nodes/compile_chunk.py` — 12 autofix layers
- `aiops-app/src/app/admin/build-traces/page.tsx` — admin page renders bullets + previews

### Open items (resolved 2026-05-14 by `f535d78` + `87d5ad2`)
- ~~Skill Builder GUI modal v15 MCQ → v18 bullets~~ — `BulletConfirmCard` wired
  into `AIAgentPanel` (the actual Skill Builder panel).

---

## 5. v19 — Chat intent confirmation (shipped 2026-05-14 · historical)

### Goal
User feedback: "新的 skill 就是要出現，不論是 skill builder or chat mode". Chat mode previously short-circuited clarify_intent.

### Q1/Q2/Q3 decisions (per user)
- **Q1**: BulletConfirmCard as independent system-message card in chat stream
- **Q2**: User starts new prompt without responding → auto-cancel previous pending
- **Q3**: In-memory pending state map (Redis later for K8s)

### Implementation (deployed)
**Backend**:
- `agent_orchestrator_v2/pending_clarify.py` (new) — in-memory map `chat_session_id → PendingClarify`. 30 min GC. New entry auto-cancels prior pending (Q2).
- `tool_execute._execute_build_pipeline_live` — detects `intent_confirm_required` in graph stream, emits `pb_intent_confirm` event to chat SSE, stores pending state, returns `clarify_pending` tool_result.
- New endpoint `POST /internal/agent/chat/intent-respond` — looks up pending state, resumes via `resume_graph_build_with_clarify`, streams SSE.
- `runner.resume_graph_build_with_clarify` fixed: pass `Command(resume=)` dict directly (was wrapping in `{answers: ...}` which broke v18 bullets path).
- `BuildClarifyRespondRequest` now accepts both `answers` (legacy MCQ) and `confirmations` (v18 bullets).
- `clarify_intent_node` removed `skip_confirm=True` short-circuit.

**Frontend**:
- `components/chat/BulletConfirmCard.tsx` (new) — dark-themed card with per-bullet ✓/✗/edit + preview chart + POST handler.
- `components/chat/ChatPanel.tsx` — handles `pb_intent_confirm` SSE event, renders card-only message; resolution synthesizes "✓ 已建好" follow-up.
- `app/api/agent/chat/intent-respond/route.ts` (new) — Next.js proxy bypassing Java directly to sidecar (Java doesn't need to know about v19).

### ⚠ Smoke test partial — RESOLVED 2026-05-19

The original ship hit `pre_clarify_check_node` / `dimensional_clarifier`
interception so v19's `clarify_intent` never reached the chat-build path.
Resolved by `1d4a35b fix(v19): resume SSE flows through chat handler so
canvas updates` — v19 bullets path is now the canonical chat clarification
mechanism; `design_intent_confirm` was removed from the build-pipeline-live
intercept.

### Skill Builder Glass Box mode
v19 bullets DO fire here. Skill Builder is fully working; chat is the open item.

---

## 6. Observability & DevOps

### Build trace viewer
- Browse: `/admin/build-traces`
- Trace files: `/tmp/builder-traces/<timestamp>-<build_id>.json` on EC2
- Schema documented in `python_ai_sidecar/agent_builder/graph_build/trace.py`
- Per-step duration_ms, LLM token usage, exec_trace snapshots, validation issues — all in trace
- Clear-all / Clear-24h+ buttons in sidebar header

### Agent workflow doc
- `docs/agent_workflow.md` (markdown, source of truth)
- `docs/agent_workflow.html` (self-contained mermaid render for sharing)
- **Both must be updated on every push** when graph routing changes — see memory `feedback_readme_before_push.md`

### DevOps spec
- Current spec: `docs/devOps_technique_guide_2.0.md`
- Old `devOps_technique_guide.md` archived to `docs/history/`
- 32 outdated docs archived to `docs/history/` on 2026-05-14

### Deploy
- EC2: `deploy/update.sh` (frontend+sim) and `deploy/java-update.sh` (Java+sidecar)
- systemd units in `deploy/*.service`
- nginx config in `deploy/nginx.conf`
- K8s: `deploy/<service>-run.sh` wrappers planned but not built — waiting on K8s target env decision

---

## 7. Open Items (as of 2026-05-24)

### Resolved since 2026-05-14
| Item | Resolution |
|---|---|
| Skill Builder GUI v15 MCQ → v18 bullets | ✓ shipped `f535d78` + `87d5ad2` 2026-05-14 |
| LLM prompt cache for catalog (cache_read=0) | ✓ shipped `bcf5195` (Anthropic prompt cache on `agentic_phase_loop` ~90% token cut) 2026-05-19 |
| v19 vs `design_intent_confirm` chat coexistence | ✓ shipped `1d4a35b` (resume SSE flows through chat handler — v19 path stable) |
| Java backend god-class architectural debt (DevOps audit flag) | ✓ shipped Phase 12 OOP refactor PR #5 2026-05-24 |
| Test coverage gap (2 active files for 15K LoC) | ✓ partial — 6 active files / 145 tests post-Phase-12. Coverage is now meaningful for JsonUtils + SkillDocument + Pipeline + PipelineBuilder + SkillAlarmEmitter (the alarm-emit critical path). Other services still uncovered — see deferred. |

### Pending
| Priority | Item | Status / Next |
|---|---|---|
| **HIGH** | **Token usage analytics panel** in admin trace viewer | Trace `input_tokens`/`output_tokens` fields populated since Tier 1 observability; admin viewer doesn't render them yet. ~3-4 hrs to add a cost summary card + per-call breakdown. |
| **HIGH** | **agent_workflow.html refresh** | Source-of-truth markdown was updated for v30 + Block Advisor + intent_completeness; HTML mermaid render lagging. Re-render via the doc page or rewrite — per `feedback_readme_before_push.md` they must match. |
| **HIGH** | **RAG tools for LLM lookups** — `query_blocks` / `query_columns` / `query_connectable_sources` | Replaces push-everything catalog. Memory `project_rag_for_llm_lookups.md`. Substantial — would cut prompt tokens further but needs new graph nodes. |
| MED | **K8s deployment** — Dockerfile × 4 + `<service>-run.sh` while-true wrappers + manifests | Waiting on K8s target env decision (GKE/EKS/self-hosted). Memory `reference_k8s_run_sh_pattern.md`. |
| MED | **`pending_clarify` Redis backend** for K8s pod horizontal scale | Tied to K8s migration. Currently in-memory map in sidecar. |
| MED | **Alarm-trigger vs user-presentation decouple** in goal_plan | Memory `project_alarm_vs_display_decouple.md` — goal_plan currently mixes the two phases; should separate alarm rule (verdict) from display (chart/table). |
| MED | **Chart-phase LLM-judge quantifier reject** | Memory `project_chart_phase_judge_quantifier.md` — chart blocks with rows=None + value_desc containing "所有" quantifier always get rejected. Pick fix path (a/b/c per memory). |
| MED | **v30.17j follow-up items A1–A5 + B1–B7** | Memory `project_v30_17j_followups.md` — collection of v30 stability tweaks (1-block spc_panel, agent success-mismatch, zero case, ChatPanel dead code, plan over-segmentation, etc.) |
| MED | **Judge-deficit user interaction** — JudgeClarifyCard for rows < 80% target | Memory `project_judge_deficit_interaction.md` — verifier should pause + open clarify card (continue / replan / cancel) instead of hard-failing. |
| MED | **Test coverage for FleetService / AgentKnowledgeService / SkillRunnerService orchestrator** | Phase 12 P3 covered the helpers + business rules but not the orchestration flows. Mockito pattern established; ~1-2 hrs per service. |
| LOW | **Phase 2 panel blocks** — `block_cpk_summary`, `block_fdc_anomaly` | Defer until 1-2 real prompts to design against. |
| LOW | **Pending self-test checks** — loop MCP detection + chart x_key format validation | Memory `pending_selftest_checks.md` — pre-existing improvements to the self-smoke harness. |
| LOW | **LLM repair pattern: doesn't remove old nodes** | Memory `feedback_llm_doesnt_remove_old_nodes.md` — repair/reflect creates `n1b` parallel to broken `n1` instead of using `remove_node`. Affects retry quality. |
| DEFERRED | **`com.aiops.api.api.* → com.aiops.api.service.*` package move** | Phase 12 P4 deliberately chose lighter-weight `package-info.java` documentation over mechanical package shuffle (YAGNI). Revisit if multi-team boundary becomes a problem. |
| DEFERRED | **fastapi_backend_service final removal** | Already decommissioned + directory deleted in dead-code purge; CI workflows referencing it dropped in `ae053bd`. Nothing left to remove. |

---

## 8. Key Files Quick-Reference

| What | Where |
|---|---|
**Python sidecar (agents + executors)**
| What | Where |
|---|---|
| Builder graph | `python_ai_sidecar/agent_builder/graph_build/graph.py` |
| Builder nodes | `python_ai_sidecar/agent_builder/graph_build/nodes/` |
| Block executors | `python_ai_sidecar/pipeline_builder/blocks/` (56+ blocks) |
| Block catalog (LLM-visible) | `python_ai_sidecar/pipeline_builder/seed.py` |
| Trace recorder | `python_ai_sidecar/agent_builder/graph_build/trace.py` |
| Chat orchestrator | `python_ai_sidecar/agent_orchestrator_v2/` |
| Block advisor (tool-using doc Q&A) | `python_ai_sidecar/agent_builder/advisor/` |

**Java backend (post-Phase-12 layering — controller↔service↔repo per package)**
| What | Where |
|---|---|
| Skill domain (1 controller + 5 services) | `java-backend/.../api/skill/` — see `package-info.java` |
| Pipeline domain (controllers + services + Dtos + DocGenerator) | `java-backend/.../api/pipeline/` — see `package-info.java` |
| Fleet domain (controller + 3-split services + façade + simulator client) | `java-backend/.../api/fleet/` — see `package-info.java` |
| Agent proxy (SSE/JSON to sidecar) + DTOs | `java-backend/.../api/agent/` — see `package-info.java` |
| Agent knowledge (user-scoped CRUD) | `java-backend/.../api/agentknowledge/` — see `package-info.java` |
| Internal (sidecar-only) RAG + embedding lifecycle | `java-backend/.../api/internal/` — see `package-info.java` |
| Shared infrastructure | `java-backend/.../common/` — `ApiResponse` / `ApiException` / `SseEmitterBridge` / `RequestBodyAccess` / `JsonUtils` |
| Mockito unit tests (145 tests / 6 files) | `java-backend/src/test/java/com/aiops/api/` |
| Flyway migrations | `java-backend/src/main/resources/db/migration/V*.sql` (latest V52) |

**Frontend**
| What | Where |
|---|---|
| Chat panel UI | `aiops-app/src/components/chat/ChatPanel.tsx` |
| BulletConfirmCard (v19) | `aiops-app/src/components/chat/BulletConfirmCard.tsx` |
| Agent Builder Panel (Skill Builder) | `aiops-app/src/components/pipeline-builder/AgentBuilderPanelV30.tsx` |
| Admin trace viewer | `aiops-app/src/app/admin/build-traces/page.tsx` |
| Admin block-docs editor | `aiops-app/src/app/admin/block-docs/` |

**Docs / DevOps**
| What | Where |
|---|---|
| Agent workflow doc | `docs/agent_workflow.md` + `docs/agent_workflow.html` |
| Spec docs (active) | `docs/SPEC_*.md` (17 archived to `docs/history/`) |
| DevOps spec | `docs/devOps_technique_guide_2.0.md` |
| Slash-command audit | `docs/slash-command-audit-2026-05-21*.md` |
| Deploy scripts | `deploy/update.sh` (FE+sim), `deploy/java-update.sh` (Java+sidecar) |
| systemd units | `deploy/aiops-*.service` |
| Project guidelines | `CLAUDE.md` (root — backend Java patterns added 2026-05-24 in `070d5b1`) |

---

## 9. Recent migrations (Flyway)

| Version | Date | What |
|---|---|---|
| V44 | 2026-05-13 | `show_means_visualize` agent_knowledge rule |
| V45 | 2026-05-14 | `block_spc_panel` + `block_apc_panel` catalog entries |
| V46 | 2026-05-14 | Panel blocks source-mode + color params update |
| V47 | 2026-05-16 | `block_find` — filter + (optional) sort + take first/last/all/N |
| V48 | 2026-05-16 | block_filter examples + block_sort description tightening (cross-ref block_find) |
| V49 | 2026-05-19 | `block_docs` table — admin-editable markdown for Block Advisor source |
| V50 | 2026-05-20 | `agent_knowledge` seeds — alarm scope + intent classification heuristics for plan_node bypass |
| V51 | 2026-05-22 | `xbar_r` block doc clarifies pre-aggregated `value_column` mode (WECO X-bar/R fix) |
| V52 | 2026-05-22 | `block_process_history` `tool_id='ALL'` sentinel for fleet-wide queries |

**Important**: Flyway auto-run disabled in EC2 prod. Apply manually:
```bash
psql -h localhost -U aiops aiops_db -f java-backend/src/main/resources/db/migration/V<N>.sql
```
DB password in `java-backend/.env`.

---

## 10. Smoke / Test commands

```bash
# Skill Builder full flow (intent_confirm → confirm_apply → build, expects 5/5)
ssh ubuntu@aiops-gill.com "python3 /tmp/driver_lastooc.py"

# Direct executor test (no graph, just pipeline run)
curl -X POST http://localhost:8050/internal/pipeline/preview \
  -H "X-Service-Token: $TOK" -H "Content-Type: application/json" \
  -d '{"pipeline_json": {...}, "node_id": "panel"}'

# Chat intent flow (smoke partial — see section 5 caveat)
ssh ubuntu@aiops-gill.com "python3 /tmp/driver_chat_intent.py"

# Trace cleanup
curl -X DELETE 'http://localhost:8050/internal/agent/build/traces?older_than_hours=24' \
  -H "X-Service-Token: $TOK"
```

---

## 11. Memory entries (per-project, auto-loaded)

Location: `/Users/gill/.claude/projects/-Users-gill-metagpt-pure-workspace-fastapi-backend-refactored/memory/`

The `MEMORY.md` index is loaded into every session's context. Below is a
curated selection of the most-referenced entries; the index has ~60 total.

**Architectural principles (referenced often)**:
- `feedback_no_case_rule_in_prompt.md` — Core Principle 0: never add case-specific rules to LLM prompts; fix via graph node / schema / structured meta
- `feedback_flow_in_graph_not_prompt.md` — flow control rules belong in graph nodes (testable / deterministic), not LLM prompts
- `feedback_graph_heavy_preference.md` — reject "30 tools + 80-turn free LLM"; push logic into graph nodes
- `feedback_plan_intent_execute_blocks.md` — plan layer = intent / execute = blocks; goal_plan is block-agnostic
- `feedback_jackson_snake_case_wire.md` — Java DTO wire is snake_case; camelCase silent-ignored
- `feedback_flyway_disabled_in_prod.md` — Flyway prod-disabled; new V**.sql via manual psql on EC2

**DevOps / infra**:
- `reference_devops_target_stack.md` — Java 17 / Spring 3.5.14 / Python 3.11 / Node 20.18
- `reference_port_convention.md` — EC2 distinct ports (8000/8002/8050/8012); K8s future 8080→80
- `reference_k8s_run_sh_pattern.md` — future K8s while-true wrapper template
- `reference_ec2_prod_repo_path.md` — `/opt/aiops` is the canonical prod path
- `reference_github_repo.md` — `gillggx/ai-ops-agentic-platform`
- `project_ec2_service_map.md` — port/service mapping
- `feedback_sidecar_restart_gotcha.md` — `deploy/update.sh` skips sidecar; must `systemctl restart aiops-python-sidecar` after sidecar code change
- `feedback_nextjs_standalone_deploy.md` — npm build alone breaks `/_next/static`; use deploy/update.sh
- `feedback_deploy_via_git_not_direct_edit.md` — never SSH-edit prod; always git push → EC2 pull

**Process discipline**:
- `feedback_readme_before_push.md` — README/SPEC/HANDOFF must update before push (this doc lives by that rule)
- `feedback_verify_like_user.md` — declare-done prerequisites: grep / curl / SELECT row / mtime check before saying fixed
- `feedback_self_smoke_before_user.md` — 4 smoke tools (CRUD + Builder LLM + GUI Playwright + full real-LLM e2e); LLM tests must pass 3× consecutively
- `feedback_check_traces_first.md` — when user reports failure, SSH `/tmp/builder-traces/*.json` for their case first, don't re-run smoke with different randomness
- `feedback_foreground_test_runs.md` — driver / smoke runs use foreground Bash so user sees real-time progress
- `feedback_no_emoji.md` — no emoji or emoji-like chars anywhere (chat / code / docs / UI strings)
- `feedback_plan_phase_format.md` — phase format = id + [expected] + text; no goal/value_desc/outcome_keys/why

**Open follow-up projects (referenced in §7 above)**:
- `project_alarm_vs_display_decouple.md` — separate alarm trigger phase from user-presentation phase in goal_plan
- `project_rag_for_llm_lookups.md` — query_blocks / query_columns / query_connectable_sources tools
- `project_chart_phase_judge_quantifier.md` — chart-phase LLM-judge over-rejects on quantifier mismatch
- `project_v30_17j_followups.md` — A1-A5 + B1-B7 v30 stability items
- `project_judge_deficit_interaction.md` — JudgeClarifyCard for rows < target situations
- `feedback_llm_doesnt_remove_old_nodes.md` — LLM repair adds `n1b` parallel instead of `remove_node`
- `pending_selftest_checks.md` — loop MCP detection + chart x_key format validation

**Refactor / cleanup history**:
- `project_pipeline_builder_progress.md` — pipeline builder phase history
- `project_p1_pipeline_migration.md` — Phase ε pipeline migration progress
- `project_object_native_phase1.md` — object-native pipeline (nested=true)
- `project_self_correction_loop.md` — inspect_execution + reflect_plan
- `project_chart_engine_overhaul.md` — 18-block charting overhaul
- `project_builder_block_advisor.md` — 5-bucket classifier + advisor graph

---

**Maintainer note for next session**: §7 above is the canonical "what's left"
list. Highest priority pending items:
1. Token usage analytics panel in admin trace viewer (HIGH, ~3-4 hrs)
2. agent_workflow.html refresh (HIGH, depends on graph diff since last render)
3. RAG tools for LLM lookups (HIGH, substantial — needs new graph nodes)

Everything else is shipped + operational on EC2 (PR #5 merged 2026-05-24, all
3 services UP, 5 refactored surfaces verified post-merge).
