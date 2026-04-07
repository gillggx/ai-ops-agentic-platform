"""EventPollerService v18 — Background poller for OntologySimulator events.

Design:
- Runs as an asyncio background task (started in lifespan).
- Every POLL_INTERVAL seconds, fetches recent events from Simulator.
- Tracks last-seen event time in memory (resets on restart — acceptable).
- For each new event, finds active Skills with matching trigger_event_id
  and trigger_mode in ('event', 'both'), then executes them in sandbox.
- trigger_alarm() inside Skills writes to the alarms table.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.repositories.alarm_repository import AlarmRepository
from app.repositories.event_type_repository import EventTypeRepository
from app.repositories.skill_definition_repository import SkillDefinitionRepository
from app.services.skill_executor_service import SkillExecutorService

logger = logging.getLogger(__name__)

# ── Default poll interval (seconds) ─────────────────────────────────────────
_DEFAULT_POLL_INTERVAL = 30


def _to_utc(ts: Any) -> Optional[datetime]:
    """Parse ISO8601 timestamp string → UTC-aware datetime. Returns None on failure."""
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _build_standard_payload(event: Dict[str, Any], event_type_name: str) -> Dict[str, Any]:
    """Normalise a Simulator event dict → v18 Standard Event Payload."""
    return {
        "event_type":   event_type_name,
        "equipment_id": event.get("toolID") or event.get("equipmentID") or event.get("eqpID") or event.get("equipment_id", ""),
        "lot_id":       event.get("lotID") or event.get("lot_id", ""),
        "step":         event.get("step", ""),
        "event_time":   event.get("eventTime") or event.get("event_time", ""),
    }


async def _fetch_sim_events(sim_url: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch recent events from the OntologySimulator."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{sim_url}/api/v1/events", params={"limit": limit})
        resp.raise_for_status()
        data = resp.json()
    return data if isinstance(data, list) else []


async def _process_event(
    event: Dict[str, Any],
    event_type_name: str,
    event_type_id: int,
) -> int:
    """Find matching Skills and execute them. Returns number of alarms created."""
    total_alarms = 0
    payload = _build_standard_payload(event, event_type_name)

    async with AsyncSessionLocal() as db:
        skill_repo = SkillDefinitionRepository(db)
        alarm_repo = AlarmRepository(db)
        skills = await skill_repo.list_by_trigger_event(event_type_id)

        if not skills:
            return 0

        executor = SkillExecutorService(
            skill_repo=skill_repo,
            mcp_executor=None,
        )

        from app.repositories.auto_patrol_repository import AutoPatrolRepository
        from app.models.execution_log import ExecutionLogModel
        patrol_repo = AutoPatrolRepository(db)

        for skill in skills:
            started_at = datetime.now(tz=timezone.utc)
            try:
                result = await executor.execute(
                    skill_id=skill.id,
                    event_payload=payload,
                    triggered_by="event_poller",
                )
                finished_at = datetime.now(tz=timezone.utc)
                duration_ms = int((finished_at - started_at).total_seconds() * 1000)

                # Get patrol config for alarm severity/title
                patrol = await patrol_repo.get_by_skill_id(skill.id)

                findings = result.findings
                condition_met = findings.condition_met if findings else False
                summary = findings.summary if findings else ""
                action = None

                # Create alarm if condition met
                if result.success and condition_met:
                    alarm_data = {
                        "skill_id": skill.id,
                        "trigger_event": event_type_name,
                        "equipment_id": payload.get("equipment_id", ""),
                        "lot_id": payload.get("lot_id", ""),
                        "step": payload.get("step", ""),
                        "event_time": payload.get("event_time", ""),
                        "severity": (patrol.alarm_severity if patrol else "HIGH"),
                        "title": (patrol.alarm_title if patrol else skill.name),
                        "summary": summary,
                        "status": "active",
                    }
                    alarm = await alarm_repo.create(alarm_data)
                    total_alarms += 1
                    action = "alarm_created"
                    logger.info(
                        "Poller: skill=%d → ALARM created (id=%s, severity=%s)",
                        skill.id, alarm.id, alarm_data["severity"],
                    )
                else:
                    logger.info(
                        "Poller: skill=%d → condition_met=%s, no alarm",
                        skill.id, condition_met,
                    )

                # Write execution log (always, regardless of condition_met)
                exec_log = ExecutionLogModel(
                    skill_id=skill.id,
                    auto_patrol_id=patrol.id if patrol else None,
                    triggered_by="event_poller",
                    event_context=json.dumps(payload, ensure_ascii=False, default=str),
                    status="success" if result.success else "error",
                    llm_readable_data=json.dumps({
                        "condition_met": condition_met,
                        "summary": summary,
                        "outputs": findings.outputs if findings else {},
                    }, ensure_ascii=False, default=str) if findings else None,
                    action_dispatched=action,
                    error_message=result.error if not result.success else None,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                )
                db.add(exec_log)
                await db.commit()

            except Exception as exc:
                logger.exception("Poller: unhandled error in skill=%d: %s", skill.id, exc)

    return total_alarms


async def _poll_once(
    sim_url: str,
    last_seen: Optional[datetime],
    event_type_map: Dict[str, int],  # {event_name: event_type_id}
) -> Optional[datetime]:
    """
    Perform one poll cycle.
    Returns the new last_seen timestamp (max eventTime seen this cycle),
    or the existing last_seen if nothing new was found.
    """
    try:
        events = await _fetch_sim_events(sim_url)
    except Exception as exc:
        logger.warning("Poller: failed to fetch from Simulator: %s", exc)
        return last_seen

    new_events = []
    for ev in events:
        ev_time = _to_utc(ev.get("eventTime") or ev.get("event_time"))
        if ev_time and (last_seen is None or ev_time > last_seen):
            new_events.append((ev_time, ev))

    if not new_events:
        logger.debug("Poller: no new events since %s", last_seen)
        return last_seen

    ooc_count = sum(1 for _, ev in new_events if ev.get("spc_status") == "OOC")
    logger.info("Poller: %d new events (%d OOC) since %s", len(new_events), ooc_count, last_seen)

    # Sort ascending so we process in order
    new_events.sort(key=lambda x: x[0])
    max_seen = last_seen

    for ev_time, ev in new_events:
        # Always advance max_seen regardless of event type match
        if max_seen is None or ev_time > max_seen:
            max_seen = ev_time

        # Determine logical event type name:
        # Simulator emits TOOL_EVENT/LOT_EVENT with spc_status field.
        # Map spc_status=OOC → "OOC" event type for Auto-Patrol matching.
        raw_type = ev.get("eventType") or ev.get("event_type", "")
        spc_status = ev.get("spc_status", "")
        if spc_status == "OOC":
            ev_type_name = "OOC"
        else:
            ev_type_name = raw_type

        ev_type_id = event_type_map.get(ev_type_name)
        if not ev_type_id:
            continue

        _poller_stats["ooc_detected"] += 1
        _poller_stats["total_events_processed"] += 1
        logger.info(
            "Poller: matched event type=%s equipment=%s lot=%s step=%s",
            ev_type_name, ev.get("toolID", "?"), ev.get("lotID", "?"), ev.get("step", "?"),
        )

        # Update event_type received count in DB (for Event Registry page)
        try:
            from app.models.event_type import EventTypeModel
            async with AsyncSessionLocal() as _db:
                from sqlalchemy import update
                await _db.execute(
                    update(EventTypeModel)
                    .where(EventTypeModel.id == ev_type_id)
                    .values(updated_at=datetime.now(tz=timezone.utc))
                )
                await _db.commit()
        except Exception:
            pass  # non-blocking

        try:
            _poller_stats["skills_triggered"] += 1
            await _process_event(ev, ev_type_name, ev_type_id)
        except Exception as exc:
            _poller_stats["errors"] += 1
            logger.exception("Poller: _process_event failed: %s", exc)

    return max_seen


async def _load_event_type_map() -> Dict[str, int]:
    """Load all active event_types from DB → {name: id}."""
    async with AsyncSessionLocal() as db:
        repo = EventTypeRepository(db)
        ets = await repo.get_all()
    return {
        et.name: et.id
        for et in ets
        if getattr(et, "is_active", True)
    }


async def run_event_poller(interval: int = _DEFAULT_POLL_INTERVAL) -> None:
    """Long-running coroutine — polls simulator for OOC events."""
    settings = get_settings()
    sim_url = settings.ONTOLOGY_SIM_URL
    from datetime import timedelta
    last_seen = datetime.now(tz=timezone.utc) - timedelta(minutes=5)

    _poller_stats["status"] = "RUNNING"
    _poller_stats["started_at"] = datetime.now(tz=timezone.utc).isoformat()
    logger.info("EventPoller started (interval=%ds, simulator=%s)", interval, sim_url)

    while True:
        try:
            _poller_stats["total_polls"] += 1
            _poller_stats["last_poll_at"] = datetime.now(tz=timezone.utc).isoformat()

            event_type_map = await _load_event_type_map()
            if event_type_map:
                new_last = await _poll_once(sim_url, last_seen, event_type_map)
                if new_last != last_seen:
                    logger.info("EventPoller: advanced last_seen %s → %s", last_seen, new_last)
                    _poller_stats["last_seen_event"] = new_last.isoformat() if new_last else None
                last_seen = new_last
        except asyncio.CancelledError:
            _poller_stats["status"] = "STOPPED"
            return
        except Exception as exc:
            _poller_stats["errors"] += 1
            _poller_stats["status"] = "ERROR"
            logger.exception("EventPoller: unexpected error: %s", exc)
        await asyncio.sleep(interval)


# ── APScheduler-compatible job (called every 30s by cron_scheduler) ────────────

_poller_last_seen: Optional[datetime] = None

# ── Observable stats for System Monitor ────────────────────────────────────
_poller_stats: Dict[str, Any] = {
    "status": "NOT_STARTED",
    "started_at": None,
    "last_poll_at": None,
    "last_seen_event": None,
    "total_polls": 0,
    "total_events_processed": 0,
    "ooc_detected": 0,
    "skills_triggered": 0,
    "errors": 0,
}


def get_poller_stats() -> Dict[str, Any]:
    """Return a snapshot of poller health stats for the monitor endpoint."""
    return dict(_poller_stats)


_main_loop = None  # set during startup


def set_event_loop(loop) -> None:
    """Called from lifespan to capture the main uvicorn event loop."""
    global _main_loop
    _main_loop = loop


def poll_once_job() -> None:
    """Sync entry point for APScheduler — schedules async poll on uvicorn's event loop."""
    import asyncio
    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(_poll_once_async(), _main_loop)
    else:
        logger.warning("EventPoller: no event loop available")


async def _poll_once_async() -> None:
    """Single async poll cycle, maintains state in module-level _poller_last_seen."""
    global _poller_last_seen
    from datetime import timedelta

    if _poller_last_seen is None:
        _poller_last_seen = datetime.now(tz=timezone.utc) - timedelta(minutes=5)

    settings = get_settings()
    sim_url = settings.ONTOLOGY_SIM_URL

    try:
        event_type_map = await _load_event_type_map()
        if not event_type_map:
            logger.warning("EventPoller: no event_types in DB")
            return

        new_last = await _poll_once(sim_url, _poller_last_seen, event_type_map)
        if new_last != _poller_last_seen:
            logger.info("EventPoller: advanced %s → %s", _poller_last_seen, new_last)
        _poller_last_seen = new_last
    except Exception as exc:
        logger.exception("EventPoller job error: %s", exc)
