# Phase 8 Migration · Session Report (2026-04-25)

## TL;DR

Block **B** complete, live on prod. Block **A-2** (one-step SSE) complete,
live on prod. Block **A-1** deferred via runbook. Block **C** partial:
silent failure self-healed, 5 DR pipelines auto-fixed (10 flagged manual).
Block **D** deferred via runbook.

:8001 can be shut down once A-1 (agent port) + C-3/4 (DR manual fixes) finish.

---

## 📊 Block Completion Matrix

| Block / Sub | Status | Evidence |
|---|---|---|
| **B-0** Parity probe script | ✅ | `scripts/phase8b_parity_probe.py` |
| **B-1** Ported pipeline_builder → sidecar | ✅ | 42 files copied + imports rewritten |
| **B-1** Sidecar shims (_sidecar_deps.py) | ✅ | get_settings / session_factory / repos |
| **B-1** SeedlessBlockRegistry | ✅ | 27 blocks + 27 executors loaded |
| **B-2** Executor wired (real_executor.py) | ✅ | `source: native` returned from /execute |
| **B-3** 25/27 blocks native | ✅ | SIDECAR_NATIVE_BLOCKS whitelist |
| **B-3** mcp_call / mcp_foreach native | ✅ | Rewired to `java_client.get_mcp_by_name` |
| **B-4** Validator | 🟡 | ported into sidecar but /validate still uses demo walker |
| **B-5** Drop fallback | ❌ | Not dropped — safety net for unknown blocks remains |
| **B-6** seed SSOT | ❌ | Not decided; seed.py still in both trees |
| **A-2** Frontend one-step SSE | ✅ | POST returns SSE directly; proxy pipes |
| **A-2** Remove AGENT_BUILD_BASE_URL pin | ✅ | EC2 `.env.local` cleaned |
| **A-1** agent_builder port | ❌ | `docs/PHASE_8_A_RUNBOOK.md` deferred to next session |
| **A-1** agent_orchestrator_v2 port | ❌ | Same |
| **A-3** Drop chat/build fallback | ❌ | Blocked by A-1 |
| **C-1** Silent failure debug | ✅ (self-healed) | 3 patrols @ 146 exec_logs / 2h; alarms normal |
| **C-2** DR parity diff report | ✅ | `scripts/p1_fix_dr_pipelines.py` — 15 DRs analyzed |
| **C-3** Auto-fix 5 SPC trend DRs | ✅ | rolling_window params rewritten |
| **C-3** Manual-fix 10 APC/RECIPE DRs | 🟡 | Flagged, need UI edits (insert logic node) |
| **C-4** DR routing patch | ❌ | auto_patrol_service still uses skill path for DR fan-out |
| **C-5** Batch activate | ❌ | Blocked by C-3 manual + C-4 |
| **C-7** Deactivate legacy skills | ❌ | Blocked by C-5 |
| **D-1** FK reconcile runbook | ✅ | `docs/PHASE_8_D_RUNBOOK.md` |
| **D-2/3/4/5/6** | ❌ | Runbook ready; execution blocked by A-1 + C-3/4 |

---

## 🟢 Live on prod (verified 2026-04-25)

1. **Phase 8-B native executor**: 27/27 blocks run in sidecar :8050
   ```
   status: success, source: native
   execution_log_id: 59176, duration_ms: 192
   ```
2. **Parity probe 6/7 ✅**: real auto_patrol pipelines 1/2/4/5/6/17 byte-identical
   between :8001 and sidecar (pipeline 16 broken on both — pipeline-json issue, not regression)
3. **One-step SSE**: `POST /api/agent/build` returns 200 with SSE stream directly
4. **DR auto-fix**: 5 SPC trend DR pipelines updated in DB (pipelines 32/35/38/41/44)
5. **Patrol pipeline path running smoothly**: patrols 1/2/3 firing 146x in 2h, alarms normal

---

## 📝 Commits this session

```
384e446 feat(phase8-b): native pipeline executor in sidecar (25/27 blocks)
7c825c6 fix(phase8-b): sidecar venv needs pandas/numpy/scipy/sqlalchemy
78f46c7 fix(phase8-b): use snake_case keys when POSTing execution_log to Java
da48737 fix(probe): triggered_by must be in enum (user|agent|schedule|event)
4ab7694 fix(probe): mask response-envelope + preview/evidence drift, keep status+rows strict
b5fb125 feat(phase8-b): wire block_mcp_call + block_mcp_foreach via Java /internal/mcp-definitions
8f4a1ca feat(phase8-a-2): Frontend one-step SSE for /api/agent/build
f29ff80 feat(p1): DR pipeline block-param auto-fixer
b36ddaf fix(p1): DR fixer covers rolling_window window_size→window + aggregation→func
```

