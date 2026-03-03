"""Routers package for the FastAPI Backend Service."""

from app.routers.auth import router as auth_router
from app.routers.builder_router import router as builder_router
from app.routers.data_subjects import router as data_subjects_router
from app.routers.diagnostic import router as diagnostic_router
from app.routers.event_types import router as event_types_router
from app.routers.items import router as items_router
from app.routers.mcp_definitions import router as mcp_definitions_router
from app.routers.mock_data_router import router as mock_data_router
from app.routers.skill_definitions import router as skill_definitions_router
from app.routers.system_parameters import router as system_parameters_router
from app.routers.users import router as users_router
# Phase 11
from app.routers.routine_check_router import router as routine_check_router
from app.routers.generated_events_router import router as generated_events_router
# Help Chat
from app.routers.help_router import router as help_router

__all__ = [
    "auth_router",
    "users_router",
    "items_router",
    "diagnostic_router",
    "builder_router",
    "mock_data_router",
    "data_subjects_router",
    "event_types_router",
    "mcp_definitions_router",
    "skill_definitions_router",
    "system_parameters_router",
    "routine_check_router",
    "generated_events_router",
    "help_router",
]
