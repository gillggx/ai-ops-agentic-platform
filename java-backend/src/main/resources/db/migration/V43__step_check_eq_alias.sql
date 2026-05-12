-- V43 — block_step_check.operator accepts '==' alongside '=' (2026-05-13).
--
-- The executor already normalizes '==' → '=' (step_check.py L62-63) but the
-- param_schema enum didn't list '==', so plan-time validator rejected it.
-- LLMs trained on Python/JS reach for '==' first; SQL ones for '='. Both
-- should pass.

UPDATE pb_blocks
SET param_schema = jsonb_set(
      param_schema::jsonb,
      '{properties,operator,enum}',
      '[">=", ">", "=", "==", "<", "<=", "changed", "drift"]'::jsonb,
      false
    )::text,
    updated_at = now()
WHERE name = 'block_step_check';
