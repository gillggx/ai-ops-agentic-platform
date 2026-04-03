"""Models package for the FastAPI Backend Service."""

from app.models.user import UserModel
from app.models.item import ItemModel
from app.models.data_subject import DataSubjectModel
from app.models.event_type import EventTypeModel
from app.models.mcp_definition import MCPDefinitionModel
from app.models.skill_definition import SkillDefinitionModel
from app.models.alarm import AlarmModel
from app.models.system_parameter import SystemParameterModel
from app.models.routine_check import RoutineCheckModel
from app.models.agent_draft import AgentDraftModel
from app.models.agent_memory import AgentMemoryModel
from app.models.user_preference import UserPreferenceModel
from app.models.agent_session import AgentSessionModel
from app.models.mock_data_source import MockDataSourceModel
from app.models.agent_tool import AgentToolModel
from app.models.feedback_log import FeedbackLogModel
from app.models.script_version import ScriptVersionModel
from app.models.cron_job import CronJobModel
from app.models.execution_log import ExecutionLogModel
from app.models.auto_patrol import AutoPatrolModel
from app.models.nats_event_log import NatsEventLogModel

__all__ = [
    "UserModel",
    "ItemModel",
    "DataSubjectModel",
    "EventTypeModel",
    "MCPDefinitionModel",
    "SkillDefinitionModel",
    "AlarmModel",
    "SystemParameterModel",
    "RoutineCheckModel",
    "AgentDraftModel",
    "AgentMemoryModel",
    "UserPreferenceModel",
    "AgentSessionModel",
    "MockDataSourceModel",
    "AgentToolModel",
    "FeedbackLogModel",
    "ScriptVersionModel",
    "CronJobModel",
    "ExecutionLogModel",
    "AutoPatrolModel",
    "NatsEventLogModel",
]
