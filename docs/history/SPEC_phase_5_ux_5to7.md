# Phase 5-UX-5 to 5-UX-7 — Glass Box Agent + 3-Kind Pipeline Split

**Status**: Implemented (local verified). Awaiting production deploy.
**Dates**: 2026-04-19

## Context

Phase 5 (prior) unified the Agent backend around a single `build_pipeline` tool that
produced a complete `pipeline_json` one-shot. Visual feedback was a final result
card — no progressive construction, no canvas continuity, and the pipeline
model conflated "agent-invocable" with "alarm-triggered".

Three iterations (UX-5, UX-6, UX-7) turn Agent + Pipeline Builder into a
coherent Glass Box experience with a cleaner data model underneath.

---

## Phase 5-UX-5 — Right-Tab Panel + Progressive DAG foundations

### What changed
- **Pipeline Builder right-side panel → tabbed**: `✦ Agent | ⚙ Parameters | ⏱ Runs`
  (`components/pipeline-builder/RightTabbedPanel.tsx`). NodeInspector moved
  from center-right to Parameters tab. Agent tab always visible.
- **Data Preview tabs already implemented** (`Rows | Schema Diff | Stats`) —
  re-surfaced and verified.
- **Progressive `pb_node_event` SSE events** wired from `PipelineExecutor` via
  `on_event` callback → chat SSE relay in `orchestrator.py` event bus.
  (Later superseded by Glass Box in UX-6; kept as dead code behind
  `build_pipeline` path.)
- **Focus context**: per-node "Ask Agent about this" sets a focus chip in the
  Agent tab; subsequent messages prepend `[Focused on <node>]` so the LLM
  knows what the user is pointing at.
- **Topbar revert**: removed ambiguous global search bar; right-side Agent is
  the sole entry. AppShell default `copilotOpen = true`.
- **AppShell live canvas overlay**: `LiveCanvasOverlay.tsx` mounts a
  full-viewport BuilderLayout when the chat agent triggers a pipeline build
  from non-Builder pages (dashboard / alarm list).

### Tool schema delta
- `propose_pipeline_patch` added (patch proposal card with Apply/Reject) —
  later retired from LLM visibility in UX-6 (schema kept dormant).

---

## Phase 5-UX-6 — Glass Box Build (subagent + live canvas)

### What changed
- **New tool `build_pipeline_live`** replaces `build_pipeline`. Input: natural
  language `goal` + optional `notes` + optional `base_pipeline_id`. No
  `pipeline_json` — the main chat agent just describes what it wants.
- **Sub-agent delegation**: `tool_execute._execute_build_pipeline_live` spawns
  an `agent_builder` session (pre-existing service, previously orphaned after
  Phase 5-UX-3b) and relays its SSE events (`chat` / `operation` / `error` /
  `done`) as chat-SSE events `pb_glass_start / chat / op / error / done`.
- **Live canvas mutation**: operations (`add_node` / `connect` / `set_param` /
  `remove_node` / `rename_node`) stream into the canvas one at a time via the
  shared `lib/pipeline-builder/glass-ops.ts` translator — node-by-node
  construction visible in real time. Auto-layout on `done`.
- **Retired tools from LLM visibility**:
  - `build_pipeline` (one-shot) — replaced by `build_pipeline_live`
  - `propose_pipeline_patch` (proposal cards) — Glass Box applies directly
  - `suggest_action` inside agent_builder's own toolset — same reason
- **Context continuity fix**: if the chat session already has a canvas
  snapshot (`agent_sessions.last_pipeline_json`) and no explicit
  `base_pipeline_id`, sub-agent hydrates with the existing canvas. Follow-up
  turns (「加一張常態分佈圖」) continue from the previous state.
- **Bug fix**: `session.operations.pop()` guarded against empty list when
  `get_state()` is called directly (bypassing dispatch).
- **Polite confirmation**: load_context prompt tells the LLM to ask the user
  before triggering `build_pipeline_live` (it takes over the viewport).
- **NestedBuilderProvider fix**: `BuilderLayoutNoProvider` variant so
  LiveCanvasOverlay can share a BuilderContext with the embedded canvas
  (operations targeted the wrong context in the first pass).

### SSE event contract
```
pb_glass_start : {session_id, goal}
pb_glass_chat  : {content}                          // agent narration
pb_glass_op    : {op, args, result}                 // canvas mutation
pb_glass_error : {message, op?, hint?}
pb_glass_done  : {status, summary, pipeline_json}
```

---

## Phase 5-UX-7 — 3-Kind Pipeline Split

### What changed
Replaced the misleading `pipeline_kind ∈ {auto_patrol, diagnostic}` binary
with a 3-role model that orthogonalises **invocation model** from **structural
role**.

| Kind | Trigger | Inputs source | Terminal block | Publish route |
|---|---|---|---|---|
| **auto_patrol** | cron schedule | none | `block_alert` | `auto_patrols.pipeline_id` |
| **auto_check** | alarm event | alarm payload (by name-match) | `block_alert` or `block_chart` | `pipeline_auto_check_triggers` (new) |
| **skill** | Agent / User on-demand | agent extracts from conversation | `block_chart` | `pb_published_skills` (existing) |

