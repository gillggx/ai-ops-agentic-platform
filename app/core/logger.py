"""
Logging configuration and utilities.

日誌配置和工具類。
"""

import logging
import logging.config
import json
from pathlib import Path
from typing import Optional
from datetime import datetime


# ============================================================================
# Logging Configuration
# ============================================================================


def setup_logging(log_dir: str = "logs", log_level: str = "INFO") -> logging.Logger:
    """Set up logging configuration.
    
    配置日誌系統。
    
    Args:
        log_dir: Directory for log files
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        
    Returns:
        Configured logger instance
    """
    # Create log directory
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Logging configuration
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "detailed": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": log_level,
                "formatter": "detailed",
                "filename": log_path / "app.log",
                "maxBytes": 10485760,  # 10MB
                "backupCount": 5,
            },
            "error_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "ERROR",
                "formatter": "detailed",
                "filename": log_path / "error.log",
                "maxBytes": 10485760,
                "backupCount": 5,
            },
        },
        "loggers": {
            "app": {
                "level": log_level,
                "handlers": ["console", "file", "error_file"],
                "propagate": False,
            },
            "app.api": {
                "level": log_level,
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "app.services": {
                "level": log_level,
                "handlers": ["console", "file"],
                "propagate": False,
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console", "file"],
        },
    }

    logging.config.dictConfig(config)
    return logging.getLogger("app")


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging.
    
    JSON 日誌格式化器，用於結構化日誌記錄。
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.
        
        將日誌記錄格式化為 JSON。
        
        Args:
            record: The log record to format
            
        Returns:
            JSON-formatted log string
        """
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if record.exc_text:
            log_data["exc_text"] = record.exc_text

        return json.dumps(log_data)


# ============================================================================
# Convenience Functions
# ============================================================================


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance.
    
    獲取日誌記錄器實例。
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def log_exception(logger: logging.Logger, message: str, exc: Exception) -> None:
    """Log an exception with context.
    
    記錄異常及其上下文。
    
    Args:
        logger: Logger instance
        message: Message prefix
        exc: The exception to log
    """
    logger.error(f"{message}: {str(exc)}", exc_info=True)


def log_timing(logger: logging.Logger, operation: str, elapsed_ms: float) -> None:
    """Log operation timing.
    
    記錄操作耗時。
    
    Args:
        logger: Logger instance
        operation: Operation name
        elapsed_ms: Elapsed time in milliseconds
    """
    if elapsed_ms > 1000:
        logger.warning(f"{operation} took {elapsed_ms:.0f}ms (slow)")
    else:
        logger.debug(f"{operation} took {elapsed_ms:.0f}ms")


# ============================================================================
# Audit Logging
# ============================================================================


class AuditLogger:
    """Audit logging for important operations.
    
    重要操作的審計日誌記錄。
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize audit logger.
        
        Args:
            logger: Logger instance (defaults to app.audit if not provided)
        """
        self.logger = logger or logging.getLogger("app.audit")

    def log_login(self, user_id: str, username: str, ip_address: Optional[str] = None) -> None:
        """Log user login.
        
        記錄用戶登錄。
        
        Args:
            user_id: User ID
            username: Username
            ip_address: Client IP address
        """
        msg = f"User login: user_id={user_id}, username={username}"
        if ip_address:
            msg += f", ip={ip_address}"
        self.logger.info(msg)

    def log_resource_created(self, resource_type: str, resource_id: str, user_id: str) -> None:
        """Log resource creation.
        
        記錄資源建立。
        
        Args:
            resource_type: Type of resource created
            resource_id: ID of created resource
            user_id: User ID who created it
        """
        self.logger.info(
            f"Resource created: type={resource_type}, id={resource_id}, user={user_id}"
        )

    def log_resource_deleted(self, resource_type: str, resource_id: str, user_id: str) -> None:
        """Log resource deletion.
        
        記錄資源刪除。
        
        Args:
            resource_type: Type of resource deleted
            resource_id: ID of deleted resource
            user_id: User ID who deleted it
        """
        self.logger.info(
            f"Resource deleted: type={resource_type}, id={resource_id}, user={user_id}"
        )

    def log_permission_denied(self, action: str, resource_type: str, user_id: str) -> None:
        """Log permission denied.
        
        記錄權限拒絕。
        
        Args:
            action: Action that was denied
            resource_type: Type of resource
            user_id: User ID
        """
        self.logger.warning(
            f"Permission denied: action={action}, resource={resource_type}, user={user_id}"
        )


# ============================================================================
# Module-level convenience
# ============================================================================

_default_logger: Optional[logging.Logger] = None


def init_default_logger(log_dir: str = "logs", log_level: str = "INFO") -> logging.Logger:
    """Initialize default logger.
    
    初始化默認日誌記錄器。
    
    Args:
        log_dir: Log directory
        log_level: Log level
        
    Returns:
        Configured logger
    """
    global _default_logger
    _default_logger = setup_logging(log_dir, log_level)
    return _default_logger


def logger() -> logging.Logger:
    """Get default logger.

    獲取默認日誌記錄器。

    Returns:
        Default logger instance
    """
    global _default_logger
    if _default_logger is None:
        _default_logger = setup_logging()
    return _default_logger


# Module-level logger instance — allows `from app.core.logger import logger`
# to be used directly as `logger.info(...)` without calling it as a function.
logger = logger()
