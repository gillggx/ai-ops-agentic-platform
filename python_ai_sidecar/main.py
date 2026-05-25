"""python_ai_sidecar — FastAPI entry-point.

Run with:
    uvicorn python_ai_sidecar.main:app --port 8050

All routes are mounted under ``/internal/*`` and gated by
``require_service_token`` (see ``auth.py``). Background tasks (event poller,
NATS subscriber) are lifecycle-managed here and gated by env flags so ops can
enable each one independently without a code change.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .background import event_poller, nats_subscriber, embedding_backfill
from .config import CONFIG
from .logging_config import configure_logging, trace_id_ctx
from .routers import agent, briefing, health, pipeline, sandbox

configure_logging("python_ai_sidecar")
log = logging.getLogger("python_ai_sidecar")

# Reject malformed X-Trace-ID values from untrusted callers (length cap + charset).
_TRACE_ID_VALID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "python_ai_sidecar starting on port %s | allowed_callers=%s | java_api_url=%s",
        CONFIG.port, CONFIG.allowed_caller_ips, CONFIG.java_api_url,
    )
    # Boot-time drift check: BUILTIN_EXECUTORS vs SIDECAR_NATIVE_BLOCKS vs
    # pb_blocks DB. Logs at ERROR level if any registry is out of sync —
    # see _boot_invariants.py for context on the four-layer registration.
    try:
        from ._boot_invariants import check_block_consistency
        from .clients.java_client import JavaAPIClient
        await check_block_consistency(
            JavaAPIClient(CONFIG.java_api_url, CONFIG.java_internal_token,
                          timeout_sec=CONFIG.java_timeout_sec)
        )
    except Exception as exc:  # noqa: BLE001 — invariants must never block boot
        log.warning("boot invariant check itself failed: %s", exc)

    await event_poller.get_instance().start()
    await nats_subscriber.get_instance().start()
    await embedding_backfill.get_instance().start()
    try:
        yield
    finally:
        log.info("python_ai_sidecar shutting down background tasks")
        await event_poller.get_instance().stop()
        await nats_subscriber.get_instance().stop()
        await embedding_backfill.get_instance().stop()


app = FastAPI(
    title="python_ai_sidecar",
    version="0.1.0",
    description="Internal AI/Executor sidecar — called only by the Java API.",
    lifespan=lifespan,
)


@app.middleware("http")
async def trace_and_log_requests(request: Request, call_next):
    inbound = request.headers.get("X-Trace-ID", "")
    tid = inbound if _TRACE_ID_VALID.match(inbound) else str(uuid.uuid4())
    token = trace_id_ctx.set(tid)
    path = request.url.path
    is_health = path.startswith("/internal/health")
    try:
        if not is_health:
            log.info(
                "request.start",
                extra={"context": {
                    "method": request.method,
                    "path": path,
                    "caller_ip": request.client.host if request.client else "",
                }},
            )
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 — outermost barrier
            log.exception(
                "request.error",
                extra={"context": {"method": request.method, "path": path}},
            )
            response = JSONResponse(
                status_code=500,
                content={"ok": False, "error": {"code": "internal_error", "message": str(exc)}},
            )
        if not is_health:
            log.info(
                "request.end",
                extra={"context": {
                    "method": request.method, "path": path, "status": response.status_code,
                }},
            )
        response.headers["X-Trace-ID"] = tid
        return response
    finally:
        trace_id_ctx.reset(token)


app.include_router(health.router)
app.include_router(agent.router)
app.include_router(pipeline.router)
app.include_router(sandbox.router)
app.include_router(briefing.router)
