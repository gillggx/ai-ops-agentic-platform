"""
Core constants and configuration values.

定義系統全局常數，包括 SSE 事件類型、優先級、狀態等。
"""

# ============================================================================
# SSE Event Types (8 required types)
# SSE 事件類型（8 種必需類型）
# ============================================================================
SSE_EVENT_CONTEXT_LOAD = "context_load"      # Blue - Loading context
SSE_EVENT_THINKING = "thinking"              # Gray italic - LLM thinking
SSE_EVENT_TOOL_START = "tool_start"          # Yellow - Tool invocation started
SSE_EVENT_TOOL_DONE = "tool_done"            # Green - Tool completed
SSE_EVENT_SYNTHESIS = "synthesis"            # Final markdown response
SSE_EVENT_MEMORY_WRITE = "memory_write"      # Purple - Memory saved
SSE_EVENT_ERROR = "error"                    # Red - Error occurred
SSE_EVENT_DONE = "done"                      # Stream end marker

SSE_EVENT_TYPES = {
    SSE_EVENT_CONTEXT_LOAD,
    SSE_EVENT_THINKING,
    SSE_EVENT_TOOL_START,
    SSE_EVENT_TOOL_DONE,
    SSE_EVENT_SYNTHESIS,
    SSE_EVENT_MEMORY_WRITE,
    SSE_EVENT_ERROR,
    SSE_EVENT_DONE,
}

# ============================================================================
# Urgency Levels (優先級)
# ============================================================================
URGENCY_HIGH = "high"
URGENCY_MEDIUM = "medium"
URGENCY_LOW = "low"

URGENCY_LEVELS = {URGENCY_HIGH, URGENCY_MEDIUM, URGENCY_LOW}

# ============================================================================
# Diagnosis Status (診斷狀態)
# ============================================================================
DIAGNOSIS_NORMAL = "NORMAL"
DIAGNOSIS_ABNORMAL = "ABNORMAL"
DIAGNOSIS_ERROR = "ERROR"
DIAGNOSIS_UNKNOWN = "UNKNOWN"

DIAGNOSIS_STATUSES = {DIAGNOSIS_NORMAL, DIAGNOSIS_ABNORMAL, DIAGNOSIS_ERROR, DIAGNOSIS_UNKNOWN}

# ============================================================================
# Event Status (事件狀態)
# ============================================================================
EVENT_STATUS_PENDING = "pending"
EVENT_STATUS_ACKNOWLEDGED = "acknowledged"
EVENT_STATUS_RESOLVED = "resolved"

EVENT_STATUSES = {EVENT_STATUS_PENDING, EVENT_STATUS_ACKNOWLEDGED, EVENT_STATUS_RESOLVED}

# ============================================================================
# MCP Visibility (MCP 可見性)
# ============================================================================
MCP_VISIBILITY_PUBLIC = "public"
MCP_VISIBILITY_PRIVATE = "private"

MCP_VISIBILITIES = {MCP_VISIBILITY_PUBLIC, MCP_VISIBILITY_PRIVATE}

# ============================================================================
# MCP Type (MCP 類型)
# ============================================================================
MCP_TYPE_SYSTEM = "system"
MCP_TYPE_CUSTOM = "custom"

MCP_TYPES = {MCP_TYPE_SYSTEM, MCP_TYPE_CUSTOM}

# ============================================================================
# Memory Source (記憶來源)
# ============================================================================
MEMORY_SOURCE_DIAGNOSIS = "diagnosis"
MEMORY_SOURCE_USER_PREFERENCE = "user_preference"
MEMORY_SOURCE_MANUAL = "manual"

MEMORY_SOURCES = {MEMORY_SOURCE_DIAGNOSIS, MEMORY_SOURCE_USER_PREFERENCE, MEMORY_SOURCE_MANUAL}

