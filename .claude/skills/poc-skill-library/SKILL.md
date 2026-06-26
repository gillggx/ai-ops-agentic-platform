---
name: poc-skill-library
description: Spawn a Skill Library POC branch from the current main by replaying the canonical POC commits (strip ontology_simulator + add MCP headers form + ${ENV} interpolation in System MCP). Use when user says "切一個 POC", "skill library POC", "POC 版本", or wants to recreate poc/skill-library after main moved on.
---

# poc-skill-library

Recreate the **Skill Library POC** on top of whatever `main` looks like
today. The POC scope is L1 Library + L2 Authoring (NL + manual) + L3 Try
Run + Block Docs + Build Trace + System MCP (external data sources).
Simulator and the auto-patrol / alarm / rules / topology / fleet
modules are intentionally removed.

The two POC commits already exist on `origin/poc/skill-library` and are
designed to be cherry-pickable forward as `main` evolves:

| SHA (origin/poc/skill-library) | Purpose |
|---|---|
| `1d443ab` | `chore(poc): strip ontology_simulator from skill-library branch` |
| `965f74b` | `feat(poc-mcp): headers form + ${ENV} interpolation for external APIs` |

## When to invoke

- User says: "切一個 POC", "重新切 POC branch", "skill library POC", "POC 版本", "幫我從現在的 main 拉一份 POC".
- After main has accumulated unrelated changes and we want a fresh POC
  branch off the latest main — don't re-do this by hand, the cherry-pick
  path keeps the diff verifiable.
- Do NOT invoke when the user is asking about an *existing* POC branch
  — only for creating a new one.

## What this skill does

1. Sanity checks: working tree clean, on a branch, `origin/poc/skill-library`
   reachable.
2. Fetches `origin/poc/skill-library`.
3. Creates a new branch off `main` named
   `poc/skill-library-YYYYMMDD` (or whatever the user passes).
4. Cherry-picks the two canonical commits in order.
5. Reports conflicts (if any) and stops — does **not** try to auto-resolve.
6. On clean apply: pushes the branch and tells the user how DevOps pulls it.

Backup: the spawn script also creates a `git worktree` for the current
main into `../<repo>_main_backup_<timestamp>` so the user has a physical
read-only copy of main while iterating on the POC branch — same pattern
used the first time.

## Two paths

| Path | When to use | How |
|---|---|---|
| **Fast (cherry-pick)** — default | `main` hasn't deeply changed the files the POC touches (deploy scripts, FleetSimulatorClient, Java MCP form, sidecar mcp_proxy) | `bash .claude/skills/poc-skill-library/spawn.sh [new-branch-name]` |
| **Fresh (re-author)** | Cherry-pick conflicts in too many places — main has restructured the POC's blast radius | Open this SKILL.md and follow the **Manual recipe** at the bottom |

The script defaults to fast path. If cherry-pick hits a conflict it
aborts cleanly with file list — never silently leaves the repo half-merged.

## Verification after spawn

```bash
git log --oneline main..HEAD     # should show the 2 POC commits
git diff main --stat | tail -5    # ontology_simulator/ deletions + page.tsx +
                                  # _http_helpers.py expected
cd aiops-app && npx tsc --noEmit  # pre-existing e2e errors only
python -c "from python_ai_sidecar.pipeline_builder.blocks._http_helpers import resolve_headers; print(resolve_headers({'X': 'v'}, mcp_name='t'))"
```

If any of these fail, the POC won't deploy cleanly — investigate before
handing off.

## Hand-off to DevOps (copy-paste-ready)

```bash
# New EC2 / fresh clone:
git clone -b <new-branch-name> https://github.com/gillggx/ai-ops-agentic-platform.git /opt/aiops

# Existing /opt/aiops:
cd /opt/aiops && git fetch && git checkout <new-branch-name> && git pull

# Add external API secrets to sidecar env:
sudo vi python_ai_sidecar/.env   # add EXTERNAL_API_TOKEN=... etc.

# Stop the simulator unit if it's still running from main:
sudo systemctl stop ontology-simulator 2>/dev/null
sudo systemctl disable ontology-simulator 2>/dev/null

# Redeploy:
sudo bash deploy/java-update.sh   # Java + sidecar
sudo bash deploy/update.sh        # frontend (no simulator now)
```

## Known POC quirks (expected, not bugs)

- `process_history` + `rework_request` blocks still show in the Pipeline
  Builder catalog. Try-run yields `MCP_UNREACHABLE` — the signal that
  these blocks were simulator-only and should not be picked.
- `/topology` and any Fleet dashboard panels show empty state. The Java
  `FleetSimulatorClient` is stubbed to return empty lists so nothing
  crashes.
