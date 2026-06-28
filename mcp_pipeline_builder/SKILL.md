# Skill — Build an AIOps analysis pipeline (via the `aiops-pipeline-builder` connector)

> Paste this into a **Claude Desktop Project → custom instructions** (or the top of
> a chat) so the model knows *how* to use the connector. The connector itself must
> be **enabled** for the tools to be callable — this doc is the "how", the connector
> is the "hands".

## What you can do
You build a semiconductor-ops analysis **pipeline** — a small DAG of typed
**blocks** (source → transform → chart) — then run and save it. A saved pipeline
gets a `/pipeline-view/<id>` URL the human can open (DAG + rendered chart, and an
"open in Builder" link).

## Tools (from the `aiops-pipeline-builder` connector)
| tool | use |
|---|---|
| `list_blocks(category?)` | see available blocks |
| `explain_block(name)` | a block's real params/description/examples — the ONLY source of truth |
| `preview(pipeline_json, node_id)` | run up to a node, get its rows + columns (learn the data) |
| `validate(pipeline_json)` | structural check |
| `execute(pipeline_json)` | run the whole thing, get status + chart |
| `save_pipeline(name, pipeline_json, description?)` | save draft → returns id + view URL |

## The pipeline JSON you assemble
```json
{"version":"1.0","name":"...","inputs":[],
 "nodes":[{"id":"n1","block_id":"block_process_history","block_version":"1.0.0","params":{}}],
 "edges":[{"id":"e1","from":{"node":"n1","port":"data"},"to":{"node":"n2","port":"data"}}]}
```
Node **positions are not needed** — the UI lays out the DAG.

## Workflow — always in this order
1. `list_blocks()`, then `explain_block(name)` for each block you intend to use.
   **Never guess params** — read them from `explain_block`.
2. Add the **source** node first and `preview` it: confirm `rows > 0` and learn the
   **actual column names** before wiring anything downstream.
3. Build the rest using the columns you saw; `preview` each new node.
4. `validate`, fix any errors.
5. `execute`, confirm `status=success` and a chart/table came out.
6. `save_pipeline` and give the human the returned **view_url**.

## Gotchas (learned the hard way)
- `block_process_history` defaults `time_range="24h"`; sim data may be older →
  a 24h window returns 0 rows. If `preview` shows `rows=0`, widen `time_range`
  (`"7d"`/`"30d"`).
