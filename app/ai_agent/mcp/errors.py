"""
MCP Server error classes.

Define custom exceptions for MCP protocol implementation.
定義 MCP 協議實現的自定義異常。
"""


class MCPError(Exception):
    """
    Base exception for all MCP protocol errors.
    
    MCP 協議所有錯誤的基類。
    
    Attributes:
        message: str - Error message
        code: str - Error code for identification
        status_code: int - HTTP status code (if applicable)
    """

    def __init__(
        self,
        message: str,
        code: str = "mcp_error",
        status_code: int = 500,
    ):
        """
        Initialize MCPError.
        
        Args:
            message: Human-readable error message
            code: Error identifier code
            status_code: HTTP status code (default: 500)
        """
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """
        Convert error to dictionary representation.
        
        Returns:
            dict - {code, message, status_code}
        
        轉換為字典表示，用於 API 響應。
        """
        return {
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
        }


class ToolNotFoundError(MCPError):
    """
    Raised when a requested tool is not found.
    
    當請求的工具不存在時拋出。
    """

    def __init__(self, tool_name: str):
        super().__init__(
            message=f"Tool '{tool_name}' not found",
            code="tool_not_found",
            status_code=404,
        )
        self.tool_name = tool_name


class InvalidToolInputError(MCPError):
    """
    Raised when tool input is invalid.
    
    當工具輸入無效時拋出。
    """

    def __init__(self, tool_name: str, reason: str):
        super().__init__(
            message=f"Invalid input for tool '{tool_name}': {reason}",
            code="invalid_tool_input",
            status_code=400,
        )
        self.tool_name = tool_name
        self.reason = reason


class ToolExecutionError(MCPError):
    """
    Raised when a tool fails during execution.
    
    當工具執行失敗時拋出。
    """

    def __init__(self, tool_name: str, error: str):
        super().__init__(
            message=f"Tool '{tool_name}' execution failed: {error}",
            code="tool_execution_failed",
            status_code=500,
        )
        self.tool_name = tool_name
        self.error = error


class SkillNotFoundError(MCPError):
    """
    Raised when a requested skill is not found.
    
    當請求的 Skill 不存在時拋出。
    """

    def __init__(self, skill_name: str):
        super().__init__(
            message=f"Skill '{skill_name}' not found",
            code="skill_not_found",
            status_code=404,
        )
        self.skill_name = skill_name


class SkillExecutionError(MCPError):
    """
    Raised when a skill fails during execution.
    
    當 Skill 執行失敗時拋出。
    """

    def __init__(self, skill_name: str, error: str):
        super().__init__(
            message=f"Skill '{skill_name}' execution failed: {error}",
            code="skill_execution_failed",
            status_code=500,
        )
        self.skill_name = skill_name
        self.error = error


class InvalidSkillInputError(MCPError):
    """
    Raised when skill input is invalid.
    
    當 Skill 輸入無效時拋出。
    """

    def __init__(self, skill_name: str, reason: str):
        super().__init__(
            message=f"Invalid input for skill '{skill_name}': {reason}",
            code="invalid_skill_input",
            status_code=400,
        )
        self.skill_name = skill_name
        self.reason = reason


class ProtocolError(MCPError):
    """
    Raised when there's a protocol-level error.
    
    當 MCP 協議級別發生錯誤時拋出。
    """

    def __init__(self, message: str):
        super().__init__(
            message=f"Protocol error: {message}",
            code="protocol_error",
            status_code=400,
        )


class AuthenticationError(MCPError):
    """
    Raised when authentication fails.
    
    當認證失敗時拋出。
    """

    def __init__(self, reason: str = "Authentication failed"):
        super().__init__(
            message=reason,
            code="authentication_error",
            status_code=401,
        )


class AuthorizationError(MCPError):
    """
    Raised when user is not authorized for an action.
    
    當用戶無權執行操作時拋出。
    """

    def __init__(self, reason: str = "Not authorized"):
        super().__init__(
            message=reason,
            code="authorization_error",
            status_code=403,
        )


class ValidationError(MCPError):
    """
    Raised when input validation fails.
    
    當輸入驗證失敗時拋出。
    """

    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="validation_error",
            status_code=422,
        )
