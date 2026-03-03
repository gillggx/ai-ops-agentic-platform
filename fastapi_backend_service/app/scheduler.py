"""APScheduler integration for Routine Check proactive engine (Phase 11).

Scheduler lifecycle:
  startup  → load all active RoutineChecks, add APScheduler jobs
  job fire → run_routine_check_job(check_id) — fetch data, diagnose, map event
  shutdown → graceful scheduler stop

Interval mapping:
  "30m"   → IntervalTrigger(minutes=30)
  "1h"    → IntervalTrigger(hours=1)
  "4h"    → IntervalTrigger(hours=4)
  "8h"    → IntervalTrigger(hours=8)
  "12h"   → IntervalTrigger(hours=12)
  "daily" → IntervalTrigger(days=1)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# One global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None

_INTERVAL_MAP = {
    "30m":   {"minutes": 30},
    "1h":    {"hours": 1},
    "4h":    {"hours": 4},
    "8h":    {"hours": 8},
    "12h":   {"hours": 12},
    "daily": {"days": 1},
}


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------


async def run_routine_check_job(check_id: int, base_url: str = "") -> Dict[str, Any]:
    """Execute a RoutineCheck job: run the Skill, optionally create a GeneratedEvent.

    This function creates its own DB session (called from scheduler, outside a request).
    Returns a summary dict for logging / manual-run response.
    """
    from app.models.routine_check import RoutineCheckModel
    from app.models.skill_definition import SkillDefinitionModel
    from app.models.event_type import EventTypeModel
    from app.repositories.routine_check_repository import RoutineCheckRepository
    from app.repositories.generated_event_repository import GeneratedEventRepository
    from app.repositories.mcp_definition_repository import MCPDefinitionRepository
    from app.repositories.data_subject_repository import DataSubjectRepository
    from app.repositories.skill_definition_repository import SkillDefinitionRepository
    from app.repositories.event_type_repository import EventTypeRepository
    from app.repositories.system_parameter_repository import SystemParameterRepository
    from app.services.mcp_builder_service import MCPBuilderService
    from app.services.event_pipeline_service import EventPipelineService
    from app.services.event_mapping_service import run_llm_mapping

    async with AsyncSessionLocal() as db:
        rc_repo = RoutineCheckRepository(db)
        rc = await rc_repo.get_by_id(check_id)
        if rc is None:
            logger.warning("RoutineCheck id=%d not found, skipping job", check_id)
            return {"error": f"RoutineCheck {check_id} not found"}

        if not rc.is_active:
            logger.info("RoutineCheck id=%d is inactive, skipping", check_id)
            return {"skipped": "inactive"}

        # Load skill_input (mandatory params to feed into the Skill)
        try:
            skill_input: Dict[str, Any] = json.loads(rc.skill_input) if rc.skill_input else {}
        except Exception:
            skill_input = {}

        # Build all repos and services for one run
        skill_repo = SkillDefinitionRepository(db)
        et_repo = EventTypeRepository(db)
        mcp_repo = MCPDefinitionRepository(db)
        ds_repo = DataSubjectRepository(db)
        sp_repo = SystemParameterRepository(db)
        llm = MCPBuilderService(mcp_repo=mcp_repo, ds_repo=ds_repo, sp_repo=sp_repo)

        pipeline = EventPipelineService(
            skill_repo=skill_repo,
            et_repo=et_repo,
            mcp_repo=mcp_repo,
            ds_repo=ds_repo,
            llm=llm,
            sp_repo=sp_repo,
        )

        # Load the skill
        skill = await skill_repo.get_by_id(rc.skill_id)
        if skill is None:
            await rc_repo.update(rc, last_run_at=datetime.now(tz=timezone.utc).isoformat(), last_run_status="ERROR")
            return {"error": f"Skill id={rc.skill_id} not found"}

        # Load the system prompt
        system_prompt = await sp_repo.get_value("PROMPT_SKILL_DIAGNOSIS")

        # Run the skill using skill_input directly (RoutineCheck owns the params)
        logger.info("RoutineCheck[%d] running Skill '%s' with skill_input=%s", check_id, skill.name, skill_input)
        result = await pipeline._run_skill(skill, skill_input, system_prompt, base_url)

        run_status = result.status if not result.error else "ERROR"

        # Update RoutineCheck last-run metadata
        await rc_repo.update(
            rc,
            last_run_at=datetime.now(tz=timezone.utc).isoformat(),
            last_run_status=run_status,
        )

        generated_event_id: Optional[int] = None

        # If ABNORMAL and RoutineCheck has trigger_event_id → map params and create alarm
        if run_status == "ABNORMAL" and rc.trigger_event_id:
            try:
                et = await et_repo.get_by_id(rc.trigger_event_id)
                if et is not None:
                    attrs = json.loads(et.attributes) if et.attributes else []

                    # Use pre-configured mappings if available, otherwise fall back to LLM
                    preconfigured: list = []
                    if rc.event_param_mappings:
                        try:
                            preconfigured = json.loads(rc.event_param_mappings)
                        except Exception:
                            preconfigured = []

                    if preconfigured:
                        # Build mapped_params directly from pre-configured {event_field, mcp_field} list
                        skill_result_dict = result.to_dict()
                        mcp_out = result.mcp_output or {}
                        mapped_params = {}
                        for m in preconfigured:
                            ef = m.get("event_field")
                            mf = m.get("mcp_field")
                            if ef and mf:
                                # Try MCP output first, then skill result, then skill_input
                                val = (
                                    mcp_out.get(mf)
                                    or skill_result_dict.get(mf)
                                    or skill_input.get(mf)
                                )
                                if val is not None:
                                    mapped_params[ef] = val
                        logger.info(
                            "RoutineCheck[%d] used pre-configured event mappings (%d fields)",
                            check_id, len(mapped_params),
                        )
                    else:
                        mapped_params = await run_llm_mapping(
                            skill_name=skill.name,
                            skill_result=result.to_dict(),
                            mcp_output=result.mcp_output,
                            event_type_name=et.name,
                            event_attributes=attrs,
                            preset_parameters=skill_input,
                        )

                    ge_repo = GeneratedEventRepository(db)
                    gen_event = await ge_repo.create(
                        event_type_id=et.id,
                        source_skill_id=skill.id,
                        source_routine_check_id=rc.id,
                        mapped_parameters=mapped_params,
                        skill_conclusion=result.conclusion,
                        status="pending",
                    )
                    generated_event_id = gen_event.id
                    logger.info(
                        "RoutineCheck[%d] created GeneratedEvent id=%d for EventType '%s'",
                        check_id, gen_event.id, et.name,
                    )
                else:
                    logger.warning(
                        "RoutineCheck[%d] has trigger_event_id=%d but EventType not found",
                        check_id, rc.trigger_event_id,
                    )
            except Exception as exc:
                logger.error("RoutineCheck[%d] LLM mapping / event creation failed: %s", check_id, exc)

        return {
            "routine_check_id": check_id,
            "skill_id": skill.id,
            "status": run_status,
            "conclusion": result.conclusion,
            "generated_event_id": generated_event_id,
            "error": result.error,
        }


# ---------------------------------------------------------------------------
# Scheduler management
# ---------------------------------------------------------------------------


def _job_id(check_id: int) -> str:
    return f"routine_check_{check_id}"


def schedule_check(check_id: int, interval: str, base_url: str = "") -> None:
    """Add or replace a job in the scheduler for the given RoutineCheck."""
    sched = get_scheduler()
    kwargs = _INTERVAL_MAP.get(interval, {"hours": 1})
    trigger = IntervalTrigger(**kwargs)
    job_id = _job_id(check_id)

    # Replace if already scheduled
    if sched.get_job(job_id):
        sched.remove_job(job_id)

    sched.add_job(
        run_routine_check_job,
        trigger=trigger,
        id=job_id,
        kwargs={"check_id": check_id, "base_url": base_url},
        replace_existing=True,
        misfire_grace_time=300,  # 5-minute grace window
    )
    logger.info("Scheduled RoutineCheck[%d] every %s (job_id=%s)", check_id, interval, job_id)


def unschedule_check(check_id: int) -> None:
    """Remove a scheduled job for the given RoutineCheck."""
    sched = get_scheduler()
    job_id = _job_id(check_id)
    if sched.get_job(job_id):
        sched.remove_job(job_id)
        logger.info("Removed scheduler job for RoutineCheck[%d]", check_id)


async def start_scheduler(base_url: str = "") -> None:
    """Load all active RoutineChecks from DB and start the scheduler."""
    from app.repositories.routine_check_repository import RoutineCheckRepository

    sched = get_scheduler()
    if sched.running:
        return

    async with AsyncSessionLocal() as db:
        repo = RoutineCheckRepository(db)
        active_checks = await repo.get_active()
        for rc in active_checks:
            schedule_check(rc.id, rc.schedule_interval, base_url)

    sched.start()
    logger.info("APScheduler started with %d active RoutineCheck job(s)", len(active_checks) if 'active_checks' in dir() else 0)


def stop_scheduler() -> None:
    """Gracefully stop the scheduler."""
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        logger.info("APScheduler stopped")
