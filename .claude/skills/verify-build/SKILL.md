---
name: verify-build
description: Run a builder test case (chat/builder/test mode) against EC2 prod sidecar, then surface a structured 3-section report — plan, stuck phase, that phase's round-by-round history — so Claude can discuss the failure without re-reading raw traces.
---

# verify-build

Wraps the existing UI-consistent verify harnesses + BuildTracer + trace_replay
into one report that's ready for diagnosis discussion.

## When to invoke

- User asks me to run a builder test case ("試跑一下", "verify this prompt", "...看看會怎樣")
- After a code change touching `goal_plan_node`, `agentic_phase_loop`,
  `phase_verifier`, `phase_revise_node`, or any block's `produces.covers`.
- When the user asks "卡在哪？" / "為什麼失敗？" — re-run and surface the
  stuck phase + verifier verdicts (cheaper than reading the full trace).

## Modes

| Mode | What it does | Uses |
|---|---|---|
| `chat` | POST `/internal/agent/chat`, auto-confirm `design_intent_confirm` card via `[intent_confirmed:CARD]` follow-up. | `tools/ui_consistent_verify/chat_walkthrough.py` |
| `builder` | POST `/internal/agent/build` directly (no intent gate — Builder Glass Box path). | `tools/ui_consistent_verify/builder_verify.py` |
| `test` | Replay a single LLM call from a saved trace under variants. For "would changing X have changed the LLM pick?" experiments. | `python -m tools.trace_replay` |

## Output

- **stdout (text)**: structured Plan / Phase / Attempt report rendered by
  `python_ai_sidecar.agent_builder.graph_build.trace_summary`. Same model
  powers the `/admin/build-traces` Summary tab.
- **--json-out PATH**: full trace_summary JSON for follow-up analysis.

## When user asks "為什麼 phase X 失敗 / 卡在哪 / 為何選 Y block?"

Don't just dump the round table. Do a **narrative reconstruction** in this
fixed format so we discuss the failure with the same shape every time:

```
## Phase pN reconstruction — call <start>→<end>

### Entry canvas
  <list nodes + edges agent saw when entering this phase>

### Agent actions

call N  <tool>(<args summary>)
        ↳ what agent saw in the tool_result: <one-line>
        ↳ what agent did next: <one-line>
        ↳ verdict (if verifier ran): <ADVANCED|REJECTED — reason>

(repeat for each call)

### Where it went wrong (layered)

| # | Layer | Detail |
|---|---|---|
| 1 | <agent hallucination / wrong block pick / loop> | <what + why> |

### What agent saw at the decision point

Pull the FULL user_msg for the round where the bad decision happened
(usually a commit_pick or add_node). Show:
- which sections were present (canvas / MATCHING BLOCKS / verifier feedback / doc)
- which sections were MISSING that should have been there
- the LLM's own reasoning text (raw_response) — what was its mental model?

### Fix options

Numbered + cross-referenced to which layer they attack:

| # | fix | attacks |
|---|---|---|
| a | <change> | Layer 1 |
| b | <change> | Layer 2 |
```

This format makes failure root causes legible across runs and lets us
decide which layer to attack first. The flat round table can't show
"agent never inspected upstream so it hallucinated output shape" — only
narrative does.

### When to use narrative vs flat report

- **Flat Summary** (default skill output) → "how far did the build get? which phases passed?"
- **Narrative reconstruction** (this section) → "why did agent pick wrong / loop / give up?"

For investigation questions, always do narrative. Pull the actual prompts +
LLM raw_response text via the trace JSON (`llm_calls[i].user_msg` and
`llm_calls[i].raw_response`).

## Invocation

The slash command `/verify-build` is the entry point. It accepts:
- A user message (chat/builder modes): the prompt to feed the builder.
- `--mode chat|builder|test` (defaults to `chat`).
- `--trace PATH` + optional `--target` / `--variants` / `--reps` (test mode).

The skill runner SSH's into EC2 (path: `~/Desktop/ai-ops-key.pem`, host:
`ubuntu@aiops-gill.com`) because (a) the sidecar isn't publicly exposed and
(b) BuildTracer writes traces to EC2's `/tmp/builder-traces/`.

## Env overrides

```
AIOPS_SSH_KEY       path to PEM (default ~/Desktop/ai-ops-key.pem)
AIOPS_SSH_HOST      ssh target (default ubuntu@aiops-gill.com)
AIOPS_REMOTE_REPO   remote repo path (default /opt/aiops)
```

## Examples

```bash
# Quick chat-mode run
python3 .claude/skills/verify-build/run.py \
  --mode chat \
  --message "檢查 EQP-01 最後一次 OOC，畫該批次 SPC chart"

# Builder mode + capture JSON for later analysis
python3 .claude/skills/verify-build/run.py \
  --mode builder \
  --message "fetch lot LOT-0001 last 7 days, show xbar chart" \
  --json-out /tmp/verify-builder.json

# Replay a saved trace's last LLM call under 3 variants × 3 reps
python3 .claude/skills/verify-build/run.py \
  --mode test \
  --trace /tmp/builder-traces/20260517-111441-a81eb1932fce.json \
  --target 'agentic_phase_loop:phase=p3:round=2' \
  --variants identity inject_matched_connect_options \
  --reps 3
```
