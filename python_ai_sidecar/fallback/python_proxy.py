"""HTTP proxy to the still-running old Python FastAPI on :8001.

All methods accept ``caller`` so the old Python's audit log pins the action
to the real Frontend user (not the sidecar). The sidecar's ``SERVICE_JWT``
env var carries a signed token the old Python will accept — we cannot reuse
the Java-issued JWT because it's signed by a different key.
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator, Optional

import httpx

from ..auth import CallerContext

log = logging.getLogger("python_ai_sidecar.fallback.proxy")


class FallbackDisabledError(RuntimeError):
    """Raised when caller invokes fallback but FALLBACK_ENABLED != 1."""


def _base_url() -> str:
    return os.getenv("FALLBACK_PYTHON_URL", "http://127.0.0.1:8001").rstrip("/")


def _service_jwt() -> str:
    return os.getenv("FALLBACK_PYTHON_TOKEN", "").strip()


def fallback_enabled() -> bool:
    return os.getenv("FALLBACK_ENABLED", "1") == "1"


def _headers(caller: Optional[CallerContext]) -> dict[str, str]:
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    token = _service_jwt()
    if token:
        h["Authorization"] = f"Bearer {token}"
    if caller:
        if caller.user_id is not None:
            h["X-Original-User-Id"] = str(caller.user_id)
        if caller.roles:
            h["X-Original-User-Roles"] = ",".join(caller.roles)
    return h


async def post_json(path: str, body: dict, caller: Optional[CallerContext]) -> dict:
    """POST → old Python, return parsed JSON. Raises on non-2xx."""
    if not fallback_enabled():
        raise FallbackDisabledError(path)
    url = f"{_base_url()}{path}"
    timeout = httpx.Timeout(float(os.getenv("FALLBACK_TIMEOUT_SEC", "120")), connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        res = await client.post(url, headers=_headers(caller), json=body)
    res.raise_for_status()
    try:
        return res.json()
    except ValueError:
        return {"raw": res.text}


async def stream_sse(path: str, body: dict, caller: Optional[CallerContext]) -> AsyncIterator[dict]:
    """POST → old Python with SSE response. Yields parsed events 1:1 back.

    The Frontend expects event frames shaped like
        event: <name>\\ndata: <json>\\n\\n
    We parse and re-emit as dicts for ``EventSourceResponse``.
    """
    if not fallback_enabled():
        raise FallbackDisabledError(path)
    url = f"{_base_url()}{path}"
    timeout = httpx.Timeout(float(os.getenv("FALLBACK_TIMEOUT_SEC", "600")), connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=_headers(caller), json=body) as res:
            if res.status_code >= 400:
                text = await res.aread()
                raise httpx.HTTPStatusError(
                    f"fallback {path} → HTTP {res.status_code}: {text[:200]}",
                    request=res.request, response=res)
            current_event = None
            data_buf: list[str] = []
            async for raw_line in res.aiter_lines():
                line = raw_line.rstrip("\r")
                if line == "":
                    if data_buf or current_event:
                        yield {"event": current_event or "message", "data": "".join(data_buf)}
                    current_event = None
                    data_buf = []
                    continue
                if line.startswith("event:"):
                    current_event = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data_buf.append(line[len("data:"):].lstrip())
                # ignore :heartbeat / id: etc.
            if data_buf or current_event:
                yield {"event": current_event or "message", "data": "".join(data_buf)}


def format_fallback_error(ex: Exception) -> dict:
    """SSE-friendly error frame for when fallback itself dies."""
    return {
        "event": "error",
        "data": json.dumps({
            "source": "sidecar_fallback",
            "error": str(ex)[:300],
            "class": ex.__class__.__name__,
        }),
    }
