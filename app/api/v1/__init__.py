"""
API v1 Routers - FastAPI Routes for API v1

API v1 路由器 - API v1 的 FastAPI 路由。
"""

from . import (
    agent_compat_router,
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
)

__all__ = [
    "auth",
    "users",
    "data_subjects",
    "event_types",
    "system_parameters",
    "items",
    "mcp_definitions",
    "skill_definitions",
    "diagnostic",
]
