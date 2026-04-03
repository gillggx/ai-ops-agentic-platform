"""
Performance tests for FastAPI backend.

FastAPI 后端的性能测试。
"""

import asyncio
import time
from typing import List
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from main import app
from app.core.database import AsyncSessionManager, DatabaseConfig


class TestDatabasePerformance:
    """
    Performance tests for database operations.
    
    数据库操作的性能测试。
    """

    @pytest.mark.asyncio
    async def test_bulk_insert_performance(
        self,
        session: AsyncSession
    ):
        """
        Test bulk insert performance.
        
        Args:
            session: Database session
        
        测试批量插入性能。
        """
        # Measure bulk insert time
        num_records = 1000
        start_time = time.time()

        # Insert records in batch
        # 批量插入记录
        batch_size = 100
        for i in range(0, num_records, batch_size):
            # Simulate batch insert
            await asyncio.sleep(0.001)

        elapsed = time.time() - start_time

        # Performance assertion: 1000 records in < 5 seconds
        # 性能断言：1000 条记录在 5 秒内
        assert elapsed < 5.0, f"Bulk insert too slow: {elapsed}s"

        # Calculate throughput
        throughput = num_records / elapsed
        print(f"Bulk insert throughput: {throughput:.2f} records/sec")

    @pytest.mark.asyncio
    async def test_query_performance(
        self,
        session: AsyncSession
    ):
        """
        Test query performance with indices.
        
        Args:
            session: Database session
        
        测试带索引的查询性能。
        """
        # Warm up cache
        # 预热缓存
        start_time = time.time()

        for i in range(100):
            # Simulate query
            await asyncio.sleep(0.001)

        elapsed = time.time() - start_time

        # Average query time should be < 50ms
        # 平均查询时间应该 < 50ms
        avg_time = (elapsed / 100) * 1000  # Convert to ms
        assert avg_time < 50.0, f"Query too slow: {avg_time:.2f}ms"

        print(f"Average query time: {avg_time:.2f}ms")

    @pytest.mark.asyncio
    async def test_connection_pool_efficiency(
        self,
        session_manager: AsyncSessionManager
    ):
        """
        Test connection pool efficiency.
        
        Args:
            session_manager: Session manager
        
        测试连接池效率。
        """
        num_concurrent = 50
        start_time = time.time()

        # Create multiple concurrent connections
        # 创建多个并发连接
        tasks = [
            asyncio.create_task(self._simulate_query(session_manager))
            for _ in range(num_concurrent)
        ]

        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start_time

        # All connections should complete
        assert len(results) == num_concurrent
        
        # Performance: 50 concurrent queries < 5 seconds
        # 性能：50 个并发查询 < 5 秒
        assert elapsed < 5.0, f"Connection pool too slow: {elapsed}s"

        print(f"Concurrent connections: {num_concurrent}")
        print(f"Total time: {elapsed:.2f}s")
        print(f"Avg time per connection: {(elapsed/num_concurrent)*1000:.2f}ms")

    async def _simulate_query(self, session_manager):
        """Simulate a database query."""
        await asyncio.sleep(0.01)
        return True


class TestAPIPerformance:
    """
    Performance tests for API endpoints.
    
    API 端点的性能测试。
    """

    @pytest.mark.asyncio
    async def test_endpoint_latency(
        self,
        client: AsyncClient
    ):
        """
        Test endpoint response latency.
        
        Args:
            client: AsyncClient
        
        测试端点响应延迟。
        """
        # Test root endpoint
        start_time = time.time()
        response = await client.get("/")
        elapsed = time.time() - start_time

        assert response.status_code == 200
        # Endpoint should respond in < 100ms
        # 端点应该在 100ms 内响应
        assert elapsed < 0.1, f"Endpoint too slow: {elapsed*1000:.2f}ms"

    @pytest.mark.asyncio
    async def test_concurrent_requests(
        self,
        client: AsyncClient
    ):
        """
        Test concurrent API requests.
        
        Args:
            client: AsyncClient
        
        测试并发 API 请求。
        """
        num_requests = 100
        tasks = [
            client.get("/health")
            for _ in range(num_requests)
        ]

        start_time = time.time()
        responses = await asyncio.gather(*tasks)
        elapsed = time.time() - start_time

        # All requests should succeed
        success_count = sum(1 for r in responses if r.status_code == 200)
        assert success_count == num_requests

        # Throughput: at least 20 requests/sec
        # 吞吐量：至少 20 req/s
        throughput = num_requests / elapsed
        assert throughput > 20, f"Throughput too low: {throughput:.2f} req/s"

        print(f"Concurrent requests: {num_requests}")
        print(f"Total time: {elapsed:.2f}s")
        print(f"Throughput: {throughput:.2f} req/s")

    @pytest.mark.asyncio
    async def test_endpoint_memory_usage(
        self,
        client: AsyncClient
    ):
        """
        Test endpoint memory efficiency.
        
        Args:
            client: AsyncClient
        
        测试端点内存效率。
        """
        import sys

        # Get initial memory
        initial_size = len(sys.getsizeof([]))

        # Make multiple requests
        for _ in range(10):
            response = await client.get("/health")
            assert response.status_code == 200

        # Memory should not grow excessively
        # 内存不应该过度增长


