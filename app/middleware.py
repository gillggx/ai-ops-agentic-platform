"""
Custom middleware for security and monitoring.

自定義中間件。
"""

import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.ai_ops import Logger


logger = Logger("middleware")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add request ID to all requests.
    
    為所有請求添加請求 ID。
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """
        Process request and add request ID.
        
        Args:
            request: Request - HTTP request
            call_next: Callable - Next middleware
        
        Returns:
            Response - HTTP response
        
        處理請求並添加請求 ID。
        """
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all HTTP requests and responses.
    
    記錄所有 HTTP 請求和響應。
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """
        Process request and log details.
        
        Args:
            request: Request - HTTP request
            call_next: Callable - Next middleware
        
        Returns:
            Response - HTTP response
        
        處理請求並記錄詳細信息。
        """
        # Get request ID from previous middleware
        request_id = getattr(request.state, "request_id", "unknown")

        # Log request
        logger.info(
            f"{request.method} {request.url.path}",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        # Measure response time
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time

        # Log response
        logger.info(
            f"{request.method} {request.url.path} - {response.status_code}",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            process_time_ms=process_time * 1000,
        )

        response.headers["X-Process-Time"] = str(process_time)

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.
    
    為所有響應添加安全標頭。
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """
        Process request and add security headers.
        
        Args:
            request: Request - HTTP request
            call_next: Callable - Next middleware
        
        Returns:
            Response - HTTP response
        
        處理請求並添加安全標頭。
        """
        response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware for rate limiting.
    
    速率限制中間件。
    
    Simple in-memory rate limiting.
    Note: In production, use Redis-based rate limiting.
    """

    def __init__(self, app: ASGIApp, requests_per_minute: int = 60):
        """
        Initialize rate limit middleware.
        
        Args:
            app: ASGIApp - ASGI application
            requests_per_minute: int - Max requests per minute per IP
        
        初始化速率限制。
        """
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.request_counts = {}

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """
        Process request with rate limiting.
        
        Args:
            request: Request - HTTP request
            call_next: Callable - Next middleware
        
        Returns:
            Response - HTTP response
        
        處理請求並應用速率限制。
        """
        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()

        # Clean old entries
        if client_ip in self.request_counts:
            self.request_counts[client_ip] = [
                req_time for req_time in self.request_counts[client_ip]
                if current_time - req_time < 60
            ]
        else:
            self.request_counts[client_ip] = []

        # Check rate limit
        if len(self.request_counts[client_ip]) >= self.requests_per_minute:
            return Response(
                content="Rate limit exceeded",
                status_code=429,
            )

        # Record request
        self.request_counts[client_ip].append(current_time)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            self.requests_per_minute - len(self.request_counts[client_ip])
        )

        return response
