"""
Database configuration and optimization with connection pooling.

带有连接池的数据库配置和优化。
"""

from typing import Optional, AsyncGenerator
import logging

from sqlalchemy import create_engine, event, pool
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool, NullPool, QueuePool

logger = logging.getLogger(__name__)


class DatabaseConfig:
    """
    Database configuration with optimization parameters.
    
    具有优化参数的数据库配置。
    """

    def __init__(
        self,
        url: str,
        echo: bool = False,
        pool_size: int = 20,
        max_overflow: int = 30,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
        pool_pre_ping: bool = True,
        connect_args: Optional[dict] = None,
    ):
        """
        Initialize database configuration.
        
        Args:
            url: Database URL
            echo: SQL logging enabled
            pool_size: Connection pool size
            max_overflow: Max overflow connections
            pool_timeout: Pool timeout in seconds
            pool_recycle: Recycle connection after N seconds
            pool_pre_ping: Test connections before use
            connect_args: Additional connection arguments
        
        初始化数据库配置。
        """
        self.url = url
        self.echo = echo
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        self.pool_pre_ping = pool_pre_ping
        self.connect_args = connect_args or {}

    def get_sync_engine(self):
        """
        Get synchronous SQLAlchemy engine.
        
        Returns:
            SQLAlchemy engine
        
        获取同步 SQLAlchemy 引擎。
        """
        return create_engine(
            self.url,
            echo=self.echo,
            poolclass=QueuePool,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_timeout=self.pool_timeout,
            pool_recycle=self.pool_recycle,
            pool_pre_ping=self.pool_pre_ping,
            connect_args=self.connect_args,
        )

    def get_async_engine(self):
        """
        Get asynchronous SQLAlchemy engine.
        
        Returns:
            Async SQLAlchemy engine
        
        获取异步 SQLAlchemy 引擎。
        """
        is_sqlite = "sqlite" in str(self.url)
        if is_sqlite:
            return create_async_engine(
                self.url,
                echo=self.echo,
                poolclass=NullPool,
                connect_args=self.connect_args or {"check_same_thread": False},
            )
        return create_async_engine(
            self.url,
            echo=self.echo,
            poolclass=QueuePool,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_timeout=self.pool_timeout,
            pool_recycle=self.pool_recycle,
            pool_pre_ping=self.pool_pre_ping,
            connect_args=self.connect_args,
        )

    def get_test_engine(self):
        """
        Get SQLAlchemy engine for testing (in-memory SQLite).
        
        Returns:
            Test SQLAlchemy engine
        
        获取用于测试的 SQLAlchemy 引擎。
        """
        return create_engine(
            "sqlite:///:memory:",
            echo=self.echo,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )


