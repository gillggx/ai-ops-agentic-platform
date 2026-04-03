"""
Custom exception classes for the application.

應用程序的自定義異常類定義。
"""

from typing import Optional, Any


class AppException(Exception):
    """Base exception class for the application.
    
    應用程序基礎異常類。
    """

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        detail: Optional[str] = None,
        error_code: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ):
        """Initialize AppException.
        
        Args:
            message: Main error message
            status_code: HTTP status code
            detail: Additional detail text
            error_code: Application-specific error code
            context: Additional context information
        """
        self.message = message
        self.status_code = status_code
        self.detail = detail or message
        self.error_code = error_code or self.__class__.__name__
        self.context = context or {}
        super().__init__(self.message)


# ============================================================================
# Authentication & Authorization
# ============================================================================


class AuthenticationError(AppException):
    """Authentication failed.
    
    認證失敗。
    """

    def __init__(self, message: str = "Authentication failed", detail: Optional[str] = None):
        super().__init__(message, status_code=401, detail=detail)


class AuthorizationError(AppException):
    """Authorization failed / Permission denied.
    
    授權失敗 / 權限不足。
    """

    def __init__(self, message: str = "Permission denied", detail: Optional[str] = None):
        super().__init__(message, status_code=403, detail=detail)


class InvalidTokenError(AuthenticationError):
    """Invalid or expired token.
    
    無效或過期的令牌。
    """

    def __init__(self, message: str = "Invalid or expired token"):
        super().__init__(message)


class InvalidCredentialsError(AuthenticationError):
    """Invalid username/password.
    
    無效的用戶名/密碼。
    """

    def __init__(self, message: str = "Invalid username or password"):
        super().__init__(message)


class TokenExpiredError(AuthenticationError):
    """Token has expired.
    
    令牌已過期。
    """

    def __init__(self, message: str = "Token has expired"):
        super().__init__(message)


class UserAlreadyExistsError(AuthenticationError):
    """User already exists.
    
    用戶已存在。
    """

    def __init__(self, message: str = "User already exists"):
        super().__init__(message, status_code=409)


class InsufficientPermissionsError(AuthorizationError):
    """Insufficient permissions for operation.
    
    操作權限不足。
    """

    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message)


class ServiceError(AppException):
    """Service operation error.
    
    服務操作錯誤。
    """

    def __init__(self, message: str = "Service error", detail: Optional[str] = None):
        super().__init__(message, status_code=500, detail=detail)


# ============================================================================
# Not Found Errors
# ============================================================================


class NotFoundError(AppException):
    """Resource not found.
    
    資源未找到。
    """

    def __init__(
        self, resource_type: str, resource_id: Optional[str] = None, detail: Optional[str] = None
    ):
        message = f"{resource_type} not found"
        if resource_id:
            message = f"{resource_type} with ID {resource_id} not found"
        super().__init__(message, status_code=404, detail=detail)


class UserNotFoundError(NotFoundError):
    """User not found.
    
    用戶未找到。
    """

    def __init__(self, user_id: Optional[str] = None):
        super().__init__("User", user_id)


class MCPDefinitionNotFoundError(NotFoundError):
    """MCP definition not found.
    
    MCP 定義未找到。
    """

    def __init__(self, mcp_id: Optional[str] = None):
        super().__init__("MCP Definition", mcp_id)


class SkillDefinitionNotFoundError(NotFoundError):
    """Skill definition not found.
    
    技能定義未找到。
    """

    def __init__(self, skill_id: Optional[str] = None):
        super().__init__("Skill Definition", skill_id)


class EventTypeNotFoundError(NotFoundError):
    """Event type not found.
    
    事件類型未找到。
    """

    def __init__(self, event_type_id: Optional[str] = None):
        super().__init__("Event Type", event_type_id)


class DataSubjectNotFoundError(NotFoundError):
    """Data subject not found.
    
    數據源未找到。
    """

    def __init__(self, ds_id: Optional[str] = None):
        super().__init__("Data Subject", ds_id)


# ============================================================================
# Conflict Errors
# ============================================================================


class ConflictError(AppException):
    """Resource already exists or conflicts with existing data.
    
    資源已存在或與現有數據衝突。
    """

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message, status_code=409, detail=detail)


