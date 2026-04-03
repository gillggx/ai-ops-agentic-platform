"""
Async utilities for improved performance and concurrency management.

用于改进的性能和并发管理的异步实用程序。
"""

import asyncio
import logging
from typing import Callable, Any, Optional, List, Dict, TypeVar, Coroutine
from functools import wraps
import time

logger = logging.getLogger(__name__)

T = TypeVar('T')


class AsyncBatcher:
    """
    Batch async operations for improved throughput.
    
    批量处理异步操作以提高吞吐量。
    """

    def __init__(
        self,
        process_func: Callable,
        batch_size: int = 100,
        wait_time: float = 0.1
    ):
        """
        Initialize async batcher.
        
        Args:
            process_func: Async function to process batches
            batch_size: Batch size
            wait_time: Wait time before processing
        
        初始化异步批处理器。
        """
        self.process_func = process_func
        self.batch_size = batch_size
        self.wait_time = wait_time
        self.queue: List[Any] = []
        self.futures: Dict[int, asyncio.Future] = {}
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """
        Start the batcher task.
        
        启动批处理器任务。
        """
        self._task = asyncio.create_task(self._process_batches())

    async def stop(self) -> None:
        """
        Stop the batcher task and process remaining items.
        
        停止批处理器任务并处理剩余项。
        """
        if self._task:
            if self.queue:
                await self._process_batch()
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def add(self, item: Any) -> Any:
        """
        Add item to batch queue.
        
        Args:
            item: Item to add
        
        Returns:
            Result from batch processing
        
        将项添加到批处理队列。
        """
        future: asyncio.Future = asyncio.Future()
        idx = len(self.queue)
        self.queue.append(item)
        self.futures[idx] = future

        if len(self.queue) >= self.batch_size:
            await self._process_batch()

        return future

    async def _process_batches(self) -> None:
        """
        Process batches in a loop.
        
        在循环中处理批次。
        """
        while True:
            try:
                await asyncio.sleep(self.wait_time)
                if self.queue:
                    await self._process_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in batch processor: {e}")

    async def _process_batch(self) -> None:
        """
        Process current batch.
        
        处理当前批次。
        """
        if not self.queue:
            return

        batch = self.queue[:]
        indices = list(self.futures.keys())
        self.queue = []

        try:
            results = await self.process_func(batch)
            for idx, result in zip(indices, results):
                if idx in self.futures:
                    future = self.futures.pop(idx)
                    if not future.done():
                        future.set_result(result)
        except Exception as e:
            logger.error(f"Error processing batch: {e}")
            for idx in indices:
                if idx in self.futures:
                    future = self.futures.pop(idx)
                    if not future.done():
                        future.set_exception(e)


class AsyncPool:
    """
    Async worker pool for parallel task execution.
    
    用于并行任务执行的异步工作池。
    """

    def __init__(self, size: int = 10):
        """
        Initialize async pool.
        
        Args:
            size: Number of workers
        
        初始化异步池。
        """
        self.size = size
        self.semaphore = asyncio.Semaphore(size)
        self.active_tasks = 0

    async def execute(
        self,
        coro: Coroutine
    ) -> Any:
        """
        Execute coroutine with pool constraint.
        
        Args:
            coro: Coroutine to execute
        
        Returns:
            Coroutine result
        
        使用池约束执行协程。
        """
        async with self.semaphore:
            return await coro

    async def map(
        self,
        func: Callable,
        items: List[Any]
    ) -> List[Any]:
        """
        Map async function over items with concurrency control.
        
        Args:
            func: Async function to map
            items: Items to process
        
        Returns:
            List of results
        
        使用并发控制将异步函数映射到项。
        """
        tasks = [
            self.execute(func(item))
            for item in items
        ]
        return await asyncio.gather(*tasks)


