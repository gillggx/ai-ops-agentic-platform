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
            alarm_repo=alarm_repo,
            mcp_executor=None,  # MCP calls inside skill sandbox use async wrapper
        )

        for skill in skills:
            try:
                result = await executor.execute(
                    skill_id=skill.id,
                    event_payload=payload,
                    triggered_by="event_poller",
                )
                if result.alarms_created > 0:
                    logger.info(
                        "Poller: skill=%d event=%s → %d alarms created",
                        skill.id, event_type_name, result.alarms_created,
                    )
                    total_alarms += result.alarms_created
                if not result.success and result.error:
                    logger.warning(
                        "Poller: skill=%d failed: %s", skill.id, result.error
                    )
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
            # Unknown event type — skip silently
            continue

        logger.debug(
            "Poller: new event type=%s equipment=%s lot=%s step=%s",
            ev_type_name,
            ev.get("equipmentID", "?"),
            ev.get("lotID", "?"),
            ev.get("step", "?"),
        )

        try:
            await _process_event(ev, ev_type_name, ev_type_id)
        except Exception as exc:
            logger.exception("Poller: _process_event failed: %s", exc)

        if max_seen is None or ev_time > max_seen:
            max_seen = ev_time

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
    """
    Long-running coroutine — call via asyncio.create_task() in lifespan.
    Polls OntologySimulator every `interval` seconds for new events.
    """
    settings = get_settings()
    sim_url  = settings.ONTOLOGY_SIM_URL
    last_seen: Optional[datetime] = None

    logger.info("EventPoller started (interval=%ds, simulator=%s)", interval, sim_url)

    # Initialise last_seen to 5 min ago so we catch recent OOC events on startup
    from datetime import timedelta
    last_seen = datetime.now(tz=timezone.utc) - timedelta(minutes=5)

    while True:
        try:
            event_type_map = await _load_event_type_map()
            if not event_type_map:
                logger.warning("EventPoller: no event_types in DB — skipping cycle")
            else:
                new_last = await _poll_once(sim_url, last_seen, event_type_map)
                if new_last != last_seen:
                    logger.info("EventPoller: advanced last_seen %s → %s", last_seen, new_last)
                last_seen = new_last
        except asyncio.CancelledError:
            logger.info("EventPoller cancelled, shutting down")
            return
        except Exception as exc:
            logger.exception("EventPoller: unexpected error: %s", exc)

        await asyncio.sleep(interval)
