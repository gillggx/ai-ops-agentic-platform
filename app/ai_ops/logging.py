"""
Logging infrastructure for AI Ops layer.

日志基础设施。
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    
    JSON 日志格式化器。
    
    Outputs logs in JSON format for easy parsing by ELK stack.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.
        
        Args:
            record: LogRecord - Log record
        
        Returns:
            str - JSON formatted log
        
        格式化日志记录。
        """
        log_obj = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # Add custom attributes
        if hasattr(record, "user_id"):
            log_obj["user_id"] = record.user_id
        if hasattr(record, "request_id"):
            log_obj["request_id"] = record.request_id

        return json.dumps(log_obj, ensure_ascii=False)


class Logger:
    """
    Wrapper around Python logging for consistent logging.
    
    日志包装器。
    
    Provides:
    - Structured logging
    - Context tracking
    - Performance metrics
    - Error tracking
    """

    def __init__(self, name: str):
        """
        Initialize logger.
        
        Args:
            name: str - Logger name
        
        初始化日志记录器。
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        # Console handler with JSON formatter
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        self.logger.addHandler(handler)

    def debug(
        self,
        message: str,
        **context: Any,
    ) -> None:
        """
        Log debug message.
        
        Args:
            message: str - Log message
            **context: Additional context
        
        记录调试消息。
        """
        self.logger.debug(message, extra=context)

    def info(
        self,
        message: str,
        **context: Any,
    ) -> None:
        """
        Log info message.
        
        Args:
            message: str - Log message
            **context: Additional context
        
        记录信息消息。
        """
        self.logger.info(message, extra=context)

    def warning(
        self,
        message: str,
        **context: Any,
    ) -> None:
        """
        Log warning message.
        
        Args:
            message: str - Log message
            **context: Additional context
        
        记录警告消息。
        """
        self.logger.warning(message, extra=context)

    def error(
        self,
        message: str,
        **context: Any,
    ) -> None:
        """
        Log error message.
        
        Args:
            message: str - Log message
            **context: Additional context
        
        记录错误消息。
        """
        self.logger.error(message, extra=context)

    def critical(
        self,
        message: str,
        **context: Any,
    ) -> None:
        """
        Log critical message.
        
        Args:
            message: str - Log message
            **context: Additional context
        
        记录严重消息。
        """
        self.logger.critical(message, extra=context)

    def exception(
        self,
        message: str,
        **context: Any,
    ) -> None:
        """
        Log exception.
        
        Args:
            message: str - Log message
            **context: Additional context
        
        记录异常。
        """
        self.logger.exception(message, extra=context)


class AuditLogger:
    """
    Audit logger for tracking important events.
    
    审计日志记录器。
    
    Tracks:
    - User actions
    - Data modifications
    - Access events
    - Security events
    """

    def __init__(self):
        """Initialize audit logger."""
        self.logger = Logger("audit")

    def log_user_action(
        self,
        user_id: str,
        action: str,
        resource: str,
        status: str = "success",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log user action.
        
        Args:
            user_id: str - User ID
            action: str - Action performed
            resource: str - Resource affected
            status: str - Action status
            details: Optional[Dict] - Additional details
        
        记录用户操作。
        """
        self.logger.info(
            f"User action: {user_id} {action} {resource}",
            user_id=user_id,
            action=action,
            resource=resource,
            status=status,
            details=details or {},
        )

    def log_data_modification(
        self,
        user_id: str,
        operation: str,
        table: str,
        record_id: Any,
        changes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log data modification.
        
        Args:
            user_id: str - User who made the change
            operation: str - Operation (create, update, delete)
            table: str - Table name
            record_id: Any - Record ID
            changes: Optional[Dict] - Changed fields
        
        记录数据修改。
        """
        self.logger.info(
            f"Data modification: {operation} on {table}",
            user_id=user_id,
            operation=operation,
            table=table,
            record_id=record_id,
            changes=changes or {},
        )

    def log_security_event(
        self,
        event_type: str,
        severity: str = "warning",
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log security event.
        
        Args:
            event_type: str - Event type
            severity: str - Severity level
            user_id: Optional[str] - User ID if applicable
            details: Optional[Dict] - Event details
        
        记录安全事件。
        """
        log_func = {
            "critical": self.logger.critical,
            "error": self.logger.error,
            "warning": self.logger.warning,
            "info": self.logger.info,
        }.get(severity, self.logger.warning)

        log_func(
            f"Security event: {event_type}",
            event_type=event_type,
            severity=severity,
            user_id=user_id,
            details=details or {},
        )
