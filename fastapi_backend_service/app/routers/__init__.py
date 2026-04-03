"""Routers package for the FastAPI Backend Service."""

from app.routers.auth import router as auth_router
from app.routers.builder_router import router as builder_router
from app.routers.data_subjects import router as data_subjects_router
from app.routers.diagnostic import router as diagnostic_router
from app.routers.event_types import router as event_types_router
from app.routers.items import router as items_router
from app.routers.mcp_definitions import router as mcp_definitions_router
from app.routers.mock_data_router import router as mock_data_router
from app.routers.mock_data_studio_router import router as mock_data_studio_router
from app.routers.skill_definitions import router as skill_definitions_router
from app.routers.system_parameters import router as system_parameters_router
from app.routers.users import router as users_router
# Phase 11
from app.routers.routine_check_router import router as routine_check_router
# v18: alarms replace generated_events
from app.routers.alarms_router import router as alarms_router
# v18: system events webhook ingest
from app.routers.system_events_router import router as system_events_router
# Help Chat
from app.routers.help_router import router as help_router
# v12 Agent routers
from app.routers.agent_router import router as agent_router
from app.routers.agent_execute_router import router as agent_execute_router
from app.routers.agent_draft_router import router as agent_draft_router
# v12.5 Expert Mode
from app.routers.agentic_skill_router import router as agentic_skill_router
# v15.0 Agent Tool Chest
from app.routers.agent_tool_router import router as agent_tool_router
# v15.2 Shadow Analyst
from app.routers.shadow_analyst_router import router as shadow_analyst_router
# v15.3 Generic Tools
from app.routers.generic_tools_router import router as generic_tools_router
# AIOps Automation Platform
from app.routers.script_registry_router import router as script_registry_router
from app.routers.cron_jobs_router import router as cron_jobs_router
from app.routers.actions_router import router as actions_router
# v2.0 Auto-Patrol
from app.routers.auto_patrols import router as auto_patrols_router
# v2.0 Diagnostic Rules
from app.routers.diagnostic_rules import router as diagnostic_rules_router

__all__ = [
    "auth_router",
    "users_router",
    "items_router",
    "diagnostic_router",
    "builder_router",
    "mock_data_router",
    "mock_data_studio_router",
    "data_subjects_router",
    "event_types_router",
    "mcp_definitions_router",
    "skill_definitions_router",
    "system_parameters_router",
    "routine_check_router",
    "alarms_router",
    "system_events_router",
    "help_router",
    "agent_router",
    "agent_execute_router",
    "agent_draft_router",
    "agentic_skill_router",
    "agent_tool_router",
    "shadow_analyst_router",
    "generic_tools_router",
    "script_registry_router",
    "cron_jobs_router",
    "actions_router",
    "auto_patrols_router",
    "diagnostic_rules_router",
]