# ============================================================================
# Schedule Intervals (排程間隔)
# ============================================================================
SCHEDULE_INTERVAL_30MIN = "30m"
SCHEDULE_INTERVAL_1HOUR = "1h"
SCHEDULE_INTERVAL_4HOUR = "4h"
SCHEDULE_INTERVAL_8HOUR = "8h"
SCHEDULE_INTERVAL_12HOUR = "12h"
SCHEDULE_INTERVAL_DAILY = "daily"

SCHEDULE_INTERVALS = {
    SCHEDULE_INTERVAL_30MIN,
    SCHEDULE_INTERVAL_1HOUR,
    SCHEDULE_INTERVAL_4HOUR,
    SCHEDULE_INTERVAL_8HOUR,
    SCHEDULE_INTERVAL_12HOUR,
    SCHEDULE_INTERVAL_DAILY,
}

# ============================================================================
# Agent Configuration (Agent 配置)
# ============================================================================
AGENT_MAX_ITERATIONS = 5
AGENT_SESSION_TTL_HOURS = 24
AGENT_SESSION_MAX_MESSAGES = 20
AGENT_MEMORY_SEARCH_TOP_K = 5
AGENT_TOOL_TIMEOUT_SECONDS = 30
AGENT_PREFLIGHT_VALIDATE_TIMEOUT = 5

# ============================================================================
# System User IDs (系統用戶 ID)
# ============================================================================
SYSTEM_USER_ID = 0  # System memories user ID

# ============================================================================
# Default System Parameters (默認系統參數)
# ============================================================================
DEFAULT_SYSTEM_PARAMETERS = {
    # NOTE: PROMPT_MCP_TRY_RUN and PROMPT_SKILL_DIAGNOSIS were removed here.
    # The real Chinese prompts live as _DEFAULT_* fallbacks in mcp_builder_service.py.
    # Admin can override them via system_parameters table (keys: PROMPT_MCP_TRY_RUN,
    # PROMPT_SKILL_DIAGNOSIS, PROMPT_MCP_GENERATE, PROMPT_SKILL_DIAG_CODE).
    "LLM_MODEL": "claude-3-5-sonnet-20241022",
    "MAX_AGENT_ITERATIONS": str(AGENT_MAX_ITERATIONS),
    "SANDBOX_TIMEOUT_SECONDS": "30",
    "SANDBOX_MAX_MEMORY_MB": "512",
}

# ============================================================================
# Forbidden Imports in Sandbox (沙盒禁止導入)
# ============================================================================
SANDBOX_FORBIDDEN_MODULES = {
    "os",
    "sys",
    "subprocess",
    "importlib",
    "__import__",
    "eval",
    "exec",
    "compile",
    "open",
    "file",
    "input",
    "raw_input",
}

