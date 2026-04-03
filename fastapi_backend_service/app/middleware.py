"""HTTP request/response logging middleware for the FastAPI Backend Service.

Provides ``RequestLoggingMiddleware``, a Starlette ``BaseHTTPMiddleware``
subclass that:

- Generates a unique ``X-Request-ID`` (UUID v4) for every incoming request.
- Attaches the request ID to ``request.state.request_id`` for downstream use.
- Records the HTTP method, path, response status code, and wall-clock
  processing duration for every request via ``AppLogger``.
- Propagates ``X-Request-ID`` back to the client as a response header.
"""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.logging import AppLogger


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs every HTTP request with timing and a unique request ID.

    Attaches to the FastAPI application via ``app.add_middleware()``.
    Generates a UUID for each request, measures processing time, and logs
    the result using ``AppLogger``.

    Examples:
        Mounting in ``main.py``::

            from app.middleware import RequestLoggingMiddleware
            app.add_middleware(RequestLoggingMiddleware)
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialise the middleware with its own ``AppLogger`` instance.

        Args:
            app: The ASGI application (passed automatically by Starlette/FastAPI).
        """
        super().__init__(app)
        self._logger = AppLogger("request")

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process a single request: add request ID, time execution, log result.

        Args:
            request: The incoming Starlette ``Request`` object.
            call_next: Callable that forwards the request to the next middleware
                       or route handler and returns a ``Response``.

        Returns:
            The ``Response`` from the downstream handler, augmented with the
            ``X-Request-ID`` header.

        Note:
            If an exception propagates out of ``call_next``, it is logged via
            ``AppLogger.log_error`` before being re-raised so that FastAPI's
            global exception handlers can process it normally.
        """
        request_id: str = str(uuid.uuid4())
        request.state.request_id = request_id

        start_time: float = time.perf_counter()

        try:
            response: Response = await call_next(request)
        except Exception as exc:
            self._logger.log_error(
                exc,
                {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            raise

        duration: float = time.perf_counter() - start_time

        self._logger.log_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration=duration,
        )

        response.headers["X-Request-ID"] = request_id
        return response
