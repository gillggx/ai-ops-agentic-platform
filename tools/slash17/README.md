# SLASH-17 builder regression harness

Runs all 17 production slash commands end-to-end through the v30 builder
(against the **local** sidecar on the host) and grades each result against a
hand-authored golden block-set. Completeness-first: graded vs golden, not just
"did it finish".

This is the harness used for the 2026-06 cost/accuracy work. It runs **on the
EC2 host** because the sidecar isn't publicly exposed and BuildTracer writes to
the host's `/tmp/builder-traces/`.

## Files

| file | what |
|---|---|
| `slash17_driver.py` | POSTs each of the 17 commands to `/internal/agent/build` (+ auto plan-confirm), captures status / nodes / terminal blocks per case. Reads `SVC_TOKEN`, `SIDECAR_BASE`, `OUT_FILE` from env. |
| `grade_strict.py` | Compares a run's per-case blocks to golden block-sets → MATCH / UNDER / OVER / WRONG / FAIL + node/round counts. |
| `run.sh` | Wrapper: runs the driver, writes `s17_<label>.{json,log,window}`. **Requires `SVC_TOKEN` in env — never hardcode it.** |

## Run

```bash
# on the EC2 host, sidecar live on :8050
export SVC_TOKEN=...            # from python_ai_sidecar/.env (X-Service-Token)
bash tools/slash17/run.sh mylabel
python3 tools/slash17/grade_strict.py mylabel
```

Env overrides: `SIDECAR_BASE` (default `http://localhost:8050`), `PYTHON`
(default `/opt/aiops/venv_sidecar/bin/python`), `RESULTS_DIR` (default `/tmp`),
`TRACE_DIR` (default `/tmp/builder-traces`).

## Golden notes — test cases are part of the contract

A failing grade is a **hypothesis**, not a verdict — rule out KIMI run-to-run
variance and simulator data gaps before blaming the agent. Some goldens encode
deliberate test-case corrections (2026-06-22) where the command itself, not the
agent, was wrong:

- **spc-xbar-r-pair** → command is **"X-bar 管制圖（含 WECO）"**, not the old
  "X-bar/R 對偶". The simulator's `process_history` exposes pre-aggregated SPC
  chart values (subgroup n=1), so the **R chart can't be computed** — the dual
  ("對偶") ask was unconstructible from this data. With it dropped, the agent
  correctly picks the dedicated `block_xbar_r`. Golden = `…+xbar_r`.
- **patrol-status** → golden is `{list_objects, data_view}` (fleet current
  snapshot), not `process_history` (single-tool history).
- **ooc-pareto** → both `block_pareto` AND `sort+bar_chart` are correct; the
  grader accepts either via `ALT[]`.

See `docs/history/PROJECT_HANDOFF.md` (2026-06 entries) for the full triage.
