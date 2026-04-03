"""ContextBuilderService — builds the event_payload dict injected into Skill execution.

Trigger mode determines the source:
  event-triggered  → event payload forwarded directly from NATS (caller provides it)
  schedule-triggered → query DB/OntologySimulator based on data_context value

data_context values:
  "recent_ooc"   → last 20 OOC events from nats_event_logs
  "active_lots"  → current In-Process lots from OntologySimulator
  "tool_status"  → all tool statuses from OntologySimulator

target_scope types (schedule-triggered fan-out):
  "event_driven"    → no fan-out (single context execution)
  "all_equipment"   → fetch all equipment IDs from sim, run Skill per equipment
  "equipment_list"  → use configured equipment_ids list, run Skill per equipment
"""

import json
import logging
from typing import Any, Dict, List

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_DEFAULT_SIM_URL = "http://localhost:8012"


async def build_event_context(event_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Pass event payload through as-is for event-triggered patrols."""
    return event_payload


async def build_schedule_context(
    data_context: str,
    db: AsyncSession,
    sim_url: str = _DEFAULT_SIM_URL,
) -> Dict[str, Any]:
    """Build input context for schedule-triggered patrols.

    Returns a dict shaped as event_payload so SkillExecutorService can consume it
    without changes:
      {
        "trigger": "schedule",
        "data_context": "<name>",
        "data": <fetched records>,
      }
    """
    handler = _CONTEXT_HANDLERS.get(data_context, _fetch_recent_ooc)
    try:
        data = await handler(db=db, sim_url=sim_url)
    except Exception as exc:
        logger.warning("ContextBuilder '%s' fetch failed: %s", data_context, exc)
        data = []

    return {
        "trigger":      "schedule",
        "data_context": data_context,
        "data":         data,
    }


# ── Individual context fetchers ───────────────────────────────────────────────

async def _fetch_recent_ooc(db: AsyncSession, sim_url: str, limit: int = 20) -> list:
    """Last N OOC events from nats_event_logs."""
    try:
        result = await db.execute(
            text("""
                SELECT id, equipment_id, lot_id, payload, received_at
                FROM nats_event_logs
                WHERE event_type_name = 'OOC'
                ORDER BY id DESC
                LIMIT :limit
            """),
            {"limit": limit},
        )
        rows = result.mappings().all()
        items = []
        for r in rows:
            item = {
                "id":           r["id"],
                "equipment_id": r["equipment_id"],
                "lot_id":       r["lot_id"],
                "received_at":  str(r["received_at"]) if r["received_at"] else None,
            }
            try:
                payload = json.loads(r["payload"] or "{}")
                item.update({k: v for k, v in payload.items() if k not in item})
            except Exception:
                pass
            items.append(item)
        return items
    except Exception as exc:
        logger.warning("_fetch_recent_ooc DB query failed: %s", exc)
        return []


async def _fetch_active_lots(db: AsyncSession, sim_url: str) -> list:
    """Current In-Process lots from OntologySimulator."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{sim_url}/api/v1/lots", params={"status": "In-Process"})
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("lots", data.get("data", []))
    except Exception as exc:
        logger.warning("_fetch_active_lots HTTP failed: %s", exc)
        return []


async def _fetch_tool_status(db: AsyncSession, sim_url: str) -> list:
    """All tool statuses from OntologySimulator."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{sim_url}/api/v1/tools")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("tools", data.get("data", []))
    except Exception as exc:
        logger.warning("_fetch_tool_status HTTP failed: %s", exc)
        return []


_CONTEXT_HANDLERS = {
    "recent_ooc":  _fetch_recent_ooc,
    "active_lots": _fetch_active_lots,
    "tool_status": _fetch_tool_status,
}


async def expand_to_targets(
    target_scope: Dict[str, Any],
    data_context: str,
    sim_url: str,
    db: AsyncSession,
) -> List[Dict[str, Any]]:
    """Expand target_scope into a list of per-target payloads for fan-out execution.

    Returns [] for "event_driven" scope (no fan-out needed).
    Each payload contains at minimum: {equipment_id, trigger: "schedule"}.
    """
    scope_type = target_scope.get("type", "event_driven")

    if scope_type == "equipment_list":
        eq_ids = [str(e) for e in target_scope.get("equipment_ids", []) if e]

    elif scope_type == "all_equipment":
        tools = await _fetch_tool_status(db=db, sim_url=sim_url)
        eq_ids = []
        for t in tools:
            eid = t.get("equipment_id") or t.get("id") or t.get("tool_id") or t.get("name")
            if eid:
                eq_ids.append(str(eid))

    else:
        # "event_driven" or unknown → no fan-out
        return []

    if not eq_ids:
        logger.warning("expand_to_targets: scope_type=%s but no equipment IDs resolved", scope_type)
        return []

    logger.info("expand_to_targets: %d targets from scope_type=%s", len(eq_ids), scope_type)
    return [{"equipment_id": eid, "trigger": "schedule"} for eid in eq_ids]