- `/admin/simulator-health` nav entry is gone.

These can be removed in a follow-up commit on the POC branch if needed
— see **Next-round cleanup candidates** below — but they don't block POC
demos.

## Next-round cleanup candidates

Not done in the canonical 2-commit POC because they widen the blast
radius. Use a third commit on the POC branch only if a demo will reach
these surfaces:

- Drop `process_history` + `rework_request` block sources + seed entries
  + a V** migration removing them from `pb_blocks`.
- Hide `/topology`, `/admin/fleet`, `/system/event-registry`,
  `/system/cron-jobs`, `/system/monitor` from nav.
- Strip L4 (auto-patrol / alarm / rules / SkillAlarmEmitter / scheduler)
  — see memory `project_v6_to_remove_list` for the existing TO-REMOVE
  inventory.

## Manual recipe (fresh path, only when cherry-pick fails badly)

Open `origin/poc/skill-library`'s two commit diffs as reference and
re-apply the categories below by hand:

1. **Remove** (git rm):
   - `ontology_simulator/` (entire directory)
   - `deploy/ontology-simulator.service`
   - `deploy/.env.ontology.template`
   - `deploy/kubernetes/components/ontology-simulator.yaml`
   - `aiops-app/src/app/admin/simulator-health/` (entire)
   - `aiops-app/src/app/api/admin/simulator-snapshot/route.ts`
   - `aiops-app/src/app/api/ontology/[...path]/route.ts`

2. **Edit** (drop simulator URLs / probes / restarts):
   - `deploy/update.sh` — drop ontology venv install + simulator restart + `wait_for_http` + summary line
   - `deploy/setup.sh` — drop venv_ontology + simulator Next.js build + mongodb install + 4-service → 3-service systemd loop
   - `deploy/java-update.sh` — comment about ontology in header / footer
   - `deploy/docker-compose.yml` — remove `ontology-simulator` + `mongodb` services + `MONGODB_URL` + `ONTOLOGY_SIM_URL` + `AIOPS_SIMULATOR_BASE_URL` + `AIOPS_MONITOR_HOST_ONTOLOGY_SIMULATOR` + `mongodata` volume
   - `deploy/nginx.conf` — drop `/simulator/`, `/simulator/_next/static/`, `/simulator/ws`, `/simulator-api/` blocks
   - `deploy/kubernetes/base/configmap.yaml` — drop `AIOPS_SIMULATOR_BASE_URL`, `ONTOLOGY_SIM_URL`, `MONGODB_URL`
   - `deploy/aiops-java-scheduler.env.example` — drop `ONTOLOGY_SIM_URL`
   - `java-backend/src/main/resources/application.yml` — drop `simulator:` block
   - `java-scheduler/src/main/resources/application.yml` — drop `simulator:` block
   - `aiops-app/src/components/shell/AppShell.tsx` — remove the Simulator Health nav entry
   - `aiops-app/src/app/admin/system-mcps/page.tsx` — change placeholder from `http://localhost:8012/...` to `https://api.example.com/v1/...`

3. **Stub** (keep file, replace body so callers still link):
   - `java-backend/src/main/java/com/aiops/api/api/fleet/FleetSimulatorClient.java` — all `fetch*` methods return empty
   - `java-scheduler/src/main/java/com/aiops/scheduler/patrol/SimulatorClient.java` — `listAllTools` + `listRecentEvents` return empty

4. **Edit** for the headers form (commit 2):
   - `aiops-app/src/app/admin/system-mcps/page.tsx`:
     - add `HeaderField` interface
     - add `headers: HeaderField[]` to `EditForm`
     - add `headers: []` to both `useState` init + `openNew()` reset
     - in `selectMcp()`, unpack `api_config.headers` object into form rows
     - add `buildApiConfig()` helper that packs form headers back into JSON
     - replace both `api_config: { endpoint_url, method }` literals with `api_config: buildApiConfig(form)`
     - add the "HTTP Headers (optional)" form section between Endpoint URL and Input 參數定義

5. **Add** the runtime helper:
   - `python_ai_sidecar/pipeline_builder/blocks/_http_helpers.py` with
     `resolve_headers(headers, *, mcp_name)` — `${NAME}` regex
     substitution from `os.environ`, raise `BlockExecutionError(INVALID_MCP_CONFIG)`
     naming any missing env vars.
   - `block_mcp_call.py` + `block_mcp_proxy.py` — call `resolve_headers`
     instead of reading `api_config.get("headers")` directly.

6. **Commit** as two commits matching the canonical messages so anyone
   diffing against `origin/poc/skill-library` sees a clean parallel.
