"""
Caching layer with multi-backend support.

带有多后端支持的缓存层。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type, TypeVar
import json
import logging
from datetime import timedelta
import asyncio

import redis
import redis.asyncio as aioredis
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CacheBackend(ABC):
    """
    Abstract base class for cache backends.
    
    缓存后端的抽象基类。
    """

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
        
        Returns:
            Cached value or None
        
        从缓存中获取值。
        """
        pass

    @abstractmethod
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> None:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
        
        设置缓存中的值。
        """
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """
        Delete value from cache.
        
        Args:
            key: Cache key
        
        从缓存中删除值。
        """
        pass

    @abstractmethod
    async def clear(self) -> None:
        """
        Clear all cache entries.
        
        清除所有缓存条目。
        """
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """
        Check if key exists in cache.
        
        Args:
            key: Cache key
        
        Returns:
            True if exists, False otherwise
        
        检查键是否存在于缓存中。
        """
        pass


class RedisCache(CacheBackend):
    """
    Redis-based cache backend.
    
    基于 Redis 的缓存后端。
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        prefix: str = "cache:",
        encoding: str = "utf-8"
    ):
        """
        Initialize Redis cache.
        
        Args:
            url: Redis connection URL
            prefix: Key prefix
            encoding: String encoding
        
        初始化 Redis 缓存。
        """
        self.url = url
        self.prefix = prefix
        self.encoding = encoding
        self.client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        """
        Connect to Redis.
        
        连接到 Redis。
        """
        try:
            self.client = await aioredis.from_url(
                self.url,
                encoding=self.encoding,
                decode_responses=True
            )
            logger.info(f"Connected to Redis at {self.url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self) -> None:
        """
        Disconnect from Redis.
        
        断开与 Redis 的连接。
        """
        if self.client:
            await self.client.close()
            logger.info("Disconnected from Redis")

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from Redis cache.
        
        Args:
            key: Cache key
        
        Returns:
            Cached value or None
        
        从 Redis 缓存中获取值。
        """
        if not self.client:
            return None

        try:
            full_key = f"{self.prefix}{key}"
            value = await self.client.get(full_key)
            if value:
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value
            return None
        except Exception as e:
            logger.error(f"Error getting cache key {key}: {e}")
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> None:
        """
        Set value in Redis cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
        
        在 Redis 缓存中设置值。
        """
        if not self.client:
            return

        try:
            full_key = f"{self.prefix}{key}"
            # Serialize if needed
            if isinstance(value, (dict, list)):
                value = json.dumps(value)

            if ttl:
                await self.client.setex(full_key, ttl, value)
            else:
                await self.client.set(full_key, value)
        except Exception as e:
            logger.error(f"Error setting cache key {key}: {e}")

    async def delete(self, key: str) -> None:
        """
        Delete value from Redis cache.
        
        Args:
            key: Cache key
        
        从 Redis 缓存中删除值。
        """
        if not self.client:
            return

        try:
            full_key = f"{self.prefix}{key}"
            await self.client.delete(full_key)
        except Exception as e:
            logger.error(f"Error deleting cache key {key}: {e}")

    async def clear(self) -> None:
        """
        Clear all cache entries with prefix.
        
        清除所有带前缀的缓存条目。
        """
        if not self.client:
            return

        try:
            pattern = f"{self.prefix}*"
            keys = await self.client.keys(pattern)
            if keys:
                await self.client.delete(*keys)
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")

    async def exists(self, key: str) -> bool:
        """
        Check if key exists in Redis cache.
        
        Args:
            key: Cache key
        
        Returns:
            True if exists, False otherwise
        
        检查键是否存在于 Redis 缓存中。
        """
        if not self.client:
            return False

        try:
            full_key = f"{self.prefix}{key}"
            return await self.client.exists(full_key) > 0
        except Exception as e:
            logger.error(f"Error checking cache key {key}: {e}")
            return False


class InMemoryCache(CacheBackend):
    """
    In-memory cache backend for testing and development.
    
    用于测试和开发的内存中缓存后端。
    """

    def __init__(self, prefix: str = "cache:"):
        """
        Initialize in-memory cache.
        
        Args:
            prefix: Key prefix
        
        初始化内存中缓存。
        """
        self.prefix = prefix
        self.data: Dict[str, tuple[Any, Optional[float]]] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """
        Initialize in-memory cache (no-op for in-memory).
        
        初始化内存中缓存。
        """
        self._cleanup_task = asyncio.create_task(self._cleanup_expired())

    async def disconnect(self) -> None:
        """
        Cleanup in-memory cache.
        
        清理内存中缓存。
        """
        if self._cleanup_task:
            self._cleanup_task.cancel()

    async def _cleanup_expired(self) -> None:
        """
        Periodically cleanup expired entries.
        
        定期清理过期的条目。
        """
        while True:
            try:
                await asyncio.sleep(60)
                now = asyncio.get_event_loop().time()
                expired_keys = [
                    k for k, (_, exp_time) in self.data.items()
                    if exp_time and exp_time < now
                ]
                for key in expired_keys:
                    del self.data[key]
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup: {e}")

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from in-memory cache.
        
        Args:
            key: Cache key
        
        Returns:
            Cached value or None
        
        从内存中缓存中获取值。
        """
        full_key = f"{self.prefix}{key}"
        if full_key not in self.data:
            return None

        value, exp_time = self.data[full_key]
        if exp_time:
            now = asyncio.get_event_loop().time()
            if exp_time < now:
                del self.data[full_key]
                return None

        return value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> None:
        """
        Set value in in-memory cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
        
        在内存中缓存中设置值。
        """
        full_key = f"{self.prefix}{key}"
        exp_time = None
        if ttl:
            exp_time = asyncio.get_event_loop().time() + ttl

        self.data[full_key] = (value, exp_time)

    async def delete(self, key: str) -> None:
        """
        Delete value from in-memory cache.
        
        Args:
            key: Cache key
        
        从内存中缓存中删除值。
        """
        full_key = f"{self.prefix}{key}"
        self.data.pop(full_key, None)

    async def clear(self) -> None:
        """
        Clear all cache entries with prefix.
        
        清除所有带前缀的缓存条目。
        """
        prefix_len = len(self.prefix)
        keys_to_delete = [
            k for k in self.data.keys()
            if k.startswith(self.prefix)
        ]
        for key in keys_to_delete:
            del self.data[key]

    async def exists(self, key: str) -> bool:
        """
        Check if key exists in in-memory cache.
        
        Args:
            key: Cache key
        
        Returns:
            True if exists, False otherwise
        
        检查键是否存在于内存中缓存中。
        """
        full_key = f"{self.prefix}{key}"
        if full_key not in self.data:
            return False

        value, exp_time = self.data[full_key]
        if exp_time:
            now = asyncio.get_event_loop().time()
            if exp_time < now:
                del self.data[full_key]
                return False

        return True


class CacheManager:
    """
    High-level cache manager with multiple backends support.
    
    具有多后端支持的高级缓存管理器。
    """

    def __init__(self, backend: CacheBackend):
        """
        Initialize cache manager.
        
        Args:
            backend: Cache backend instance
        
        初始化缓存管理器。
        """
        self.backend = backend

    async def connect(self) -> None:
        """
        Connect cache backend.
        
        连接缓存后端。
        """
        await self.backend.connect()

    async def disconnect(self) -> None:
        """
        Disconnect cache backend.
        
        断开缓存后端的连接。
        """
        await self.backend.disconnect()

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
        
        Returns:
            Cached value or None
        
        从缓存中获取值。
        """
        return await self.backend.get(key)

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> None:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
        
        在缓存中设置值。
        """
        await self.backend.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        """
        Delete value from cache.
        
        Args:
            key: Cache key
        
        从缓存中删除值。
        """
        await self.backend.delete(key)

    async def clear(self) -> None:
        """
        Clear all cache entries.
        
        清除所有缓存条目。
        """
        await self.backend.clear()

    async def exists(self, key: str) -> bool:
        """
        Check if key exists in cache.
        
        Args:
            key: Cache key
        
        Returns:
            True if exists, False otherwise
        
        检查键是否存在于缓存中。
        """
        return await self.backend.exists(key)

    def cache_decorator(
        self,
        ttl: int = 300,
        key_builder=None
    ):
        """
        Decorator for caching async function results.
        
        Args:
            ttl: Time to live in seconds
            key_builder: Function to build cache key
        
        Returns:
            Decorator function
        
        用于缓存异步函数结果的装饰器。
        """
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Build cache key
                if key_builder:
                    cache_key = key_builder(func, args, kwargs)
                else:
                    cache_key = f"{func.__module__}.{func.__name__}"
                    if args:
                        cache_key += f":{':'.join(str(a) for a in args)}"
                    if kwargs:
                        cache_key += f":{':'.join(f'{k}={v}' for k, v in kwargs.items())}"

                # Try to get from cache
                cached = await self.get(cache_key)
                if cached is not None:
                    return cached

                # Call function
                result = await func(*args, **kwargs)

                # Store in cache
                await self.set(cache_key, result, ttl)

                return result

            return wrapper

        return decorator


# Global cache manager instance
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> Optional[CacheManager]:
    """
    Get global cache manager instance.
    
    Returns:
        Cache manager instance or None
    
    获取全局缓存管理器实例。
    """
    return _cache_manager


async def initialize_cache(backend: CacheBackend) -> None:
    """
    Initialize global cache manager.
    
    Args:
        backend: Cache backend instance
    
    初始化全局缓存管理器。
    """
    global _cache_manager
    _cache_manager = CacheManager(backend)
    await _cache_manager.connect()


async def shutdown_cache() -> None:
    """
    Shutdown cache manager.
    
    关闭缓存管理器。
    """
    global _cache_manager
    if _cache_manager:
        await _cache_manager.disconnect()
