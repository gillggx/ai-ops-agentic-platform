"""OOC Event Publisher — publishes SPC_OOC events to NATS.

Subject: aiops.events.ooc

Each publish opens a short-lived connection, sends the message, then closes.
This avoids state management and works even when NATS restarts between events.
If NATS is unavailable the exception is caught and logged — it never crashes the
simulation pipeline.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
NATS_SUBJECT = "aiops.events.ooc"


@dataclass
class OOCDetail:
    rule: str
    value: float
    ucl: float
    lcl: float
    sigma: Optional[float] = None


@dataclass
class OOCEventPayload:
    equipment_id: str
    lot_id: str
    step_id: str
    parameter: str
    ooc_details: OOCDetail
    severity: str = "warning"
    event_type: str = "OOC"
    source: str = "ontology_simulator"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


async def publish_ooc_event(payload: OOCEventPayload) -> None:
    """Publish a single OOC event to NATS. Silently degrades if NATS is down."""
    try:
        import nats  # imported lazily so missing package only fails here

        msg = json.dumps(
            {
                **{k: v for k, v in asdict(payload).items() if k != "ooc_details"},
                "ooc_details": asdict(payload.ooc_details),
            },
            ensure_ascii=False,
        ).encode()

        nc = await nats.connect(NATS_URL, connect_timeout=3)
        try:
            await nc.publish(NATS_SUBJECT, msg)
            await nc.flush()
            logger.info(
                "OOC event published to NATS subject=%s equipment=%s lot=%s",
                NATS_SUBJECT, payload.equipment_id, payload.lot_id,
            )
        finally:
            await nc.close()

    except Exception as exc:
        logger.warning(
            "OOC event publish failed (NATS may be unavailable): %s", exc
        )