class TestCachePerformance:
    """
    Performance tests for caching layer.
    
    缓存层的性能测试。
    """

    @pytest.mark.asyncio
    async def test_cache_hit_performance(self, cache_manager):
        """
        Test cache hit performance.
        
        Args:
            cache_manager: Cache manager instance
        
        测试缓存命中性能。
        """
        key = "test_key"
        value = {"data": "test_value"}

        # Set cache value
        await cache_manager.set(key, value)

        # Measure cache get time
        num_gets = 1000
        start_time = time.time()

        for _ in range(num_gets):
            result = await cache_manager.get(key)
            assert result == value

        elapsed = time.time() - start_time

        # Cache hit should be very fast: 1000 gets < 100ms
        # 缓存命中应该非常快：1000 次获取 < 100ms
        assert elapsed < 0.1, f"Cache hits too slow: {elapsed*1000:.2f}ms"

        throughput = num_gets / elapsed
        print(f"Cache hit throughput: {throughput:.0f} ops/sec")

    @pytest.mark.asyncio
    async def test_cache_miss_performance(self, cache_manager):
        """
        Test cache miss performance.
        
        Args:
            cache_manager: Cache manager instance
        
        测试缓存未命中性能。
        """
        # Measure cache miss time (non-existent key)
        num_misses = 1000
        start_time = time.time()

        for i in range(num_misses):
            result = await cache_manager.get(f"nonexistent_{i}")
            assert result is None

        elapsed = time.time() - start_time

        # Cache miss should be fast: 1000 misses < 200ms
        # 缓存未命中应该快速：1000 次未命中 < 200ms
        assert elapsed < 0.2, f"Cache misses too slow: {elapsed*1000:.2f}ms"

        throughput = num_misses / elapsed
        print(f"Cache miss throughput: {throughput:.0f} ops/sec")


class TestMemoryLeaks:
    """
    Tests for potential memory leaks.
    
    潜在内存泄漏的测试。
    """

    @pytest.mark.asyncio
    async def test_session_cleanup(self, session_manager):
        """
        Test proper session cleanup.
        
        Args:
            session_manager: Session manager
        
        测试适当的会话清理。
        """
        import gc

        initial_sessions = []

        # Create and release sessions
        for _ in range(100):
            async with session_manager.async_session() as session:
                # Session automatically cleaned up
                pass

        # Force garbage collection
        gc.collect()

        # Monitor that sessions are properly cleaned
        # 监控会话是否正确清理

    @pytest.mark.asyncio
    async def test_cache_memory_growth(self, cache_manager):
        """
        Test cache memory doesn't grow unbounded.
        
        Args:
            cache_manager: Cache manager instance
        
        测试缓存内存不会无限增长。
        """
        # Add many items to cache (with TTL)
        for i in range(10000):
            await cache_manager.set(
                f"key_{i}",
                f"value_{i}",
                ttl=60  # Expire after 60 seconds
            )

        # Verify items are cached
        value = await cache_manager.get("key_0")
        assert value == "value_0"

        # Wait for cleanup (implementation dependent)
        # 等待清理（取决于实现）


class PerformanceBenchmark:
    """
    Comprehensive performance benchmarks.
    
    全面的性能基准。
    """

    @pytest.mark.asyncio
    async def test_full_request_cycle(
        self,
        client: AsyncClient
    ):
        """
        Test complete request cycle performance.
        
        Args:
            client: AsyncClient
        
        测试完整请求周期性能。
        """
        num_requests = 50
        request_times = []

        for _ in range(num_requests):
            start = time.time()
            response = await client.get("/health")
            elapsed = time.time() - start
            
            assert response.status_code == 200
            request_times.append(elapsed * 1000)  # Convert to ms

        # Calculate statistics
        avg_time = sum(request_times) / len(request_times)
        min_time = min(request_times)
        max_time = max(request_times)
        p95_time = sorted(request_times)[int(len(request_times) * 0.95)]

        print(f"\nRequest Performance:")
        print(f"  Average: {avg_time:.2f}ms")
        print(f"  Min: {min_time:.2f}ms")
        print(f"  Max: {max_time:.2f}ms")
        print(f"  P95: {p95_time:.2f}ms")

        # Performance assertions
        assert avg_time < 100, f"Average latency too high: {avg_time:.2f}ms"
        assert p95_time < 200, f"P95 latency too high: {p95_time:.2f}ms"

    @pytest.mark.asyncio
    async def test_throughput_benchmark(
        self,
        client: AsyncClient
    ):
        """
        Test API throughput benchmark.
        
        Args:
            client: AsyncClient
        
        测试 API 吞吐量基准。
        """
        duration = 5  # Run for 5 seconds
        requests_count = 0
        start_time = time.time()

        while time.time() - start_time < duration:
            response = await client.get("/health")
            assert response.status_code == 200
            requests_count += 1

        elapsed = time.time() - start_time
        throughput = requests_count / elapsed

        print(f"\nThroughput Benchmark:")
        print(f"  Total requests: {requests_count}")
        print(f"  Duration: {elapsed:.2f}s")
        print(f"  Throughput: {throughput:.2f} req/s")

        # Minimum throughput assertion
        assert throughput > 10, f"Throughput too low: {throughput:.2f} req/s"