class RateLimiter:
    """
    Async rate limiter with token bucket algorithm.
    
    具有令牌桶算法的异步速率限制器。
    """

    def __init__(self, rate: int, period: float = 1.0):
        """
        Initialize rate limiter.
        
        Args:
            rate: Number of requests per period
            period: Time period in seconds
        
        初始化速率限制器。
        """
        self.rate = rate
        self.period = period
        self.tokens = rate
        self.updated_at = time.monotonic()

    async def acquire(self) -> None:
        """
        Acquire rate limit token.
        
        获取速率限制令牌。
        """
        while self.tokens < 1:
            now = time.monotonic()
            elapsed = now - self.updated_at
            self.tokens += elapsed * (self.rate / self.period)
            self.updated_at = now

            if self.tokens < 1:
                await asyncio.sleep((1 - self.tokens) * (self.period / self.rate))

        self.tokens -= 1

    def __call__(self, func: Callable) -> Callable:
        """
        Decorator for rate limiting.
        
        Args:
            func: Function to decorate
        
        Returns:
            Decorated function
        
        用于速率限制的装饰器。
        """
        @wraps(func)
        async def wrapper(*args, **kwargs):
            await self.acquire()
            return await func(*args, **kwargs)

        return wrapper


class AsyncTimeout:
    """
    Async timeout context manager with graceful degradation.
    
    具有优雅降级的异步超时上下文管理器。
    """

    def __init__(
        self,
        timeout: float,
        fallback: Optional[Callable] = None
    ):
        """
        Initialize async timeout.
        
        Args:
            timeout: Timeout in seconds
            fallback: Fallback function if timeout occurs
        
        初始化异步超时。
        """
        self.timeout = timeout
        self.fallback = fallback

    async def __aenter__(self):
        """
        Enter async context.
        
        进入异步上下文。
        """
        self.task = asyncio.current_task()
        self.handle = asyncio.get_event_loop().call_later(
            self.timeout,
            self._on_timeout
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Exit async context.
        
        退出异步上下文。
        """
        self.handle.cancel()
        return False

    def _on_timeout(self) -> None:
        """
        Handle timeout.
        
        处理超时。
        """
        if self.fallback:
            try:
                asyncio.create_task(self.fallback())
            except Exception as e:
                logger.error(f"Fallback error: {e}")
        else:
            if self.task:
                self.task.cancel()


class AsyncRetry:
    """
    Async retry with exponential backoff.
    
    具有指数退避的异步重试。
    """

    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
    ):
        """
        Initialize async retry.
        
        Args:
            max_retries: Maximum number of retries
            initial_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            backoff_factor: Exponential backoff factor
        
        初始化异步重试。
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor

    async def execute(
        self,
        coro: Coroutine,
        on_retry: Optional[Callable] = None
    ) -> Any:
        """
        Execute coroutine with retry logic.
        
        Args:
            coro: Coroutine to execute
            on_retry: Callback on retry
        
        Returns:
            Coroutine result
        
        使用重试逻辑执行协程。
        """
        delay = self.initial_delay
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                return await coro()
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries:
                    if on_retry:
                        await on_retry(attempt, delay, e)
                    await asyncio.sleep(delay)
                    delay = min(delay * self.backoff_factor, self.max_delay)

        raise last_exception

    def __call__(self, func: Callable) -> Callable:
        """
        Decorator for retry logic.
        
        Args:
            func: Function to decorate
        
        Returns:
            Decorated function
        
        用于重试逻辑的装饰器。
        """
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async def coro():
                return await func(*args, **kwargs)

            return await self.execute(coro)

        return wrapper


async def gather_with_limit(
    *coros: Coroutine,
    limit: int = 10
) -> List[Any]:
    """
    Gather coroutines with concurrency limit.
    
    Args:
        coros: Coroutines to gather
        limit: Concurrency limit
    
    Returns:
        List of results
    
    使用并发限制收集协程。
    """
    semaphore = asyncio.Semaphore(limit)

    async def bounded(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(bounded(c) for c in coros))
