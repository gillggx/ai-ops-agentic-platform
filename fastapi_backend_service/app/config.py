## app/config.py
"""Application configuration module.

This module provides centralized configuration management using Pydantic BaseSettings.
All configuration values are loaded from environment variables with sensible defaults.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    """Application configuration settings.

    All settings can be overridden via environment variables or a .env file.
    Uses pydantic-settings for automatic environment variable parsing and validation.

    Attributes:
        APP_NAME: The name of the application.
        APP_VERSION: The current version of the application.
        DEBUG: Whether to run in debug mode.
        DATABASE_URL: The database connection URL.
        SECRET_KEY: Secret key for JWT token signing.
        ALGORITHM: JWT signing algorithm.
        ACCESS_TOKEN_EXPIRE_MINUTES: JWT token expiration time in minutes.
        ALLOWED_ORIGINS: Comma-separated list of allowed CORS origins.
    """

    APP_NAME: str = Field(
        default="FastAPI Backend Service",
        description="Application name",
    )
    APP_VERSION: str = Field(
        default="1.0.0",
        description="Application version",
    )
    DEBUG: bool = Field(
        default=False,
        description="Debug mode flag",
    )
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./dev.db",
        description="Database connection URL",
    )
    SECRET_KEY: str = Field(
        default="your-secret-key-change-this-in-production-use-openssl-rand-hex-32",
        description="Secret key for JWT token signing",
    )
    ALGORITHM: str = Field(
        default="HS256",
        description="JWT signing algorithm",
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=720,
        description="Access token expiration time in minutes (default: 720 = 12 hours)",
        ge=1,
    )
    ALLOWED_ORIGINS: str = Field(
        default="*",
        description="Comma-separated list of allowed CORS origins",
    )
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    API_V1_PREFIX: str = Field(
        default="/api/v1",
        description="URL prefix for API version 1 routes",
    )
    ANTHROPIC_API_KEY: str = Field(
        default="",
        description="Anthropic API key for Claude LLM calls",
    )

    # ── LLM Settings ─────────────────────────────────────────────────────────
    LLM_PROVIDER: str = Field(
        default="anthropic",
        description="LLM backend: 'anthropic' (Claude) or 'ollama' (OpenAI-compatible local model)",
    )
    LLM_MODEL: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Anthropic model ID used when LLM_PROVIDER=anthropic",
    )
    # ── Ollama / OpenAI-compatible settings (used when LLM_PROVIDER=ollama) ──
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434/v1",
        description="Base URL for Ollama / OpenAI-compatible API endpoint",
    )
    OLLAMA_MODEL: str = Field(
        default="qwen2.5:32b",
        description="Model name to use when LLM_PROVIDER=ollama",
    )
    OLLAMA_API_KEY: str = Field(
        default="ollama",
        description="API key for Ollama (any non-empty string works; set to real key for vLLM/remote)",
    )
    LLM_MAX_TOKENS_DIAGNOSTIC: int = Field(
        default=4096,
        description="Max output tokens for the diagnostic agent loop",
    )
    LLM_MAX_TOKENS_GENERATE: int = Field(
        default=4096,
        description="Max output tokens for MCP/Skill generation prompts",
    )
    LLM_MAX_TOKENS_CHAT: int = Field(
        default=2048,
        description="Max output tokens for help-chat and copilot intent parsing",
    )

    # ── HTTP Client ────────────────────────────────────────────────────────────
    HTTPX_TIMEOUT_SECONDS: float = Field(
        default=15.0,
        description="Timeout in seconds for outbound HTTP calls to DataSubject APIs",
    )
    SERVER_BASE_URL: str = Field(
        default="http://127.0.0.1:8765",
        description="Base URL of this server for self-referential System MCP calls (e.g. mock data sources). Set to match the actual uvicorn port.",
    )

    # ── Scheduler ─────────────────────────────────────────────────────────────
    SCHEDULER_MISFIRE_GRACE_TIME_SECONDS: int = Field(
        default=300,
        description="Grace period (seconds) before a delayed APScheduler job is skipped",
    )

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse ALLOWED_ORIGINS string into a list of origin strings.

        Returns:
            A list of allowed origin strings. Returns ["*"] if ALLOWED_ORIGINS
            is set to wildcard, otherwise splits by comma and strips whitespace.

        Examples:
            >>> config = Config(ALLOWED_ORIGINS="*")
            >>> config.allowed_origins_list
            ['*']
            >>> config = Config(ALLOWED_ORIGINS="http://localhost:3000,https://example.com")
            >>> config.allowed_origins_list
            ['http://localhost:3000', 'https://example.com']
        """
        if self.ALLOWED_ORIGINS.strip() == "*":
            return ["*"]
        return [
            origin.strip()
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


@lru_cache(maxsize=1)
def get_settings() -> Config:
    """Get the application settings singleton.

    Uses lru_cache to ensure only one instance of Config is created,
    avoiding repeated reads of environment variables. This function
    should be used as a FastAPI dependency via ``Depends(get_settings)``.

    Returns:
        The application Config instance.

    Examples:
        >>> settings = get_settings()
        >>> print(settings.APP_NAME)
        'FastAPI Backend Service'

        # Usage as FastAPI dependency:
        # @app.get("/info")
        # def get_info(settings: Config = Depends(get_settings)):
        #     return {"app_name": settings.APP_NAME}
    """
    return Config()
