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
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .background import event_poller, nats_subscriber
from .config import CONFIG
from .routers import agent, briefing, health, pipeline, sandbox

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("python_ai_sidecar")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "python_ai_sidecar starting on port %s | allowed_callers=%s | java_api_url=%s",
        CONFIG.port, CONFIG.allowed_caller_ips, CONFIG.java_api_url,
    )
    await event_poller.get_instance().start()
    await nats_subscriber.get_instance().start()
    try:
        yield
    finally:
        log.info("python_ai_sidecar shutting down background tasks")
        await event_poller.get_instance().stop()
        await nats_subscriber.get_instance().stop()


app = FastAPI(
    title="python_ai_sidecar",
    version="0.1.0",
    description="Internal AI/Executor sidecar — called only by the Java API.",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    path = request.url.path
    if path.startswith("/internal/health"):
        return await call_next(request)
    log.info("→ %s %s caller_ip=%s", request.method, path, request.client.host if request.client else "")
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 — outermost barrier
        log.exception("internal error handling %s %s", request.method, path)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": {"code": "internal_error", "message": str(exc)}},
        )
    log.info("← %s %s status=%s", request.method, path, response.status_code)
    return response


app.include_router(health.router)
app.include_router(agent.router)
app.include_router(pipeline.router)
app.include_router(sandbox.router)
app.include_router(briefing.router)
