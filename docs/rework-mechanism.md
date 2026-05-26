# Rework Mechanism

How photo-station rework is generated, stored, and surfaced through the
MCP / block stack.

## The trigger

In [station_agent.py](../ontology_simulator/app/agent/station_agent.py):

1. **Photo step detection** — `_is_photo_step(step_num)` returns true when
   step number is a multiple of 5 (STEP_005 / _010 / _015 / _020 in the
   current 20-step flow).
2. **OOC rate boost** — at photo steps, if SPC didn't already trip OOC,
   roll once with `PHOTO_OOC_PROBABILITY` (default 0.30, override via
   env). Non-photo steps keep the global `OOC_PROBABILITY` (~0.07).
3. **Rework write** — every photo-station OOC inserts one row into
   `db.rework_records`. Per-lot count auto-increments via a count of
   existing rows for that lot.

## The schema

```js
db.rework_records.insertOne({
  reworkTime:  ISODate,
  reworkCount: NumberInt,   // running per-lot
  lotID:       "LOT-0123",
  step:        "STEP_010",
  reworkInfo: {
    // 20 fields, deliberately renamed from MESInfo
    mainPD_ID, PDID, rwJobID, slotMap, prodCode, layerName, techNode,
    rootPD, subPDCode, routeName, recipeFamily, carrierID, slotCount,
    lotKind, priorityClass, customerCode, region, stepSeq,
    toolRecipeRev, holdStatus,
  },
})
```

## Field-name mapping (this is the whole point)

The same lot-step that produced the rework also writes a `MESInfo` block
onto its `db.events` row. The names are intentionally different so the
LLM has to learn the correspondence from the MCP description — not from
prompt-hardcoded recipes.

| `MESInfo` (events.MESInfo) | `reworkInfo` (rework_records.reworkInfo) |
|---|---|
| flowID | **mainPD_ID** |
| stageID | **PDID** |
| processJobID | **rwJobID** |
| slotList | **slotMap** |
| productID | **prodCode** |
| photoLayerID | **layerName** |
| technology | **techNode** |
| mainPD | **rootPD** |
| subPDID | **subPDCode** |
| routeID | **routeName** |
| recipeGroup | **recipeFamily** |
| foupID | **carrierID** |
| waferCount | **slotCount** |
| lotType | **lotKind** |
| lotPriority | **priorityClass** |
| customer | **customerCode** |
| mfgRegion | **region** |
| processOrder | **stepSeq** |
| eqpRecipeRevision | **toolRecipeRev** |
| holdState | **holdStatus** |
| dispatchPriority | dispatchPriority *(same)* |

## Surface layers

| Layer | Identifier | Notes |
|---|---|---|
| Simulator HTTP | `POST /api/v1/rework_request` | body: `{lotID, step?, flowID?}`. `flowID` filter actually matches `reworkInfo.mainPD_ID` |
| System MCP | `rework_request` | seeded by `V53__rework_mcp_and_block.sql`. Description carries the full field-mapping table — single source of truth |
| Pipeline-builder block | `block_rework_request` | dedicated executor, flattens `reworkInfo` to `rwi_<key>` columns on the DataFrame |

## Why a dedicated block (not `block_mcp_call`)

`block_mcp_call` makes the LLM do two-step reasoning: pick MCP name +
hand-craft JSON args. A dedicated block gives:

- Static `param_schema` so the LLM sees `lot_id` is required, `step` /
  `flow_id` are optional, with examples
- Auto-flatten of `reworkInfo` to top-level `rwi_*` columns — downstream
  filter / groupby blocks just reference `rwi_techNode` like any other
  column
- The block description is the same field-mapping table as the MCP, so
  the agent can answer "what's the flowID of LOT-0123 rework?" without
  hopping through the catalog

## Tunables

| Env var | Default | Where |
|---|---|---|
| `PHOTO_OOC_PROBABILITY` | `0.30` | simulator `config.py` — raise to make rework more frequent for demos |
| `OOC_PROBABILITY` | `0.07` | unchanged — applies to non-photo steps only |

## Backfill

MESInfo and rework_records are written **forward-only**. Events that
existed before this change have `MESInfo: null` (or the key absent).
There is no backfill — old rows are left as-is and consumers must
tolerate the missing field.

## Tests

- [`python_ai_sidecar/tests/test_rework_block.py`](../python_ai_sidecar/tests/test_rework_block.py) covers the block's request shape, flattening, and error paths.
- Simulator-side rework trigger is exercised indirectly by running the
  simulator (any photo step OOC produces a row).
