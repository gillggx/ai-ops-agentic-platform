"""Event poller — Phase 7 real HTTP poll loop.

Pulls from the ontology-simulator HTTP event endpoint (or a custom source
via ``POLLER_SOURCE_URL``) and publishes each new event into Java's
``/internal/generated-events`` endpoint.

Uses an in-memory ``last_seen_id`` watermark (restart = replay). Phase 8+
can persist this via a dedicated Java endpoint.

Env:
    EVENT_POLLER_ENABLED         0|1     master switch (default 0)
    POLLER_SOURCE_URL            http://127.0.0.1:8012/events
    POLLER_INTERVAL_SEC          5
    POLLER_SERVICE_USER_ID       <int>   user_id forwarded to Java audit
    POLLER_SERVICE_ROLES         IT_ADMIN,PE   forwarded roles (CSV)
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
from typing import Optional

import httpx

from ..auth import CallerContext
from ..clients.java_client import JavaAPIClient, JavaAPIError

log = logging.getLogger("python_ai_sidecar.background.event_poller")


class EventPoller:
    def __init__(self, poll_interval_sec: float | None = None):
        self.poll_interval_sec = poll_interval_sec or float(os.getenv("POLLER_INTERVAL_SEC", "5"))
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._last_seen_id: int = -1

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="event-poller")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            self._task.cancel()
            log.warning("event poller forced to cancel")
        self._task = None

    def _caller(self) -> CallerContext:
        uid_raw = os.getenv("POLLER_SERVICE_USER_ID", "").strip()
        uid = int(uid_raw) if uid_raw.isdigit() else None
        roles_csv = os.getenv("POLLER_SERVICE_ROLES", "IT_ADMIN").strip()
        roles = tuple(r.strip() for r in roles_csv.split(",") if r.strip())
        return CallerContext(user_id=uid, roles=roles)

    async def _run(self) -> None:
        if os.getenv("EVENT_POLLER_ENABLED", "0") != "1":
            log.info("event poller disabled (EVENT_POLLER_ENABLED != 1)")
            return
        source_url = os.getenv("POLLER_SOURCE_URL", "http://127.0.0.1:8012/events").rstrip("/")
        log.info("event poller live: source=%s interval=%ss", source_url, self.poll_interval_sec)
        java = JavaAPIClient.for_caller(self._caller())
        while not self._stop.is_set():
            try:
                count = await self._poll_once(source_url, java)
                if count:
                    log.info("published %d new events to Java", count)
            except Exception:  # noqa: BLE001
                log.exception("poller iteration failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_sec)
            except asyncio.TimeoutError:
                pass

    async def _poll_once(self, source_url: str, java: JavaAPIClient) -> int:
        params = {"since_id": self._last_seen_id} if self._last_seen_id > 0 else {}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(source_url, params=params)
            res.raise_for_status()
            payload = res.json()
        except Exception as ex:  # noqa: BLE001
            log.warning("poll source failure: %s", ex)
            return 0

        events = payload.get("events") if isinstance(payload, dict) else payload
        if not isinstance(events, list):
            return 0

        published = 0
        for ev in events:
            if not isinstance(ev, dict):
                continue
            try:
                await self._publish_one(java, ev)
                published += 1
                eid = ev.get("id") or ev.get("event_id")
                if isinstance(eid, int) and eid > self._last_seen_id:
                    self._last_seen_id = eid
            except JavaAPIError as ex:
                log.warning("java publish rejected event %s: %s", ev.get("id"), ex)
        return published

    async def _publish_one(self, java: JavaAPIClient, ev: dict) -> None:
        body = {
            "eventTypeId": ev.get("event_type_id") or ev.get("eventTypeId") or -1,
            "sourceSkillId": ev.get("source_skill_id") or ev.get("sourceSkillId") or -1,
            "sourceRoutineCheckId": ev.get("source_routine_check_id"),
            "mappedParameters": _json.dumps(
                ev.get("mapped_parameters") or ev.get("payload") or {}, ensure_ascii=False),
            "skillConclusion": ev.get("skill_conclusion"),
            "status": ev.get("status", "pending"),
        }
        await java.create_generated_event(body)


_instance: Optional[EventPoller] = None


def get_instance() -> EventPoller:
    global _instance
    if _instance is None:
        _instance = EventPoller()
    return _instance
