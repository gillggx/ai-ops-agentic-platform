-- V53 — Rework feature: system MCP + pipeline-builder block registration.
--
-- Background: photo stations (STEP_005/_010/_015/_020) in ontology_simulator
-- have OOC_PROBABILITY pinned to 0.30 (vs global 0.07); every photo-station
-- OOC creates a row in db.rework_records with reworkInfo (renamed keys vs
-- MESInfo). This migration registers:
--   1. system MCP `rework_request` pointing at simulator's POST /api/v1/rework_request
--   2. pb_blocks row for block_rework_request — the dedicated Pipeline
--      Builder block that wraps the MCP and flattens reworkInfo to rwi_*
--      columns on the returned DataFrame.
--
-- Idempotent via ON CONFLICT — re-running on a DB that already has these
-- rows updates them in place rather than failing.
--
-- ⚠ Flyway is disabled in prod (see memory feedback_flyway_disabled_in_prod):
-- apply on EC2 with `psql -h localhost -U aiops aiops_db -f V53__rework_mcp_and_block.sql`.

-- ─── 1. system MCP: rework_request ────────────────────────────────────────
INSERT INTO mcp_definitions
  (name, mcp_type, visibility, description, processing_intent, api_config, input_schema)
VALUES
  (
    'rework_request', 'system', 'public',
       E'== What ==\n'
    || E'查 lot 在某 step 的 rework 紀錄。Rework 由 photo 站（step 號為 5 的倍數）OOC 時\n'
    || E'自動觸發（OOC ↔ rework 1:1）。\n\n'
    || E'== Use when ==\n'
    || E'- 「LOT-0123 有沒有 rework 過？」→ lotID=''LOT-0123''\n'
    || E'- 「LOT-0123 在 STEP_010 的 rework」→ lotID + step\n'
    || E'- 「FLOW-LOGIC-28-V2 路線的 LOT-0123 rework」→ lotID + flowID\n\n'
    || E'== Returns ==\n'
    || E'{total: int, rework_records: [{reworkTime, reworkCount, lotID, step, reworkInfo:{...}}]}\n\n'
    || E'== ⚠ Field-name mapping (reworkInfo vs MESInfo / get_process_info) ==\n'
    || E'reworkInfo 故意用不同欄位名（測 LLM 是否懂對照）：\n'
    || E'  MESInfo            → reworkInfo\n'
    || E'  ─────────────────    ─────────────\n'
    || E'  flowID             → mainPD_ID\n'
    || E'  stageID            → PDID\n'
    || E'  processJobID       → rwJobID\n'
    || E'  slotList           → slotMap\n'
    || E'  productID          → prodCode\n'
    || E'  photoLayerID       → layerName\n'
    || E'  technology         → techNode\n'
    || E'  mainPD             → rootPD\n'
    || E'  subPDID            → subPDCode\n'
    || E'  routeID            → routeName\n'
    || E'  recipeGroup        → recipeFamily\n'
    || E'  foupID             → carrierID\n'
    || E'  waferCount         → slotCount\n'
    || E'  lotType            → lotKind\n'
    || E'  lotPriority        → priorityClass\n'
    || E'  customer           → customerCode\n'
    || E'  mfgRegion          → region\n'
    || E'  processOrder       → stepSeq\n'
    || E'  eqpRecipeRevision  → toolRecipeRev\n'
    || E'  holdState          → holdStatus\n\n'
    || E'== Common mistakes ==\n'
    || E'⚠ rework_records 用 reworkInfo.mainPD_ID 過濾 flowID，不是頂層 flowID\n'
    || E'⚠ 非 photo step (5 的倍數之外) 永遠沒有 rework；查 STEP_007 得 0 筆是正常的\n'
    || E'⚠ 對應 block 是 `block_rework_request`（rwi_<key> 前綴），不要用 block_mcp_call wrap\n',
    '',
    '{"endpoint_url": "http://localhost:8012/api/v1/rework_request", "method": "POST", "headers": {"Content-Type": "application/json"}}',
    '{"fields": [{"name": "lotID", "type": "string", "required": true}, {"name": "step", "type": "string", "required": false}, {"name": "flowID", "type": "string", "required": false}]}'
  )
ON CONFLICT (name) DO UPDATE SET
  description       = EXCLUDED.description,
  api_config        = EXCLUDED.api_config,
  input_schema      = EXCLUDED.input_schema;


-- ─── 2. block_rework_request ──────────────────────────────────────────────
-- The description / param_schema mirror python_ai_sidecar/pipeline_builder/seed.py
-- so the boot invariant check (BUILTIN_EXECUTORS == DB rows) passes.
INSERT INTO pb_blocks
  (name, version, category, status, description,
   input_schema, output_schema, param_schema, implementation,
   examples, output_columns_hint, is_custom)
