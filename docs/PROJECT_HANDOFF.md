# AIOps Platform — Project Handoff

**Last updated: 2026-05-14** · **Current phase: v19 (Chat Intent Confirmation)**

> 上次大改版是 2026-04-27 的 Phase 8 (Java cutover)。本次 handoff 重寫覆蓋 Phase 8 之後的所有重大進展（v9–v19）。

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

---

## 4. v18 — Reject-and-ask loop + Intent bullets

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

### Open items
- Skill Builder GUI modal still shows v15 MCQ format; not yet migrated to bullets UI (admin trace viewer already shows the new format)

---

## 5. v19 — Chat intent confirmation (CURRENT)

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

### ⚠ Smoke test partial — known issue

**Full chat path NOT verified end-to-end**:
- New v19 endpoint reachable (HTTP 200).
- BulletConfirmCard renders when `pb_intent_confirm` arrives.
- BUT in actual chat flow, an existing mechanism (`pre_clarify_check_node` + `tool_execute` build_pipeline_live intercept using `dimensional_clarifier`) fires the older `design_intent_confirm` card BEFORE `build_pipeline_live` runs. So v19's `clarify_intent` inside the build never gets reached for build prompts that have ambiguity.

**Decision deferred (next session)**: should v19 bullets **replace** existing `design_intent_confirm`, or coexist? Both target chat-mode clarification:
- `design_intent_confirm` (existing) — `dimensional_clarifier` asks specific dims (time / target / metric) — pre-build intercept
- `v19 intent bullets` — `clarify_intent_node` restates the whole intent — inside-build pause

Recommend: replace dimensional_clarifier with v19 bullets (cleaner, single mechanism). But need to verify dimensional_clarifier's dim-detection rules can be folded into clarify_intent's LLM prompt.

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

## 7. Open Items

| Priority | Item | Owner / Next |
|---|---|---|
| **HIGH** | Decide v19 vs `design_intent_confirm` — replace or coexist in chat | Product decision; recommend: replace |
| HIGH | Skill Builder GUI modal: migrate from v15 MCQ to v18 bullets | Frontend, ~3-4 hours |
| MED | K8s deployment (Dockerfile + run.sh × 4 + manifests) | Waiting on target env decision |
| MED | `pending_clarify` Redis backend for K8s (currently in-memory) | Tied to K8s migration |
| MED | Token usage analytics from new trace `input_tokens`/`output_tokens` fields | Could add cost panel to admin viewer |
| LOW | Phase 2 panel blocks: `block_cpk_summary`, `block_fdc_anomaly` | Per spec discussion; defer until 1-2 real prompts to design against |
| LOW | Improve LLM accuracy: prompt cache for catalog (currently cache_read=0) | Could reduce token cost 90%; needs Anthropic prompt caching wiring |

---

## 8. Key Files Quick-Reference

| What | Where |
|---|---|
| Builder graph | `python_ai_sidecar/agent_builder/graph_build/graph.py` |
| Builder nodes | `python_ai_sidecar/agent_builder/graph_build/nodes/` |
| Block executors | `python_ai_sidecar/pipeline_builder/blocks/` (56 blocks) |
| Block catalog (LLM-visible) | `python_ai_sidecar/pipeline_builder/seed.py` |
| Trace recorder | `python_ai_sidecar/agent_builder/graph_build/trace.py` |
| Chat orchestrator | `python_ai_sidecar/agent_orchestrator_v2/` |
| Block advisor | `python_ai_sidecar/agent_builder/advisor/` |
| Chat panel UI | `aiops-app/src/components/chat/ChatPanel.tsx` |
| BulletConfirmCard | `aiops-app/src/components/chat/BulletConfirmCard.tsx` (v19 new) |
| Admin trace viewer | `aiops-app/src/app/admin/build-traces/page.tsx` |
| Agent workflow doc | `docs/agent_workflow.md` + `docs/agent_workflow.html` |
| Spec docs | `docs/SPEC_*.md` (active 4 files; 17 archived to history/) |
| DevOps spec | `docs/devOps_technique_guide_2.0.md` |
| Deploy scripts | `deploy/update.sh`, `deploy/java-update.sh` |
| Service files | `deploy/aiops-*.service` |
| Flyway migrations | `java-backend/src/main/resources/db/migration/V*.sql` (latest V46) |

---

## 9. Recent migrations (Flyway)

| Version | Date | What |
|---|---|---|
| V44 | 2026-05-13 | `show_means_visualize` agent_knowledge rule |
| V45 | 2026-05-14 | `block_spc_panel` + `block_apc_panel` catalog entries |
| V46 | 2026-05-14 | Panel blocks source-mode + color params update |
| V47 | 2026-05-16 | `block_find` — filter + (optional) sort + take first/last/all/N |
| V48 | 2026-05-16 | block_filter examples + block_sort description tightening (cross-ref block_find) |

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

Notable:
- `reference_devops_target_stack.md` — Java 17 / Spring 3.5.14 / Python 3.11 / Node 20.18
- `reference_port_convention.md` — EC2 vs K8s port rules
- `reference_k8s_run_sh_pattern.md` — future K8s run.sh template
- `feedback_readme_before_push.md` — README/SPEC/HANDOFF must update before push
- `feedback_flow_in_graph_not_prompt.md` — flow rules belong in graph not LLM prompt
- `project_pipeline_builder_progress.md` — pipeline builder phase history

---

**Maintainer note**: When next session starts, the most actionable thing is the v19/design_intent_confirm decision (section 7 first row). Everything else is shipped and operational on EC2.
