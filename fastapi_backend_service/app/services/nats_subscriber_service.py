"""NATS Subscriber Service — listens for OOC events from the Ontology Simulator.

Subject: aiops.events.ooc

On each message:
  1. Write to nats_event_log table
  2. Look up EventType by name "OOC" in DB
  3. Fan-out to all matching Auto-Patrols via AutoPatrolService.trigger_by_event()

Graceful degradation: if NATS is unreachable on startup, logs a warning and
returns without raising — the HTTP API continues to work normally.

Naming: publisher sends event_type="SPC_OOC"; we normalise to "OOC" to match
the canonical EventType name in the DB.
"""

import asyncio
import json
import logging
from typing import Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)

NATS_SUBJECT = "aiops.events.ooc"
_MAX_LOG_ROWS = 500  # prune log beyond this many rows per event type

# Remap legacy publisher names → canonical DB names
_EVENT_TYPE_ALIASES: dict[str, str] = {
    "SPC_OOC": "OOC",
}

_subscriber_task: Optional[asyncio.Task] = None


async def _write_event_log(db, event_type_name: str, raw: dict) -> None:
    """Persist received event to nats_event_logs; prune oldest beyond cap."""
    try:
        from sqlalchemy import delete, func
        from app.models.nats_event_log import NatsEventLogModel

        entry = NatsEventLogModel(
            event_type_name=event_type_name,
            equipment_id=str(raw.get("equipment_id", "") or ""),
            lot_id=str(raw.get("lot_id", "") or ""),
            payload=json.dumps(raw, ensure_ascii=False),
        )
        db.add(entry)
        await db.flush()

        # Prune: keep only the most recent _MAX_LOG_ROWS rows for this event type
        count_result = await db.execute(
            select(func.count()).where(NatsEventLogModel.event_type_name == event_type_name)
        )
        total = count_result.scalar_one()
        if total > _MAX_LOG_ROWS:
            # find id threshold (keep newest _MAX_LOG_ROWS)
            cutoff_result = await db.execute(
                select(NatsEventLogModel.id)
                .where(NatsEventLogModel.event_type_name == event_type_name)
                .order_by(NatsEventLogModel.id.desc())
                .offset(_MAX_LOG_ROWS - 1)
                .limit(1)
            )
            cutoff_id = cutoff_result.scalar_one_or_none()
            if cutoff_id is not None:
                await db.execute(
                    delete(NatsEventLogModel).where(
                        NatsEventLogModel.event_type_name == event_type_name,
                        NatsEventLogModel.id < cutoff_id,
                    )
                )
    except Exception as exc:
        logger.warning("NATS: failed to write event log: %s", exc)


async def _handle_message(msg, nats_url: str) -> None:
    """Process a single incoming NATS message."""
    try:
        raw = json.loads(msg.data.decode())
    except Exception as exc:
        logger.warning("NATS: failed to decode message: %s", exc)
        return

    # Normalise event_type name
    raw_event_type: str = raw.get("event_type", "OOC")
    event_type_name: str = _EVENT_TYPE_ALIASES.get(raw_event_type, raw_event_type)

    logger.info(
        "NATS: received event_type=%s equipment=%s lot=%s",
        event_type_name,
        raw.get("equipment_id"),
        raw.get("lot_id"),
    )

    try:
        from app.config import get_settings
        from app.database import get_db
        from app.models.event_type import EventTypeModel
        from app.repositories.alarm_repository import AlarmRepository
        from app.repositories.auto_patrol_repository import AutoPatrolRepository
        from app.repositories.skill_definition_repository import SkillDefinitionRepository
        from app.services.auto_patrol_service import AutoPatrolService
        from app.services.skill_executor_service import SkillExecutorService, build_mcp_executor

        settings = get_settings()

        async for db in get_db():
            # 1. Write event log
            await _write_event_log(db, event_type_name, raw)

            # 2. Look up event type
            result = await db.execute(
                select(EventTypeModel).where(EventTypeModel.name == event_type_name)
            )
            event_type = result.scalar_one_or_none()
            if event_type is None:
                logger.warning(
                    "NATS: event_type '%s' not found in DB — log written, fan-out skipped",
                    event_type_name,
                )
                await db.commit()
                break

            # 3. Fan-out to Auto-Patrols
            patrol_service = AutoPatrolService(
                repo=AutoPatrolRepository(db),
                alarm_repo=AlarmRepository(db),
                executor=SkillExecutorService(
                    skill_repo=SkillDefinitionRepository(db),
                    mcp_executor=build_mcp_executor(db, sim_url=settings.ONTOLOGY_SIM_URL),
                ),
                sim_url=settings.ONTOLOGY_SIM_URL,
            )
            responses = await patrol_service.trigger_by_event(
                event_type_id=event_type.id,
                event_payload=raw,
            )
            await db.commit()
            logger.info(
                "NATS: fan-out complete event_type=%s triggered=%d patrols",
                event_type_name,
                len(responses),
            )
            break

    except Exception as exc:
        logger.exception("NATS: error handling event_type=%s: %s", event_type_name, exc)


async def _run_subscriber(nats_url: str) -> None:
    """Long-running coroutine: connect, subscribe, dispatch messages."""
    try:
        import nats

        nc = await nats.connect(nats_url, connect_timeout=5)
        logger.info("NATS: connected to %s — subscribing to '%s'", nats_url, NATS_SUBJECT)

        async def _cb(msg):
            asyncio.create_task(_handle_message(msg, nats_url))

        await nc.subscribe(NATS_SUBJECT, cb=_cb)

        while True:
            await asyncio.sleep(10)

    except asyncio.CancelledError:
        logger.info("NATS: subscriber shutting down")
    except Exception as exc:
        logger.warning(
            "NATS: subscriber failed to start (NATS may be unavailable): %s — "
            "HTTP API continues normally",
            exc,
        )


def start_nats_subscriber(nats_url: str) -> asyncio.Task:
    """Launch the subscriber as a background asyncio task. Called from lifespan."""
    global _subscriber_task
    _subscriber_task = asyncio.create_task(_run_subscriber(nats_url))
    return _subscriber_task


def stop_nats_subscriber() -> None:
    """Cancel the subscriber task. Called on app shutdown."""
    global _subscriber_task
    if _subscriber_task and not _subscriber_task.done():
        _subscriber_task.cancel()
        _subscriber_task = None
