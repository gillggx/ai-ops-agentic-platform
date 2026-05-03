# Agent Eval Harness

End-to-end regression test suite for the LangGraph chat orchestrator + Glass
Box build orchestrator. Hits the live sidecar, captures SSE events, runs
scorers, compares against `baseline.json`.

## Quick start

```bash
# Set up (once per shell): SSH tunnel to prod sidecar
ssh -i ~/Desktop/ai-ops-key.pem -fN -L 18050:127.0.0.1:8050 ubuntu@43.213.71.239

# Run all suites against prod
SIDECAR_URL=http://127.0.0.1:18050 \
SIDECAR_TOKEN=<service_token> \
python3 -m tests.agent_eval.runner

# Run one suite
python3 -m tests.agent_eval.runner --suite builder_advisor_explain

# Accept current results as new baseline
python3 -m tests.agent_eval.runner --update-baseline
```

Exit code: `0` if no regressions vs baseline, `1` if regressions found.

## Layout

```
tests/agent_eval/
  runner.py                           # CLI: load YAML → POST sidecar → score → report
  scorers.py                          # 8 composable scoring functions
  scenarios/
    builder_intent_7bucket.yaml       # Builder Glass Box classifier sanity (12)
    builder_advisor_explain.yaml      # advisor EXPLAIN happy path (4)
    builder_advisor_compare.yaml      # advisor COMPARE happy path (3)
    builder_advisor_recommend.yaml    # advisor RECOMMEND happy path (4)
    chat_intent_5bucket.yaml          # Chat orchestrator classifier sanity (5)
    knowledge_no_tools.yaml           # KNOWLEDGE bucket guarantees (2)
  baseline.json                       # last accepted run — committed
  reports/                            # per-run JSON + text — gitignored
```

## Scorer reference

| Scorer | YAML key | Description |
|---|---|---|
| `http_ok` | (always on) | HTTP must be 2xx |
| `sse_event_types_include` | `sse_event_types_include: [type1, ...]` | All listed types must appear |
| `sse_event_types_exclude` | `sse_event_types_exclude: [type1, ...]` | None of listed types may appear |
| `advisor_kind` | `advisor_kind: explain\|compare\|recommend\|ambiguous` | First advisor_answer's kind matches |
| `answer_contains_any` | `answer_contains_any: [keyword1, ...]` | Markdown answer contains ≥1 keyword |
| `candidates_include_any` | `candidates_include_any: [block_xxx, ...]` | RECOMMEND output includes ≥1 expected block |
| `block_name_equals` | `block_name_equals: block_xxx` | EXPLAIN's block_name matches |
| `min_event_count` | `min_event_count: 3` | At least N SSE events received |

Add new scorers by appending to `ALL_SCORERS` in `scorers.py`.

## Adding a new scenario

```yaml
# scenarios/my_suite.yaml
suite: my_suite
endpoint: /internal/agent/build         # or /internal/agent/chat
description: |
  What this suite covers.
default_body: {}                         # body fields applied to every case

cases:
  - id: my_case_001
    description: human-readable
    input:
      message: "user input string"        # auto-translated to `instruction:` for /agent/build
    expect:
      sse_event_types_include: [advisor_answer]
      advisor_kind: explain
      answer_contains_any: ["expected", "keywords"]
```

## Baseline workflow

1. Make a change (prompt / graph / classifier).
2. `python3 -m tests.agent_eval.runner` — exits 1 if regressions vs baseline.
3. If the new behavior is intended → `--update-baseline` + commit the new
   `baseline.json` alongside the code change. PR review now diffs both.
4. If unintended → revert / fix.

## Known baseline failures (2026-05-03)

These are real bugs surfaced by the harness on first run, accepted as
baseline so we can detect *regressions* without blocking. Track + fix:

- **`builder_intent_7bucket :: recommend_001`** — "我有 SPC data 想看異常點"
  → advisor recommends `block_chart`/`block_process_history`/`block_spc_long_form`
  instead of SPC family (xbar_r/imr/ewma_cusum). Cause: legacy mega-block
  `block_chart`'s description still wins on substring score over the
  enriched dedicated SPC blocks. Fix needs deprioritising
  `status='deprecated'` blocks in `advisor.graph._score_block_for_keywords`.

- **`builder_intent_7bucket :: knowledge_001` + `knowledge_no_tools :: weco_r5` + `cpk_definition`** —
  KNOWLEDGE-class messages on `/internal/agent/build` get classified as
  EXPLAIN/COMPARE by the **advisor's own classifier** (which has 5 buckets:
  BUILD/EXPLAIN/COMPARE/RECOMMEND/AMBIGUOUS — no KNOWLEDGE bucket). The
  chat orchestrator's classifier DOES have a knowledge bucket and routes
  correctly. Two-classifier inconsistency. Fix needs adding KNOWLEDGE
  bucket to `agent_builder.advisor.classifier`.

Both are tracked in [docs/AGENT_BACKLOG.md](../../docs/AGENT_BACKLOG.md) for
follow-up.

## CI integration (TODO)

Future: GitHub Actions runs this on PR with `EVAL_MOCK_LLM=1` to use
fixture replay (no real LLM cost). Today: manual run pre-deploy.