class DuplicateError(ConflictError):
    """Duplicate resource.
    
    資源重複。
    """

    def __init__(
        self, resource_type: str, field: str, value: str, detail: Optional[str] = None
    ):
        message = f"{resource_type} with {field}='{value}' already exists"
        super().__init__(message, detail=detail)


class DuplicateUsernameError(DuplicateError):
    """Username already exists.
    
    用戶名已存在。
    """

    def __init__(self, username: str):
        super().__init__("User", "username", username)


class DuplicateEmailError(DuplicateError):
    """Email already exists.
    
    電子郵件已存在。
    """

    def __init__(self, email: str):
        super().__init__("User", "email", email)


# ============================================================================
# Validation Errors
# ============================================================================


class ValidationError(AppException):
    """Data validation failed.
    
    數據驗證失敗。
    """

    def __init__(self, message: str, field: Optional[str] = None, detail: Optional[str] = None):
        self.field = field
        super().__init__(message, status_code=422, detail=detail)


class InvalidRequestError(AppException):
    """Invalid request format.
    
    無效的請求格式。
    """

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message, status_code=400, detail=detail)


# ============================================================================
# Execution Errors
# ============================================================================


class ExecutionError(AppException):
    """Execution failed.
    
    執行失敗。
    """

    def __init__(self, message: str, detail: Optional[str] = None, context: Optional[dict] = None):
        super().__init__(message, status_code=500, detail=detail, context=context)


class MCPExecutionError(ExecutionError):
    """MCP execution failed.
    
    MCP 執行失敗。
    """

    def __init__(self, mcp_id: str, message: str, detail: Optional[str] = None):
        full_message = f"MCP {mcp_id} execution failed: {message}"
        super().__init__(full_message, detail=detail)


class SkillExecutionError(ExecutionError):
    """Skill execution failed.
    
    技能執行失敗。
    """

    def __init__(self, skill_id: str, message: str, detail: Optional[str] = None):
        full_message = f"Skill {skill_id} execution failed: {message}"
        super().__init__(full_message, detail=detail)


class SandboxExecutionError(ExecutionError):
    """Python sandbox execution failed.
    
    Python 沙盒執行失敗。
    """

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(f"Sandbox execution failed: {message}", detail=detail)


class SandboxSecurityError(SandboxExecutionError):
    """Sandbox detected forbidden operation.
    
    沙盒偵測到禁止操作。
    """

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(f"Security violation: {message}", detail=detail)


class SandboxTimeoutError(SandboxExecutionError):
    """Sandbox execution timeout.
    
    沙盒執行超時。
    """

    def __init__(self, timeout_seconds: int):
        message = f"Execution exceeded {timeout_seconds} second timeout"
        super().__init__(message)


# ============================================================================
# Data Processing Errors
# ============================================================================


class DataSourceError(AppException):
    """Error accessing data source.
    
    訪問數據源出錯。
    """

    def __init__(self, ds_name: str, message: str, detail: Optional[str] = None):
        full_message = f"Data source '{ds_name}' error: {message}"
        super().__init__(full_message, status_code=500, detail=detail)


class DataFetchError(DataSourceError):
    """Failed to fetch data from source.
    
    從源獲取數據失敗。
    """

    def __init__(self, ds_name: str, status_code: Optional[int] = None, message: Optional[str] = None):
        msg = message or f"HTTP {status_code}" if status_code else "Unknown error"
        super().__init__(ds_name, f"Fetch failed: {msg}")


class SchemaMismatchError(AppException):
    """Data schema mismatch.
    
    數據模式不匹配。
    """

    def __init__(self, expected: str, actual: str, detail: Optional[str] = None):
        message = f"Schema mismatch: expected {expected}, got {actual}"
        super().__init__(message, status_code=422, detail=detail)


# ============================================================================
# AI/LLM Errors
# ============================================================================


class LLMError(AppException):
    """LLM API error.
    
    LLM API 錯誤。
    """

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message, status_code=500, detail=detail)


class LLMAPIError(LLMError):
    """LLM API call failed.
    
    LLM API 調用失敗。
    """

    def __init__(self, status_code: int, message: str):
        super().__init__(f"LLM API error (HTTP {status_code}): {message}")


