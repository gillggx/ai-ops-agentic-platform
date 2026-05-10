-- V28 — Phase 11 v6: register block_step_check in pb_blocks so the
-- agent catalog includes it. Without this row, plan_node never adds
-- a block_step_check op (the LLM literally can't see it), and Skill
-- step pipelines end up with chart/alert/data_view terminators that
-- SkillRunner can't read pass/fail from.
--
-- Boot invariant in python_ai_sidecar/_boot_invariants.py warned about
-- this drift; V28 closes it.

-- pb_blocks.name has no unique constraint, so use DELETE+INSERT to be idempotent.
DELETE FROM pb_blocks WHERE name = 'block_step_check';

INSERT INTO pb_blocks (
  name, category, version, status, description,
  input_schema, output_schema, param_schema,
  implementation, examples, output_columns_hint, is_custom
) VALUES (
  'block_step_check',
  'output',
  '1.0.0',
  'active',
  $$== What ==
Skill step terminator. Aggregates upstream dataframe to a scalar value,
compares against a threshold, emits a structured check record:
  { pass: bool, value: <scalar>, threshold, operator, note: <str> }
SkillRunner reads this output to decide step pass/fail.

== When to use ==
- ✅ EVERY pipeline backing a Skill confirm or checklist step MUST end here
- ✅ Use case examples:
    "OOC count last 5 lots ≥ 3" → aggregate=count, operator=>=, threshold=3
    "drift > 5%"                → aggregate=mean, operator=drift, threshold=0.05
    "value changed from baseline" → aggregate=last, operator=changed, baseline=...
- ❌ NOT for chart-style skills (use block_chart) — those aren't Skill steps
- ❌ NOT for alarm-emitting auto_patrols (use block_alert)

== Connect ==
input.data ← upstream dataframe (any block emitting `data` port)

== Params ==
operator   (string, required) >= | > | = | < | <= | changed | drift
threshold  (number/string)    target value to compare against
aggregate  (string)           count(default) | sum | mean | max | min | last | exists
column     (string)           column to aggregate (NOT needed for count/exists)
baseline   (number/string)    used by 'changed' / 'drift' operators
note       (string)           human-readable description rendered in run UI

== Behaviour ==
1. Aggregate upstream dataframe → scalar `value`
2. Compare value vs threshold using `operator`
3. Emit single-row dataframe: { pass, value, threshold, operator, note }

== Output ==
port: check (dataframe) — exactly 1 row

== Common mistakes ==
⚠ Forgetting `column` when aggregate≠count/exists → MISSING_PARAM
⚠ Wrong operator name (e.g. ">=3" instead of ">=", "3") → INVALID_PARAM
⚠ Treating block_step_check as visualisation — it's the verdict, not the chart
$$,
  $${"data": {"type": "dataframe", "required": true}}$$,
  $${"check": {"type": "dataframe", "row_count": 1, "columns": ["pass", "value", "threshold", "operator", "note"]}}$$,
  $${
    "operator": {"type": "string", "required": true, "enum": [">=", ">", "=", "<", "<=", "changed", "drift"]},
    "threshold": {"type": "any"},
    "aggregate": {"type": "string", "default": "count", "enum": ["count", "sum", "mean", "max", "min", "last", "exists"]},
    "column": {"type": "string"},
    "baseline": {"type": "any"},
    "note": {"type": "string"}
  }$$,
  'native:block_step_check',
  $$[
    {"title": "OOC count ≥ 3", "params": {"operator": ">=", "threshold": 3, "aggregate": "count", "note": "近 5 lot OOC ≥ 3 視為異常"}},
    {"title": "drift > 5%", "params": {"operator": "drift", "threshold": 0.05, "aggregate": "mean", "column": "etch_rate", "baseline": 1.5}},
    {"title": "value changed", "params": {"operator": "changed", "aggregate": "last", "column": "recipe_version", "baseline": 1}}
  ]$$,
  $$[
    {"name": "pass", "type": "bool"},
    {"name": "value", "type": "any"},
    {"name": "threshold", "type": "any"},
    {"name": "operator", "type": "string"},
    {"name": "note", "type": "string"}
  ]$$,
  FALSE
);
