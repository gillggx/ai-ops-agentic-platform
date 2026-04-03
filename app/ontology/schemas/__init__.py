"""
Ontology Layer Pydantic Schemas

Pydantic V2 models for request/response validation across all layers.
用於跨層請求/回應驗證的 Pydantic V2 模型。
"""

from .agent_session import (
    AgentMemoryCreate,
    AgentMemoryRead,
    AgentMemoryUpdate,
    AgentPreferenceCreate,
    AgentPreferenceRead,
    AgentPreferenceUpdate,
    AgentSessionCreate,
    AgentSessionRead,
    AgentSessionUpdate,
    AgentToolCreate,
    AgentToolRead,
    AgentToolUpdate,
)
from .common import BaseSchema, ErrorResponse, PagedResponse, SuccessResponse
from .data_subject import (
    DataSubjectCreate,
    DataSubjectRead,
    DataSubjectUpdate,
)
from .event import EventCreate, EventRead, EventTypeCreate, EventTypeRead
from .generated_event import (
    GeneratedEventCreate,
    GeneratedEventRead,
    GeneratedEventStatusUpdate,
)
from .mcp import MCPCreate, MCPRead, MCPDefinitionCreate, MCPDefinitionRead
from .mock_data import MockDataCreate, MockDataRead, MockDataUpdate
from .skill import SkillCreate, SkillRead, SkillDefinitionCreate, SkillDefinitionRead
from .system_parameter import (
    SystemParameterCreate,
    SystemParameterRead,
    SystemParameterReadWithoutSecret,
    SystemParameterUpdate,
)
from .user import UserCreate, UserRead, UserUpdate, UserLoginSchema, UserRegisterSchema

__all__ = [
    # Common
    "BaseSchema",
    "SuccessResponse",
    "ErrorResponse",
    "PagedResponse",
    # User
    "UserCreate",
    "UserRead",
    "UserUpdate",
    "UserLoginSchema",
    "UserRegisterSchema",
    # Event
    "EventTypeCreate",
    "EventTypeRead",
    "EventCreate",
    "EventRead",
    # Skill
    "SkillDefinitionCreate",
    "SkillDefinitionRead",
    "SkillCreate",
    "SkillRead",
    # MCP
    "MCPDefinitionCreate",
    "MCPDefinitionRead",
    "MCPCreate",
    "MCPRead",
    # DataSubject
    "DataSubjectCreate",
    "DataSubjectRead",
    "DataSubjectUpdate",
    # SystemParameter
    "SystemParameterCreate",
    "SystemParameterRead",
    "SystemParameterReadWithoutSecret",
    "SystemParameterUpdate",
    # AgentSession
    "AgentSessionCreate",
    "AgentSessionRead",
    "AgentSessionUpdate",
    # AgentMemory
    "AgentMemoryCreate",
    "AgentMemoryRead",
    "AgentMemoryUpdate",
    # AgentTool
    "AgentToolCreate",
    "AgentToolRead",
    "AgentToolUpdate",
    # AgentPreference
    "AgentPreferenceCreate",
    "AgentPreferenceRead",
    "AgentPreferenceUpdate",
    # GeneratedEvent
    "GeneratedEventCreate",
    "GeneratedEventRead",
    # MockData
    "MockDataCreate",
    "MockDataRead",
    "MockDataUpdate",
]
