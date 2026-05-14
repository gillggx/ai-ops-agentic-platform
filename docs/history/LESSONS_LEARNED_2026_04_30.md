# Lessons Learned — 2026-04-30 Session

A single 8+ hour session shipping the pipeline-mode auto-patrol /
auto-check end-to-end. Most of the time was spent NOT writing the
feature but discovering that the feature didn't reach the user
because of silent drift between layers. This doc captures the
patterns so the next contributor doesn't repeat them.

---

## 🚨 Theme 1: Hidden drift between parallel registries

The codebase has many "register the same thing in N places" patterns.
Every miss is silent until the broken code path runs.

### Block registration — 5 places (we discovered the 5th the hard way)

Adding one block requires:

1. `pipeline_builder/blocks/<x>.py` — executor implementation
2. `BUILTIN_EXECUTORS` dict in [`blocks/__init__.py`](python_ai_sidecar/pipeline_builder/blocks/__init__.py) — runtime registry
3. `SIDECAR_NATIVE_BLOCKS` frozenset in [`real_executor.py`](python_ai_sidecar/executor/real_executor.py) — native fast-path whitelist
4. `pb_blocks` DB row (Flyway / manual seed) — catalog visible to LLM
5. **`seed.py:_blocks()` entry** — `SeedlessBlockRegistry` source (drives `execute_native` runtime)

Miss #3 → patrol fan-out 500s in legacy walker.
Miss #5 → `"No executor registered for block_X@1.0.0"` at execute_native.

**Mitigation shipped:** [`_boot_invariants.py:check_block_consistency`](python_ai_sidecar/_boot_invariants.py)
diffs all 5 sources at startup and ERROR-logs any drift. See
`block consistency OK: 29 builtin, 29 native, 29 in seed, 29 in DB`
in sidecar startup logs.

### State field plumbing — 6 layers

Adding `mode` + `pipeline_snapshot` from chat panel → Glass Box sub-agent
required updates at:

1. Frontend `AIAgentPanel.tsx` send body
2. **Java `AgentProxyController.ChatRequest` record + handler** ← we missed this
3. Sidecar `routers/agent.py:ChatRequest` Pydantic
4. Sidecar `orchestrator.py:run()` kwargs
5. **Sidecar `graph.py:GraphState` TypedDict** ← we missed this too
6. Node `state.get(...)` consumers

Miss #2 → Java silently dropped fields when re-marshalling ChatRequest.
Miss #5 → LangGraph stripped any state key not declared in TypedDict.

**Mitigation shipped:** [`_boot_invariants.py:assert_graph_state_covers_run_kwargs`](python_ai_sidecar/_boot_invariants.py)
fails import if `orchestrator.run()` passes a key `GraphState` doesn't
declare. The Java side has no equivalent yet — TODO if it bites again.

### Lesson

**When N places must agree, expect drift. Add a boot-time invariant
check, not docs.** Documentation explaining the 5 places didn't stop
us missing place 5. The Python-side check catches the next miss in
~5 seconds at boot.

---

## 🔍 Theme 2: Verify what's actually wired before editing

### Two implementations, one route

`/alarms` route used [`src/app/alarms/page.tsx`](aiops-app/src/app/alarms/page.tsx)
(Master-Detail v2). [`src/components/operations/AlarmCenter.tsx`](aiops-app/src/components/operations/AlarmCenter.tsx)
was the v1 modal — never imported anywhere. We spent ~90 minutes
shipping all the alarm-content / banner / data-view rendering fixes
into the v1 file, then watched the user's browser show none of them.

**Rule:** before editing a UI component, grep its import path:
```
grep -rln "import.*<Component>" src/
```
Or better, check the route file (`app/<route>/page.tsx`) and follow
its actual imports.

After ruthless removal (commit `5e55d8c`), there's now exactly one
alarm UI file in the repo.

### "Deploy didn't take"

Two failure modes seen this session:

- `update.sh` has a "git diff HEAD@{1} HEAD" check that returns empty
  if there were no aiops-app changes since the last pull. Manual edits
  on EC2 outside git get skipped. Workaround: `--force-rebuild`.
- Stale `next/` dir means BUILD_ID mtime is misleading.

**Rule:** when something "should be deployed but isn't visible," check:
1. `ls -la .next/BUILD_ID` mtime ≥ last commit timestamp
2. `grep <new-string> .next/static/chunks/...` actually contains
   your change
3. Compare the chunk path to which file your route imports

### Default-config landmines