VALUES (
  'block_rework_request', '1.0.0', 'source', 'production',
$desc$== What ==
查指定 lot 在 photo 站（STEP 編號 5 倍數）的 rework 紀錄。
Rework 由 simulator 自動觸發：photo 站每次 OOC = 一筆 rework_record。

== When to use ==
- 「LOT-0123 有沒有 rework 過？」→ lot_id='LOT-0123'
- 「LOT-0123 在 STEP_010 的 rework 紀錄」→ lot_id + step
- 「flowID=FLOW-LOGIC-28-V2 的 LOT-0123 rework」→ lot_id + flow_id

== Params ==
lot_id  (string, 必填) e.g. 'LOT-0123'
step    (string, 選填) e.g. 'STEP_010' — 必須是 photo step（5 倍數）
flow_id (string, 選填) e.g. 'FLOW-LOGIC-28-V2' — 過濾 reworkInfo.mainPD_ID

== ⚠ Field-name mapping (deliberate, important!) ==
reworkInfo 的欄位名跟 MESInfo / get_process_info **故意不同**。block 把
reworkInfo 鋪平到 column 時加 `rwi_` 前綴。對照表：
  MESInfo                  reworkInfo (column = rwi_<key>)
  ─────────────────────    ──────────────────────────────
  flowID                   mainPD_ID         → rwi_mainPD_ID
  stageID                  PDID              → rwi_PDID
  processJobID             rwJobID           → rwi_rwJobID
  slotList                 slotMap           → rwi_slotMap
  productID                prodCode          → rwi_prodCode
  photoLayerID             layerName         → rwi_layerName
  technology               techNode          → rwi_techNode
  mainPD                   rootPD            → rwi_rootPD
  subPDID                  subPDCode         → rwi_subPDCode
  routeID                  routeName         → rwi_routeName
  recipeGroup              recipeFamily      → rwi_recipeFamily
  foupID                   carrierID         → rwi_carrierID
  waferCount               slotCount         → rwi_slotCount
  lotType                  lotKind           → rwi_lotKind
  lotPriority              priorityClass     → rwi_priorityClass
  customer                 customerCode      → rwi_customerCode
  mfgRegion                region            → rwi_region
  processOrder             stepSeq           → rwi_stepSeq
  eqpRecipeRevision        toolRecipeRev     → rwi_toolRecipeRev
  holdState                holdStatus        → rwi_holdStatus

== Output ==
port: data (dataframe). Top-level columns: reworkTime, reworkCount, lotID,
step, rwi_<key> (one per reworkInfo field, listed above).
Empty DataFrame when the lot has never been reworked.

== Errors ==
- MISSING_PARAM   : lot_id absent
- HTTP_ERROR      : simulator unreachable
- UPSTREAM_ERROR  : simulator returned non-2xx
$desc$,
  '[]',
  '[{"port": "data", "type": "dataframe", "columns": ["reworkTime", "reworkCount", "lotID", "step", "rwi_mainPD_ID", "rwi_PDID"]}]',
  '{"type": "object", "required": ["lot_id"], "properties": {"lot_id": {"type": "string", "title": "Lot ID (必填)"}, "step": {"type": "string", "title": "Step (選填)"}, "flow_id": {"type": "string", "title": "Flow ID (選填)"}}}',
  '{"type": "python", "ref": "python_ai_sidecar.pipeline_builder.blocks.rework_request:ReworkRequestBlockExecutor"}',
  '[{"params": {"lot_id": "LOT-0123"}, "desc": "查 LOT-0123 所有 rework"}, {"params": {"lot_id": "LOT-0123", "step": "STEP_010"}, "desc": "只看 STEP_010 的 rework"}]',
  '["reworkTime", "reworkCount", "lotID", "step", "rwi_mainPD_ID", "rwi_PDID", "rwi_rwJobID", "rwi_slotMap", "rwi_prodCode", "rwi_layerName", "rwi_techNode", "rwi_rootPD", "rwi_subPDCode", "rwi_routeName", "rwi_recipeFamily", "rwi_carrierID", "rwi_slotCount", "rwi_lotKind", "rwi_priorityClass", "rwi_customerCode", "rwi_region", "rwi_stepSeq", "rwi_toolRecipeRev", "rwi_dispatchPriority", "rwi_holdStatus"]',
  false
)
ON CONFLICT (name, version) DO UPDATE SET
  description    = EXCLUDED.description,
  input_schema   = EXCLUDED.input_schema,
  output_schema  = EXCLUDED.output_schema,
  param_schema   = EXCLUDED.param_schema,
  implementation = EXCLUDED.implementation,
  examples       = EXCLUDED.examples,
  output_columns_hint = EXCLUDED.output_columns_hint,
  status         = EXCLUDED.status,
  category       = EXCLUDED.category,
  updated_at     = now();
