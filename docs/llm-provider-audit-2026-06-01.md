# LLM Provider Audit — 2026-06-01

3-way comparison of Anthropic Claude vs OpenRouter alternatives on the
Pipeline Builder Glass Box agent (`/internal/agent/build`).

## Motivation

Anthropic API bill (separate from Claude Code Max subscription) became a
standing cost concern. We needed data on whether OpenRouter-hosted open
models can replace Claude Haiku 4.5 as the default LLM for the builder
agent — chat orchestrator v2, Block Advisor, and Glass Box builder all
share the same `python_ai_sidecar/agent_helpers_native/llm_client.py`,
so a clean env-flip suffices for prod replacement.

## Methodology

17 slash command tpls drawn verbatim from
`aiops-app/src/components/pipeline-builder/SlashCommandMenu.tsx`
(10 SPC + 3 APC + 4 patrol). Each fired against `/internal/agent/build`
with `v30Mode=true, skillStepMode=false, skip_confirm=true`, traces
captured via `BuildTracer` → `/tmp/audit-runs/<model>/<case>.json`.
Driver: `/tmp/slash-audit-multi.sh` (multi-model variant of
`slash-audit.sh`). Sequenced by `/tmp/audit-orchestrator.sh`.

Models:

- **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) — current prod default
- **Kimi K2.5** (`moonshotai/kimi-k2.5` via OpenRouter)
- **Qwen3-235B-A22B** (`qwen/qwen3-235b-a22b` via OpenRouter)

All three runs executed back-to-back on EC2 (same sidecar, same code,
same simulator data) on 2026-06-01 20:28 — 2026-06-02 01:15 CST.

## Results

### Reliability and quality

| Metric | Claude Haiku 4.5 | Kimi K2.5 | Qwen3-235B |
| --- | --- | --- | --- |
| Reached terminal state (finished + handover_pending) | 17/17 | 16/17 | 17/17 |
| **Actually finished** | **16/17 (94%)** | 12/17 (71%) | 8/17 (47%) |
| Has chart block in final pipeline | **16/17 (94%)** | 13/17 (76%) | 12/17 (71%) |
| Outright failed | 0 | 1 (spc-multi-step) | 0 |
| handover_pending (stuck on verifier deficit) | 1 | 4 | 9 |
| Chart-block matches Claude's choice | — | 11/17 | 8/17 |

`handover_pending` means the build paused awaiting user clarification
(verifier deficit card). For an automated audit measuring "did the
model produce a working chart pipeline end-to-end", these count as
non-completions even though the partial pipeline exists.

### Speed

| Metric | Claude | Kimi | Qwen |
| --- | --- | --- | --- |
| Avg duration per case | **82s** (1.4 min) | 363s (6.1 min) | 477s (8.0 min) |
| Total wall-clock for 17 cases | 23 min | 103 min (**4.5×**) | 135 min (**5.9×**) |
| LLM calls per case | 25.5 | 22.9 | 28.6 |
| Avg LLM call latency | **3.2s** | 15.9s (**5×**) | 16.7s |

Call counts are similar across models (Kimi slightly fewer than
Claude). The latency gap is per-call.

### Token economics — root cause of the speed gap

| Metric | Claude | Kimi | Qwen |
| --- | --- | --- | --- |
| Total input tokens (17 cases × ~25 calls) | **2,180** | 6,308,028 | 10,099,224 |
| Average input per call | ~5 tok | **16.2k tok** | 20.8k tok |
| Total output tokens | 93,324 | 102,842 | 363,629 |

**Anthropic prompt caching is doing ~95% of the work.** The first
build-LLM call writes the ~16-20k system prompt + tool catalog to
the 5-minute cache; subsequent calls within the window pay only the
user-message delta. Trace-reported input tokens drop to ~5 per call.

OpenRouter does not transparently cache prompts for Kimi / Qwen — every
call re-sends 16-20k tokens. The 5× latency gap is not "Kimi inference
is 5× slower than Haiku"; it's "every call carries 16k more bytes of
input that have to traverse network + re-parse + re-embed".

### Where chart-block choices diverge

