"""Parameter Audit Log – Phase 12.

Writes immutable audit rows to MongoDB collection `parameter_audit_log`
whenever an APC parameter or Recipe parameter is modified, regardless of
the source (auto self-correction, recipe version bump, or engineer manual
override). Skills and dashboards query this collection to trace who/what
changed which parameter and when.

Schema (per row):
    eventTime       UTC datetime   when the change happened
    objectName      'APC' | 'RECIPE'
    objectID        APC-001 / RCP-007 / etc.
    parameter       parameter name (e.g. etch_time_offset)
    old_value       float / int / str
    new_value       same
    delta           new - old (numeric only)
    delta_pct       (new-old)/old * 100, numeric only
    source          'apc_auto_correct' | 'recipe_version_bump' | 'engineer:<name>'
    reason          free-text (auto-corrects use 'self-correction toward target')
    metadata        any additional context (recipe version, prev_spc_status, etc.)

A single bulk-write helper (`record_changes`) is offered so callers can push
multiple parameter diffs in one round-trip.
"""
from datetime import datetime
from typing import Any, Iterable
from app.database import get_db


def _safe_delta(old: Any, new: Any) -> tuple[float | None, float | None]:
    """Return (delta, delta_pct) or (None, None) if either side isn't numeric."""
    try:
        old_f = float(old)
        new_f = float(new)
    except (TypeError, ValueError):
        return None, None
    delta = new_f - old_f
    pct = (delta / old_f * 100.0) if old_f != 0 else None
    return round(delta, 6), (round(pct, 4) if pct is not None else None)


async def record_changes(
    *,
    object_name: str,
    object_id: str,
    changes: Iterable[tuple[str, Any, Any]],
    source: str,
    reason: str,
    event_time: datetime | None = None,
    metadata: dict | None = None,
) -> int:
    """Insert one audit row per (param, old, new) tuple. Returns insert count.

    Skips entries where old == new (no real change).
    """
    db = get_db()
    ts = event_time or datetime.utcnow()
    docs: list[dict] = []
    for param, old, new in changes:
        if old == new:
            continue
        delta, delta_pct = _safe_delta(old, new)
        docs.append({
            "eventTime":  ts,
            "objectName": object_name,
            "objectID":   object_id,
            "parameter":  param,
            "old_value":  old,
            "new_value":  new,
            "delta":      delta,
            "delta_pct":  delta_pct,
            "source":     source,
            "reason":     reason,
            "metadata":   metadata or {},
        })
    if not docs:
        return 0
    await db.parameter_audit_log.insert_many(docs)
    return len(docs)


async def record_engineer_override(
    *,
    object_name: str,
    object_id: str,
    parameter: str,
    old_value: Any,
    new_value: Any,
    engineer: str,
    reason: str,
    event_time: datetime | None = None,
) -> str:
    """Convenience for the manual-override cron / API path."""
    db = get_db()
    delta, delta_pct = _safe_delta(old_value, new_value)
    doc = {
        "eventTime":  event_time or datetime.utcnow(),
        "objectName": object_name,
        "objectID":   object_id,
        "parameter":  parameter,
        "old_value":  old_value,
        "new_value":  new_value,
        "delta":      delta,
        "delta_pct":  delta_pct,
        "source":     f"engineer:{engineer}",
        "reason":     reason,
        "metadata":   {},
    }
    result = await db.parameter_audit_log.insert_one(doc)
    return str(result.inserted_id)