# ============================================================================
# Builtin DataSubjects (內建數據源)
# ============================================================================
BUILTIN_DATA_SUBJECTS = {
    "SystemAPC": {
        "description": "Advanced Process Control data from equipment",
        "api_config": {
            "endpoint_url": "http://localhost:8000/api/v1/mock/apc",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {"lot_id": "string", "operation_number": "integer"},
        "output_schema": {
            "apc_values": "array",
            "timestamp": "string",
            "equipment_id": "string",
        },
    },
    "SystemRecipe": {
        "description": "Recipe and process parameters",
        "api_config": {
            "endpoint_url": "http://localhost:8000/api/v1/mock/recipe",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {"lot_id": "string", "tool_id": "string"},
        "output_schema": {
            "recipe_name": "string",
            "parameters": "object",
            "version": "string",
        },
    },
    "SystemEC": {
        "description": "Equipment Constants",
        "api_config": {
            "endpoint_url": "http://localhost:8000/api/v1/mock/ec",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {"tool_id": "string"},
        "output_schema": {
            "tool_name": "string",
            "specifications": "object",
            "calibration": "object",
        },
    },
    "SystemSPC": {
        "description": "Statistical Process Control data",
        "api_config": {
            "endpoint_url": "http://localhost:8000/api/v1/mock/spc",
            "method": "GET",
            "headers": {},
        },
        "input_schema": {"chart_name": "string", "tool_id": "string"},
        "output_schema": {
            "measurements": "array",
            "ucl": "number",
            "lcl": "number",
            "center_line": "number",
        },
    },
}

# ============================================================================
# Default Builtin System MCPs (內建 System MCPs)
# ============================================================================
BUILTIN_SYSTEM_MCPS = {
    "SPC_ChartProcessor": {
        "description": "Process SPC chart data for statistical analysis",
        "data_subject_id": "SystemSPC",
        "processing_intent": "Calculate SPC statistics and detect out-of-control conditions",
    },
    "APC_Analyzer": {
        "description": "Analyze APC values for process anomalies",
        "data_subject_id": "SystemAPC",
        "processing_intent": "Analyze equipment APC values for abnormal patterns",
    },
    "RecipeValidator": {
        "description": "Validate recipe parameters against equipment specs",
        "data_subject_id": "SystemRecipe",
        "processing_intent": "Validate recipe parameters are within equipment specifications",
    },
}

# ============================================================================
# Default Builtin Event Types (內建事件類型)
# ============================================================================
BUILTIN_EVENT_TYPES = {
    "SPC_OOC": {
        "description": "SPC Out-Of-Control detection",
        "attributes": {
            "tool_id": "string",
            "chart_name": "string",
            "violation_type": "string",
            "affected_points": "integer",
        },
    },
    "Equipment_Alarm": {
        "description": "Equipment alarm from APC",
        "attributes": {
            "equipment_id": "string",
            "alarm_code": "string",
            "severity": "string",
            "parameter": "string",
        },
    },
    "Recipe_Drift": {
        "description": "Recipe parameter drift detected",
        "attributes": {
            "lot_id": "string",
            "parameter_name": "string",
            "deviation_percent": "number",
            "baseline": "number",
        },
    },
}

# ============================================================================
# Default Builtin System Users (內建系統用戶)
# ============================================================================
DEFAULT_SYSTEM_USERS = {
    "admin": {
        "email": "admin@glassbox.ai",
        "password": "admin",  # Will be hashed
        "is_superuser": True,
    },
    "gill": {
        "email": "gill@glassbox.ai",
        "password": "password",  # Will be hashed
        "is_superuser": False,
    },
}

# ============================================================================
# Pagination Defaults (分頁默認值)
# ============================================================================
DEFAULT_SKIP = 0
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000

# ============================================================================
# Token Configuration (令牌配置)
# ============================================================================
# Note: JWT_SECRET_KEY should be loaded from environment in production
# 注意：在生产环境中应该从环境变量加载 JWT_SECRET_KEY
import os
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
TOKEN_ALGORITHM = "HS256"
TOKEN_EXPIRATION_HOURS = 12
JWT_EXPIRATION_HOURS = 12
REFRESH_TOKEN_EXPIRATION_DAYS = 30

# ============================================================================
# Cache Configuration (緩存配置)
# ============================================================================
CACHE_TTL_MINUTES = {
    "system_parameters": 60,
    "data_subjects": 60,
    "event_types": 60,
    "mcp_definitions": 30,
    "skill_definitions": 30,
}

# ============================================================================
# Error Messages (錯誤訊息)
# ============================================================================
ERROR_UNAUTHORIZED = "Unauthorized"
ERROR_FORBIDDEN = "Forbidden"
ERROR_NOT_FOUND = "Not found"
ERROR_CONFLICT = "Conflict"
ERROR_INVALID_REQUEST = "Invalid request"
ERROR_INTERNAL_SERVER = "Internal server error"

# ============================================================================
# HTTP Status Codes (HTTP 狀態碼)
# ============================================================================
STATUS_OK = 200
STATUS_CREATED = 201
STATUS_BAD_REQUEST = 400
STATUS_UNAUTHORIZED = 401
STATUS_FORBIDDEN = 403
STATUS_NOT_FOUND = 404
STATUS_CONFLICT = 409
STATUS_UNPROCESSABLE_ENTITY = 422
STATUS_INTERNAL_SERVER_ERROR = 500
STATUS_SERVICE_UNAVAILABLE = 503
