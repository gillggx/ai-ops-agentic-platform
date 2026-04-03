"""
MCP (Model Context Protocol) Server implementation.

MCP 協議實現和 Tool/Resource 定義。
"""

from .errors import (
    AuthenticationError,
    AuthorizationError,
    InvalidSkillInputError,
    InvalidToolInputError,
    MCPError,
    ProtocolError,
    SkillExecutionError,
    SkillNotFoundError,
    ToolExecutionError,
    ToolNotFoundError,
    ValidationError,
)
from .server import FastAPIMCPServer

__all__ = [
    # Error classes
    "MCPError",
    "ToolNotFoundError",
    "InvalidToolInputError",
    "ToolExecutionError",
    "SkillNotFoundError",
    "SkillExecutionError",
    "InvalidSkillInputError",
    "ProtocolError",
    "AuthenticationError",
    "AuthorizationError",
    "ValidationError",
    # Server
    "FastAPIMCPServer",
]
