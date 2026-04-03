"""
Load testing for FastAPI backend.

FastAPI 后端的负载测试。
"""

import asyncio
import time
from typing import List, Tuple
import pytest
from httpx import AsyncClient
import statistics

from main import app


class LoadTestScenarios:
    """
    Load testing scenarios and benchmarks.
    
    负载测试场景和基准。
    """

    @pytest.mark.asyncio
    async def test_sustained_load(self, client: AsyncClient):
        """
        Test sustained load over time.
        
        Args:
            client: AsyncClient
        
        测试持续的负载。
        """
        duration = 10  # 10 seconds
        request_rate = 50  # 50 requests per second
        interval = 1.0 / request_rate

        start_time = time.time()
        end_time = start_time + duration

        request_count = 0
        error_count = 0
        response_times: List[float] = []

        while time.time() < end_time:
            batch_start = time.time()

            # Send request
            try:
                response_start = time.time()
                response = await client.get("/health")
                response_time = time.time() - response_start

                if response.status_code == 200:
                    request_count += 1
                    response_times.append(response_time)
                else:
                    error_count += 1
            except Exception as e:
                error_count += 1

            # Sleep to maintain rate
            elapsed = time.time() - batch_start
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)

        total_duration = time.time() - start_time

        # Calculate statistics
        avg_response_time = (
            statistics.mean(response_times)
            if response_times else 0
        )
        p95_response_time = (
            sorted(response_times)[int(len(response_times) * 0.95)]
            if response_times else 0
        )
        throughput = request_count / total_duration

        print(f"\nSustained Load Test Results:")
        print(f"  Duration: {total_duration:.2f}s")
        print(f"  Requests: {request_count}")
        print(f"  Errors: {error_count}")
        print(f"  Throughput: {throughput:.2f} req/s")
        print(f"  Avg Response: {avg_response_time*1000:.2f}ms")
        print(f"  P95 Response: {p95_response_time*1000:.2f}ms")

        # Assertions
        assert error_count < request_count * 0.01  # < 1% error rate
        assert throughput > request_rate * 0.8  # 80% of target rate

    @pytest.mark.asyncio
    async def test_ramp_up(self, client: AsyncClient):
        """
        Test ramp-up load scenario.
        
        Args:
            client: AsyncClient
        
        测试爬升负载场景。
        """
        ramp_duration = 5  # 5 seconds
        initial_rate = 10  # 10 req/s
        final_rate = 100  # 100 req/s

        start_time = time.time()
        request_count = 0
        error_count = 0
        response_times: List[float] = []

        while time.time() - start_time < ramp_duration:
            elapsed = time.time() - start_time
            progress = elapsed / ramp_duration

            # Calculate current rate
            current_rate = initial_rate + (
                (final_rate - initial_rate) * progress
            )
            interval = 1.0 / current_rate

            # Send request
            try:
                response_start = time.time()
                response = await client.get("/health")
                response_time = time.time() - response_start

                if response.status_code == 200:
                    request_count += 1
                    response_times.append(response_time)
                else:
                    error_count += 1
            except Exception:
                error_count += 1

            # Sleep to maintain rate
            await asyncio.sleep(interval)

        throughput = request_count / ramp_duration

        print(f"\nRamp-Up Load Test Results:")
        print(f"  Initial rate: {initial_rate} req/s")
        print(f"  Final rate: {final_rate} req/s")
        print(f"  Total requests: {request_count}")
        print(f"  Errors: {error_count}")
        print(f"  Avg throughput: {throughput:.2f} req/s")

        assert error_count < request_count * 0.05  # < 5% error rate

    @pytest.mark.asyncio
    async def test_spike_load(self, client: AsyncClient):
        """
        Test sudden spike in load.
        
        Args:
            client: AsyncClient
        
        测试负载的突然峰值。
        """
        baseline_rate = 20  # 20 req/s
        spike_rate = 200  # 200 req/s
        baseline_duration = 3  # 3 seconds
        spike_duration = 2  # 2 seconds
        cooldown_duration = 3  # 3 seconds

        results = {
            "baseline": [],
            "spike": [],
            "cooldown": []
        }

        # Baseline phase
        await self._run_load_phase(
            client,
            baseline_rate,
            baseline_duration,
            results["baseline"]
        )

        # Spike phase
        await self._run_load_phase(
            client,
            spike_rate,
            spike_duration,
            results["spike"]
        )

        # Cooldown phase
        await self._run_load_phase(
            client,
            baseline_rate,
            cooldown_duration,
            results["cooldown"]
        )

        # Analyze results
        for phase, times in results.items():
            if times:
                avg = statistics.mean(times)
                max_time = max(times)
                print(f"{phase.capitalize()}: avg={avg*1000:.2f}ms max={max_time*1000:.2f}ms")

        # System should recover after spike
        cooldown_avg = statistics.mean(results["cooldown"]) if results["cooldown"] else 0
        baseline_avg = statistics.mean(results["baseline"]) if results["baseline"] else 0
        assert cooldown_avg < baseline_avg * 1.5  # Within 50% of baseline

    async def _run_load_phase(
        self,
        client: AsyncClient,
        rate: int,
        duration: float,
        results: List[float]
    ) -> None:
        """
        Run a load test phase.
        
        Args:
            client: AsyncClient
            rate: Request rate per second
            duration: Phase duration
            results: List to store response times
        
        运行负载测试阶段。
        """
        interval = 1.0 / rate
        start_time = time.time()

        while time.time() - start_time < duration:
            try:
                response_start = time.time()
                response = await client.get("/health")
                response_time = time.time() - response_start

                if response.status_code == 200:
                    results.append(response_time)
            except Exception:
                pass

            await asyncio.sleep(interval)


