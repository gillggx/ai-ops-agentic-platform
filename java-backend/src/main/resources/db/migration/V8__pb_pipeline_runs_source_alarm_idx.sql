-- Expression index on pb_pipeline_runs.node_results->>'source_alarm_id'.
-- AlarmEnrichmentService.findAllByAlarmIds runs a JSONB extract + IN scan
-- across all alarms in a list page; without this index Postgres does a
-- full sequential scan of pb_pipeline_runs (~3k rows and growing) per
-- request, which already deadlocked the alarm list endpoint at N≈400.
CREATE INDEX IF NOT EXISTS idx_pb_pipeline_runs_source_alarm_id
    ON pb_pipeline_runs ((node_results::jsonb->>'source_alarm_id'));
