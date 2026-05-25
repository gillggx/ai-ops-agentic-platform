# Distributed Config Matrix

Single source of truth for every environment variable each service reads.
When you add a new env var, update this table in the same PR.

## Service URL conventions

| Environment | URL pattern |
|---|---|
| EC2 (current prod, single host) | `http://localhost:<port>` |
| Docker Compose | `http://<service-name>:8080` (compose bridge DNS) |
| Kubernetes | `http://<service>.aiops.svc.cluster.local` (port 80 → 8080 in pod) |

All in-source URLs must be env-driven — no `http://localhost:<port>`
hardcoded in code. Pattern:

```python
url = os.environ.get("XXX_URL", "http://localhost:80NN").rstrip("/")
```
```typescript
const BASE = process.env.XXX_BASE_URL ?? "http://localhost:80NN";
```

## Required env vars (per service)

Legend: ✓ = required, ○ = optional, — = not used.

| Variable | sidecar | java-api | scheduler | aiops-app | simulator | Notes |
|---|:---:|:---:|:---:|:---:|:---:|---|
| `INTERNAL_API_TOKEN` | ✓ (`SERVICE_TOKEN` + `JAVA_INTERNAL_TOKEN`) | ✓ | ✓ | ✓ | — | Shared service token. >=16 chars. Build fails in prod if missing (aiops-app); sidecar will 401 on java calls if mismatched. |
| `NEXTAUTH_SECRET` | — | — | — | ✓ | — | Session signing. >=32 chars. |
| `POSTGRES_PASSWORD` | — | ✓ (`SPRING_DATASOURCE_PASSWORD`) | ✓ | — | — |  |
| `LOG_LEVEL` | ○ | ○ | ○ | — | ○ | Default INFO. See docs/logging-schema.md. |
| `LLM_PROVIDER` | ✓ | — | — | — | — | `anthropic` / `ollama` / `internal-proxy`. |
| `LLM_MODEL` | ✓ | — | — | — | — |  |
| `ANTHROPIC_API_KEY` | ✓ (if anthropic) | — | — | — | — |  |
| `OLLAMA_BASE_URL` / `_API_KEY` / `_MODEL` | ✓ (if ollama) | — | — | — | — |  |
| `INTERNAL_PROXY_BASE_URL` / `_API_KEY` / `_HEADER_NAME` / `_HEADER_VALUE` | ✓ (if internal-proxy) | — | — | — | — |  |
| `FASTAPI_BASE_URL` | — | — | — | ✓ | — | URL of java-api (kept the legacy var name for compat). |
| `JAVA_API_URL` | ✓ | — | ✓ (`AIOPS_JAVA_API_BASE_URL`) | — | — |  |
| `AIOPS_SIDECAR_PYTHON_BASE_URL` + `_SERVICE_TOKEN` | — | ✓ | — | — | — | java-api → sidecar. |
| `AIOPS_SCHEDULER_BASE_URL` + `_INTERNAL_TOKEN` | — | ✓ | — | — | — |  |
| `AIOPS_SIMULATOR_BASE_URL` | — | — | ✓ | — | — |  |
| `ONTOLOGY_SIM_URL` | ✓ | — | — | — | — | Sidecar (pipeline blocks) → simulator. |
| `SPRING_DATASOURCE_URL` | — | ✓ | ✓ | — | — | jdbc:postgresql://... |
| `SPRING_DATA_REDIS_HOST` | — | — | ✓ | — | — | Distributed lock + leader election. |
| `MONGODB_URL` | — | — | — | — | ✓ |  |
| `ALLOWED_CALLERS` | ○ | — | — | — | — | IP-allowlist for sidecar; `*` to disable. |
| `NEXTAUTH_URL` | — | — | — | ✓ | — | Public origin used by NextAuth callbacks. |

## Trace-ID propagation

All 4 services participate in the `X-Trace-ID` header convention defined
in [logging-schema.md](logging-schema.md). No env config needed — it
auto-forwards through `JavaAPIClient` (python) / `WebClient` filters (java).

## Where to set it

| Surface | Mechanism |
|---|---|
| EC2 systemd | per-unit `EnvironmentFile=` in `/etc/systemd/system/*.service` |
| Docker Compose | `deploy/docker/.env` + `env_file` directive |
| Kubernetes | `aiops-config` ConfigMap (non-secret) + `aiops-secrets` / `aiops-secrets-llm` Secrets |
| Local dev | `.env.local` per workspace; sidecar venv reads via python-dotenv |
