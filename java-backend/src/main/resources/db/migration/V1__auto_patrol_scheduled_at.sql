-- P3: one-shot Auto-Patrol trigger.
-- trigger_mode="once" + scheduled_at (UTC) fires a single DateTrigger job
-- in APScheduler; after the job fires, auto_patrol_service.py deactivates the
-- row (is_active=false) so startup re-registration skips it.
ALTER TABLE auto_patrols
    ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMP WITH TIME ZONE;