### Schema delta
- `PipelineKind = "auto_patrol" | "auto_check" | "skill" | "diagnostic"` —
  `diagnostic` kept as read-only legacy alias. Write paths reject it.
- New table `pipeline_auto_check_triggers` with columns
  `(id, pipeline_id, event_type, created_at)`. **No `inputs_mapping` column** —
  mapping is implicit by name-match (pipeline input name == alarm payload key).
- Migration (idempotent): `diagnostic` + has `block_alert` → `auto_check`;
  `diagnostic` + no `block_alert` → `skill`.
- Validator C11/C12/C13 updated for 3 kinds; `auto_check` additionally requires
  at least one declared input.

### New endpoints
- `POST /pipelines/{id}/publish-auto-check` — body `{event_types: string[]}`.
  Writes trigger bindings + transitions pipeline → active.
- `GET  /auto-check-rules` — list all bindings with parent pipeline metadata.
- `DELETE /auto-check-rules/{trigger_id}` — unbind without touching pipeline.

### Runtime dispatch
- `auto_check_dispatcher.dispatch_alarm_to_auto_checks(db, alarm_id,
  trigger_event, alarm_payload)` — called from `auto_patrol_service` after
  alarm creation. Finds triggers matching `trigger_event`, resolves each
  pipeline's inputs from `alarm_payload` by name (falling back to defaults),
  executes, logs results. Never blocks caller.

### UI changes
- `/admin/pipeline-builder/new` — 3-card picker (auto_patrol / auto_check / skill).
- `PipelineInfoModal` — inline kind selector; mutable while pipeline is
  `draft` / `validating`; frozen otherwise (requires Clone to change).
- `BuilderLayout` Publish button routing:
  - `skill` → `PublishReviewModal` (existing, writes `pb_published_skills`)
  - `auto_check` → `AutoCheckPublishModal` (new, purple, picks event_types)
  - `auto_patrol` → direct transition to active + bind via `/admin/auto-patrols`
- New sidebar item `⚡ Auto-Check Rules` → `/admin/auto-check-rules` page
  (grouped-by-pipeline list, per-event delete button).
- Agent prompt updated to use "skills" terminology (formerly "diagnostic").

### Design simplification (user's insight)
Earlier draft included a `inputs_mapping` column in the trigger table with a
drag-and-drop UI for mapping alarm payload fields → pipeline input names.
User pointed out this was redundant: the pipeline's own input schema already
documents what it needs from alarms. By convention (name-match), the mapping
is implicit. The Auto-Check publish modal now just shows the match
**derived** from the pipeline's inputs — no user input required.

---

## Deploy notes

### Startup migration (auto, idempotent)
1. Widens `pb_pipelines.pipeline_kind` allowed values (nullable already from
   5-UX-3b).
2. `UPDATE pb_pipelines SET pipeline_kind='auto_check' WHERE pipeline_kind='diagnostic' AND pipeline_json LIKE '%block_alert%'`.
3. `UPDATE pb_pipelines SET pipeline_kind='skill' WHERE pipeline_kind='diagnostic'` (residual).
4. `CREATE TABLE pipeline_auto_check_triggers` via ORM `create_all`.

### Back-compat
- Legacy `diagnostic` read-only alias preserved (any row that escapes
  migration is treated as `skill` at publish time).
- Existing `pb_published_skills` rows don't need migration; their source
  pipelines have `kind='skill'` now.
- Existing `auto_patrols.pipeline_id` bindings untouched — no schema change
  to `auto_patrols` table.

### Known dead code (kept dormant)
- `build_pipeline` tool schema + `_execute_build_pipeline` handler + related
  `pb_structure` / `pb_node_event` SSE relay.
- `propose_pipeline_patch` tool + `PbPatchProposalCard` render path.
- `suggest_action` tool in agent_builder toolset.

All hidden from LLM via `_LLM_HIDDEN_TOOLS` + filtered `claude_tool_defs()`.
Can be reactivated for future copilot-mode without code recovery.

### Tests
- `tests/pipeline_builder/` : 257/257 passing.
- Pre-existing failures in `test_combined_flow.py`, `test_diagnostic_flow.py`,
  `test_phase6_etch_copilot.py` (21 failures) are unrelated — they patch a
  removed `app.services.diagnostic_service.anthropic` module from an earlier
  refactor.

### Smoke tests (manual)
- [ ] Dashboard → right Agent "EQP-07 最近 100 次 xbar 趨勢" → agent asks
      confirmation → yes → LiveCanvasOverlay opens → node-by-node build.
- [ ] Follow-up "再加個常態分佈圖" → sub-agent sees existing 2 nodes → adds
      histogram + chart on top.
- [ ] Pipeline Builder `/new` → pick each of 3 kinds → Save → Info modal
      kind selector reflects + lets you switch (while draft).
- [ ] `auto_check` lock → Publish → AutoCheckPublishModal → bind event_type
      → check `/admin/auto-check-rules` shows the binding.
- [ ] `skill` lock → Publish → existing flow unchanged.
- [ ] `auto_patrol` lock → Publish → existing flow unchanged.
