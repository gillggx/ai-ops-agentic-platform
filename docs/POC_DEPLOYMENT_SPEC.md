# Skill Library POC — Product / Deployment Spec

**Audience:** DevOps / Platform Engineering
**Deploy branch:** `poc/skill-library-20260624` (cut from `main` @ `1a51ec3`)
**Repo:** `https://github.com/gillggx/ai-ops-agentic-platform`
**Status:** POC — single-host (EC2 systemd) today; K8s-ready (manifests stubbed)

---

## 1. Purpose

An AI-assisted **Skill Library** for semiconductor operations: engineers author,
test, and run analytics "skills" (data pipelines) in natural language or by hand,
backed by a block catalog with self-documenting descriptions. An LLM agent turns
a request into a pipeline of blocks, runs it against external data sources, and
returns charts / tables / verdicts.

This POC isolates that surface. The internal **ontology simulator** and the
**auto-patrol / alarm / rules / topology / fleet** modules are intentionally
**removed** — external data comes only through **System MCPs** (configurable HTTP
data sources).

## 2. Scope

**In scope (the POC):**
- **L1 — Library**: browse / search published skills + the block catalog.
- **L2 — Authoring**: build skills in natural language (Glass Box agent) or by
  hand (manual pipeline builder).
- **L3 — Try Run**: execute a draft skill against live data, view the result.
- **Block Docs**: per-block description / params / examples (single source of
  truth for both the LLM and the UI).
- **Build Trace**: per-build agent reasoning trace for debugging.
- **System MCP**: admin-configured external HTTP data sources (endpoint, method,
  HTTP headers with `${ENV}` secret interpolation, input schema).

**Out of scope (removed on this branch):**
- `ontology_simulator` service (and its MongoDB).
- Auto-patrol / alarm / rules engine / SkillAlarmEmitter / scheduler (L4).
- Topology / Fleet dashboards (`FleetSimulatorClient` stubbed to empty).
- `/admin/simulator-health` and related simulator UI.

## 3. System Architecture

Four runtime services (single host today; each is its own Docker image for K8s):

| Service | Port (EC2) | Role |
|---|---|---|
| `aiops-app` (Next.js, standalone) | 8000 | UI render + `/api/` proxy only — no business logic, never calls backend services directly except via proxy |
| `aiops-java-api` (Spring Boot) | 8002 | **Sole DB owner**: all PostgreSQL R/W, auth (JWT), business CRUD, skill/block/MCP registry, role audit. `/api/v1/*` (user-facing, JWT) + `/internal/*` (service-to-service, `X-Service-Token`) |
| `python_ai_sidecar` (FastAPI + LangGraph) | 8050 | All agents (chat orchestrator, Glass Box builder, block advisor) + the in-process pipeline executor (56 builtin blocks). Talks to Java via JavaAPIClient; **never** connects to PostgreSQL directly |
| `aiops-java-scheduler` (Spring Boot) | 8003 | Cron / scheduled work (minimal in POC; fleet/patrol stubbed) |

**Data store:** PostgreSQL (`aiops_db`) + pgvector. **No MongoDB** on this branch.

```
Browser → aiops-app:8000 (UI + /api proxy)
            → aiops-java-api:8002 (DB owner, auth, registries)
                 ↔ python_ai_sidecar:8050 (agents + executor)
                      → External HTTP data sources (System MCP)
```

**Boundary rules:** frontend only renders + proxies; Java owns the DB; the
sidecar reaches the DB only through Java; external data flows only via System
MCP. URLs/ports are read from `.env` / ConfigMap — no hardcoded `localhost:PORT`
in source.

## 4. Tech Stack (must stay consistent across pom.xml / Dockerfile / deploy)

| Component | Version |
|---|---|
| Java | Temurin **17** |
| Spring Boot | **3.5.14** (Maven, not Gradle) |
| Python | **3.11** |
| Node.js | **20.18** |
| PostgreSQL | + pgvector |
| LLM (default) | KIMI K2.5 via OpenRouter (single switch: sidecar `.env` `OLLAMA_MODEL`) |

## 5. External Data Sources — System MCP

The POC's data layer. An admin registers a System MCP via the admin UI
(`/admin/system-mcps`): endpoint URL, HTTP method, **HTTP headers**, and input
schema. Header values support **`${ENV_VAR}` interpolation** — the literal
secret is NOT stored in the DB; at runtime `resolve_headers()` substitutes from
the sidecar's environment and fails loudly (`INVALID_MCP_CONFIG`) naming any
missing env var.

**Operational implication:** every secret referenced as `${NAME}` in an MCP
header config must exist in the **sidecar** environment
(`python_ai_sidecar/.env`), e.g. `EXTERNAL_API_TOKEN=...`.