- **Spring WebClient `maxInMemorySize`: 256 KiB** — pipeline responses
  with `block_data_view` rows or full process_history dumps blow
  through this. Result: HTTP 200 with `DataBufferLimitException`
  silently aborting parsing → caller sees empty body → "auto-check
  binding broken" misdiagnosis.
  *Fix:* explicit 16 MiB on every WebClient.builder() in patrol code.

- **LangGraph `recursion_limit`: 25** — too tight for builder turns
  involving `update_plan + build_pipeline_live + auto-run + retry`.
  Hit limit → opaque error in browser.
  *Fix:* explicit 60 in [`orchestrator.py`](python_ai_sidecar/agent_orchestrator_v2/orchestrator.py).

- **Flyway in prod: `enabled: false`** — every V<N> migration after
  the cutover needs manual `psql -f` + insert into
  `flyway_schema_history`. Easy to forget. There's no warning at
  startup. (V5, V6, V7 all caught us.)

- **Wizard input suggestions: missing `example` field** — `required=false`
  + no example + no default ≠ "optional"; means
  `_resolve_inputs` resolves `$step` → None → block.require()
  raises MISSING_PARAM. *Fix:* every suggestion now ships an example.

### Lesson

**Defaults from frameworks were tuned for generic web apps. When
your data shape exceeds the assumption, set values explicitly with
a comment explaining why.** Don't rely on "the default just works."

---

## 🎯 Theme 3: Trust the right signal

### "Alarm exists" IS proof of triggering

The detail UI used `findings.condition_met` as the "did it fire?"
flag. But:
- `findings` came from legacy DR/skill flow.
- Pipeline-mode alarms have no `condition_met` field — `findings`
  is the raw `execution_log.llm_readable_data` JSON.
- `condition_met === undefined` → falsy → banner showed "🟢 條件未達成"
- ...on an alarm row that IS in the DB BECAUSE the pipeline triggered.

**Rule:** for displaying state, use the **most authoritative signal**.
An alarm row's existence is unimpeachable proof; downstream
findings.X flags are derived data and may be missing in new code paths.

### Pipeline output is the canonical alert content

`block_alert` emits a templated title/message DataFrame. Java's
`writeAlarm` ignored it and stored `result_summary` as a JSON dump
in `summary`. Result: alarm summary was an unreadable JSON blob.

