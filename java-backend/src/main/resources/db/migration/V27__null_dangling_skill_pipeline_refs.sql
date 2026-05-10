-- V27 — Phase 11 v6 follow-up: null out skill_documents pipeline refs
-- whose underlying pb_pipelines row was deleted in V26.
--
-- skill_documents.confirm_check (JSON) and skill_documents.steps (JSON
-- array) carry pipeline_id refs that V26 didn't cascade-clean (the FK
-- target lived inside JSON text, not a pg-managed column). Without this
-- cleanup, the Skill page's "Refine" button generates a builder-url
-- pointing at /admin/pipeline-builder/<deleted_id> which 404s.
--
-- Idempotent. Skill structure (description, suggested_actions, etc.) is
-- preserved; only the dangling pipeline_id is set to null so the slot
-- shows up as "needs build" again in the UI.

-- ── confirm_check: null out pipeline_id when pipeline doesn't exist ──
UPDATE skill_documents
SET confirm_check = jsonb_set(
        confirm_check::jsonb,
        '{pipeline_id}',
        'null'::jsonb,
        true
    )::text
WHERE confirm_check IS NOT NULL
  AND confirm_check != ''
  AND (confirm_check::jsonb->>'pipeline_id') IS NOT NULL
  AND (confirm_check::jsonb->>'pipeline_id')::int NOT IN (
      SELECT id FROM pb_pipelines
  );

-- ── steps[].pipeline_id: same cleanup, but per-element on the JSON array ──
-- We rebuild the array by iterating, nulling the pipeline_id field on
-- elements whose target pipeline no longer exists.
UPDATE skill_documents AS sd
SET steps = (
    SELECT jsonb_agg(
        CASE
            WHEN step ? 'pipeline_id'
                 AND step->>'pipeline_id' IS NOT NULL
                 AND (step->>'pipeline_id')::int NOT IN (SELECT id FROM pb_pipelines)
            THEN jsonb_set(step, '{pipeline_id}', 'null'::jsonb)
            ELSE step
        END
    )::text
    FROM jsonb_array_elements(sd.steps::jsonb) AS step
)
WHERE sd.steps IS NOT NULL
  AND sd.steps != ''
  AND sd.steps != '[]'
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements(sd.steps::jsonb) AS step
      WHERE step ? 'pipeline_id'
        AND step->>'pipeline_id' IS NOT NULL
        AND (step->>'pipeline_id')::int NOT IN (SELECT id FROM pb_pipelines)
  );

DO $$
DECLARE
  cnt_cc INTEGER;
  cnt_steps INTEGER;
BEGIN
  SELECT COUNT(*) INTO cnt_cc FROM skill_documents
   WHERE confirm_check IS NOT NULL AND (confirm_check::jsonb->>'pipeline_id') IS NULL;
  RAISE NOTICE 'V27 cleanup: skills with null confirm_check.pipeline_id = %', cnt_cc;
END
$$;
