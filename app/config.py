"""
Application configuration management.

應用程序配置管理。
"""

import os
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings from environment variables.
    
    應用程序設置。
    
    Configuration:
    - Database connection
    - Security settings
    - Logging configuration
    - Performance tuning
    - Monitoring settings
    """

    # Application
    APP_NAME: str = "Glass Box AI Diagnostic Platform"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./database.db"
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 30
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_POOL_RECYCLE: int = 3600

    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: list[str] = ["*"]
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: list[str] = ["*"]
    CORS_HEADERS: list[str] = ["*"]

    # API
    API_V1_PREFIX: str = "/api/v1"
    API_TITLE: str = "Glass Box AI Diagnostic Platform API"
    API_DESCRIPTION: str = "Three-layer FastAPI backend with MCP Skills"

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    LOG_FILE: Optional[str] = None
    LOG_RETENTION_DAYS: int = 30

    # Performance
    REQUEST_TIMEOUT: int = 30
    BACKGROUND_TASK_TIMEOUT: int = 60
    CACHE_TTL_SECONDS: int = 300
    MAX_CONCURRENT_REQUESTS: int = 1000

    # Monitoring
    METRICS_ENABLED: bool = True
    HEALTH_CHECK_INTERVAL: int = 60
    PROMETHEUS_ENABLED: bool = False
    PROMETHEUS_PORT: int = 8001

    # LLM
    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = "claude-haiku-4-5-20251001"
    ANTHROPIC_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_API_KEY: str = "ollama"
    OLLAMA_MODEL: str = "qwen3:8b"

    # Feature Flags
    FEATURE_MCP_SERVER: bool = True
    FEATURE_SKILLS: bool = True
    FEATURE_AUDIT_LOG: bool = True
    FEATURE_RATE_LIMITING: bool = True

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = True

    def get_database_url(self) -> str:
        """
        Get full database URL with connection parameters.
        
        Args:
            None
        
        Returns:
            str - Full database URL
        
        獲取完整的數據庫 URL。
        """
        if self.ENVIRONMENT == "production":
            return self.DATABASE_URL.replace(
                "//", f"//pool_size={self.DATABASE_POOL_SIZE}&echo={self.DATABASE_ECHO}&"
            )
        return self.DATABASE_URL

    def is_production(self) -> bool:
        """
        Check if running in production.
        
        Returns:
            bool - True if production
        
        檢查是否在生產環境。
        """
        return self.ENVIRONMENT == "production"

    def is_development(self) -> bool:
        """
        Check if running in development.
        
        Returns:
            bool - True if development
        
        檢查是否在開發環境。
        """
        return self.ENVIRONMENT == "development"

    def is_testing(self) -> bool:
        """
        Check if running in testing.
        
        Returns:
            bool - True if testing
        
        檢查是否在測試環境。
        """
        return self.ENVIRONMENT == "testing"


# Create settings instance
settings = Settings()

# Compatibility alias for get_settings
def get_settings() -> Settings:
    return settings

