"""Cron Scheduler Service — APScheduler-backed cron job lifecycle management.

Responsibilities:
- Persist cron job definitions in DB (via CronJobRepository)
- Register / unregister jobs in APScheduler at runtime
- Execute Skill diagnose() scripts on schedule via ScriptVersionRepository
- Write ExecutionLog for every run
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.repositories.cron_job_repository import CronJobRepository
from app.repositories.execution_log_repository import ExecutionLogRepository
from app.repositories.script_version_repository import ScriptVersionRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.schemas.automation import CronJobCreate, CronJobResponse, CronJobUpdate, EventContext
from app.services.sandbox_service import execute_diagnose_fn

logger = logging.getLogger(__name__)

# Module-level scheduler singleton (created once on app startup)
_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


class CronSchedulerService:
    def __init__(
        self,
        db: AsyncSession,
        cron_repo: CronJobRepository,
        script_repo: ScriptVersionRepository,
        skill_repo: SkillDefinitionRepository,
        log_repo: ExecutionLogRepository,
    ) -> None:
        self._db = db
        self._cron = cron_repo
        self._scripts = script_repo
        self._skills = skill_repo
        self._logs = log_repo
        self._scheduler = get_scheduler()

    # ── List / Get ───────────────────────────────────────────────────────────

    async def list_jobs(self, skill_id: Optional[int] = None) -> List[CronJobResponse]:
        if skill_id is not None:
            rows = await self._cron.get_by_skill(skill_id)
        else:
            rows = await self._cron.get_all_active()
        return [CronJobResponse.model_validate(r) for r in rows]

    async def get_job(self, job_id: int) -> CronJobResponse:
        row = await self._cron.get_by_id(job_id)
        if not row:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"CronJob id={job_id} 不存在")
        return CronJobResponse.model_validate(row)

    # ── Create ───────────────────────────────────────────────────────────────

    async def create_job(self, payload: CronJobCreate, created_by: Optional[str] = None) -> CronJobResponse:
        skill = await self._skills.get_by_id(payload.skill_id)
        if not skill:
            raise AppException(status_code=404, error_code="NOT_FOUND", detail=f"Skill id={payload.skill_id} 不存在")

        # Validate cron expression before persisting
        try:
            CronTrigger.from_crontab(payload.schedule, timezone=payload.timezone)
        except Exception as exc:
            raise AppException(status_code=422, error_code="INVALID_CRON", detail=f"無效的 Cron 表達式：{exc}")

        next_run = self._next_run(payload.schedule, payload.timezone)
        row = await self._cron.create(
            skill_id=payload.skill_id,
            schedule=payload.schedule,
            timezone=payload.timezone,
            label=payload.label,
            created_by=created_by,
            next_run_at=next_run,
        )
        self._register_in_scheduler(row.id, row.schedule, row.timezone)
        logger.info("CronJob created: id=%d skill_id=%d schedule=%s", row.id, row.skill_id, row.schedule)
        return CronJobResponse.model_validate(row)

    # ── Update ───────────────────────────────────────────────────────────────

    async def update_job(self, job_id: int, payload: CronJobUpdate) -> CronJobResponse:
        row = await self._get_or_404(job_id)
        updates: Dict[str, Any] = {k: v for k, v in payload.model_dump().items() if v is not None}
        if "schedule" in updates or "timezone" in updates:
            schedule = updates.get("schedule", row.schedule)
            tz = updates.get("timezone", row.timezone)
            try:
                CronTrigger.from_crontab(schedule, timezone=tz)
            except Exception as exc:
                raise AppException(status_code=422, error_code="INVALID_CRON", detail=f"無效的 Cron 表達式：{exc}")
            updates["next_run_at"] = self._next_run(schedule, tz)
            self._reschedule_in_scheduler(job_id, schedule, tz)
        updated = await self._cron.update(row, **updates)
        return CronJobResponse.model_validate(updated)

    # ── Delete ───────────────────────────────────────────────────────────────

    async def delete_job(self, job_id: int) -> None:
        row = await self._get_or_404(job_id)
        await self._cron.soft_delete(row)
        self._remove_from_scheduler(job_id)
        logger.info("CronJob deleted: id=%d", job_id)

    # ── Scheduler registration ────────────────────────────────────────────────

    def _register_in_scheduler(self, job_id: int, schedule: str, timezone: str) -> None:
        sched = self._scheduler
        if not sched.running:
            logger.warning("Scheduler not running — job %d will be registered on next startup", job_id)
            return
        try:
            trigger = CronTrigger.from_crontab(schedule, timezone=timezone)
            sched.add_job(
                _run_cron_job,
                trigger=trigger,
                id=f"cron_{job_id}",
                kwargs={"job_id": job_id},
                replace_existing=True,
                misfire_grace_time=300,
            )
        except Exception as exc:
            logger.error("Failed to register cron job %d in scheduler: %s", job_id, exc)

    def _reschedule_in_scheduler(self, job_id: int, schedule: str, timezone: str) -> None:
        self._remove_from_scheduler(job_id)
        self._register_in_scheduler(job_id, schedule, timezone)

    def _remove_from_scheduler(self, job_id: int) -> None:
        sched = self._scheduler
        try:
            sched.remove_job(f"cron_{job_id}")
        except Exception:
            pass  # job may not exist

    @staticmethod
    def _next_run(schedule: str, timezone: str) -> Optional[datetime]:
        try:
            from apscheduler.triggers.cron import CronTrigger as CT
            trigger = CT.from_crontab(schedule, timezone=timezone)
            from zoneinfo import ZoneInfo
            return trigger.get_next_fire_time(None, datetime.now(tz=ZoneInfo(timezone)))
        except Exception:
            return None


# ── Standalone cron runner (called by APScheduler in background) ─────────────

async def _run_cron_job(job_id: int) -> None:
    """Execute the active ScriptVersion for a CronJob. Called by APScheduler."""
    from app.database import AsyncSessionLocal  # avoid circular import at module level

    async with AsyncSessionLocal() as db:
        cron_repo = CronJobRepository(db)
        script_repo = ScriptVersionRepository(db)
        log_repo = ExecutionLogRepository(db)

        job = await cron_repo.get_by_id(job_id)
        if not job or job.status != "active":
            logger.warning("CronJob %d skipped (not found or not active)", job_id)
            return

        script = await script_repo.get_active(job.skill_id)
        if not script:
            logger.warning("CronJob %d: no active ScriptVersion for skill_id=%d", job_id, job.skill_id)
            return

        event_ctx = EventContext(
            event_type="cron",
            eventTime=datetime.now(tz=timezone.utc).isoformat(),
            severity="info",
            payload={"cron_job_id": job_id, "schedule": job.schedule},
        )

        log = await log_repo.create(
            skill_id=job.skill_id,
            triggered_by="cron",
            event_context=event_ctx.model_dump(),
            script_version_id=script.id,
            cron_job_id=job_id,
        )

        t0 = time.monotonic()
        try:
            result = await execute_diagnose_fn(
                code=script.code,
                mcp_outputs={"event_context": event_ctx.model_dump()},
                timeout=10.0,
            )
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            await log_repo.finish(
                log,
                status="success",
                llm_readable_data=result,
                duration_ms=elapsed_ms,
            )
            logger.info("CronJob %d executed successfully in %dms", job_id, elapsed_ms)
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            await log_repo.finish(
                log,
                status="timeout" if isinstance(exc, TimeoutError) else "error",
                error_message=str(exc),
                duration_ms=elapsed_ms,
            )
            logger.error("CronJob %d failed: %s", job_id, exc)

        # Update last/next run timestamps
        from apscheduler.triggers.cron import CronTrigger
        try:
            trigger = CronTrigger.from_crontab(job.schedule, timezone=job.timezone)
            from zoneinfo import ZoneInfo
            next_run = trigger.get_next_fire_time(None, datetime.now(tz=ZoneInfo(job.timezone)))
        except Exception:
            next_run = None
        await cron_repo.mark_run(job, next_run_at=next_run)


async def load_all_jobs_into_scheduler(db: AsyncSession) -> None:
    """Called on app startup — re-register all active cron jobs in APScheduler."""
    cron_repo = CronJobRepository(db)
    jobs = await cron_repo.get_all_active()
    sched = get_scheduler()
    for job in jobs:
        try:
            trigger = CronTrigger.from_crontab(job.schedule, timezone=job.timezone)
            sched.add_job(
                _run_cron_job,
                trigger=trigger,
                id=f"cron_{job.id}",
                kwargs={"job_id": job.id},
                replace_existing=True,
                misfire_grace_time=300,
            )
            logger.info("Loaded CronJob id=%d schedule=%s into scheduler", job.id, job.schedule)
        except Exception as exc:
            logger.error("Failed to load CronJob id=%d into scheduler: %s", job.id, exc)
