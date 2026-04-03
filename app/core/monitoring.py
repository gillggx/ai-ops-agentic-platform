"""
Advanced monitoring and metrics collection.

高级监控和指标收集。
"""

from typing import Dict, Optional, Any, Callable
from datetime import datetime
import logging
import time
from enum import Enum
from dataclasses import dataclass, asdict
import json

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """
    Types of metrics.
    
    指标类型。
    """

    COUNTER = "counter"  # Monotonically increasing value
    GAUGE = "gauge"  # Point-in-time value
    HISTOGRAM = "histogram"  # Distribution of values
    TIMER = "timer"  # Timing measurements


@dataclass
class MetricPoint:
    """
    Individual metric data point.
    
    单个指标数据点。
    """

    name: str
    value: float
    metric_type: MetricType
    timestamp: datetime
    labels: Optional[Dict[str, str]] = None
    unit: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary.
        
        转换为字典。
        """
        return {
            "name": self.name,
            "value": self.value,
            "type": self.metric_type.value,
            "timestamp": self.timestamp.isoformat(),
            "labels": self.labels or {},
            "unit": self.unit
        }


class MetricsCollector:
    """
    Collect and aggregate application metrics.
    
    收集和聚合应用程序指标。
    """

    def __init__(self):
        """Initialize metrics collector."""
        self.metrics: Dict[str, list] = {}
        self.timers: Dict[str, float] = {}

    def increment(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Increment counter metric.
        
        Args:
            name: Metric name
            value: Increment value
            labels: Metric labels
        
        递增计数器指标。
        """
        if name not in self.metrics:
            self.metrics[name] = []

        point = MetricPoint(
            name=name,
            value=value,
            metric_type=MetricType.COUNTER,
            timestamp=datetime.utcnow(),
            labels=labels
        )
        self.metrics[name].append(point)

    def gauge(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Record gauge metric.
        
        Args:
            name: Metric name
            value: Gauge value
            labels: Metric labels
        
        记录仪表指标。
        """
        if name not in self.metrics:
            self.metrics[name] = []

        point = MetricPoint(
            name=name,
            value=value,
            metric_type=MetricType.GAUGE,
            timestamp=datetime.utcnow(),
            labels=labels
        )
        # For gauge, keep only latest value
        self.metrics[name] = [point]

    def histogram(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Record histogram metric.
        
        Args:
            name: Metric name
            value: Value for histogram
            labels: Metric labels
        
        记录直方图指标。
        """
        if name not in self.metrics:
            self.metrics[name] = []

        point = MetricPoint(
            name=name,
            value=value,
            metric_type=MetricType.HISTOGRAM,
            timestamp=datetime.utcnow(),
            labels=labels
        )
        self.metrics[name].append(point)

    def start_timer(self, name: str) -> None:
        """
        Start timer.
        
        Args:
            name: Timer name
        
        启动计时器。
        """
        self.timers[name] = time.time()

    def stop_timer(
        self,
        name: str,
        labels: Optional[Dict[str, str]] = None
    ) -> float:
        """
        Stop timer and record duration.
        
        Args:
            name: Timer name
            labels: Metric labels
        
        Returns:
            Elapsed time in seconds
        
        停止计时器并记录持续时间。
        """
        if name not in self.timers:
            logger.warning(f"Timer {name} was not started")
            return 0.0

        elapsed = time.time() - self.timers[name]
        del self.timers[name]

        # Record as histogram
        self.histogram(name, elapsed, labels)

        return elapsed

    def get_all_metrics(self) -> Dict[str, Any]:
        """
        Get all collected metrics.
        
        Returns:
            Dictionary of all metrics
        
        获取所有收集的指标。
        """
        return {
            name: [point.to_dict() for point in points]
            for name, points in self.metrics.items()
        }

    def get_metric(self, name: str) -> Optional[list]:
        """
        Get specific metric.
        
        Args:
            name: Metric name
        
        Returns:
            Metric points or None
        
        获取特定指标。
        """
        return self.metrics.get(name)

    def get_metric_stats(self, name: str) -> Dict[str, float]:
        """
        Get statistics for metric.
        
        Args:
            name: Metric name
        
        Returns:
            Statistics (min, max, avg, count)
        
        获取指标的统计信息。
        """
        points = self.metrics.get(name, [])
        if not points:
            return {}

        values = [p.value for p in points]
        return {
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "count": len(values),
            "sum": sum(values)
        }

    def clear(self) -> None:
        """Clear all metrics."""
        self.metrics.clear()


class HealthCheck:
    """
    Application health check manager.
    
    应用程序健康检查管理器。
    """

    def __init__(self):
        """Initialize health check manager."""
        self.checks: Dict[str, Callable] = {}
        self.check_results: Dict[str, bool] = {}
        self.last_check: Optional[datetime] = None

    def register_check(
        self,
        name: str,
        check_func: Callable
    ) -> None:
        """
        Register health check.
        
        Args:
            name: Check name
            check_func: Async check function
        
        注册健康检查。
        """
        self.checks[name] = check_func

    async def run_checks(self) -> Dict[str, bool]:
        """
        Run all health checks.
        
        Returns:
            Dictionary of check results
        
        运行所有健康检查。
        """
        self.check_results = {}

        for name, check_func in self.checks.items():
            try:
                result = await check_func() if hasattr(
                    check_func, '__await__'
                ) else check_func()
                self.check_results[name] = bool(result)
            except Exception as e:
                logger.error(f"Health check {name} failed: {e}")
                self.check_results[name] = False

        self.last_check = datetime.utcnow()
        return self.check_results

    def get_status(self) -> Dict[str, Any]:
        """
        Get overall health status.
        
        Returns:
            Status dictionary
        
        获取总体健康状态。
        """
        overall = all(self.check_results.values()) if self.check_results else True

        return {
            "overall": "healthy" if overall else "unhealthy",
            "checks": self.check_results,
            "last_check": self.last_check.isoformat() if self.last_check else None
        }


class PerformanceMonitor:
    """
    Monitor application performance.
    
    监控应用程序性能。
    """

    def __init__(self):
        """Initialize performance monitor."""
        self.request_times: Dict[str, list] = {}
        self.error_counts: Dict[str, int] = {}
        self.database_queries: int = 0
        self.cache_hits: int = 0
        self.cache_misses: int = 0

    def record_request(
        self,
        endpoint: str,
        duration: float
    ) -> None:
        """
        Record request timing.
        
        Args:
            endpoint: API endpoint
            duration: Request duration in seconds
        
        记录请求时间。
        """
        if endpoint not in self.request_times:
            self.request_times[endpoint] = []

        self.request_times[endpoint].append(duration)

    def record_error(self, endpoint: str) -> None:
        """
        Record error occurrence.
        
        Args:
            endpoint: API endpoint
        
        记录错误发生。
        """
        if endpoint not in self.error_counts:
            self.error_counts[endpoint] = 0

        self.error_counts[endpoint] += 1

    def record_cache_hit(self) -> None:
        """Record cache hit."""
        self.cache_hits += 1

    def record_cache_miss(self) -> None:
        """Record cache miss."""
        self.cache_misses += 1

    def get_performance_report(self) -> Dict[str, Any]:
        """
        Get performance report.
        
        Returns:
            Performance statistics
        
        获取性能报告。
        """
        report = {
            "endpoints": {},
            "errors": self.error_counts,
            "cache": {
                "hits": self.cache_hits,
                "misses": self.cache_misses,
                "hit_rate": self._calculate_hit_rate()
            }
        }

        for endpoint, times in self.request_times.items():
            report["endpoints"][endpoint] = {
                "count": len(times),
                "avg": sum(times) / len(times),
                "min": min(times),
                "max": max(times),
                "p95": self._calculate_percentile(times, 0.95)
            }

        return report

    @staticmethod
    def _calculate_percentile(values: list, percentile: float) -> float:
        """Calculate percentile."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = int(len(sorted_values) * percentile)
        return sorted_values[index]

    def _calculate_hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return (self.cache_hits / total) * 100


class MetricsExporter:
    """
    Export metrics in different formats.
    
    以不同格式导出指标。
    """

    @staticmethod
    def to_prometheus(metrics: Dict[str, Any]) -> str:
        """
        Export metrics in Prometheus format.
        
        Args:
            metrics: Metrics dictionary
        
        Returns:
            Prometheus format string
        
        以 Prometheus 格式导出指标。
        """
        lines = []

        for metric_name, points in metrics.items():
            for point in points:
                line = f"{metric_name}"
                if point.get("labels"):
                    labels = ",".join(
                        f'{k}="{v}"' for k, v in point["labels"].items()
                    )
                    line += f"{{{labels}}}"
                line += f' {point["value"]}'
                lines.append(line)

        return "\n".join(lines)

    @staticmethod
    def to_json(metrics: Dict[str, Any]) -> str:
        """
        Export metrics as JSON.
        
        Args:
            metrics: Metrics dictionary
        
        Returns:
            JSON string
        
        以 JSON 格式导出指标。
        """
        return json.dumps(metrics, default=str)

    @staticmethod
    def to_csv(metrics: Dict[str, Any]) -> str:
        """
        Export metrics as CSV.
        
        Args:
            metrics: Metrics dictionary
        
        Returns:
            CSV string
        
        以 CSV 格式导出指标。
        """
        lines = ["metric_name,value,type,timestamp"]

        for metric_name, points in metrics.items():
            for point in points:
                line = f"{metric_name},{point['value']},{point['type']},{point['timestamp']}"
                lines.append(line)

        return "\n".join(lines)


# Global instances
_metrics_collector: Optional[MetricsCollector] = None
_health_check: Optional[HealthCheck] = None
_performance_monitor: Optional[PerformanceMonitor] = None


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector."""
    global _metrics_collector
    if not _metrics_collector:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def get_health_check() -> HealthCheck:
    """Get global health check manager."""
    global _health_check
    if not _health_check:
        _health_check = HealthCheck()
    return _health_check


def get_performance_monitor() -> PerformanceMonitor:
    """Get global performance monitor."""
    global _performance_monitor
    if not _performance_monitor:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor
