"""
Monitoring and health check for AI Ops layer.

監控和健康檢查。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional


class MetricsCollector:
    """
    Collect and track metrics for system monitoring.
    
    指標收集器。
    
    Tracks:
    - Request metrics (count, latency, errors)
    - System metrics (CPU, memory, DB connections)
    - Business metrics (operations, conversions)
    - Custom metrics
    """

    def __init__(self):
        """Initialize metrics collector."""
        self._metrics: Dict[str, Dict[str, Any]] = {}
        self._start_time = datetime.utcnow()

    def record_metric(
        self,
        name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Record a metric.
        
        Args:
            name: str - Metric name
            value: float - Metric value
            tags: Optional[Dict] - Metric tags
        
        記錄指標。
        """
        if name not in self._metrics:
            self._metrics[name] = {
                "values": [],
                "tags": tags or {},
                "created_at": datetime.utcnow(),
            }

        self._metrics[name]["values"].append(value)
        self._metrics[name]["last_value"] = value
        self._metrics[name]["last_updated"] = datetime.utcnow()

    def get_metric(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get metric by name.
        
        Args:
            name: str - Metric name
        
        Returns:
            Dict or None - Metric data or None
        
        獲取指標。
        """
        return self._metrics.get(name)

    def get_all_metrics(self) -> Dict[str, Any]:
        """
        Get all metrics.
        
        Returns:
            Dict - All metrics
        
        獲取所有指標。
        """
        return self._metrics.copy()

    def calculate_average(self, name: str) -> Optional[float]:
        """
        Calculate average of a metric.
        
        Args:
            name: str - Metric name
        
        Returns:
            float or None - Average value or None
        
        計算平均值。
        """
        metric = self._metrics.get(name)
        if not metric or not metric.get("values"):
            return None

        values = metric["values"]
        return sum(values) / len(values)

    def calculate_percentile(
        self,
        name: str,
        percentile: int = 95,
    ) -> Optional[float]:
        """
        Calculate percentile of a metric.
        
        Args:
            name: str - Metric name
            percentile: int - Percentile (1-100)
        
        Returns:
            float or None - Percentile value or None
        
        計算百分位數。
        """
        metric = self._metrics.get(name)
        if not metric or not metric.get("values"):
            return None

        values = sorted(metric["values"])
        index = int(len(values) * (percentile / 100)) - 1
        return values[max(0, index)]

    def __repr__(self) -> str:
        """Return detailed representation."""
        return f"MetricsCollector(metrics={len(self._metrics)})"


class HealthCheck:
    """
    System health check and status monitoring.
    
    健康檢查。
    
    Tracks:
    - Service availability
    - Database connectivity
    - Cache status
    - External service status
    - Overall system health
    """

    def __init__(self):
        """Initialize health check."""
        self._checks: Dict[str, Dict[str, Any]] = {}
        self._last_check = None

    def register_check(
        self,
        name: str,
        check_fn,
    ) -> None:
        """
        Register a health check.
        
        Args:
            name: str - Check name
            check_fn: callable - Check function (async or sync)
        
        註冊健康檢查。
        """
        self._checks[name] = {
            "fn": check_fn,
            "status": "unknown",
            "last_checked": None,
            "message": None,
        }

    async def run_checks(self) -> Dict[str, Any]:
        """
        Run all health checks.
        
        Returns:
            Dict - Check results
        
        運行所有健康檢查。
        """
        results = {}
        self._last_check = datetime.utcnow()

        for name, check in self._checks.items():
            try:
                fn = check["fn"]
                # Check if async
                if hasattr(fn, "__await__"):
                    result = await fn()
                else:
                    result = fn()

                results[name] = {
                    "status": "healthy" if result else "unhealthy",
                    "message": result if isinstance(result, str) else None,
                    "checked_at": datetime.utcnow(),
                }

                self._checks[name]["status"] = results[name]["status"]
                self._checks[name]["last_checked"] = datetime.utcnow()

            except Exception as e:
                results[name] = {
                    "status": "unhealthy",
                    "message": str(e),
                    "checked_at": datetime.utcnow(),
                }
                self._checks[name]["status"] = "unhealthy"

        return results

    def get_status(self) -> Dict[str, Any]:
        """
        Get current health status.
        
        Returns:
            Dict - Health status
        
        獲取當前健康狀態。
        """
        statuses = [check["status"] for check in self._checks.values()]
        overall = "healthy" if all(s == "healthy" for s in statuses) else "unhealthy"

        return {
            "overall": overall,
            "checks": {name: check["status"] for name, check in self._checks.items()},
            "last_check": self._last_check,
            "uptime_seconds": (datetime.utcnow() - self._last_check).total_seconds() if self._last_check else 0,
        }

    def __repr__(self) -> str:
        """Return detailed representation."""
        return f"HealthCheck(checks={len(self._checks)})"