**Fix shipped:** sidecar's `_build_result_summary` now emits an
`alerts: [...]` field; Java's `writeAlarm` picks `alerts[0].title /
.message / .severity` and falls back to patrol-level fields only
when absent. The user-authored template is now what the user sees.

### `@Transactional` defers FK errors to commit time

`AutoCheckExecutor.executeAutoCheck` had:
```java
@Transactional
public void executeAutoCheck(...) {
    ...
    try {
        alarmRepo.findById(sourceAlarmId).ifPresent(a -> {
            a.setDiagnosticLogId(runId);
            alarmRepo.save(a);   // ← does NOT throw here
        });
    } catch (Exception ex) {
        log.warn(...);  // ← never fires
    }
}
```

The `save()` only buffers the write. The actual SQL runs at
commit, which is *outside* the try-catch. So the FK violation
was logged at the @Transactional boundary's exception handler, not
where we expected.

**Lesson:** with JPA + @Transactional, try-catch around individual
saves doesn't catch commit-time integrity violations. Either drop
`@Transactional`, use `flush()` to force the SQL inside the try,
or catch at the outer (Spring-managed) boundary.

### `str.format()` partial substitution

`tpl.format(**row)` aborts on the first KeyError. So a template
`"機台 {toolID} 最近5次有 {count} 次OOC"` rendered against a row
that has `count` but not `toolID` returns the entire template
*unchanged* — `{count}` stays literal even though the data was
present.

**Fix shipped:** `block_alert._render_template` now uses regex
to substitute keys present in the row and leave unknown
placeholders intact for downstream layers (Java's
`fillPlaceholdersFromTarget` finishes the job).

---

## 🛠 Theme 4: Migrations leave stale FKs / type mismatches

### `alarms.diagnostic_log_id` FK to `execution_logs`

Set during the legacy diagnostic_rules era. Phase C moved auto_check
runs to `pb_pipeline_runs` (different table). The FK persisted. Backlinking
the diagnostic run id to the alarm threw:

```
ERROR: insert or update on table "alarms" violates foreign key
constraint "alarms_diagnostic_log_id_fkey"
Detail: Key (diagnostic_log_id)=(1217) is not present in
table "execution_logs".
```

**Fix shipped:** V7 migration drops the FK. The id can land in
either table; application-layer lookup tries both. `execution_log_id`
keeps its FK (always points at execution_logs).

### `Integer` vs `Long` for entity ids

`PipelineRunRepository extends JpaRepository<PipelineRunEntity, Long>` —
not Integer, despite some adjacent code using Integer for similar
sequence ids. Caught at compile time, but only after a deploy.

**Lesson:** when wiring a new repository call, look up the actual
generic type — don't assume from neighboring code.

---

## 🪞 Theme 5: Verify like a user, not like the writer

**The most expensive mistake of the session was repeated false-positive
"done" declarations** — claiming a fix shipped while the user's browser
showed it didn't. Three concrete instances:

1. "Builder mode prompt fixed" — actually broken because `GraphState`
   silently dropped the kwargs. Never tested with an actual chat
   request before declaring done.
2. "Alarm UI fixed" — shipped to `AlarmCenter.tsx` while the route
   used `app/alarms/page.tsx`. Never grepped the import path.
3. "Frontend deployed" — `update.sh` skipped the rebuild silently.
   Never grepped the built chunks for the new strings.

Each time the user had to take a screenshot before I noticed.

### Rule: declare-done has prerequisites

Before saying "✅ done" / "fixed":

| Change kind | Mandatory check |
|---|---|
| Frontend component edit | `grep <new-string> .next/static/chunks/.../app/<route>/page-*.js` — if 0 hits, you edited the wrong file or didn't rebuild |
| Backend API field addition | `curl` the user-facing endpoint with auth, `python3 -c "..."` parse the response, assert new field present |
| New block / new state field | Boot-time invariant log shows expected count |
| DB linkage write | `SELECT ... FROM <table> WHERE <recent>` — confirm value populated |
| Service restart claimed | `systemctl show -p ActiveEnterTimestamp` ≥ deploy time |

These checks take 30 sec - 2 min total. The cost of skipping them was
multiple round-trips with the user this session.

### Rule: grep import path before editing any UI component

```
grep -rln "import.*<Component>" src/
```

If two paths show up, the component is shared — verify your edit lands
in the right one. If one path shows up, confirm that path is what the
route loads. The 30-second grep would have saved 90 minutes today.

### What we don't have (and the cost of not having it)

A headless browser test loop (Playwright) is the only true
user-visible verification mechanism. We didn't build one this session —
each fix took a reload-screenshot-feedback cycle from the user. For
the next high-stakes UI change, building one is probably worth the
hour. For a one-shot fix, the chunk-grep + curl-parse pair from
above catches ~80% of the same bugs at 5% of the cost.

---

## 📌 Quick checklist for the next contributor

Before declaring "done":

- [ ] If you added a state field, did you trace it through every
      layer (FE → proxy → router → state schema → graph → consumer)?
- [ ] If you added a block, did the boot invariant log
      `block consistency OK: N builtin, N native, N in seed, N in DB`?
- [ ] If you edited a UI component, did you grep its import path
      to confirm the route actually uses it?
- [ ] If you "deployed," does `BUILD_ID` mtime exceed your commit
      timestamp AND does the chunk grep show your new strings?
- [ ] If you added a Flyway migration, did you `psql -f` it on prod
      and insert into `flyway_schema_history`?
- [ ] If you added a default-laden framework call (WebClient,
      LangGraph, etc.), are the limits set explicitly with a comment?
- [ ] If you wired alarm/run linkage, did you check that the FK
      target table matches the writer (or that there's no FK)?
- [ ] If you added template substitution, can missing keys leave
      placeholders intact for downstream layers?

---

## Commits referenced

- `bdae3a5` SIDECAR_NATIVE_BLOCKS missing entries
- `0d54080` Java proxy ChatRequest missing fields
- `e44e2b1` GraphState TypedDict missing keys
- `ba5ea5d` `_boot_invariants.py` (Theme 1 mitigation)
- `7a678e4` seed.py 5th-place miss
- `cc0b862` wizard suggestions missing `example`
- `fd9b06f` patrol input_binding NULL fallback only set tool_id
- `afee974` WebClient 256KB buffer + missing `alerts` in result_summary
- `09e0b84` alarm.execution_log_id / diagnostic_log_id linkage
- `09fd2b4` V7 drop stale FK
- `b7633f2` data_view rendering (initial — wrong file)
- `61a1036` banner triggered logic (initial — wrong file)
- `39dc6d9` block_alert partial template substitution
- `ee8f943` ALARM UI — moved to the actual `app/alarms/page.tsx`
- `5e55d8c` deleted dead `AlarmCenter.tsx`
