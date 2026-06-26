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

## Example request → what you do
> "查 EQP-08 最近 7 天的 SPC 趨勢,畫成圖並存起來"

`explain_block(block_process_history)` → add n1 (`tool_id=EQP-08`, `time_range=7d`)
→ `preview(n1)` to find the xbar value/UCL/LCL columns → add `block_unnest` /
`block_filter` / `block_line_chart` → `execute` → `save_pipeline` → return the
view_url.
