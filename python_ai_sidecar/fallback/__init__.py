"""Hybrid-cutover fallback.

Proxies requests the sidecar can't fully handle back to the still-running
old Python FastAPI (``fastapi_backend_service`` on :8001). This lets the
Frontend flip to Java :8002 immediately even though a few sidecar ports
(full LangGraph agent, full pipeline executor, agent_builder) aren't 1:1
yet. Phase 8 replaces each fallback with a native implementation.

Env contract:
    FALLBACK_PYTHON_URL    http://localhost:8001  — old FastAPI base URL
    FALLBACK_PYTHON_TOKEN  <JWT>                   — admin-style token to
                                                     reach authenticated
                                                     endpoints (same JWT the
                                                     sidecar gets from
                                                     Frontend is not usable
                                                     because Java issues it;
                                                     sidecar keeps a dedicated
                                                     service JWT)
    FALLBACK_ENABLED       1                       — master switch
"""
