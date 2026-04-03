"""
FastAPI Application Entry Point

FastAPI 应用程序入口。
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import Settings
from app.core.database import initialize_database, shutdown_database, DatabaseConfig
from app.core.initialization import init_database, seed_database

from app.ai_agent.mcp import FastAPIMCPServer
from app.ai_agent.skills import (
    AgentManagementSkill,
    AnalyticsSkill,
    BusinessLogicSkill,
    DataProcessingSkill,
)
from app.api.routes import user_routes
from app.api.v1 import (
    auth,
    users,
    data_subjects,
    event_types,
    system_parameters,
    items,
    mcp_definitions,
    skill_definitions,
    diagnostic,
    simulator_proxy,
    agent_router,
    agent_draft_router,
    agent_execute_router,
    agent_chat_router,
    agent_memory_router,
    agent_preference_router,
    agent_tool_router,
    builder_router,
    event_router,
    generated_event_router,
    agent_chat_router as agent_chat_router_v2,
    routine_check_router,
    mock_data_router,
    mock_data_studio_router,
    help_router,
    agentic_skill_router,
    shadow_analyst_router,
    generic_tools_router,
)
from app.api.v1 import agent_compat_router
from app.ai_ops import HealthCheck, MetricsCollector


_settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init DB tables + seed
    db_url = _settings.get_database_url()
    await init_database(db_url)
    await initialize_database(DatabaseConfig(url=db_url))
    # Seed initial data
    from app.core.database import get_async_session
    async for session in get_async_session():
        await seed_database(session)
        break
    yield
    # Shutdown
    await shutdown_database()


def create_app() -> FastAPI:
    """
    Create and configure FastAPI application.
    
    Returns:
        FastAPI - Configured application instance
    
    创建和配置 FastAPI 应用程序。
    """
    # Create FastAPI instance
    app = FastAPI(
        title="Glass Box AI Diagnostic Platform",
        description="Three-layer FastAPI backend with MCP Skills",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialize MCP Server
    mcp_server = FastAPIMCPServer(app, prefix="/mcp")

    # Register skills
    mcp_server.register_skill(AgentManagementSkill())
    mcp_server.register_skill(DataProcessingSkill())
    mcp_server.register_skill(AnalyticsSkill())
    mcp_server.register_skill(BusinessLogicSkill())

    # Initialize monitoring
    metrics = MetricsCollector()
    health_check = HealthCheck()

    # Register health checks
    health_check.register_check("database", lambda: True)
    health_check.register_check("cache", lambda: True)

    # Include API routes
    app.include_router(user_routes, prefix="/api/v1")
    
    # Include v1 routers (all under /api/v1)
    _v1 = "/api/v1"
    # Phase 1A/1B: Core foundation
    app.include_router(auth.router, prefix=_v1)
    app.include_router(users.router, prefix=_v1)
    app.include_router(data_subjects.router, prefix=_v1)
    app.include_router(event_types.router, prefix=_v1)
    app.include_router(system_parameters.router, prefix=_v1)
    app.include_router(items.router, prefix=_v1)

    # Phase 1C: MCP/Skill/Diagnostic (already have /api/v1 in their own prefix)
    app.include_router(mcp_definitions.router)
    app.include_router(skill_definitions.router)
    app.include_router(diagnostic.router)

    # Phase 2: Agent Routers (already have /api/v1 in their own prefix)
    app.include_router(agent_router.router)
    app.include_router(agent_draft_router.router)
    app.include_router(agent_execute_router.router)
    app.include_router(agent_chat_router.router)
    app.include_router(agent_memory_router.router)
    app.include_router(agent_preference_router.router)
    app.include_router(agent_tool_router.router)

    # Phase 3: P1 Routers (already have /api/v1 in their own prefix)
    app.include_router(builder_router.router)
    app.include_router(event_router.router)
    app.include_router(generated_event_router.router)

    # New routers ported from fastapi_backend_service
    app.include_router(agent_chat_router_v2.router)   # replaces old agent-chat, SSE streaming
    app.include_router(routine_check_router.router)
    app.include_router(mock_data_router.router)
    app.include_router(mock_data_studio_router.router)
    app.include_router(help_router.router)
    app.include_router(agentic_skill_router.router)
    app.include_router(shadow_analyst_router.router)
    app.include_router(generic_tools_router.router)
    app.include_router(agent_compat_router.router)

    # Simulator proxy — /simulator-api/* → localhost:8099
    app.include_router(simulator_proxy.router)

    # Simulator static frontend — Next.js export served at /simulator
    _sim_static = os.path.join(
        os.path.dirname(__file__), "ontology_simulator", "frontend", "out"
    )
    if os.path.isdir(_sim_static):
        app.mount("/simulator", StaticFiles(directory=_sim_static, html=True), name="simulator")

    # Serve static frontend
    _static_dir = os.path.join(os.path.dirname(__file__), "fastapi_backend_service", "static")
    if os.path.isdir(_static_dir):
        app.mount("/static", StaticFiles(directory=_static_dir), name="static")

        # Serve root-level static assets referenced by index.html
        for _fname in ["app.js", "builder.js", "cjr.js", "v143_patch.js",
                        "style.css", "cjr.css", "v143_styles.css"]:
            _fpath = os.path.join(_static_dir, _fname)
            if os.path.isfile(_fpath):
                def _make_route(p=_fpath):
                    async def _serve():
                        return FileResponse(p)
                    return _serve
                app.get(f"/{_fname}")(_make_route())

        @app.get("/")
        async def root():
            return FileResponse(os.path.join(_static_dir, "index.html"))
    else:
        @app.get("/")
        async def root():
            return {"service": "Glass Box AI Diagnostic Platform", "version": "2.0.0", "status": "running"}

    # Health check endpoint
    @app.get("/health")
    async def health():
        """Health check endpoint."""
        checks = await health_check.run_checks()
        overall = health_check.get_status()
        return {
            "overall": overall["overall"],
            "checks": checks,
            "metrics": metrics.get_all_metrics(),
        }

    # Metrics endpoint
    @app.get("/metrics")
    async def get_metrics():
        """Get system metrics."""
        return {
            "metrics": metrics.get_all_metrics(),
            "mcp_skills": mcp_server.get_skill_count(),
        }

    return app


# Create application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
