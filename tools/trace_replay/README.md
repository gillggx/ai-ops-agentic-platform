# trace_replay

Replay an LLM call from a build trace under controlled variants. Pairs
with `BuildTracer` (see [graph_build/trace.py](../../python_ai_sidecar/agent_builder/graph_build/trace.py)).

**Purpose**: when LLM in `agentic_phase_loop` (or `goal_plan` / `phase_revise`)
picks something we didn't expect, this tool lets you test "would changing
X have changed the pick?" empirically — without re-running the whole build.

## Usage

```bash
# List all LLM calls in a trace
python -m tools.trace_replay --trace /tmp/builder-traces/xxx.json --list-calls

# Replay the last LLM call with default control variant (identity)
python -m tools.trace_replay --trace /tmp/builder-traces/xxx.json

# Replay a specific phase-loop round under multiple variants, 3 reps each
python -m tools.trace_replay \
  --trace /tmp/builder-traces/xxx.json \
  --target agentic_phase_loop:phase=p1:round=1 \
  --variants identity enrich_catalog_brief rewrite_phase_goal_generic prepend_oneblock_solutions \
  --reps 3 \
  --out /tmp/replay_results.json
```

## Built-in variants

| Name | What it does |
|---|---|
| `identity` | Pass-through (control). |
| `enrich_catalog_brief` | Adds `[1-BLOCK covers N: ...]` prefix to composite blocks (covers ≥ 2). |
| `rewrite_phase_goal_generic` | Strips `process_history` / `spc_summary` / `block_xxx` tokens from CURRENT PHASE goal text. Tests whether goal-text leakage anchors LLM. |
| `prepend_oneblock_solutions` | Prepends a server-detected "== 1-BLOCK SOLUTIONS ==" section listing composite blocks that fast-forward through current + upcoming phases. |

## Writing a new variant

Each variant is a pure function `(LLMInput) -> LLMInput`. Add a file
under `tools/trace_replay/variants/` and register in `variants/__init__.py`:

```python
# tools/trace_replay/variants/my_variant.py
from ..types import LLMInput

def my_variant(inp: LLMInput) -> LLMInput:
    new_msg = inp.user_msg.replace("foo", "bar")
    return LLMInput(
        system=inp.system, user_msg=new_msg,
        tool_specs=inp.tool_specs,
        messages=[{"role": "user", "content": new_msg}],
        meta={**inp.meta, "variant_applied": "my_variant"},
    )
```

```python
# tools/trace_replay/variants/__init__.py
from .my_variant import my_variant
VARIANT_REGISTRY = { ..., "my_variant": my_variant }
```

## How it pairs with trace

`BuildTracer.record_llm` captures per-call `node`, `phase_id`, `round`,
`user_msg`, `raw_response`, `parsed`. trace_replay extracts the **user_msg**
from there; **system** + **tool_specs** are static per node so they're
re-loaded at replay time from the live sidecar code (lets you test
"would my proposed prompt change actually help?").

## Output format

JSON written to `--out`:

```json
{
  "meta": {
    "trace": "...", "node": "agentic_phase_loop",
    "phase_id": "p1", "round": 1, "original_pick": "inspect_block_doc",
    "variants": ["identity", "enrich_catalog_brief"],
    "reps": 3
  },
  "results": [
    {"variant": "identity", "rep": 1, "tool": "add_node",
     "picked": "block_process_history", "tool_input": {...},
     "text_blocks": ["I'll add..."], "duration_ms": 1234,
     "input_tokens": 500, "output_tokens": 80, "error": null},
    ...
  ]
}
```

Console summary shows per-variant pick distribution as ASCII bars + first
text reasoning per variant for empathy.

## Running on EC2 (where traces live)

```bash
ssh -i ~/Desktop/ai-ops-key.pem ubuntu@aiops-gill.com
cd /opt/aiops
sudo bash -c 'set -a && source python_ai_sidecar/.env && set +a && \
  /opt/aiops/venv_sidecar/bin/python3 -m tools.trace_replay \
  --trace /tmp/builder-traces/<latest>.json \
  --variants identity rewrite_phase_goal_generic \
  --reps 3'
```

The `.env` sourcing is needed to pick up `ANTHROPIC_API_KEY` /
`ANTHROPIC_MODEL`. Replay calls the **live** LLM provider, so it does cost
tokens — use 3 reps as the canonical sample size (LLM non-determinism
needs ≥3 reps to call a result stable; see
[`feedback_self_smoke_before_user.md`](../../../../.claude/projects/.../memory/feedback_self_smoke_before_user.md)).

## Limitations / known gaps

- **Round ≥ 2 of phase loop**: trace stores final `user_msg` per round but
  not the full assistant + tool_result history of prior rounds. Replay
  reconstructs a single-user-turn conversation. Most variants only touch
  the latest user turn so this is rarely an issue — call out in variant
  docstring when it matters.
- **Variant param overrides**: not supported in v1. Write a custom
  variant file for parameterized experiments.
- **No automatic A vs B significance test**: small N (3) makes formal
  tests low-power; rely on visible pick distribution shifts.