- **"all machines / 全廠"** → `block_list_objects(kind='tool')` →
  `block_mcp_foreach` → `block_unnest`, **not** a single `process_history`
  (that's one machine only).
- Multiple ids → do **not** comma-pack `tool_id`; leave it unset and filter
  downstream with `block_filter` `operator='in' value=[...]`.
- Ranked bar ("由多到少 / top-N") → set `block_bar_chart` `order='desc'`
  (`block_pareto` self-sorts) — no separate sort block.
- Be economical: a few preview/inspect calls, then build. Don't loop blindly.

## Skills v2 (`*_skill_v2` tools) — current shape, prefer over `rule_*`

The platform's authoring model is now **Skill = 1 pipeline + optional automation
wrapper**. A Skill on its own is just a reusable analysis tool; wrapping it as an
**Auto Patrol** (cron) or **Data Check** (cron, no alarm) is a separate decision
the human makes. There is no multi-step checklist anymore; one skill, one pipeline.

### Three canonical use cases

| Human said | What you do |
|---|---|
| 「幫我查 XXX」(one-shot analysis) | build pipeline → `save_pipeline` → `create_skill_v2` → `bind_skill_pipeline`. Stop. Skill stays as `tool` — no automation yet. |
| 「幫我建個自動巡檢」(daily watch) | same first 3 steps → then `automate_skill_patrol(slug, schedule, target, gate, outcome)`. Pipeline MUST contain a `block_step_check` node (the verdict → alarm-eligible). |
| 「OOC 時自動檢查」(event-driven) | same first 3 steps → then `automate_skill_event(slug, upstream_slug)` where `upstream_slug` is an existing Auto Patrol that emits alarms (find via `list_skills_v2`). |

### Tools

| tool | use |
|---|---|
| `list_skills_v2()` | scan the library — find an upstream alarm source, check whether a similar skill already exists |
| `get_skill_v2(slug)` | one skill in full, including `pipeline_nodes` (Editor-rendered) |
| `create_skill_v2(name, sub?, nl?)` | create. Returns `{slug, view_url}`. Skill starts as `tool` with empty pipeline. |
| `bind_skill_pipeline(slug, pipeline_id)` | link a `save_pipeline` result to a skill. Server derives `pipeline_nodes` + `has_alarm` from the DAG. |
| `automate_skill_patrol(slug, schedule, target, alarm_gate, outcome)` | wrap as cron-scheduled Auto Patrol. Skill must have `has_alarm=True`. |
| `automate_skill_event(slug, upstream_slug, alarm_gate, outcome)` | wrap as event-driven Auto Patrol. Skill must have `has_alarm=True`. |
| `automate_skill_datacheck(slug, schedule, target)` | wrap as scheduled Data Check (no alarm; terminal). |
| `remove_skill_automation(slug)` | strip wrapper → back to plain `tool`. |

### Workflow patterns

**Use case 1 — "幫我查 XXX"**
```
list_blocks() → preview() → assemble pj → validate(pj) → execute(pj) → save_pipeline()
→ create_skill_v2(name) → bind_skill_pipeline(slug, pipeline_id)
hand human the view_url at /skills/<slug>. Done.
```

**Use case 2 — "幫我建個自動巡檢"**
```
…same as above, then:
→ automate_skill_patrol(slug, schedule="每 1 小時", target="所有機台",
                        alarm_gate="任一符合 → alarm",
                        outcome="raise alarm · 可被下游接")
```
The pipeline MUST end in `block_step_check` so the server marks `has_alarm=True`.

**Use case 3 — "OOC 時自動檢查"**
```
list_skills_v2() to find an upstream patrol (look for role='patrol', has_alarm=True).
…build pipeline + save_pipeline + create_skill_v2 + bind_skill_pipeline as above…
→ automate_skill_event(slug, upstream_slug="p-ooc52", …)
```

### Gotchas

- Schedule, target, gate, outcome strings must be exactly one of the catalogued
  values (see each tool's docstring). The server rejects unknown values.
- Pipelines without `block_step_check` cannot be patrols. If the human wants
  Auto Patrol but the analysis is data-only, propose Data Check instead.
- `bind_skill_pipeline` overwrites any previous binding. That's intentional —
  re-running the build replaces the bound pipeline.
- A skill's slug is auto-generated and irrelevant to the human; always refer
  to skills by `name` in your replies. Use `slug` only as an internal key.

---

## Legacy: Auto-check Rules (`rule_*` tools)
> Older multi-step authoring shape. Prefer the Skills v2 tools above for new
> work — they map 1:1 to what the user sees in the UI. `rule_*` is kept for
> in-flight tasks that started on the legacy surface.

A **rule** = TRIGGER (when) + CONFIRM/CHECKLIST (what to check) + the platform fires
the alarm. It is a Skill Document. Build it one part at a time, like a guided author:

| tool | use | confirm |
|---|---|---|
| `rule_list` / `rule_get` / `rule_describe_options` / `rule_validate` | read | none |
| `rule_create` | new rule (draft) + trigger | direct |
| `rule_update` | patch title/desc/stage/trigger | direct |
| `rule_bind_checkpoint` | bind a check pipeline YOU built to a slot | direct |
| `rule_set_confirm_check_nl` / `rule_add_step_nl` | NL → check (slower; prefer build+bind) | direct |
| `rule_request_review` | open the whole-rule review GUI for the user | hand-off |
| `rule_request_activate` / `rule_request_disable` / `rule_request_delete` | go live / turn off / remove | hand-off |

Flow: `rule_describe_options` → `rule_create(title, stage, trigger_config)` → for each
checkpoint build a pipeline that **ends in `block_step_check`** (no `block_alert`),
`save_pipeline`, then `rule_bind_checkpoint(slot='confirm' or 'step:NEW', pipeline_id)`.
Build the WHOLE rule (don't review per-checkpoint) → `rule_validate` →
`rule_request_review(slug)` → give the user the returned `launch_url`: our GUI try-runs
the whole rule and shows every checkpoint's result together, where they edit any one or
activate it.

**Draft edits run directly** (create/update/bind/nl) — they only make a reversible draft.
**Hard rule:** after ANY create OR modify, finish by calling `rule_request_review(slug)`
and give the user the launch_url — never say a rule is built/changed without launching
the review GUI; they decide there whether to try-run more or activate.
**Going live / disable / delete never run from a tool**: call `rule_request_*`, which
returns a `launch_url`; give it to the user, who reviews/confirms in our GUI where the
action actually runs (under their auth). If their app is open it auto-pops; otherwise
the link is the way in.

**How to report a `rule_request_*` result:** it executed NOTHING (`executed:false`,
`status:PENDING_USER_*`). Relay its `tell_user` + the launch_url. NEVER say a rule was
deleted/disabled/activated/"done" — it's only a request until the user confirms in the
system. You can't open the URL for them; present it as the action they must take.

## Example request → what you do
> "查 EQP-08 最近 7 天的 SPC 趨勢,畫成圖並存起來"

`explain_block(block_process_history)` → add n1 (`tool_id=EQP-08`, `time_range=7d`)
→ `preview(n1)` to find the xbar value/UCL/LCL columns → add `block_unnest` /
`block_filter` / `block_line_chart` → `execute` → `save_pipeline` → return the
view_url.
