"""Structured logging module for the FastAPI Backend Service.

Provides a centralised ``AppLogger`` class that wraps Python's standard
``logging`` module with structured formatting. All application components
should obtain their logger through this module rather than calling
``logging.getLogger`` directly.
"""

import logging
import sys

from app.config import get_settings


class AppLogger:
    """Structured application logger.

    Wraps Python's built-in ``logging.Logger`` with a structured log format
    and convenience methods for common logging patterns (request logging,
    error logging). Log level is driven by the ``LOG_LEVEL`` setting in
    ``app/config.py``.

    Attributes:
        _logger: The underlying ``logging.Logger`` instance.

    Examples:
        Basic usage::

            logger = AppLogger("app.routers.users")
            logger.log_request("GET", "/api/v1/users", 200, 0.042)

        Using the raw logger::

            log = AppLogger("app.services.auth").get_logger()
            log.debug("Attempting login for user: %s", username)
    """

    def __init__(self, name: str) -> None:
        """Initialise and configure the logger.

        Args:
            name: Logger name (typically the module's ``__name__``).
                  Used as the logger identifier in log output.
        """
        self._logger: logging.Logger = logging.getLogger(name)
        self._setup()

    def _setup(self) -> None:
        """Configure handler, formatter, and log level.

        Adds a ``StreamHandler`` writing to stdout only if the logger does
        not already have handlers (prevents duplicate log lines when the
        module is reloaded). Sets ``propagate = False`` to avoid double
        logging if a root logger handler is also configured.
        """
        settings = get_settings()
        level: int = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

        self._logger.setLevel(level)
        self._logger.propagate = False

    def get_logger(self) -> logging.Logger:
        """Return the underlying ``logging.Logger`` instance.

        Returns:
            The configured ``logging.Logger`` for direct use when fine-grained
            log-level control is needed (e.g. ``logger.debug(...)``).
        """
        return self._logger

    def log_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration: float,
    ) -> None:
        """Log a completed HTTP request in a structured key=value format.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, …).
            path: Request URL path (e.g. ``/api/v1/users``).
            status_code: HTTP response status code returned to the client.
            duration: Request processing time in seconds.

        Examples:
            >>> app_logger.log_request("GET", "/api/v1/users", 200, 0.042)
            # 2026-01-01T00:00:00 | INFO     | request | method=GET path=/api/v1/users status=200 duration=0.042s
        """
        self._logger.info(
            "method=%s path=%s status=%d duration=%.3fs",
            method,
            path,
            status_code,
            duration,
        )

    def log_error(self, error: Exception, context: dict) -> None:
        """Log an exception with contextual metadata.

        Args:
            error: The exception instance to log.
            context: A dictionary of additional context fields
                     (e.g. ``{"request_id": "...", "user_id": 1}``).

        Examples:
            >>> app_logger.log_error(exc, {"request_id": req_id, "path": "/api/v1/users/99"})
        """
        self._logger.error(
            "error=%s message=%s context=%s",
            type(error).__name__,
            str(error),
            context,
        )
