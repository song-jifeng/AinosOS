"""
Performance metrics and monitoring utilities.
"""

import time
import json
import threading
from collections import defaultdict, deque
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from functools import wraps


@dataclass
class TimingStats:
    """Statistics for a timed operation."""
    count: int = 0
    total_time: float = 0.0
    min_time: float = float('inf')
    max_time: float = 0.0
    mean_time: float = 0.0
    p50_time: float = 0.0
    p95_time: float = 0.0
    p99_time: float = 0.0
    times: List[float] = field(default_factory=list)

    def update(self, elapsed: float):
        """Update statistics with a new timing."""
        self.count += 1
        self.total_time += elapsed
        self.times.append(elapsed)
        if elapsed < self.min_time:
            self.min_time = elapsed
        if elapsed > self.max_time:
            self.max_time = elapsed

    def compute_percentiles(self):
        """Compute percentile statistics."""
        if not self.times:
            return
        sorted_times = sorted(self.times)
        n = len(sorted_times)
        self.mean_time = self.total_time / n
        self.p50_time = sorted_times[int(n * 0.5)]
        self.p95_time = sorted_times[int(n * 0.95)]
        self.p99_time = sorted_times[int(n * 0.99)]

    def reset(self):
        """Reset all statistics."""
        self.count = 0
        self.total_time = 0.0
        self.min_time = float('inf')
        self.max_time = 0.0
        self.mean_time = 0.0
        self.p50_time = 0.0
        self.p95_time = 0.0
        self.p99_time = 0.0
        self.times.clear()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        self.compute_percentiles()
        return {
            "count": self.count,
            "total_time": round(self.total_time, 6),
            "min_time": round(self.min_time, 6) if self.min_time != float('inf') else 0.0,
            "max_time": round(self.max_time, 6),
            "mean_time": round(self.mean_time, 6),
            "p50_time": round(self.p50_time, 6),
            "p95_time": round(self.p95_time, 6),
            "p99_time": round(self.p99_time, 6),
        }


@dataclass
class MemoryStats:
    """Memory usage statistics."""
    total_vectors: int = 0
    total_dimensions: int = 0
    vector_memory_bytes: int = 0
    index_memory_bytes: int = 0
    metadata_memory_bytes: int = 0
    total_memory_bytes: int = 0

    def update(self, vector_bytes: int = 0, index_bytes: int = 0, metadata_bytes: int = 0):
        """Update memory statistics."""
        self.vector_memory_bytes += vector_bytes
        self.index_memory_bytes += index_bytes
        self.metadata_memory_bytes += metadata_bytes
        self.total_memory_bytes = (self.vector_memory_bytes +
                                   self.index_memory_bytes +
                                   self.metadata_memory_bytes)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_vectors": self.total_vectors,
            "total_dimensions": self.total_dimensions,
            "vector_memory_bytes": self.vector_memory_bytes,
            "index_memory_bytes": self.index_memory_bytes,
            "metadata_memory_bytes": self.metadata_memory_bytes,
            "total_memory_bytes": self.total_memory_bytes,
            "vector_memory_mb": round(self.vector_memory_bytes / (1024 * 1024), 2),
            "index_memory_mb": round(self.index_memory_bytes / (1024 * 1024), 2),
            "metadata_memory_mb": round(self.metadata_memory_bytes / (1024 * 1024), 2),
            "total_memory_mb": round(self.total_memory_bytes / (1024 * 1024), 2),
        }


@dataclass
class OperationStats:
    """Overall operation statistics."""
    total_operations: int = 0
    successful_operations: int = 0
    failed_operations: int = 0
    operations_per_second: float = 0.0
    timing: Dict[str, TimingStats] = field(default_factory=dict)

    def record_operation(self, operation: str, elapsed: float, success: bool = True):
        """Record an operation."""
        self.total_operations += 1
        if success:
            self.successful_operations += 1
        else:
            self.failed_operations += 1

        if operation not in self.timing:
            self.timing[operation] = TimingStats()
        self.timing[operation].update(elapsed)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_operations": self.total_operations,
            "successful_operations": self.successful_operations,
            "failed_operations": self.failed_operations,
            "operations_per_second": round(self.operations_per_second, 2),
            "timing": {k: v.to_dict() for k, v in self.timing.items()},
        }


