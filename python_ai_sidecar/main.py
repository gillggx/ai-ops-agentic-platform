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
from .feature_flags import parse_feature_flags_header, set_request_overrides, reset_request_overrides
from .logging_config import configure_logging, trace_id_ctx
from .routers import agent, briefing, health, mcp_derivative, pipeline, sandbox, supervisor_runs

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
    log.info(
        "[startup] features: prompt_cache=%s auto_signal=%s "
        "atomic_add_connect=%s auto_verifier=%s strict_tool_id=%s "
        "no_duplicate_node=%s rich_canvas_snapshot=%s plan_knowledge=%s "
        "strict_phase_output=%s construct_param_doc=%s strict_phase_verify=%s "
        "next_memo=%s execute_knowledge=%s layered_plan_knowledge=%s "
        "interactive_brief=%s",
        "on" if CONFIG.enable_prompt_cache else "off",
        "on" if CONFIG.enable_auto_signal else "off",
        "on" if CONFIG.enable_atomic_add_connect else "off",
        "on" if CONFIG.enable_auto_verifier else "off",
        "on" if CONFIG.enable_strict_tool_id else "off",
        "on" if CONFIG.enable_no_duplicate_node else "off",
        "on" if CONFIG.enable_rich_canvas_snapshot else "off",
        "on" if CONFIG.enable_plan_knowledge else "off",
        "on" if CONFIG.enable_strict_phase_output else "off",
        "on" if CONFIG.enable_construct_param_doc else "off",
        "on" if CONFIG.enable_strict_phase_verify else "off",
        "on" if CONFIG.enable_next_memo else "off",
        "on" if CONFIG.enable_execute_knowledge else "off",
        "on" if CONFIG.enable_layered_plan_knowledge else "off",
        "on" if CONFIG.enable_interactive_brief else "off",
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
    flag_overrides = parse_feature_flags_header(request.headers.get("X-Feature-Flags", ""))
    flag_token = set_request_overrides(flag_overrides)
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
        reset_request_overrides(flag_token)
        trace_id_ctx.reset(token)


app.include_router(health.router)
app.include_router(agent.router)
app.include_router(pipeline.router)
app.include_router(sandbox.router)
app.include_router(briefing.router)
app.include_router(mcp_derivative.router)
app.include_router(supervisor_runs.router)