## 6. Deployment

### 6.1 Single-host (EC2 systemd — current)

systemd units (in `deploy/`): `aiops-app`, `aiops-java-api`,
`aiops-java-scheduler`, `aiops-python-sidecar`.

**Fresh host:**
```bash
git clone -b poc/skill-library-20260624 \
  https://github.com/gillggx/ai-ops-agentic-platform.git /opt/aiops
cd /opt/aiops
# fill secrets (see §7) in each service .env, then:
sudo bash deploy/setup.sh         # one-time host/service bootstrap (3-service, no simulator/mongo)
```

**Existing host / redeploy:**
```bash
cd /opt/aiops && git fetch && git checkout poc/skill-library-20260624 && git pull
# stop the simulator unit if it lingers from a main deploy:
sudo systemctl stop ontology-simulator 2>/dev/null; sudo systemctl disable ontology-simulator 2>/dev/null
sudo bash deploy/java-update.sh   # rebuild Java jars + sidecar venv, restart Java + sidecar
sudo bash deploy/update.sh        # frontend (no simulator on this branch)
```

> `java-update.sh` restarts Java + sidecar; `update.sh` restarts frontend.
> Changing sidecar code requires `java-update.sh` (not `update.sh`).

### 6.2 Database init (IMPORTANT)

- Schema migrations live in `java-backend/src/main/resources/db/migration/V*.sql`.
- **Flyway is DISABLED in prod** — new `V*.sql` must be applied manually:
  `psql -f` on the host (DB creds in `java-backend/.env`).
- **Block catalog**: `pb_blocks` is seeded deterministically. `java-update.sh`
  applies `db/canonical/pb_blocks_canonical.sql`
  (`ON CONFLICT DO NOTHING` — backfills a fresh DB to the full 56-block set, a
  no-op on an established DB). A fresh DB therefore converges to the full catalog
  without relying on the incremental migration history.

### 6.3 K8s (future)

Per-service Docker image, container `EXPOSE 8080`, service port → 80,
service-name discovery. Manifests under `deploy/kubernetes/` (ontology-simulator
component removed on this branch). Run wrappers (`deploy/<service>-run.sh`
while-true loops) pending the target K8s env decision.

## 7. Configuration / Secrets

Each service reads its own `.env` (created from `deploy/*.env.example` on first
deploy if missing). Key items:

| Service `.env` | Required keys (representative) |
|---|---|
| `java-backend/.env` | `DB_URL` (jdbc postgres), `DB_USER`, `DB_PASSWORD`, JWT secret, `SERVICE_TOKEN` (internal) |
| `python_ai_sidecar/.env` | `SERVICE_TOKEN` (must match Java), `JAVA_API_URL`, LLM provider key + `OLLAMA_MODEL`, **`${ENV}` secrets referenced by System MCP headers** (e.g. `EXTERNAL_API_TOKEN`) |
| `aiops-app/.env.local` | proxy base URLs, NextAuth/OIDC config (OIDC optional; credentials login always on) |

**Ports are env-driven** (`AIOPS_JAVA_PORT`, etc.); do not hardcode.

## 8. Operations

- **Health**: Java `:8002/actuator/health`; sidecar `:8050/internal/health`
  (401 without `X-Service-Token` = up); app `:8000`.
- **Logs**: `journalctl -u aiops-java-api | aiops-python-sidecar | aiops-app`.
- **Restart**: `systemctl restart aiops-<service>`.
- **Block-catalog invariant** (sidecar boot log): `block consistency OK: N
  builtin, N native, N in seed, N in DB` — all four equal (56) = healthy.

## 9. Known Quirks (expected, not bugs)

- `block_process_history` + `rework_request` blocks still appear in the catalog
  but Try-Run yields `MCP_UNREACHABLE` (they were simulator-only). Signal to
  authors not to pick them; configure a real System MCP instead.
- `/topology` and Fleet panels show empty state (`FleetSimulatorClient` stubbed).
- `/admin/simulator-health` nav entry removed.

## 10. Acceptance / Smoke

After deploy, confirm:
1. All four services `active`; health endpoints respond.
2. Sidecar boot log shows `block consistency OK: 56 / 56 / 56 / 56`.
3. UI: log in, open the Skill Library, open a block's docs drawer.
4. Register a System MCP (with a `${ENV}` header) → Try-Run a one-block skill
   against it → result renders.
5. Glass Box: author a skill in natural language → it builds + runs.

---

*Generated 2026-06-24. Source of truth for architecture/boundaries:
`CLAUDE.md`. POC scope/quirks: `.claude/skills/poc-skill-library/SKILL.md`.*