class MetricsCollector:
    """Collects and manages performance metrics."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()
        self._operation_stats = OperationStats()
        self._memory_stats = MemoryStats()
        self._start_time = time.time()
        self._recent_operations: deque = deque(maxlen=1000)
        self._timers: Dict[str, float] = {}

    def start_timer(self, name: str):
        """Start a named timer."""
        if not self.enabled:
            return
        self._timers[name] = time.time()

    def stop_timer(self, name: str, success: bool = True) -> float:
        """Stop a named timer and record the elapsed time."""
        if not self.enabled or name not in self._timers:
            return 0.0

        elapsed = time.time() - self._timers.pop(name)
        with self._lock:
            self._operation_stats.record_operation(name, elapsed, success)
            self._recent_operations.append((name, elapsed, time.time()))
        return elapsed

    def record_operation(self, operation: str, elapsed: float, success: bool = True):
        """Record an operation directly."""
        if not self.enabled:
            return
        with self._lock:
            self._operation_stats.record_operation(operation, elapsed, success)
            self._recent_operations.append((operation, elapsed, time.time()))

    def update_memory(self, vector_bytes: int = 0, index_bytes: int = 0,
                       metadata_bytes: int = 0):
        """Update memory statistics."""
        if not self.enabled:
            return
        with self._lock:
            self._memory_stats.update(vector_bytes, index_bytes, metadata_bytes)

    def get_operation_stats(self) -> Dict[str, Any]:
        """Get operation statistics."""
        with self._lock:
            uptime = time.time() - self._start_time
            if uptime > 0:
                self._operation_stats.operations_per_second = (
                    self._operation_stats.total_operations / uptime
                )
            return self._operation_stats.to_dict()

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        with self._lock:
            return self._memory_stats.to_dict()

    def get_all_stats(self) -> Dict[str, Any]:
        """Get all statistics."""
        return {
            "uptime_seconds": time.time() - self._start_time,
            "operations": self.get_operation_stats(),
            "memory": self.get_memory_stats(),
            "recent_operations": [
                {"operation": op, "elapsed": round(el, 6), "timestamp": ts}
                for op, el, ts in list(self._recent_operations)[-10:]
            ],
        }

    def reset(self):
        """Reset all metrics."""
        with self._lock:
            self._operation_stats = OperationStats()
            self._memory_stats = MemoryStats()
            self._recent_operations.clear()
            self._timers.clear()
            self._start_time = time.time()

    def get_metrics_report(self) -> str:
        """Get a formatted metrics report."""
        stats = self.get_all_stats()
        lines = [
            "=" * 60,
            "Ainos Vector Database - Metrics Report",
            "=" * 60,
            f"Uptime: {stats['uptime_seconds']:.2f}s",
            f"Total Operations: {stats['operations']['total_operations']}",
            f"Successful: {stats['operations']['successful_operations']}",
            f"Failed: {stats['operations']['failed_operations']}",
            f"Ops/sec: {stats['operations']['operations_per_second']:.2f}",
            "",
            "Memory Usage:",
            f"  Total: {stats['memory']['total_memory_mb']:.2f} MB",
            f"  Vectors: {stats['memory']['vector_memory_mb']:.2f} MB",
            f"  Index: {stats['memory']['index_memory_mb']:.2f} MB",
            f"  Metadata: {stats['memory']['metadata_memory_mb']:.2f} MB",
            "",
            "Timing by Operation:",
        ]
        for op_name, timing in sorted(stats['operations']['timing'].items()):
            lines.append(f"  {op_name}:")
            lines.append(f"    Count: {timing['count']}")
            lines.append(f"    Mean: {timing['mean_time']*1000:.2f}ms")
            lines.append(f"    P95: {timing['p95_time']*1000:.2f}ms")
            lines.append(f"    P99: {timing['p99_time']*1000:.2f}ms")
            lines.append(f"    Max: {timing['max_time']*1000:.2f}ms")

        if stats['recent_operations']:
            lines.extend(["", "Recent Operations (last 10):"])
            for op in stats['recent_operations']:
                lines.append(f"  {op['operation']}: {op['elapsed']*1000:.2f}ms")

        return '\n'.join(lines)


def timed(metrics_collector: Optional[MetricsCollector] = None):
    """Decorator to time a function and record metrics."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            collector = metrics_collector
            if collector is None:
                # Try to find it in kwargs or instance
                if 'self' in func.__code__.co_varnames[:func.__code__.co_argcount]:
                    idx = func.__code__.co_varnames.index('self')
                    if idx < len(args):
                        instance = args[idx]
                        if hasattr(instance, 'metrics'):
                            collector = instance.metrics
                        elif hasattr(instance, '_metrics'):
                            collector = instance._metrics

            start = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                if collector:
                    collector.record_operation(func.__name__, elapsed, True)
                return result
            except Exception as e:
                elapsed = time.time() - start
                if collector:
                    collector.record_operation(func.__name__, elapsed, False)
                raise
        return wrapper
    return decorator


class ThroughputMeter:
    """Measures throughput over time windows."""

    def __init__(self, window_size: int = 60):
        self.window_size = window_size
        self._lock = threading.Lock()
        self._buckets: deque = deque(maxlen=window_size)

    def record(self, count: int = 1):
        """Record an event."""
        with self._lock:
            self._buckets.append((time.time(), count))

    def get_throughput(self, window_seconds: int = 60) -> float:
        """Get the throughput over the specified window."""
        with self._lock:
            now = time.time()
            cutoff = now - window_seconds
            total = sum(c for t, c in self._buckets if t >= cutoff)
            return total / window_seconds if window_seconds > 0 else 0.0

    def reset(self):
        """Reset the meter."""
        with self._lock:
            self._buckets.clear()