class TokenLimitError(LLMError):
    """Token limit exceeded.
    
    令牌限制已超。
    """

    def __init__(self, context_tokens: int, limit: int):
        message = f"Context {context_tokens} tokens exceeds limit of {limit}"
        super().__init__(message)


class PromptRejectedError(LLMError):
    """Prompt was rejected (safety/content policy).
    
    提示被拒絕（安全/內容政策）。
    """

    def __init__(self, reason: str):
        super().__init__(f"Prompt rejected: {reason}")


# ============================================================================
# Service Integration Errors
# ============================================================================


class ServiceIntegrationError(AppException):
    """Error integrating with external service.
    
    與外部服務集成出錯。
    """

    def __init__(self, service_name: str, message: str, detail: Optional[str] = None):
        full_message = f"{service_name} integration error: {message}"
        super().__init__(full_message, status_code=500, detail=detail)


class SchedulerError(ServiceIntegrationError):
    """APScheduler error.
    
    APScheduler 錯誤。
    """

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__("Scheduler", message, detail=detail)


class CacheError(ServiceIntegrationError):
    """Cache operation error.
    
    緩存操作錯誤。
    """

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__("Cache", message, detail=detail)


class DatabaseError(AppException):
    """Database operation failed.
    
    數據庫操作失敗。
    """

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message, status_code=500, detail=detail)


# ============================================================================
# System Configuration Errors
# ============================================================================


class ConfigurationError(AppException):
    """System configuration error.
    
    系統配置錯誤。
    """

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message, status_code=500, detail=detail)


class MissingConfigError(ConfigurationError):
    """Required configuration missing.
    
    缺少必需的配置。
    """

    def __init__(self, config_key: str):
        super().__init__(f"Missing required configuration: {config_key}")


class InvalidConfigError(ConfigurationError):
    """Invalid configuration value.
    
    無效的配置值。
    """

    def __init__(self, config_key: str, message: str):
        super().__init__(f"Invalid configuration for {config_key}: {message}")


# ============================================================================
# Business Logic Errors
# ============================================================================


class BusinessLogicError(AppException):
    """Business logic constraint violated.
    
    違反業務邏輯約束。
    """

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message, status_code=400, detail=detail)


class OperationNotAllowedError(BusinessLogicError):
    """Operation not allowed in current state.
    
    當前狀態下不允許操作。
    """

    def __init__(self, operation: str, reason: str):
        message = f"Operation '{operation}' not allowed: {reason}"
        super().__init__(message)


class ReadOnlyResourceError(BusinessLogicError):
    """Cannot modify read-only resource.
    
    無法修改只讀資源。
    """

    def __init__(self, resource_type: str):
        message = f"Cannot modify {resource_type}: resource is read-only"
        super().__init__(message)


class ProtectedResourceError(BusinessLogicError):
    """Cannot delete protected system resource.
    
    無法刪除受保護的系統資源。
    """

    def __init__(self, resource_type: str, resource_id: str):
        message = f"Cannot delete {resource_type} {resource_id}: resource is system-protected"
        super().__init__(message)


class InvalidStateTransitionError(BusinessLogicError):
    """Invalid state transition.
    
    無效的狀態轉換。
    """

    def __init__(self, current_state: str, requested_state: str, reason: Optional[str] = None):
        message = f"Cannot transition from {current_state} to {requested_state}"
        if reason:
            message += f": {reason}"
        super().__init__(message)


# ============================================================================
# Rate Limiting & Quota Errors
# ============================================================================


class RateLimitError(AppException):
    """Rate limit exceeded.
    
    超過速率限制。
    """

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, status_code=429)


class QuotaExceededError(AppException):
    """Usage quota exceeded.
    
    超出使用配額。
    """

    def __init__(self, quota_name: str, limit: int):
        message = f"{quota_name} quota exceeded (limit: {limit})"
        super().__init__(message, status_code=429)


# ============================================================================
# Utility Functions
# ============================================================================


def to_error_response(exc: AppException) -> dict[str, Any]:
    """Convert exception to error response format.
    
    將異常轉換為錯誤響應格式。
    
    Args:
        exc: The exception to convert
        
    Returns:
        Dictionary with error details
    """
    return {
        "error": exc.error_code,
        "message": exc.message,
        "detail": exc.detail,
        "context": exc.context if exc.context else None,
    }
