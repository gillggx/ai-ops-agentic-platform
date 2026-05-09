-- V25 — Phase 11 v4: Skill-driven pipeline ownership.
--
-- Per user decision 2026-05-10: Skill is the single publish gate. Pipelines
-- built INSIDE the Skill→Builder→Confirm loop are owned by the Skill and
-- inherit lifecycle (draft / stable) from skill_documents.status. They no
-- longer need their own publish step.
--
-- Free-standing pipelines (built directly in /admin/pipeline-builder, not
-- under a Skill) are unaffected: parent_skill_doc_id IS NULL, lifecycle
-- behaviour unchanged.

ALTER TABLE pb_pipelines
  ADD COLUMN parent_skill_doc_id BIGINT
    REFERENCES skill_documents(id) ON DELETE CASCADE,
  ADD COLUMN parent_slot VARCHAR(40);

CREATE INDEX ix_pb_pipelines_parent_skill ON pb_pipelines(parent_skill_doc_id)
  WHERE parent_skill_doc_id IS NOT NULL;

COMMENT ON COLUMN pb_pipelines.parent_skill_doc_id IS
  'Phase 11 v4: when set, this pipeline is owned by the referenced Skill — its lifecycle is driven by skill_documents.status, not its own pb_pipelines.status. Free-standing pipelines have NULL.';

COMMENT ON COLUMN pb_pipelines.parent_slot IS
  'Phase 11 v4: which slot in the parent skill this pipeline backs — confirm | step:s1 | step:s2 | ... NULL for free-standing.';


-- ── Phase 11 v4: backfill event_types.attributes ────────────────────────
-- The Pipeline Builder embed mode reads these to prefill input bindings
-- for confirm / step pipelines. Shape per row:
--   [{"name": "tool_id", "type": "string", "required": true,
--     "description": "Equipment ID, e.g. EQP-01"}, ...]
--
-- attributes are upserted only when the row currently has '[]' so manual
-- IT_ADMIN edits are never overwritten.

UPDATE event_types SET attributes = $$[
  {"name":"tool_id","type":"string","required":true,"description":"Equipment ID, e.g. EQP-01"},
  {"name":"lot_id","type":"string","required":true,"description":"Lot ID, e.g. LOT-0123"},
  {"name":"step","type":"string","required":false,"description":"STEP_NNN where the breach happened"},
  {"name":"chamber_id","type":"string","required":false,"description":"CH-1..CH-4"},
  {"name":"spc_chart","type":"string","required":false,"description":"Which SPC chart (xbar / r / s / ...) tripped"},
  {"name":"severity","type":"string","required":false,"description":"low | med | high"}
]$$ WHERE name='OOC' AND attributes='[]';

UPDATE event_types SET attributes = $$[
  {"name":"tool_id","type":"string","required":true,"description":"Equipment ID"},
  {"name":"lot_id","type":"string","required":true,"description":"Lot ID"},
  {"name":"step","type":"string","required":false,"description":"STEP_NNN"},
  {"name":"chamber_id","type":"string","required":false},
  {"name":"fault_code","type":"string","required":false,"description":"FDC fault code, e.g. FDC_RGA_H2O_HIGH"},
  {"name":"contributing_sensors","type":"array","required":false,"description":"List of sensor names that breached the warning band"}
]$$ WHERE name IN ('FDC_FAULT','FDC_WARNING') AND attributes='[]';

UPDATE event_types SET attributes = $$[
  {"name":"tool_id","type":"string","required":true,"description":"Equipment ID"},
  {"name":"reason","type":"string","required":false,"description":"Scheduled / forced reason"}
]$$ WHERE name IN ('PM_START','PM_DONE') AND attributes='[]';

UPDATE event_types SET attributes = $$[
  {"name":"tool_id","type":"string","required":true,"description":"Equipment ID held"},
  {"name":"lot_id","type":"string","required":false,"description":"Lot held mid-process"},
  {"name":"step","type":"string","required":false},
  {"name":"reason","type":"string","required":false}
]$$ WHERE name='EQUIPMENT_HOLD' AND attributes='[]';

UPDATE event_types SET attributes = $$[
  {"name":"recipe_id","type":"string","required":true,"description":"e.g. RCP-001"},
  {"name":"old_version","type":"number","required":false},
  {"name":"new_version","type":"number","required":true},
  {"name":"changed_params","type":"array","required":false,"description":"List of {param,old,new}"}
]$$ WHERE name='RECIPE_VERSION_BUMP' AND attributes='[]';

UPDATE event_types SET attributes = $$[
  {"name":"apc_id","type":"string","required":true},
  {"name":"parameter","type":"string","required":true},
  {"name":"old_value","type":"number","required":false},
  {"name":"new_value","type":"number","required":true},
  {"name":"prev_spc_status","type":"string","required":false}
]$$ WHERE name='APC_AUTO_CORRECT' AND attributes='[]';

UPDATE event_types SET attributes = $$[
  {"name":"object_name","type":"string","required":true,"description":"APC | RECIPE"},
  {"name":"object_id","type":"string","required":true},
  {"name":"parameter","type":"string","required":true},
  {"name":"old_value","type":"number","required":false},
  {"name":"new_value","type":"number","required":true},
  {"name":"engineer","type":"string","required":true,"description":"e.g. alice.chen"},
  {"name":"reason","type":"string","required":true}
]$$ WHERE name='ENGINEER_OVERRIDE' AND attributes='[]';

UPDATE event_types SET attributes = $$[
  {"name":"tool_id","type":"string","required":true},
  {"name":"lot_id","type":"string","required":true},
  {"name":"step","type":"string","required":true},
  {"name":"spc_status","type":"string","required":false}
]$$ WHERE name='MONITOR_LOT_RUN' AND attributes='[]';

UPDATE event_types SET attributes = $$[
  {"name":"alarm_id","type":"number","required":true},
  {"name":"tool_id","type":"string","required":true},
  {"name":"lot_id","type":"string","required":false},
  {"name":"severity","type":"string","required":true},
  {"name":"trigger_event","type":"string","required":false}
]$$ WHERE name='ALARM_RAISED' AND attributes='[]';