class AsyncSessionManager:
    """
    Async database session manager with connection pooling optimization.
    
    具有连接池优化的异步数据库会话管理器。
    """

    def __init__(self, config: DatabaseConfig):
        """
        Initialize async session manager.
        
        Args:
            config: Database configuration
        
        初始化异步会话管理器。
        """
        self.config = config
        self.engine = config.get_async_engine()
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    async def close(self) -> None:
        """
        Close database engine and cleanup resources.
        
        关闭数据库引擎并清理资源。
        """
        await self.engine.dispose()
        logger.info("Database connection closed")

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get async database session.
        
        Yields:
            AsyncSession instance
        
        获取异步数据库会话。
        """
        async with self.async_session() as session:
            try:
                yield session
            except Exception as e:
                logger.error(f"Database session error: {e}")
                await session.rollback()
                raise
            finally:
                await session.close()

    async def init_db(self) -> None:
        """
        Initialize database with optimization settings.
        
        初始化具有优化设置的数据库。
        """
        async with self.engine.begin() as conn:
            # Enable performance optimizations based on database type
            if "postgresql" in str(self.config.url):
                await conn.execute(
                    "SET jit = on; SET jit_above_cost = 100000;"
                )
                logger.info("PostgreSQL JIT compilation enabled")

            elif "mysql" in str(self.config.url):
                await conn.execute("SET SESSION sql_mode = 'STRICT_TRANS_TABLES'")
                logger.info("MySQL strict mode enabled")

    async def optimize_indices(self) -> None:
        """
        Optimize database indices for better query performance.
        
        优化数据库索引以获得更好的查询性能。
        """
        async with self.engine.begin() as conn:
            if "postgresql" in str(self.config.url):
                await conn.execute("ANALYZE;")
                logger.info("PostgreSQL index analysis completed")

            elif "mysql" in str(self.config.url):
                await conn.execute("OPTIMIZE TABLE;")
                logger.info("MySQL table optimization completed")


class SyncSessionManager:
    """
    Synchronous database session manager.
    
    同步数据库会话管理器。
    """

    def __init__(self, config: DatabaseConfig):
        """
        Initialize sync session manager.
        
        Args:
            config: Database configuration
        
        初始化同步会话管理器。
        """
        self.config = config
        self.engine = config.get_sync_engine()
        self.session_factory = sessionmaker(
            self.engine,
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    def close(self) -> None:
        """
        Close database engine.
        
        关闭数据库引擎。
        """
        self.engine.dispose()
        logger.info("Sync database connection closed")

    def get_session(self) -> Session:
        """
        Get sync database session.
        
        Returns:
            Session instance
        
        获取同步数据库会话。
        """
        return self.session_factory()


class QueryOptimizer:
    """
    Query optimization utilities and monitoring.
    
    查询优化实用程序和监控。
    """

    @staticmethod
    def get_query_stats(session: AsyncSession) -> dict:
        """
        Get query statistics from session.
        
        Args:
            session: Database session
        
        Returns:
            Query statistics
        
        从会话获取查询统计信息。
        """
        # This is a placeholder for query statistics
        # In production, integrate with database query logs
        return {
            "slow_queries": [],
            "query_count": 0,
            "total_time": 0.0,
        }

    @staticmethod
    async def enable_slow_query_log(
        session: AsyncSession,
        threshold_ms: float = 1000.0
    ) -> None:
        """
        Enable slow query logging for database.
        
        Args:
            session: Database session
            threshold_ms: Slow query threshold in milliseconds
        
        为数据库启用慢查询日志记录。
        """
        try:
            if "mysql" in str(session.bind.url):
                await session.execute(
                    f"SET GLOBAL slow_query_log = 'ON';"
                )
                await session.execute(
                    f"SET GLOBAL long_query_time = {threshold_ms / 1000};"
                )
                logger.info(f"MySQL slow query log enabled (threshold: {threshold_ms}ms)")

            elif "postgresql" in str(session.bind.url):
                await session.execute(
                    f"SET log_min_duration_statement = {int(threshold_ms)};"
                )
                logger.info(f"PostgreSQL slow query log enabled (threshold: {threshold_ms}ms)")
        except Exception as e:
            logger.warning(f"Could not enable slow query log: {e}")

    @staticmethod
    def get_index_stats(session: Session, table_name: str) -> dict:
        """
        Get index statistics for a table.
        
        Args:
            session: Database session
            table_name: Table name
        
        Returns:
            Index statistics
        
        获取表的索引统计信息。
        """
        if "postgresql" in str(session.bind.url):
            result = session.execute(
                f"""
                SELECT indexname, idx_scan, idx_tup_read, idx_tup_fetch
                FROM pg_stat_user_indexes
                WHERE relname = '{table_name}'
                """
            )
            return result.fetchall()

        return []

    @staticmethod
    def analyze_query_plan(session: Session, query: str) -> dict:
        """
        Analyze query execution plan.
        
        Args:
            session: Database session
            query: SQL query to analyze
        
        Returns:
            Query plan information
        
        分析查询执行计划。
        """
        if "postgresql" in str(session.bind.url):
            result = session.execute(f"EXPLAIN ANALYZE {query}")
            return {"plan": result.fetchall()}

        return {"plan": []}


# Global session manager instance
_session_manager: Optional[AsyncSessionManager] = None


def get_session_manager() -> Optional[AsyncSessionManager]:
    """
    Get global async session manager.
    
    Returns:
        Session manager instance or None
    
    获取全局异步会话管理器。
    """
    return _session_manager


async def initialize_database(config: DatabaseConfig) -> None:
    """
    Initialize global database session manager.
    
    Args:
        config: Database configuration
    
    初始化全局数据库会话管理器。
    """
    global _session_manager
    _session_manager = AsyncSessionManager(config)
    await _session_manager.init_db()
    logger.info("Database initialized")


async def shutdown_database() -> None:
    """
    Shutdown database session manager.
    
    关闭数据库会话管理器。
    """
    global _session_manager
    if _session_manager:
        await _session_manager.close()


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for getting async database session.
    
    Used as Depends(get_async_session) in FastAPI route handlers.
    获取异步数据库会话的 FastAPI 依赖。
    
    在 FastAPI 路由处理程序中用作 Depends(get_async_session)。
    
    Yields:
        AsyncSession: Database session / 数据库会话
    """
    manager = get_session_manager()
    if not manager:
        raise RuntimeError("Database not initialized. Call initialize_database() first.")
    
    async for session in manager.get_session():
        yield session
