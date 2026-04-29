-- Phase D: per-alarm-attribute filter on auto_check triggers.
-- A NULL match_filter (the default for existing rows) means "trigger on every
-- alarm that matches event_type" — same behaviour as before. When set, the
-- value is a JSON object whose keys are alarm fields (equipment_id, severity,
-- step, lot_id, …) and values are either a literal or a list-of-literals
-- treated as OR. Multiple keys = AND.
ALTER TABLE pipeline_auto_check_triggers
    ADD COLUMN IF NOT EXISTS match_filter text;

COMMENT ON COLUMN pipeline_auto_check_triggers.match_filter IS
    'JSON object {alarm_field: value | [value,...]}. NULL = no filter.';
