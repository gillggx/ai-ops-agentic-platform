# AIOps Platform — Roadmap

> Single-source phase tracker. Updates when a phase's status changes; not
> a release log. For per-phase deliverables / runbooks see the linked
> `PHASE_*.md` docs.

**Last updated**: 2026-05-08

---

## Where we are

**Current phase**: ✅ Phase 8-A-1d complete · 🛠 Phase 9 design draft

**Active branch**: `main`
**Live services on EC2**:
- `aiops-app` :8000 (Next.js 15 standalone)
- `aiops-java-api` :8002 (Spring Boot, sole DB owner)
- `aiops-python-sidecar` :8050 (LangGraph + 48 native block executors)
- `ontology-simulator` :8012 (MES + station agents)
- `fastapi-backend` :8001 — **stopped + disabled** (Phase 8-A-1d cutover)

---

## Phase history

| phase | status | summary | runbook |
|---|---|---|---|
| **0–7** | shipped | Initial chat orchestrator, builder, MCP catalog, simulator v1, alarm center, dashboard | (pre-Phase-8 history not consolidated) |
| **8-A** | ✅ shipped 2026-04-25 | Glass Box builder + chat orchestrator_v2 ported into sidecar; fastapi-backend (:8001) decommissioned | [PHASE_8_A_RUNBOOK.md](PHASE_8_A_RUNBOOK.md) |
| **8-B** | ✅ shipped 2026-04-25 | 27 → 48 BUILTIN_EXECUTORS native in sidecar; legacy walker retired | [PHASE_8_SESSION_REPORT.md](PHASE_8_SESSION_REPORT.md) |
| **8-D** | ✅ shipped | Live data pipelines (DR/Patrol migration to Phase 8 native) | [PHASE_8_D_RUNBOOK.md](PHASE_8_D_RUNBOOK.md) |
| **9** | 🛠 **design draft** | Agent-Authored Rules — chat output becomes runnable rule artifacts (cron + pipeline + channel) | [PHASE_9_AGENT_AUTHORED_RULES.md](PHASE_9_AGENT_AUTHORED_RULES.md) |
| **10** | 📋 backlog | Write operations from chat (ack alarm / hold tool / pause patrol) + audit | TBD |
| **11** | 📋 backlog | Multi-tenant team rules (sharing / RBAC on personal rules) | TBD |

## Recent shipped (last 10 days)

| date | scope | commit |
|---|---|---|
| 2026-05-08 | Sidecar LLM → Claude Haiku 4.5; max_tokens 1024 → 8192 | env-only |
| 2026-05-08 | `RECYCLE_LOTS` / `TOTAL_LOTS` removed; pacer is sole lifecycle | `2d9c84f` |
| 2026-05-08 | Topology · Trace UX overhaul: solid lines + box-bg focus + visx brush + 6H reset fix | `73299b9`, `1606fc3` |
| 2026-05-07 | `block_list_objects` typed list MCP dispatcher (5 kinds) | `6549d95`, `afb2536` |
| 2026-05-07 | Simulator graceful-shutdown step-skip fix | `5ca060a` |

---

## What's next (Phase 9)

See [PHASE_9_AGENT_AUTHORED_RULES.md](PHASE_9_AGENT_AUTHORED_RULES.md) for full
design. Headline thesis:

> **Agent specs rules at design-time. Deterministic code runs them at runtime.**

Build sequence:
1. **9-A** — `auto_patrol` schema extension + `notification_inbox` + dispatch service
2. **9-B** — sidecar tool `propose_personal_rule` (NL → Rule Artifact)
3. **9-C** — UI: in-app banner + `/rules` page + chat panel "save as rule" button
4. **9-D** *(optional v0.9 stretch)* — email / push channels + event-triggered watch rules

## What's deliberately NOT in Phase 9

| out-of-scope | reason | revisit |
|---|---|---|
| Write operations from chat (ack alarm / hold) | Audit + role-permission complexity | Phase 10 |
| Multi-turn entity context store (Scenario 4 drilling) | Touches whole agent state model — bigger architectural lift | Phase 10 (parallel) |
| Team-shared rules | Cross-tenant leak risk; need RBAC on rules | Phase 11 |
| Email / Slack / PagerDuty | External infra dependency; in-app banner first | Phase 9-D stretch |

---

## Reference docs (still authoritative)

- [agent_capability.md](agent_capability.md) — capability map by use case
- [AGENT_BACKLOG.md](AGENT_BACKLOG.md) — agent-specific backlog (eval harness, classifier fixes, etc.)
- [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) — onboarding overview
- [Hybrid_java_python.md](Hybrid_java_python.md) — Java + sidecar boundary contract
- [Chat Orchestrator_LangGraph.md](Chat%20Orchestrator_LangGraph.md) — chat orchestrator v2 internals