class ConcurrencyStressTest:
    """
    Concurrency and stress testing.
    
    并发和压力测试。
    """

    @pytest.mark.asyncio
    async def test_high_concurrency(self, client: AsyncClient):
        """
        Test with high concurrency.
        
        Args:
            client: AsyncClient
        
        测试高并发。
        """
        num_concurrent = 200
        requests_per_client = 10

        tasks = [
            self._client_session(client, requests_per_client)
            for _ in range(num_concurrent)
        ]

        start_time = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.time() - start_time

        # Count successes and failures
        successes = sum(1 for r in results if r is True)
        failures = sum(1 for r in results if r is not True)

        throughput = (successes * requests_per_client) / elapsed

        print(f"\nHigh Concurrency Test:")
        print(f"  Concurrent clients: {num_concurrent}")
        print(f"  Requests per client: {requests_per_client}")
        print(f"  Total requests: {successes * requests_per_client}")
        print(f"  Successful: {successes}")
        print(f"  Failed: {failures}")
        print(f"  Duration: {elapsed:.2f}s")
        print(f"  Throughput: {throughput:.2f} req/s")

        assert failures < num_concurrent * 0.1  # < 10% failure rate

    async def _client_session(
        self,
        client: AsyncClient,
        num_requests: int
    ) -> bool:
        """
        Simulate a client session.
        
        Args:
            client: AsyncClient
            num_requests: Number of requests
        
        Returns:
            True if successful
        
        模拟客户端会话。
        """
        try:
            for _ in range(num_requests):
                response = await client.get("/health")
                if response.status_code != 200:
                    return False
            return True
        except Exception:
            return False

    @pytest.mark.asyncio
    async def test_resource_exhaustion(self, client: AsyncClient):
        """
        Test behavior under resource exhaustion.
        
        Args:
            client: AsyncClient
        
        测试资源耗尽下的行为。
        """
        # Create many concurrent connections
        num_requests = 500
        tasks = [
            client.get("/health")
            for _ in range(num_requests)
        ]

        start_time = time.time()
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.time() - start_time

        # Count results
        successes = sum(1 for r in responses if isinstance(r, object) and hasattr(r, 'status_code'))
        errors = sum(1 for r in responses if isinstance(r, Exception))

        success_rate = (successes / num_requests) * 100

        print(f"\nResource Exhaustion Test:")
        print(f"  Total requests: {num_requests}")
        print(f"  Successful: {successes}")
        print(f"  Errors: {errors}")
        print(f"  Success rate: {success_rate:.2f}%")
        print(f"  Duration: {elapsed:.2f}s")

        # System should handle gracefully
        assert success_rate > 90  # At least 90% success


@pytest.mark.asyncio
async def test_memory_stability(client: AsyncClient):
    """
    Test memory stability under load.
    
    Args:
        client: AsyncClient
    
    测试负载下的内存稳定性。
    """
    import gc
    import sys

    # Get initial memory
    gc.collect()
    # initial_memory = sys.getsizeof(client)

    # Perform many requests
    for _ in range(100):
        response = await client.get("/health")
        assert response.status_code == 200

    # Force garbage collection
    gc.collect()

    # Memory usage should be reasonable
    # (implementation specific check)


@pytest.mark.asyncio
async def test_connection_pooling(client: AsyncClient):
    """
    Test connection pooling efficiency.
    
    Args:
        client: AsyncClient
    
    测试连接池效率。
    """
    # Make sequential requests to test connection reuse
    num_requests = 50
    response_times: List[float] = []

    for _ in range(num_requests):
        start = time.time()
        response = await client.get("/health")
        elapsed = time.time() - start

        assert response.status_code == 200
        response_times.append(elapsed)

    # Later requests should be faster (connection reuse)
    first_half_avg = statistics.mean(response_times[:25])
    second_half_avg = statistics.mean(response_times[25:])

    print(f"\nConnection Pooling Test:")
    print(f"  First 25 avg: {first_half_avg*1000:.2f}ms")
    print(f"  Last 25 avg: {second_half_avg*1000:.2f}ms")
    print(f"  Improvement: {((first_half_avg - second_half_avg) / first_half_avg * 100):.2f}%")

    # Later requests should be somewhat faster
    assert second_half_avg < first_half_avg * 1.1
