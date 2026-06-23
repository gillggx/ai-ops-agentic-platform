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

## ⚠ WANT is provisional — a product decision gates the goldens

The grader's `WANT` map assumes an operations **data** question should be
*answered* (directly, or by build+run+report — both count as `answer`). The
2026-06-23 baseline showed chat instead often **pivots data questions into the
pipeline-build confirm flow** (`confirm_pipeline_intent` → "我先跟你確認要建什麼"),
after thrashing the skill/tool catalog for many iterations.

Whether that pivot is **correct by design** (operations chat builds+runs a
pipeline to answer) or a **regression** (it should answer directly) is a product
call. Confirm with the owner before treating a `WRONG` as a real failure —
otherwise this repeats the SLASH-17 stale-golden trap (blaming the agent for
behaviour that was actually intended). Update `WANT` once the intended behaviour
per case is settled.

`behavior` classification (in `chat_driver._classify`):
- `answer` — produced a synthesis answer, no build-confirm pivot
- `build_confirm` — proposed a pipeline + asked to confirm
- `clarify` — asked the user to disambiguate
- `error` / `empty` — failed / produced nothing

`iterations` > 4 is flagged (`thrash?`) as an efficiency smell, not a failure.