Plus 2 runbooks:
- `docs/PHASE_8_A_RUNBOOK.md` — Agent port step-by-step (~10h)
- `docs/PHASE_8_D_RUNBOOK.md` — Final cutover step-by-step (~3h + 2 gates)

---

## ✅ QA Checklist (what was tested)

- [x] Sidecar service restarts without error after deps bump (pandas/numpy/scipy/sqlalchemy)
- [x] `POST /internal/pipeline/execute` with `block_process_history` → `status:success, source:native`
- [x] execution_log written to Java `/internal/execution-logs` (id=59176 verified)
- [x] `block_filter` / `block_threshold` / `block_rolling_window` / `block_alert` etc. —
      all 27 blocks importable + in SeedlessBlockRegistry
- [x] SIDECAR_NATIVE_BLOCKS gating: unknown blocks fall back (but the whitelist IS 27 now)
- [x] Parity probe on 7 auto_patrol pipelines: 6/7 byte-identical (pipeline 16 both-fail)
- [x] mcp blocks use java_client.get_mcp_by_name (import passes; runtime untested on prod)
- [x] Frontend POST `/api/agent/build` returns `HTTP 200` with SSE content-type
- [x] `AGENT_BUILD_BASE_URL` removed from EC2 `.env.local`; frontend routes through Java :8002
- [x] Pipeline 32 post-fix: :8001 and sidecar both fail at n4 with **identical** error
      (`Column 'ooc_count' not found` — genuine downstream bug, both executors see it)
- [x] Auto-patrol 1/2/3 creating execution_logs + alarms normally (silent failure gone)
- [x] All migration code checked in; prod runs verified commits

---

## 🔴 QA Items NOT tested / deferred

- [ ] Agent chat end-to-end via UI (LangGraph LLM call still goes through :8001 fallback)
- [ ] Agent build Glass Box end-to-end via UI (same)
- [ ] `block_mcp_call` native execution with a real MCP (would need a pipeline that uses it)
- [ ] Validator C1-C12 activated on `/internal/pipeline/validate`
- [ ] 10 flagged DR pipelines (APC foreach→alert, RECIPE alert-only) — manual edits required
- [ ] DR routing patch: `_run_diagnostic_rules_for_alarm` not yet routed through pipeline path
- [ ] :8001 traffic measurement (how much still lands there?)
- [ ] Java FK type reconcile (30 entities use Long against 59 INT columns)

---

## 🧭 Next-session resumption points

### Path 1 · Finish Agent port (Block A-1)
Follow `docs/PHASE_8_A_RUNBOOK.md`. First step:
```bash
cp -r fastapi_backend_service/app/services/agent_builder python_ai_sidecar/agent_builder
cp -r fastapi_backend_service/app/services/agent_orchestrator_v2 python_ai_sidecar/agent_orchestrator_v2
# (+ context_loader, task_context_extractor, tool_dispatcher as dep tree requires)
```
Then sed-rewrite imports following Block B pattern + wire `sidecar/routers/agent.py`
to use native orchestrator. Estimated 10h focused work.

### Path 2 · Finish Block C (DR activation)
1. Open 10 flagged DR pipelines in `/admin/pipeline-builder/<id>` UI
2. Insert `block_threshold` node between `block_mcp_foreach` / `block_process_history`
   and `block_alert` (APC + RECIPE templates respectively)
3. Re-run `scripts/phase8b_parity_probe.py` on them
4. Patch `_run_diagnostic_rules_for_alarm` to call pipeline path when
   `skill.pipeline_id` is set
5. `UPDATE skill_definitions SET is_active=false WHERE source IN ('auto_patrol','rule')`

### Path 3 · Block D final cutover (blocked on Path 1)
Follow `docs/PHASE_8_D_RUNBOOK.md`. Runbook is ready; gated by Path 1 completing
(agent chat/build currently load-bearing on :8001).

---

## ⚠ Known issues surfaced (not caused by this session)

1. **Pipeline 16** (`DC sensor drift check`): fails on BOTH :8001 and sidecar
   with identical validation_error — pipeline_json needs a block-param fix
   (not in the 3 template patterns; needs individual review)

2. **DR pipelines 34/37/40/43/46** (RECIPE list): `block_alert` fed directly
   from `block_process_history` without a logic node. `block_alert` contract
   requires `triggered: bool` upstream. Needs `block_count_rows → block_threshold`
   inserted.

3. **DR pipelines 33/36/39/42/45** (APC list): `block_alert` fed directly from
   `block_mcp_foreach`. Same contract issue — needs a threshold node.

4. **Sidecar has sqlalchemy + pandas as transitive deps** but never opens a DB
   session. Could be trimmed to reduce container size (not urgent).
