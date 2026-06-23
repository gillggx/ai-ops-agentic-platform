# Chat-mode eval harness (W1)

The chat-surface counterpart to `tools/slash17` (which covers the builder).
Runs operations questions through the chat orchestrator (`/internal/agent/chat`)
and grades **behaviour**, not block-sets — chat answers questions / calls tools,
it doesn't (primarily) build a pipeline, so "right answer / right action" is the
bar, not "right blocks".

Runs **on the EC2 host** (sidecar isn't publicly exposed).

## Files

| file | what |
|---|---|
| `chat_driver.py` | Runs each case → captures `tools_called`, `iterations`, `synthesis` (answer text), `behavior` (answer / build_confirm / clarify / error / empty), `status`. Env-driven, no secret. |
| `grade_chat.py` | Grades captured `behavior` vs an expected-behaviour map (`WANT`). |
| `run.sh` | Wrapper; **requires `SVC_TOKEN` from env**. |

## Run

```bash
export SVC_TOKEN=...            # from python_ai_sidecar/.env
bash tools/chat_eval/run.sh baseline
python3 tools/chat_eval/grade_chat.py baseline
```

## Product decision (2026-06-23) — chat = pipeline entry (B)

A data question routing to a build-intent confirm card ("我先跟你確認要建什麼")
is **correct by design** — chat is a pipeline entry point, consistent with the
builder. So `WANT` is: data questions → `build_confirm`, concept questions →
`answer`, vague → `clarify`. For `build_confirm` cases the bar is higher than "a
card showed": after auto-confirm the pipeline must actually **build + run +
return a result** (`MATCH` requires `confirmed_ran` + non-empty
`confirmed_blocks`; `BUILD?` = card shown but the build didn't complete).

## The intervention — why this verifies, not just observes

The confirm card PAUSES the graph waiting for the user to click "開始建", so a
naive driver can only see "a card appeared". This harness auto-confirms it
(leg 2: re-POST `[intent_confirmed:CARD]` + session_id, the same call the
frontend makes) and drains the resulting Glass Box build — so we grade the
**actual pipeline + run result**, not the card.

## Role matters — runs as PE

`ON_DUTY` (empty roles, fail-closed) is BLOCKED from `build_pipeline_live`, so a
data question dead-ends at "值班帳號無法建立 Pipeline". The eval sends
`X-User-Roles: PE` (override via `EVAL_ROLES`) to exercise the full build path.
(Open product question: an on-duty engineer asking a data question hits that
dead-end — should chat route ON_DUTY to a direct answer / published skill
instead of a build they can't run?)

`behavior` (in `chat_driver._classify`): `answer` / `build_confirm` / `clarify`
/ `error`. Each `build_confirm` case is followed by the auto-confirm leg whose
deliverable (`confirmed_blocks` from `pb_glass_done.pipeline_json`,
`confirmed_ran` from `pb_run_done`) is what the grader checks.