| Case | Claude | Kimi | Qwen |
| --- | --- | --- | --- |
| spc-trend | line_chart | xbar_r | spc_panel |
| spc-ooc | — | data_view | data_view |
| spc-cpk | line_chart | line_chart | — |
| spc-multi-tool | line_chart | line_chart | spc_panel |
| spc-multi-step | xbar_r | (failed) | spc_panel |
| apc-drift | ewma_cusum | — | — |
| apc-trend | line_chart | line_chart | — |
| ooc-ranking | pareto | — | — |
| ooc-pareto | bar_chart | — | — |

Qwen frequently substitutes `block_spc_panel` (general SPC panel) for
the more specific block Claude picks (`block_xbar_r`, `block_line_chart`).
Defensible choice but cruder.

## Cost interpretation

OpenRouter per-token list price is meaningfully cheaper than Anthropic,
but the **per-task** cost difference shrinks once you account for:

1. **Lost prompt cache** on OpenRouter: 16k input × 25 calls × 17 cases
   = 6.3M tokens uncached for Kimi, vs 2k tokens uncached for Claude.
2. **Longer builds** on OpenRouter consume more reasoning tokens, more
   verifier passes, and more developer wall time waiting.
3. **Lower chart success** means a percentage of "saved" runs are
   actually unusable and the user retries — burning the saved cost.

Rough per-task cost (single SPC trend build):

- Claude Haiku 4.5: ~25 calls × (5 input + ~3700 output avg) tokens
  ≈ $0.02 at list price after cache.
- Kimi K2.5 via OpenRouter: ~23 calls × (16k input + ~4500 output avg)
  ≈ $0.05–$0.10 depending on OpenRouter spread.
- Qwen3-235B via OpenRouter: ~29 calls × (21k input + ~21k output avg)
  ≈ $0.15–$0.30 (reasoning tokens balloon).

For the production workload as it stands today, **Claude Haiku 4.5 is
both faster and competitively priced**.

## Recommendations

### Production default

Keep `LLM_PROVIDER=anthropic` with `claude-haiku-4-5-20251001` as the
prod default for `python_ai_sidecar`. Rotate the API key (the prior
key was active for an extended period across multiple environments —
see `feedback_cost_control_llm`).

### Cost control on Anthropic, not provider switch

Cheaper to control consumption than swap vendor:

1. **Per-user / per-day build quota** on `/internal/agent/build`.
2. **Aggressive prompt-cache reuse** — keep system prompt + tool catalog
   byte-identical across calls within a session. Any drift invalidates
   the 5-min cache and re-bills the full prefix.
3. **Disable expensive knobs by default** — `reasoning.effort=high`
   on the gpt-oss path cost ~12 min/build for marginal quality gain.

### Fallback strategy

Wire Kimi K2.5 as a documented fallback (Anthropic outage / key
incident). Quality acceptable for the 11/17 chart-matched cases;
the spc-multi-step failure mode and 4 stuck handovers should be
re-tested before treating Kimi as production-ready.

Do **not** wire Qwen3-235B as a fallback. 9/17 stuck on
handover_pending, 8/17 truly finished, slowest of the three. Open
question whether different prompt shape (no tool-use chaining,
single-shot plan) would help; not the right shape for the current
agentic loop.

### Pre-conditions to revisit OpenRouter as default

The 5× Kimi gap closes meaningfully if either of these ships:

1. **System prompt + tool catalog shrunk to ~5k tokens** via
   RAG-style lazy lookup (see memory `project_rag_for_llm_lookups`).
   Predicted Kimi latency 5–8s/call, total ~2.5–3 min/build.
2. **LLM call count reduced from ~25 to ~12-15/build** by batching
   small reasoning steps and converting more verifier work to
   deterministic checks.

With both, expected Claude vs Kimi delta drops from 5× to ~1.5×,
at which point the OpenRouter price spread becomes net-positive.

## Artifacts

All trace JSONs preserved on EC2:

- `/tmp/audit-runs/claude-rebaseline/` — 17 files, results.tsv
- `/tmp/audit-runs/kimi/` — 17 files, results.tsv
- `/tmp/audit-runs/qwen/` — 17 files, results.tsv
- `/tmp/audit-3run-final.py` — tabulation script
- `/tmp/audit-orchestrator.sh` + `/tmp/slash-audit-multi.sh` — drivers
