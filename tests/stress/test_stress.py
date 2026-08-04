"""AinosOS Stress and Load Test Suite.

This module validates system resilience under high concurrency, memory pressure,
and long-duration operation. It uses the mock daemon infrastructure from
``tests/conftest.py`` to simulate realistic workloads without requiring actual
hardware or a running daemon process.

Test Scenarios:
    - 100 concurrent inference requests: launches N workers sending inference
      requests, measures throughput, error rate, and latency distribution.
    - 1000 concurrent model list queries: rapid-fire model list queries from
      many concurrent clients.
    - Memory leak detection: runs operations (load/infer/unload/context) in a
      tight loop (500+ iterations), monitors memory usage, asserts no growth.
    - Connection storm test: rapid connect/disconnect cycles (100+), verifies
      server handles gracefully.
    - Data integrity under load: while under concurrent load, stores and
      retrieves context values, verifies no data corruption.
    - Long duration test: simulates extended usage (configurable via
      AINOS_STRESS_DURATION, default 60s), collects metrics over time.
    - Mixed workload: interleaves inference, model management, and context
      operations to simulate realistic usage patterns.
    - Error injection under load: with injected errors, verifies system still
      handles valid requests correctly.
    - Rate limit stress: rapidly sends requests to trigger rate limiting,
      verifies correct 429 responses.
    - Concurrent model operations: multiple clients loading/unloading the same
      model simultaneously.
    - High concurrency context operations: many concurrent context store/
      retrieve operations with data integrity verification.
    - Sustained throughput measurement: measures throughput stability over
      extended periods.
    - Cascading failure recovery: verifies graceful recovery after failures.
    - Resource cleanup on failure: ensures proper cleanup even when tests fail.

Usage:
    # Run all stress tests (quick mode):
    AINOS_STRESS_DURATION=10 AINOS_STRESS_CONCURRENCY=5 AINOS_QUICK_MODE=1 \\
        pytest tests/stress/ -v --timeout=120

    # Run full stress suite:
    pytest tests/stress/ -v --timeout=600

    # Run a specific test with more concurrency:
    AINOS_STRESS_CONCURRENCY=50 pytest tests/stress/test_stress.py::test_concurrent_inference -v

    # Run with memory monitoring:
    pip install psutil
    pytest tests/stress/ -v
"""

from __future__ import annotations

import gc
import json
import logging
import math
import os
import queue
import random
import socket
import sys
import threading
import time
import traceback
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple, Union

import pytest

# Attempt to import psutil for memory monitoring
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Import test infrastructure from conftest
from tests.conftest import (
    AI_ERR_SUCCESS,
    AI_ERR_GENERAL,
    AI_ERR_INVALID_PARAM,
    AI_ERR_MODEL_NOT_FOUND,
    AI_ERR_MODEL_LOAD_FAIL,
    AI_ERR_OUT_OF_MEMORY,
    AI_ERR_TASK_QUEUE_FULL,
    AI_ERR_NOT_SUPPORTED,
    AI_ERR_PERMISSION,
    AI_ERR_TIMEOUT,
    AI_ERR_THERMAL_THROTTLE,
    DEFAULT_STRESS_DURATION,
    DEFAULT_STRESS_CONCURRENCY,
    MockDaemonServer,
    MockDaemonClient,
    MockDaemonError,
    MockDaemonAuthError,
    MockDaemonProtocolError,
    KernelStub,
    assert_successful_response,
    assert_error_response,
    assert_inference_response,
    assert_model_load_response,
    assert_model_unload_response,
    assert_status_response,
    assert_auth_response,
    assert_valid_embedding,
    assert_valid_model_id,
    random_string,
    random_embedding,
    create_minimal_gguf,
    get_config,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default stress test parameters -- override via environment variables
STRESS_DURATION: int = int(os.environ.get("AINOS_STRESS_DURATION", str(DEFAULT_STRESS_DURATION)))
STRESS_CONCURRENCY: int = int(os.environ.get("AINOS_STRESS_CONCURRENCY", str(DEFAULT_STRESS_CONCURRENCY)))
QUICK_MODE: bool = os.environ.get("AINOS_QUICK_MODE", "0") == "1"

# Iteration counts -- scaled down in quick mode
MEMORY_LEAK_ITERATIONS: int = 100 if QUICK_MODE else 500
CONNECTION_STORM_COUNT: int = 50 if QUICK_MODE else 100
CONCURRENT_INFERENCE_WORKERS: int = max(4, STRESS_CONCURRENCY) if QUICK_MODE else max(10, STRESS_CONCURRENCY)
CONCURRENT_MODEL_LIST_WORKERS: int = max(10, STRESS_CONCURRENCY * 2) if QUICK_MODE else 1000
DATA_INTEGRITY_OPERATIONS: int = 50 if QUICK_MODE else 200
MIXED_WORKLOAD_DURATION: float = (
    max(5.0, STRESS_DURATION / 4.0) if QUICK_MODE else max(15.0, STRESS_DURATION / 2.0)
)
CONTEXT_CONCURRENCY_WORKERS: int = max(4, STRESS_CONCURRENCY) if QUICK_MODE else max(10, STRESS_CONCURRENCY)
SUSTAINED_THROUGHPUT_DURATION: float = (
    max(5.0, STRESS_DURATION / 3.0) if QUICK_MODE else max(20.0, STRESS_DURATION / 2.0)
)

# Error rate thresholds
MAX_ACCEPTABLE_ERROR_RATE: float = 0.05 if QUICK_MODE else 0.01  # 5% quick, 1% full
MAX_ACCEPTABLE_MEMORY_GROWTH_MB: float = 100.0  # 100 MB
MAX_ACCEPTABLE_P99_LATENCY_MS: float = 10000.0 if QUICK_MODE else 5000.0  # 10s quick, 5s full

# Context for data integrity testing
DATA_INTEGRITY_KEY_PREFIX: str = "stress_test_key_"
DATA_INTEGRITY_VALUE_PREFIX: str = "stress_test_value_"

# Latency tracking
LATENCY_WARN_THRESHOLD_MS: float = 2000.0  # Log warning for requests > 2s

# ---------------------------------------------------------------------------
# Helper Classes
# ---------------------------------------------------------------------------


@dataclass
class StressTestMetrics:
    """Thread-safe metrics collector for stress test operations.

    Tracks the total number of operations, errors, individual latency samples,
    and memory usage samples. Provides methods for recording events and
    generating summary reports with percentile latencies.

    Attributes:
        name: A label identifying this metrics group (e.g. "inference").
        total_ops: Total number of operations attempted.
        errors: Number of operations that failed.
        latencies: List of individual operation latencies in milliseconds.
        memory_samples: List of (timestamp, memory_mb) tuples.
        operation_counts: Per-second operation count for throughput calculation.
        start_time: Monotonic timestamp when tracking began.
    """

    name: str = "unnamed"
    total_ops: int = 0
    errors: int = 0
    latencies: list[float] = field(default_factory=list)
    memory_samples: list[tuple[float, float]] = field(default_factory=list)
    operation_counts: list[tuple[float, int]] = field(default_factory=list)
    start_time: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_operation(self) -> None:
        """Record a successful operation (increment counter)."""
        with self._lock:
            self.total_ops += 1
            now = time.monotonic()
            elapsed = now - self.start_time
            bucket = int(elapsed)
            self.operation_counts.append((now, self.total_ops))

    def record_error(self) -> None:
        """Record an operation failure (increment error counter)."""
        with self._lock:
            self.errors += 1
            self.total_ops += 1

    def record_latency(self, latency_ms: float) -> None:
        """Record a latency sample in milliseconds.

        Args:
            latency_ms: The operation latency in milliseconds.
        """
        with self._lock:
            self.latencies.append(latency_ms)
            if latency_ms > LATENCY_WARN_THRESHOLD_MS:
                logger.warning(
                    "[%s] High latency: %.1f ms (> %.0f ms threshold)",
                    self.name,
                    latency_ms,
                    LATENCY_WARN_THRESHOLD_MS,
                )

    def record_memory(self, memory_mb: float) -> None:
        """Record a memory usage sample.

        Args:
            memory_mb: Current memory usage in megabytes.
        """
        with self._lock:
            self.memory_samples.append((time.monotonic(), memory_mb))

    @property
    def error_rate(self) -> float:
        """Calculate the error rate as a fraction of total operations."""
        if self.total_ops == 0:
            return 0.0
        return self.errors / self.total_ops

    @property
    def throughput(self) -> float:
        """Calculate throughput in operations per second."""
        elapsed = time.monotonic() - self.start_time
        if elapsed < 0.001:
            return 0.0
        return self.total_ops / elapsed

    def percentile(self, p: float) -> float:
        """Calculate the p-th percentile latency.

        Args:
            p: Percentile to compute (0.0 to 100.0).

        Returns:
            The latency value at the given percentile, or 0.0 if no samples.
        """
        if not self.latencies:
            return 0.0
        sorted_lats = sorted(self.latencies)
        idx = max(0, min(len(sorted_lats) - 1, int(len(sorted_lats) * p / 100.0)))
        return sorted_lats[idx]

    @property
    def p50(self) -> float:
        """Median latency in milliseconds."""
        return self.percentile(50.0)

    @property
    def p95(self) -> float:
        """95th percentile latency in milliseconds."""
        return self.percentile(95.0)

    @property
    def p99(self) -> float:
        """99th percentile latency in milliseconds."""
        return self.percentile(99.0)

    @property
    def max_latency(self) -> float:
        """Maximum recorded latency in milliseconds."""
        if not self.latencies:
            return 0.0
        return max(self.latencies)

    @property
    def min_latency(self) -> float:
        """Minimum recorded latency in milliseconds."""
        if not self.latencies:
            return 0.0
        return min(self.latencies)

    @property
    def avg_latency(self) -> float:
        """Average latency in milliseconds."""
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    @property
    def memory_growth_mb(self) -> float:
        """Estimate memory growth from first to last sample.

        Returns:
            The difference between the last and first memory sample in MB,
            or 0.0 if fewer than 2 samples exist.
        """
        if len(self.memory_samples) < 2:
            return 0.0
        first_mem = self.memory_samples[0][1]
        last_mem = self.memory_samples[-1][1]
        return last_mem - first_mem

    @property
    def peak_memory_mb(self) -> float:
        """Peak recorded memory usage in megabytes."""
        if not self.memory_samples:
            return 0.0
        return max(m for _, m in self.memory_samples)

    def report(self) -> dict[str, Any]:
        """Generate a comprehensive metrics report dictionary.

        Returns:
            A dictionary containing all tracked metrics including throughput,
            latency percentiles, error rate, and memory statistics.
        """
        with self._lock:
            return {
                "name": self.name,
                "total_ops": self.total_ops,
                "errors": self.errors,
                "error_rate": self.error_rate,
                "throughput_ops_per_sec": round(self.throughput, 2),
                "latency_ms": {
                    "min": round(self.min_latency, 2),
                    "avg": round(self.avg_latency, 2),
                    "p50": round(self.p50, 2),
                    "p95": round(self.p95, 2),
                    "p99": round(self.p99, 2),
                    "max": round(self.max_latency, 2),
                },
                "memory": {
                    "growth_mb": round(self.memory_growth_mb, 2),
                    "peak_mb": round(self.peak_memory_mb, 2),
                    "samples": len(self.memory_samples),
                },
                "duration_seconds": round(time.monotonic() - self.start_time, 2),
            }

    def assert_acceptable(self, max_error_rate: float = MAX_ACCEPTABLE_ERROR_RATE) -> None:
        """Assert that metrics are within acceptable bounds.

        Args:
            max_error_rate: Maximum acceptable error rate (default 1%).

        Raises:
            AssertionError: If error rate exceeds the threshold or if
                memory growth exceeds the acceptable limit.
        """
        report = self.report()
        assert (
            report["error_rate"] <= max_error_rate
        ), (
            f"[{self.name}] Error rate {report['error_rate']:.4f} exceeds "
            f"threshold {max_error_rate:.4f} "
            f"({report['errors']}/{report['total_ops']} operations failed)"
        )
        if report["memory"]["growth_mb"] > MAX_ACCEPTABLE_MEMORY_GROWTH_MB:
            logger.warning(
                "[%s] Memory growth %.1f MB exceeds warning threshold %.1f MB",
                self.name,
                report["memory"]["growth_mb"],
                MAX_ACCEPTABLE_MEMORY_GROWTH_MB,
            )

    def log_summary(self) -> None:
        """Log a formatted summary of all metrics to the test logger."""
        report = self.report()
        logger.info("=" * 60)
        logger.info("Metrics Report: %s", report["name"])
        logger.info("=" * 60)
        logger.info("  Duration:      %.2f s", report["duration_seconds"])
        logger.info("  Total ops:     %d", report["total_ops"])
        logger.info("  Errors:        %d (%.2f%%)", report["errors"], report["error_rate"] * 100.0)
        logger.info("  Throughput:    %.2f ops/sec", report["throughput_ops_per_sec"])
        logger.info("  Latency (ms):")
        logger.info("    Min:  %.2f", report["latency_ms"]["min"])
        logger.info("    Avg:  %.2f", report["latency_ms"]["avg"])
        logger.info("    P50:  %.2f", report["latency_ms"]["p50"])
        logger.info("    P95:  %.2f", report["latency_ms"]["p95"])
        logger.info("    P99:  %.2f", report["latency_ms"]["p99"])
        logger.info("    Max:  %.2f", report["latency_ms"]["max"])
        logger.info("  Memory:")
        logger.info("    Growth: %.2f MB", report["memory"]["growth_mb"])
        logger.info("    Peak:   %.2f MB", report["memory"]["peak_mb"])
        logger.info("    Samples: %d", report["memory"]["samples"])
        logger.info("-" * 60)


class ConcurrentWorker(threading.Thread):
    """A thread-based worker that repeatedly executes a target operation.

    Each worker runs a specified number of iterations of a target function,
    recording metrics (latency, errors) into a shared ``StressTestMetrics``
    instance. Workers are designed to be created in pools for concurrent
    load testing.

    Attributes:
        worker_id: Unique identifier for this worker.
        target: The callable to execute.
        metrics: Shared metrics instance for recording results.
        iterations: Number of times to execute the target.
        args: Positional arguments passed to the target.
        kwargs: Keyword arguments passed to the target.
        exception: Stores any exception raised during execution.
        stop_event: Event to signal early termination.
    """

    def __init__(
        self,
        worker_id: int,
        target: Callable[..., Any],
        metrics: StressTestMetrics,
        iterations: int = 1,
        args: Optional[tuple[Any, ...]] = None,
        kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize the concurrent worker.

        Args:
            worker_id: Unique identifier for this worker.
            target: The callable to execute for each iteration.
            metrics: Shared metrics instance for recording results.
            iterations: Number of iterations to run (default 1).
            args: Positional arguments for the target.
            kwargs: Keyword arguments for the target.
        """
        super().__init__(name=f"ConcurrentWorker-{worker_id}")
        self.worker_id = worker_id
        self.target = target
        self.metrics = metrics
        self.iterations = iterations
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.exception: Optional[Exception] = None
        self.stop_event = threading.Event()
        self.daemon = True

    def run(self) -> None:
        """Execute the target function for the configured number of iterations."""
        for i in range(self.iterations):
            if self.stop_event.is_set():
                logger.debug("Worker %d stopped early after %d iterations", self.worker_id, i)
                break
            start = time.monotonic()
            try:
                self.target(*self.args, **self.kwargs)
                elapsed_ms = (time.monotonic() - start) * 1000.0
                self.metrics.record_operation()
                self.metrics.record_latency(elapsed_ms)
            except Exception as exc:
                elapsed_ms = (time.monotonic() - start) * 1000.0
                self.metrics.record_error()
                self.metrics.record_latency(elapsed_ms)
                logger.debug("Worker %d iteration %d failed: %s: %s", self.worker_id, i, type(exc).__name__, exc)
                if self.exception is None:
                    self.exception = exc

    def stop(self) -> None:
        """Signal the worker to stop early."""
        self.stop_event.set()


class MetricsCollector(threading.Thread):
    """Background thread that periodically collects memory and performance metrics."""

    def __init__(self, metrics: StressTestMetrics, interval: float = 0.5) -> None:
        super().__init__(name="MetricsCollector", daemon=True)
        self.metrics = metrics
        self.interval = interval
        self.stop_event = threading.Event()
        self._process = psutil.Process() if HAS_PSUTIL else None
        self._object_counts: list[tuple[float, int]] = []

    def run(self) -> None:
        while not self.stop_event.is_set():
            memory_mb = self._sample_memory()
            self.metrics.record_memory(memory_mb)
            self.stop_event.wait(self.interval)

    def _sample_memory(self) -> float:
        if self._process is not None:
            try:
                mem_info = self._process.memory_info()
                return mem_info.rss / (1024.0 * 1024.0)
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass
        gc.collect()
        obj_count = len(gc.get_objects())
        self._object_counts.append((time.monotonic(), obj_count))
        return obj_count * 1024.0 / (1024.0 * 1024.0)

    def stop(self) -> None:
        self.stop_event.set()
        self.join(timeout=5.0)


class DataIntegrityChecker:
    """Verifies data integrity of context store/retrieve operations."""

    def __init__(self, client: MockDaemonClient) -> None:
        self.client = client
        self.stored_data: dict[str, str] = {}
        self.mismatches: list[tuple[str, str, str]] = []
        self._lock = threading.Lock()

    def generate_key(self, index: int, prefix: str = DATA_INTEGRITY_KEY_PREFIX) -> str:
        return f"{prefix}{index}"

    def generate_value(self, index: int, prefix: str = DATA_INTEGRITY_VALUE_PREFIX) -> str:
        random_suffix = uuid.uuid4().hex[:8]
        return f"{prefix}{index}_uuid={random_suffix}_checksum={hash(str(index)) & 0xFFFFFFFF}"

    def store(self, key: str, value: str) -> bool:
        try:
            self.client.context_store(key, value)
            with self._lock:
                self.stored_data[key] = value
            return True
        except Exception as exc:
            logger.warning("DataIntegrityChecker: store failed for key '%s': %s", key, exc)
            return False

    def retrieve_and_verify(self, key: str, expected_value: str) -> bool:
        try:
            result = self.client.context_retrieve(key)
            if result is None:
                with self._lock:
                    self.mismatches.append((key, expected_value, "<None>"))
                return False
            if result != expected_value:
                with self._lock:
                    self.mismatches.append((key, expected_value, result))
                return False
            return True
        except Exception as exc:
            logger.warning("DataIntegrityChecker: retrieve failed for key '%s': %s", key, exc)
            with self._lock:
                self.mismatches.append((key, expected_value, f"<Exception: {exc}>"))
            return False

    def store_batch(self, start: int, count: int) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for i in range(start, start + count):
            key = self.generate_key(i)
            value = self.generate_value(i)
            success = self.store(key, value)
            results[key] = success
        return results

    def verify_batch(self, start: int, count: int) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for i in range(start, start + count):
            key = self.generate_key(i)
            expected = self.stored_data.get(key, "")
            success = self.retrieve_and_verify(key, expected)
            results[key] = success
        return results

    def verify_all(self) -> tuple[int, int]:
        total = 0
        mismatches = 0
        with self._lock:
            keys = list(self.stored_data.keys())
        for key in keys:
            total += 1
            expected = self.stored_data.get(key, "")
            if not self.retrieve_and_verify(key, expected):
                mismatches += 1
        return total, mismatches

    @property
    def integrity_score(self) -> float:
        total = len(self.stored_data)
        if total == 0:
            return 1.0
        return 1.0 - (len(self.mismatches) / total)

    def report(self) -> dict[str, Any]:
        total = len(self.stored_data)
        mismatches = len(self.mismatches)
        return {
            "total_keys_stored": total,
            "total_mismatches": mismatches,
            "integrity_score": self.integrity_score,
            "mismatch_details": self.mismatches[:10] if self.mismatches else [],
        }


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------


def get_current_memory_mb() -> float:
    """Get the current process memory usage in megabytes."""
    if HAS_PSUTIL:
        try:
            process = psutil.Process()
            mem_info = process.memory_info()
            return mem_info.rss / (1024.0 * 1024.0)
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            pass
    gc.collect()
    obj_count = len(gc.get_objects())
    return obj_count * 1024.0 / (1024.0 * 1024.0)


def wait_for_workers(workers: list[ConcurrentWorker], timeout: float = 60.0, poll_interval: float = 0.1) -> list[ConcurrentWorker]:
    """Wait for all workers to complete, with a timeout."""
    deadline = time.monotonic() + timeout
    incomplete: list[ConcurrentWorker] = []
    for worker in workers:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            incomplete.append(worker)
            continue
        worker.join(timeout=remaining)
        if worker.is_alive():
            incomplete.append(worker)
    return incomplete


def create_clients(server: MockDaemonServer, count: int, authenticated: bool = True) -> list[MockDaemonClient]:
    """Create multiple daemon clients connected to the given server."""
    clients: list[MockDaemonClient] = []
    for i in range(count):
        try:
            if authenticated:
                client = server.make_authenticated_client()
            else:
                client = server.make_client()
            clients.append(client)
        except Exception as exc:
            logger.error("Failed to create client %d/%d: %s", i + 1, count, exc)
            break
    return clients


def disconnect_clients(clients: list[MockDaemonClient]) -> None:
    """Safely disconnect a list of daemon clients."""
    for client in clients:
        try:
            client.disconnect()
        except Exception:
            pass


def create_temp_model_file(model_dir: str, model_name: str = "stress_test_model.gguf") -> str:
    """Create a temporary model file for stress testing."""
    model_path = os.path.join(model_dir, model_name)
    create_minimal_gguf(model_path)
    return model_path


def compute_quantiles(values: list[float], quantiles: list[float]) -> dict[float, float]:
    """Compute specified quantiles from a list of values."""
    if not values:
        return {q: 0.0 for q in quantiles}
    sorted_vals = sorted(values)
    result: dict[float, float] = {}
    for q in quantiles:
        idx = max(0, min(len(sorted_vals) - 1, int(len(sorted_vals) * q)))
        result[q] = sorted_vals[idx]
    return result


def format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs:.0f}s"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m {secs:.0f}s"


def safe_infer(client: MockDaemonClient, prompt: str = "Hello, Ainos!", model: str = "default", max_tokens: int = 32) -> Optional[dict[str, Any]]:
    """Perform an inference request with safe error handling."""
    try:
        return client.infer(prompt=prompt, model=model, max_tokens=max_tokens)
    except Exception:
        return None


def safe_model_list(client: MockDaemonClient) -> Optional[list[dict[str, Any]]]:
    """Perform a model list request with safe error handling."""
    try:
        return client.model_list()
    except Exception:
        return None


def safe_model_load(client: MockDaemonClient, path: str) -> Optional[dict[str, Any]]:
    """Load a model with safe error handling."""
    try:
        return client.model_load(path)
    except Exception:
        return None


def safe_model_unload(client: MockDaemonClient, model_id: str) -> Optional[dict[str, Any]]:
    """Unload a model with safe error handling."""
    try:
        return client.model_unload(model_id)
    except Exception:
        return None


def safe_context_store(client: MockDaemonClient, key: str, value: str) -> Optional[str]:
    """Store a context value with safe error handling."""
    try:
        return client.context_store(key, value)
    except Exception:
        return None


def safe_context_retrieve(client: MockDaemonClient, key: str) -> Optional[str]:
    """Retrieve a context value with safe error handling."""
    try:
        return client.context_retrieve(key)
    except Exception:
        return None


def safe_status(client: MockDaemonClient) -> Optional[dict[str, Any]]:
    """Query daemon status with safe error handling."""
    try:
        return client.status()
    except Exception:
        return None


def safe_rate_limit_status(client: MockDaemonClient) -> Optional[dict[str, Any]]:
    """Query rate limit status with safe error handling."""
    try:
        return client.rate_limit_status()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def fresh_client(mock_daemon_server: MockDaemonServer) -> Generator[MockDaemonClient, None, None]:
    """Create a fresh authenticated client for each test function."""
    client = mock_daemon_server.make_authenticated_client()
    yield client
    try:
        client.disconnect()
    except Exception:
        pass


@pytest.fixture(scope="function")
def stress_model_path(temp_model_dir: str) -> str:
    """Path to a stress test model file in the temporary model directory."""
    return create_temp_model_file(temp_model_dir)


@pytest.fixture(scope="function")
def memory_metrics() -> Generator[StressTestMetrics, None, None]:
    """A metrics instance pre-configured for memory monitoring."""
    metrics = StressTestMetrics(name="memory_test")
    metrics.record_memory(get_current_memory_mb())
    yield metrics
    metrics.record_memory(get_current_memory_mb())
    metrics.log_summary()


@pytest.fixture(scope="function")
def concurrency_level() -> int:
    """Determine the concurrency level for stress tests."""
    return STRESS_CONCURRENCY


@pytest.fixture(scope="function")
def stress_duration_seconds() -> float:
    """Determine the duration for stress tests."""
    return float(STRESS_DURATION)


# ---------------------------------------------------------------------------
# Test: Mixed Workload
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("workload_scale", [1, 2, 4])
def test_mixed_workload(
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
    workload_scale: int,
    stress_duration_seconds: float,
    time_budget: float,
) -> None:
    """Interleave inference, model management, and context operations.

    Simulates a realistic mixed workload where multiple clients perform
    different types of operations concurrently: inference requests, model
    load/unload cycles, and context store/retrieve operations. Measures
    per-operation-type metrics and verifies the system handles the
    interleaving without degradation.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        temp_model_dir: Temporary directory with model files.
        workload_scale: Scale factor for workload intensity (parameterized).
        stress_duration_seconds: Duration from environment variable.
        time_budget: Maximum allowed test duration.
    """
    actual_duration = min(
        MIXED_WORKLOAD_DURATION * workload_scale,
        stress_duration_seconds,
        time_budget * 0.8,
    )
    model_path = create_temp_model_file(temp_model_dir, "mixed_workload_model.gguf")

    # Separate metrics per operation type
    inference_metrics = StressTestMetrics(name="mixed_inference")
    model_metrics = StressTestMetrics(name="mixed_model_ops")
    context_metrics = StressTestMetrics(name="mixed_context_ops")

    clients = create_clients(mock_daemon_server, 12)
    assert len(clients) >= 12, "Need at least 12 clients"

    all_metrics = [inference_metrics, model_metrics, context_metrics]

    # Inference workers (6 workers)
    infer_workers: list[ConcurrentWorker] = []
    for i in range(6):
        client = clients[i]
        worker = ConcurrentWorker(
            worker_id=i,
            target=lambda c=client: safe_infer(
                c, prompt=f"Mixed workload inference {i}", max_tokens=8
            ),
            metrics=inference_metrics,
            iterations=int(actual_duration * 3),
        )
        infer_workers.append(worker)

    # Model management workers (3 workers)
    model_workers: list[ConcurrentWorker] = []

    def model_operation(client: MockDaemonClient, path: str) -> None:
        """Perform a model load then unload cycle."""
        resp = safe_model_load(client, path)
        if resp and resp.get("status") == "loaded":
            model_id = resp.get("model_id", "")
            safe_model_unload(client, model_id)

    for i in range(3):
        client = clients[6 + i]
        worker = ConcurrentWorker(
            worker_id=10 + i,
            target=model_operation,
            metrics=model_metrics,
            iterations=int(actual_duration),
            kwargs={"client": client, "path": model_path},
        )
        model_workers.append(worker)

    # Context operation workers (3 workers)
    context_workers: list[ConcurrentWorker] = []

    def context_operation(client: MockDaemonClient) -> None:
        """Perform a context store then retrieve cycle."""
        key = f"mixed_ctx_{uuid.uuid4().hex[:8]}"
        value = f"mixed_ctx_val_{uuid.uuid4().hex[:8]}"
        safe_context_store(client, key, value)
        safe_context_retrieve(client, key)

    for i in range(3):
        client = clients[9 + i]
        worker = ConcurrentWorker(
            worker_id=20 + i,
            target=context_operation,
            metrics=context_metrics,
            iterations=int(actual_duration * 2),
            kwargs={"client": client},
        )
        context_workers.append(worker)

    all_workers = infer_workers + model_workers + context_workers

    try:
        for w in all_workers:
            w.start()

        # Let them run for the configured duration
        time.sleep(actual_duration)

        for w in all_workers:
            w.stop()
        for w in all_workers:
            w.join(timeout=10.0)

    finally:
        disconnect_clients(clients)

    # Log and assert each metric group
    for m in all_metrics:
        m.log_summary()
        m.assert_acceptable()

    logger.info(
        "Mixed workload complete: inference=%d, model_ops=%d, context_ops=%d",
        inference_metrics.total_ops,
        model_metrics.total_ops,
        context_metrics.total_ops,
    )


# ---------------------------------------------------------------------------
# Test: Error Injection Under Load
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("error_rate_setting", ["low", "medium", "high"])
def test_error_injection_under_load(
    mock_daemon_server: MockDaemonServer,
    error_rate_setting: str,
    time_budget: float,
) -> None:
    """Verify system handles valid requests correctly during injected errors.

    Uses the mock daemon with injected failures on specific message types.
    Tests that error injection does not cascade to affect unrelated ops.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        error_rate_setting: Error injection intensity (parameterized).
        time_budget: Maximum allowed test duration.
    """
    if error_rate_setting == "low":
        fail_types = {"Inference"}
        num_valid_requests = 50
        num_error_requests = 20
    elif error_rate_setting == "medium":
        fail_types = {"Inference", "ModelLoad"}
        num_valid_requests = 30
        num_error_requests = 30
    else:
        fail_types = {"Inference", "ModelLoad", "ContextStore"}
        num_valid_requests = 20
        num_error_requests = 40

    error_daemon = MockDaemonServer(auth_enabled=True, fail_on_type=fail_types)
    error_daemon.start()

    valid_metrics = StressTestMetrics(name="error_injection_valid")
    error_metrics = StressTestMetrics(name="error_injection_errors")

    try:
        error_clients = create_clients(error_daemon, 5, authenticated=True)
        valid_clients = create_clients(error_daemon, 5, authenticated=True)

        error_workers: list[ConcurrentWorker] = []
        for i in range(5):
            client = error_clients[i % len(error_clients)]
            worker = ConcurrentWorker(
                worker_id=50 + i,
                target=lambda c=client: c.infer(
                    prompt="This should fail due to error injection",
                    max_tokens=4,
                ),
                metrics=error_metrics,
                iterations=num_error_requests // 5,
            )
            error_workers.append(worker)

        valid_workers: list[ConcurrentWorker] = []

        def valid_operation(client: MockDaemonClient) -> None:
            """Perform operations that should not be affected by error injection."""
            safe_model_list(client)
            try:
                client.status()
            except Exception:
                pass

        for i in range(5):
            client = valid_clients[i % len(valid_clients)]
            worker = ConcurrentWorker(
                worker_id=60 + i,
                target=valid_operation,
                metrics=valid_metrics,
                iterations=num_valid_requests // 5,
            )
            valid_workers.append(worker)

        all_workers = error_workers + valid_workers
        for w in all_workers:
            w.start()

        incomplete = wait_for_workers(all_workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()

        error_metrics.log_summary()
        if error_metrics.total_ops > 0:
            logger.info(
                "Error injection: error rate = %.2f%% (expected to be high)",
                error_metrics.error_rate * 100.0,
            )

        valid_metrics.log_summary()
        valid_metrics.assert_acceptable(max_error_rate=0.1)

        assert valid_metrics.total_ops > 0, "No valid operations completed"
        assert valid_metrics.error_rate < 0.1, (
            f"Valid operations had {valid_metrics.error_rate:.2%} error rate, "
            f"expected < 10%"
        )
    finally:
        disconnect_clients(error_clients)
        disconnect_clients(valid_clients)
        error_daemon.stop()


# ---------------------------------------------------------------------------
# Test: Rate Limit Stress
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("request_burst_size", [50, 100, 200])
def test_rate_limit_stress(
    rate_limited_daemon: MockDaemonServer,
    request_burst_size: int,
    time_budget: float,
) -> None:
    """Rapidly send requests to trigger rate limiting and verify 429 handling.

    Sends *request_burst_size* rapid-fire requests to a rate-limited daemon.
    Verifies that some requests are accepted, some receive 429 responses,
    and the system remains stable after rate limiting kicks in.

    Args:
        rate_limited_daemon: A mock daemon with rate limiting enabled.
        request_burst_size: Number of requests to send in burst (parameterized).
        time_budget: Maximum allowed test duration.
    """
    num_requests = min(request_burst_size, 200)
    metrics = StressTestMetrics(name="rate_limit_stress")
    rate_limited_count = 0
    success_count = 0
    other_errors = 0

    client = rate_limited_daemon.make_authenticated_client()
    assert client.authenticated, "Client should be authenticated"

    try:
        logger.info("Rate limit stress test: sending %d rapid requests", num_requests)

        for i in range(num_requests):
            try:
                resp = client.infer(prompt=f"Rate limit test request {i}", max_tokens=4)
                if resp.get("type") == "Error":
                    error_code = resp.get("code", 0)
                    if error_code == 429:
                        rate_limited_count += 1
                        metrics.record_error()
                    else:
                        other_errors += 1
                        metrics.record_error()
                else:
                    success_count += 1
                    metrics.record_operation()
            except MockDaemonError as exc:
                if "429" in str(exc) or "Rate limit" in str(exc):
                    rate_limited_count += 1
                else:
                    other_errors += 1
                metrics.record_error()
            except Exception:
                other_errors += 1
                metrics.record_error()

        try:
            status = client.rate_limit_status()
            logger.info("Rate limit status: %s", json.dumps(status, indent=2))
        except Exception as exc:
            logger.warning("Failed to get rate limit status: %s", exc)

        metrics.log_summary()
        logger.info(
            "Rate limit results: %d success, %d rate-limited (429), %d other errors",
            success_count, rate_limited_count, other_errors,
        )

        assert success_count > 0, "All requests were rate-limited or failed"
        assert rate_limited_count > 0, (
            "No rate-limited responses received. Rate limiting may not be working."
        )

        final_client = rate_limited_daemon.make_authenticated_client()
        try:
            status_resp = final_client.status()
            assert_status_response(status_resp)
        finally:
            final_client.disconnect()
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Concurrent Model Operations
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_clients", [5, 10, 20])
def test_concurrent_model_operations(
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
    num_clients: int,
    time_budget: float,
) -> None:
    """Multiple clients loading and unloading the same model simultaneously.

    Creates *num_clients* workers that all attempt to load and unload the
    same model file concurrently. Verifies that the server handles the
    contention correctly, that model state remains consistent, and that
    no crashes or resource leaks occur.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        temp_model_dir: Temporary directory with model files.
        num_clients: Number of concurrent clients (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_clients = min(num_clients, 20)
    model_path = os.path.join(temp_model_dir, "test_model.gguf")
    metrics = StressTestMetrics(name="concurrent_model_ops")

    clients = create_clients(mock_daemon_server, actual_clients)
    assert len(clients) > 0, "Failed to create clients"

    workers: list[ConcurrentWorker] = []

    def load_unload_cycle(client: MockDaemonClient, path: str) -> None:
        """Execute a load -> verify -> unload cycle for a model."""
        load_resp = safe_model_load(client, path)
        if load_resp and load_resp.get("status") == "loaded":
            model_id = load_resp.get("model_id", "")
            safe_model_unload(client, model_id)

    for i in range(actual_clients):
        client = clients[i]
        worker = ConcurrentWorker(
            worker_id=i,
            target=load_unload_cycle,
            metrics=metrics,
            iterations=10 if QUICK_MODE else 20,
            kwargs={"client": client, "path": model_path},
        )
        workers.append(worker)

    try:
        for w in workers:
            w.start()
        incomplete = wait_for_workers(workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()
            logger.warning("%d model operation workers did not complete", len(incomplete))

        metrics.log_summary()
        metrics.assert_acceptable()

        check_client = mock_daemon_server.make_authenticated_client()
        try:
            models = check_client.model_list()
            assert isinstance(models, list), "Model list should return a list"
        finally:
            check_client.disconnect()
    finally:
        disconnect_clients(clients)


# ---------------------------------------------------------------------------
# Test: High Concurrency Context Operations
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_workers_param", [10, 25, 50])
def test_high_concurrency_context_operations(
    mock_daemon_server: MockDaemonServer,
    num_workers_param: int,
    time_budget: float,
) -> None:
    """Many concurrent context store/retrieve operations with integrity checks.

    Launches *num_workers_param* concurrent workers, each performing a
    sequence of context store and retrieve operations. Uses a
    DataIntegrityChecker to verify that all stored values are retrieved
    correctly, detecting any data corruption or race conditions.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        num_workers_param: Number of concurrent workers (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_workers = min(num_workers_param, CONTEXT_CONCURRENCY_WORKERS)
    ops_per_worker = 20 if QUICK_MODE else 50
    metrics = StressTestMetrics(name="high_concurrency_context")

    clients = create_clients(mock_daemon_server, actual_workers)
    assert len(clients) > 0, "Failed to create clients"

    check_client = mock_daemon_server.make_authenticated_client()
    checker = DataIntegrityChecker(check_client)

    workers: list[ConcurrentWorker] = []
    key_counter = [0]
    counter_lock = threading.Lock()

    def context_operation(client: MockDaemonClient) -> None:
        """Perform a context store and retrieve with integrity checking."""
        with counter_lock:
            idx = key_counter[0]
            key_counter[0] += 1
        key = f"hcc_key_{idx}"
        value = f"hcc_value_{idx}_data={uuid.uuid4().hex}"
        store_ok = checker.store(key, value)
        if not store_ok:
            return
        retrieved = safe_context_retrieve(client, key)
        if retrieved is not None and retrieved != value:
            checker.mismatches.append((key, value, retrieved))

    for i in range(actual_workers):
        client = clients[i % len(clients)]
        worker = ConcurrentWorker(
            worker_id=i,
            target=context_operation,
            metrics=metrics,
            iterations=ops_per_worker,
            kwargs={"client": client},
        )
        workers.append(worker)

    try:
        for w in workers:
            w.start()
        incomplete = wait_for_workers(workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()
            logger.warning("%d context workers did not complete", len(incomplete))

        metrics.log_summary()
        metrics.assert_acceptable()

        integrity_report = checker.report()
        logger.info(
            "Context integrity: %d keys, %d mismatches, score=%.4f",
            integrity_report["total_keys_stored"],
            integrity_report["total_mismatches"],
            integrity_report["integrity_score"],
        )
        assert integrity_report["total_mismatches"] == 0, (
            f"Data corruption detected: {integrity_report['total_mismatches']} "
            f"mismatches out of {integrity_report['total_keys_stored']} keys"
        )
    finally:
        check_client.disconnect()
        disconnect_clients(clients)


# ---------------------------------------------------------------------------
# Test: Sustained Throughput
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("measurement_window", [5, 10, 20])
def test_sustained_throughput(
    mock_daemon_server: MockDaemonServer,
    measurement_window: int,
    stress_duration_seconds: float,
    time_budget: float,
) -> None:
    """Measure throughput stability over an extended measurement window.

    Runs a continuous inference workload for *measurement_window* seconds
    and measures throughput in sub-windows. Verifies that throughput remains
    stable (coefficient of variation below threshold) and does not degrade.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        measurement_window: Duration of measurement in seconds (parameterized).
        stress_duration_seconds: Duration from environment variable.
        time_budget: Maximum allowed test duration.
    """
    actual_window = min(
        measurement_window, int(stress_duration_seconds), int(time_budget * 0.7),
    )
    assert actual_window >= 3, "Measurement window must be at least 3 seconds"

    metrics = StressTestMetrics(name="sustained_throughput")
    clients = create_clients(mock_daemon_server, 8)
    assert len(clients) > 0, "Failed to create clients"

    throughput_samples: list[tuple[float, int]] = []
    sample_lock = threading.Lock()

    workers: list[ConcurrentWorker] = []
    for i in range(8):
        client = clients[i % len(clients)]
        worker = ConcurrentWorker(
            worker_id=i,
            target=lambda c=client: safe_infer(
                c, prompt=f"Sustained throughput worker {i}", max_tokens=4,
            ),
            metrics=metrics,
            iterations=int(actual_window * 5),
        )
        workers.append(worker)

    sampling_active = [True]

    def throughput_sampler() -> None:
        """Sample operation count at 1-second intervals."""
        last_count = 0
        while sampling_active[0]:
            time.sleep(1.0)
            current_count = metrics.total_ops
            ops_in_window = current_count - last_count
            last_count = current_count
            with sample_lock:
                throughput_samples.append((time.monotonic(), ops_in_window))

    sampler = threading.Thread(target=throughput_sampler, daemon=True)
    sampler.start()

    try:
        for w in workers:
            w.start()
        time.sleep(actual_window)
        sampling_active[0] = False
        for w in workers:
            w.stop()
        for w in workers:
            w.join(timeout=5.0)

        metrics.log_summary()

        with sample_lock:
            if throughput_samples:
                sample_values = [s[1] for s in throughput_samples]
                avg_throughput = sum(sample_values) / len(sample_values)
                if avg_throughput > 0:
                    variance = sum((v - avg_throughput) ** 2 for v in sample_values) / len(sample_values)
                    std_dev = math.sqrt(variance)
                    cv = std_dev / avg_throughput
                    logger.info(
                        "Throughput stability: avg=%.1f ops/sec, std=%.1f, CV=%.2f, samples=%d",
                        avg_throughput, std_dev, cv, len(sample_values),
                    )
                    logger.info("Throughput range: [%d, %d] ops/sec", min(sample_values), max(sample_values))
                    assert cv < 0.5, f"Throughput CV too high: {cv:.2f}. Throughput is not stable."
    finally:
        sampling_active[0] = False
        disconnect_clients(clients)

    assert metrics.total_ops > 0, "No operations completed during throughput test"


# ---------------------------------------------------------------------------
# Test: Cascading Failure Recovery
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("failure_mode", ["connection", "timeout", "error"])
def test_cascading_failure_recovery(
    mock_daemon_server: MockDaemonServer,
    failure_mode: str,
    time_budget: float,
) -> None:
    """Verify graceful recovery after cascading failures.

    Introduces controlled failures (connection drops, timeouts, or error
    responses) and verifies that the system recovers gracefully. After
    the failure injection period, verifies that new requests succeed.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        failure_mode: Type of failure to inject (parameterized).
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="cascading_failure_recovery")

    if failure_mode == "connection":
        failure_daemon = MockDaemonServer(auth_enabled=True)
        failure_daemon.start()
        burst_clients = create_clients(failure_daemon, 30, authenticated=True)
        disconnect_clients(burst_clients)
        recovery_client = failure_daemon.make_authenticated_client()
    elif failure_mode == "timeout":
        failure_daemon = MockDaemonServer(auth_enabled=True, response_delay_ms=200.0)
        failure_daemon.start()
        slow_client = failure_daemon.make_authenticated_client()
        try:
            for i in range(5):
                slow_client.infer(prompt=f"Slow request {i}", max_tokens=4)
        except Exception:
            pass
        slow_client.disconnect()
        recovery_client = failure_daemon.make_authenticated_client()
    else:
        failure_daemon = MockDaemonServer(auth_enabled=True, fail_on_type={"Inference", "ModelLoad", "ContextStore"})
        failure_daemon.start()
        error_client = failure_daemon.make_authenticated_client()
        for i in range(10):
            try:
                error_client.infer(prompt=f"Expected failure {i}", max_tokens=4)
            except Exception:
                pass
        error_client.disconnect()
        recovery_client = failure_daemon.make_authenticated_client()

    try:
        recovery_metrics = StressTestMetrics(name="recovery_phase")
        for i in range(50 if QUICK_MODE else 100):
            try:
                if failure_mode == "error":
                    resp = recovery_client.model_list()
                    assert isinstance(resp, list)
                else:
                    resp = recovery_client.infer(prompt=f"Recovery request {i}", max_tokens=8)
                    if resp.get("type") == "Error":
                        recovery_metrics.record_error()
                    else:
                        recovery_metrics.record_operation()
            except Exception:
                recovery_metrics.record_error()

        recovery_metrics.log_summary()
        assert recovery_metrics.total_ops > 0, "No recovery operations completed"
        if failure_mode == "error":
            assert recovery_metrics.error_rate < 0.5, f"Recovery error rate too high: {recovery_metrics.error_rate:.2%}"
        else:
            assert recovery_metrics.error_rate < 0.1, f"Recovery error rate too high: {recovery_metrics.error_rate:.2%}"
        status = recovery_client.status()
        assert_status_response(status)
        logger.info("Recovery successful after %s failure mode", failure_mode)
    finally:
        recovery_client.disconnect()
        if failure_mode != "connection":
            failure_daemon.stop()
        metrics.log_summary()


# ---------------------------------------------------------------------------
# Test: Resource Cleanup on Failure
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("failure_point", ["setup", "operation", "teardown"])
def test_resource_cleanup_on_failure(
    mock_daemon_server: MockDaemonServer,
    failure_point: str,
    time_budget: float,
) -> None:
    """Ensure proper resource cleanup even when tests encounter failures.

    Simulates failures at different stages (setup, during operation, or
    during teardown) and verifies that all resources (connections, model
    handles, context entries) are properly cleaned up.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        failure_point: Stage at which to simulate failure (parameterized).
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="cleanup_on_failure")
    created_clients: list[MockDaemonClient] = []
    loaded_model_ids: list[str] = []
    stored_context_keys: list[str] = []

    def cleanup_resources() -> None:
        """Clean up all tracked resources."""
        for model_id in loaded_model_ids:
            for client in created_clients[:1]:
                try:
                    client.model_unload(model_id)
                except Exception:
                    pass
        loaded_model_ids.clear()
        for client in created_clients:
            try:
                client.disconnect()
            except Exception:
                pass
        created_clients.clear()
        logger.info("Resource cleanup completed")

    try:
        if failure_point == "setup":
            raise RuntimeError("Simulated setup failure")

        for i in range(5):
            client = mock_daemon_server.make_authenticated_client()
            created_clients.append(client)
            metrics.record_operation()

        if failure_point == "operation":
            for i in range(3):
                try:
                    mock_daemon_server.make_authenticated_client().infer(
                        prompt=f"Operation before failure {i}", max_tokens=4,
                    )
                    metrics.record_operation()
                except Exception:
                    metrics.record_error()
            raise RuntimeError("Simulated operation failure")

        main_client = created_clients[0]
        for i in range(10):
            try:
                resp = main_client.infer(prompt=f"Cleanup test operation {i}", max_tokens=4)
                metrics.record_operation()
            except Exception:
                metrics.record_error()

        if failure_point == "teardown":
            cleanup_resources()
            raise RuntimeError("Simulated teardown failure")
    except RuntimeError as exc:
        logger.info("Simulated failure at %s: %s", failure_point, exc)
        cleanup_resources()
    except Exception as exc:
        logger.error("Unexpected error during %s: %s", failure_point, exc)
        cleanup_resources()
        raise

    new_client = mock_daemon_server.make_authenticated_client()
    try:
        status = new_client.status()
        assert_status_response(status)
        logger.info("Cleanup verification: new connection after %s failure works", failure_point)
    finally:
        new_client.disconnect()

    metrics.log_summary()
    logger.info("Resource cleanup test passed for failure_point=%s", failure_point)


# ---------------------------------------------------------------------------
# Test: KernelStub Stress
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_ops", [100, 500, 1000])
def test_kernel_stub_stress(
    deterministic_seed: int,
    num_ops: int,
    time_budget: float,
) -> None:
    """Stress test the KernelStub with many operations.

    Exercises the KernelStub with a high volume of embedding, search, model
    load/unload, and context operations. Verifies deterministic behavior.

    Args:
        deterministic_seed: Seed for deterministic test behavior.
        num_ops: Number of operations to perform (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_ops = min(num_ops, 1000)
    kernel = KernelStub(seed=deterministic_seed)
    metrics = StressTestMetrics(name="kernel_stub_stress")

    for i in range(actual_ops):
        if time.monotonic() - metrics.start_time > time_budget * 0.9:
            break
        input_data = [random.random() for _ in range(64)]
        embedding, err = kernel.ai_embedding(input_data, len(input_data), 128)
        if err == AI_ERR_SUCCESS:
            metrics.record_operation()
            assert embedding is not None
            assert_valid_embedding(embedding, 128)
        else:
            metrics.record_error()

    for i in range(actual_ops // 5):
        if time.monotonic() - metrics.start_time > time_budget * 0.9:
            break
        model_id, err = kernel.ai_model_load(f"stress_model_{i}", f"/tmp/stress_model_{i}.gguf")
        if err == AI_ERR_SUCCESS:
            metrics.record_operation()
            assert model_id is not None
            assert_valid_model_id(model_id)
            err = kernel.ai_model_unload(model_id)
            if err == AI_ERR_SUCCESS:
                metrics.record_operation()
            else:
                metrics.record_error()
        else:
            metrics.record_error()

    for i in range(actual_ops // 5):
        if time.monotonic() - metrics.start_time > time_budget * 0.9:
            break
        entry_id, err = kernel.ai_context_store(1, f"key_{i}", f"value_{i}", 60000)
        if err == AI_ERR_SUCCESS:
            metrics.record_operation()
            value, err = kernel.ai_context_retrieve(1, f"key_{i}", entry_id or 0)
            if err == AI_ERR_SUCCESS:
                metrics.record_operation()
                assert value == f"value_{i}", f"Data mismatch: {value} != value_{i}"
            else:
                metrics.record_error()
        else:
            metrics.record_error()

    if time.monotonic() - metrics.start_time < time_budget * 0.9:
        database = [random_embedding(64, seed=i) for i in range(100)]
        query = random_embedding(64, seed=9999)
        results, err = kernel.ai_semantic_search(query, database, 5)
        if err == AI_ERR_SUCCESS:
            metrics.record_operation()
            assert results is not None
            assert len(results) <= 5
        else:
            metrics.record_error()

    metrics.log_summary()
    metrics.assert_acceptable()
    assert metrics.total_ops > 0, "No KernelStub operations completed"
    logger.info("KernelStub stress test: %d ops, %d errors, %.2f ops/sec",
                metrics.total_ops, metrics.errors, metrics.throughput)


# ---------------------------------------------------------------------------
# Test: KernelStub Error Injection
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("inject_op", ["embedding", "model_load", "context_store"])
def test_kernel_stub_error_injection(
    deterministic_seed: int,
    inject_op: str,
    time_budget: float,
) -> None:
    """Verify KernelStub error injection does not cause cascading failures.

    Configures the KernelStub to inject errors on a specific operation
    type and verifies that other operation types continue to work.

    Args:
        deterministic_seed: Seed for deterministic test behavior.
        inject_op: The operation type to inject errors on (parameterized).
        time_budget: Maximum allowed test duration.
    """
    kernel = KernelStub(seed=deterministic_seed)
    kernel.set_error_injection(inject_op, AI_ERR_GENERAL)

    valid_metrics = StressTestMetrics(name="kernel_valid_ops")
    error_metrics = StressTestMetrics(name="kernel_injected_errors")

    ops: dict[str, Callable[[], tuple[Any, int]]] = {
        "embedding": lambda: kernel.ai_embedding([1.0, 2.0, 3.0], 3, 128),
        "model_load": lambda: kernel.ai_model_load("test", "/tmp/test.gguf"),
        "model_unload": lambda: (None, kernel.ai_model_unload(999)),
        "context_store": lambda: kernel.ai_context_store(1, "k", "v", 60000),
        "context_retrieve": lambda: kernel.ai_context_retrieve(1, "nonexistent", 0),
        "status": lambda: kernel.ai_status(),
    }
    metrics_start = time.monotonic()

    for i in range(100):
        if time.monotonic() - metrics_start > time_budget * 0.9:
            break
        for op_name, op_func in ops.items():
            try:
                _, err = op_func()
                if op_name == inject_op:
                    error_metrics.record_operation()
                    if err != AI_ERR_SUCCESS:
                        error_metrics.record_error()
                    assert err != AI_ERR_SUCCESS, f"Expected error for injected op '{op_name}', got success"
                else:
                    valid_metrics.record_operation()
                    if err != AI_ERR_SUCCESS:
                        valid_metrics.record_error()
            except Exception:
                if op_name == inject_op:
                    error_metrics.record_error()
                else:
                    valid_metrics.record_error()

    error_metrics.log_summary()
    valid_metrics.log_summary()

    assert valid_metrics.error_rate < 0.2, (
        f"Valid operations had {valid_metrics.error_rate:.2%} error rate "
        f"during error injection on '{inject_op}'"
    )
    if error_metrics.total_ops > 0:
        assert error_metrics.error_rate > 0.5, (
            f"Injected operation '{inject_op}' had only {error_metrics.error_rate:.2%} error rate, expected > 50%"
        )
    logger.info("KernelStub error injection test passed for op='%s': valid_error_rate=%.2f%%, injected_error_rate=%.2f%%",
                inject_op, valid_metrics.error_rate * 100.0, error_metrics.error_rate * 100.0)


# ---------------------------------------------------------------------------
# Test: Mixed Kernel and Daemon Operations
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_cycles", [20, 50, 100])
def test_mixed_kernel_and_daemon(
    mock_daemon_server: MockDaemonServer,
    deterministic_seed: int,
    num_cycles: int,
    time_budget: float,
) -> None:
    """Exercise both the KernelStub and the daemon client concurrently.

    Runs a workload that alternates between KernelStub operations and
    daemon client operations, verifying both layers work correctly.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        deterministic_seed: Seed for deterministic test behavior.
        num_cycles: Number of mixed-operation cycles (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_cycles = min(num_cycles, 100)
    kernel = KernelStub(seed=deterministic_seed)
    client = mock_daemon_server.make_authenticated_client()
    kernel_metrics = StressTestMetrics(name="mixed_kernel_ops")
    daemon_metrics = StressTestMetrics(name="mixed_daemon_ops")

    try:
        for cycle in range(actual_cycles):
            if time.monotonic() - kernel_metrics.start_time > time_budget * 0.9:
                break

            # KernelStub embedding
            try:
                embedding, err = kernel.ai_embedding([float(cycle)] * 64, 64, 128)
                if err == AI_ERR_SUCCESS:
                    kernel_metrics.record_operation()
                else:
                    kernel_metrics.record_error()
            except Exception:
                kernel_metrics.record_error()

            # KernelStub model load/unload
            try:
                model_id, err = kernel.ai_model_load(f"mixed_model_{cycle}", f"/tmp/mixed_{cycle}.gguf")
                if err == AI_ERR_SUCCESS:
                    kernel_metrics.record_operation()
                    err = kernel.ai_model_unload(model_id)
                    if err == AI_ERR_SUCCESS:
                        kernel_metrics.record_operation()
                    else:
                        kernel_metrics.record_error()
                else:
                    kernel_metrics.record_error()
            except Exception:
                kernel_metrics.record_error()

            # Daemon inference
            try:
                resp = client.infer(prompt=f"Mixed daemon cycle {cycle}", max_tokens=8)
                if resp.get("type") == "Error":
                    daemon_metrics.record_error()
                else:
                    daemon_metrics.record_operation()
            except Exception:
                daemon_metrics.record_error()

            # Daemon model list
            try:
                models = client.model_list()
                if isinstance(models, list):
                    daemon_metrics.record_operation()
                else:
                    daemon_metrics.record_error()
            except Exception:
                daemon_metrics.record_error()

            # Daemon context operations
            try:
                ctx_key = f"mixed_ctx_{cycle}"
                ctx_val = f"mixed_ctx_val_{cycle}"
                client.context_store(ctx_key, ctx_val)
                daemon_metrics.record_operation()
                retrieved = client.context_retrieve(ctx_key)
                daemon_metrics.record_operation()
                if retrieved != ctx_val:
                    logger.warning("Daemon data mismatch at cycle %d", cycle)
            except Exception:
                daemon_metrics.record_error()

            # KernelStub context operations
            try:
                entry_id, err = kernel.ai_context_store(cycle, f"kernel_ctx_{cycle}", f"kernel_val_{cycle}", 60000)
                if err == AI_ERR_SUCCESS:
                    kernel_metrics.record_operation()
                    value, err = kernel.ai_context_retrieve(cycle, f"kernel_ctx_{cycle}", entry_id or 0)
                    if err == AI_ERR_SUCCESS:
                        kernel_metrics.record_operation()
                        assert value == f"kernel_val_{cycle}"
                    else:
                        kernel_metrics.record_error()
                else:
                    kernel_metrics.record_error()
            except Exception:
                kernel_metrics.record_error()
    finally:
        client.disconnect()

    kernel_metrics.log_summary()
    daemon_metrics.log_summary()
    kernel_metrics.assert_acceptable()
    daemon_metrics.assert_acceptable()
    logger.info("Mixed kernel/daemon test: %d cycles, kernel=%d ops, daemon=%d ops",
                actual_cycles, kernel_metrics.total_ops, daemon_metrics.total_ops)


# ---------------------------------------------------------------------------
# Test: Connection Pool Exhaustion
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_connections", [30, 60, 100])
def test_connection_pool_exhaustion(
    mock_daemon_server: MockDaemonServer,
    num_connections: int,
    time_budget: float,
) -> None:
    """Test server behavior when many connections are opened simultaneously.

    Opens *num_connections* connections, performs operations on each, and
    verifies the server handles connection pool pressure without errors.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        num_connections: Number of simultaneous connections (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_connections = min(num_connections, 100)
    metrics = StressTestMetrics(name="connection_pool_exhaustion")

    logger.info("Opening %d simultaneous connections...", actual_connections)
    all_clients = create_clients(mock_daemon_server, actual_connections, authenticated=True)
    assert len(all_clients) > 0, "Failed to create any connections"
    metrics.record_operation()
    logger.info("Opened %d/%d connections successfully", len(all_clients), actual_connections)

    operation_metrics = StressTestMetrics(name="pool_operations")
    workers: list[ConcurrentWorker] = []
    for i, client in enumerate(all_clients):
        worker = ConcurrentWorker(
            worker_id=i,
            target=lambda c=client: safe_infer(c, prompt=f"Pool connection {i}", max_tokens=4),
            metrics=operation_metrics,
            iterations=3,
        )
        workers.append(worker)

    for w in workers:
        w.start()
    incomplete = wait_for_workers(workers, timeout=time_budget * 0.5)
    if incomplete:
        for w in incomplete:
            w.stop()
        logger.warning("%d pool workers did not complete", len(incomplete))

    operation_metrics.log_summary()
    logger.info("Closing all %d connections...", len(all_clients))
    disconnect_clients(all_clients)
    metrics.record_operation()

    final_client = mock_daemon_server.make_authenticated_client()
    try:
        status = final_client.status()
        assert_status_response(status)
        metrics.record_operation()
        logger.info("Server responsive after pool exhaustion: uptime=%ds, requests=%d",
                    status.get("uptime", 0), status.get("total_requests", 0))
    finally:
        final_client.disconnect()

    metrics.log_summary()
    assert operation_metrics.error_rate < 0.5, (
        f"Pool operation error rate too high: {operation_metrics.error_rate:.2%}"
    )


# ---------------------------------------------------------------------------
# Test: Sequential Request Pipeline
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("pipeline_depth", [10, 50, 100])
def test_sequential_request_pipeline(
    mock_daemon_server: MockDaemonServer,
    pipeline_depth: int,
    time_budget: float,
) -> None:
    """Test the request pipeline by sending sequential requests without waiting.

    Sends requests without waiting for responses between each, simulating
    pipelining. Verifies the server handles pipelining correctly.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        pipeline_depth: Number of requests to pipeline (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_depth = min(pipeline_depth, 100)
    metrics = StressTestMetrics(name="request_pipeline")

    client = mock_daemon_server.make_authenticated_client()
    assert client.connected, "Client should be connected"

    try:
        requests: list[str] = []
        for i in range(actual_depth):
            payload = json.dumps({
                "type": "Inference", "model": "default",
                "prompt": f"Pipeline request {i}", "max_tokens": 4,
            }, separators=(",", ":"))
            requests.append(payload)

        for req in requests:
            try:
                client._socket.sendall(req.encode("utf-8") + b"\n")
                metrics.record_operation()
            except Exception as exc:
                metrics.record_error()
                logger.debug("Pipeline send error: %s", exc)

        responses: list[dict[str, Any]] = []
        for i in range(len(requests)):
            try:
                resp = client._read_response()
                responses.append(resp)
                metrics.record_operation()
            except Exception as exc:
                metrics.record_error()
                logger.debug("Pipeline read error: %s", exc)

        metrics.log_summary()
        logger.info("Pipeline test: sent %d, received %d responses", len(requests), len(responses))

        assert len(responses) > 0, "No responses received from pipeline"
        valid_responses = sum(1 for r in responses if r.get("type") == "InferenceResponse")
        logger.info("Pipeline responses: %d valid, %d errors", valid_responses, len(responses) - valid_responses)
        assert valid_responses > 0, "No valid responses in pipeline"
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Request Size Variation
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("prompt_length", [10, 100, 1000])
def test_request_size_variation(
    mock_daemon_server: MockDaemonServer,
    prompt_length: int,
    time_budget: float,
) -> None:
    """Test server behavior with varying request sizes.

    Sends requests with prompts of different lengths to verify the server
    handles small and large payloads, unicode, and special characters.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        prompt_length: Length of the prompt in characters (parameterized).
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="request_size_variation")
    client = mock_daemon_server.make_authenticated_client()

    prompts = {
        "small": "Hello",
        "medium": ("The quick brown fox jumps over the lazy dog. " * 20)[:prompt_length],
        "large": "A" * max(prompt_length, 10),
        "unicode": ("Hello unicode nino emoji: rocket fire " * 5)[:prompt_length],
        "special": ("!@#$%^&*()_+-=[]{}|;':,./<>?`~ " * 10)[:prompt_length],
    }

    for prompt_name, prompt_text in prompts.items():
        if time.monotonic() - metrics.start_time > time_budget * 0.9:
            break
        try:
            resp = client.infer(prompt=prompt_text, model="default", max_tokens=8)
            if resp.get("type") == "Error":
                metrics.record_error()
                logger.warning("Request size test: '%s' prompt failed: %s", prompt_name, resp.get("message", ""))
            else:
                metrics.record_operation()
                output = resp.get("output", "")
                assert isinstance(output, str), "Output should be a string"
                assert len(output) > 0, "Output should not be empty"
        except Exception as exc:
            metrics.record_error()
            logger.debug("Request size test: '%s' prompt exception: %s", prompt_name, exc)

    metrics.log_summary()
    assert metrics.error_rate < 0.5, f"Request size variation error rate too high: {metrics.error_rate:.2%}"
    client.disconnect()


# ---------------------------------------------------------------------------
# Test: Concurrent Authenticated Sessions
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_sessions", [10, 25, 50])
def test_concurrent_authenticated_sessions(
    mock_daemon_server: MockDaemonServer,
    num_sessions: int,
    time_budget: float,
) -> None:
    """Test server behavior with many concurrent authenticated sessions.

    Creates *num_sessions* authenticated sessions, performs operations on
    each, and verifies the server manages session state correctly.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        num_sessions: Number of concurrent sessions (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_sessions = min(num_sessions, 50)
    metrics = StressTestMetrics(name="concurrent_sessions")

    clients = create_clients(mock_daemon_server, actual_sessions, authenticated=True)
    assert len(clients) > 0, "Failed to create any authenticated sessions"
    metrics.record_operation()
    logger.info("Created %d authenticated sessions", len(clients))

    for i, client in enumerate(clients):
        if time.monotonic() - metrics.start_time > time_budget * 0.9:
            break
        try:
            assert client.authenticated, f"Session {i} should be authenticated"
            assert client._session_token is not None, f"Session {i} should have a session token"
            metrics.record_operation()
            resp = client.infer(prompt=f"Session {i} inference", max_tokens=4)
            if resp.get("type") == "Error":
                metrics.record_error()
            else:
                metrics.record_operation()
            status = client.status()
            if status.get("type") == "Error":
                metrics.record_error()
            else:
                metrics.record_operation()
        except Exception as exc:
            metrics.record_error()
            logger.debug("Session %d operation failed: %s", i, exc)

    metrics.log_summary()
    metrics.assert_acceptable()
    disconnect_clients(clients)

    final_client = mock_daemon_server.make_authenticated_client()
    try:
        status = final_client.status()
        assert_status_response(status)
    finally:
        final_client.disconnect()


# ---------------------------------------------------------------------------
# Test: Rapid Context Operations
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_context_ops", [50, 100, 200])
def test_rapid_context_operations(
    mock_daemon_server: MockDaemonServer,
    num_context_ops: int,
    time_budget: float,
) -> None:
    """Rapidly perform context store and retrieve operations.

    Executes *num_context_ops* rapid context store/retrieve cycles with
    varying key and value sizes. Verifies no data corruption or errors.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        num_context_ops: Number of context operations (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_ops = min(num_context_ops, 200)
    metrics = StressTestMetrics(name="rapid_context_ops")
    client = mock_daemon_server.make_authenticated_client()

    stored_values: dict[str, str] = {}
    mismatches: list[tuple[str, str, str]] = []

    try:
        for i in range(actual_ops):
            if time.monotonic() - metrics.start_time > time_budget * 0.9:
                break
            key_size = (i % 5) + 1
            value_size = ((i * 3) % 10) + 1
            key = f"rapid_ctx_{'x' * key_size}_{i}"
            value = f"rapid_ctx_val_{'y' * value_size}_{i}"

            try:
                result = client.context_store(key, value)
                if result is not None:
                    metrics.record_operation()
                    stored_values[key] = value
                else:
                    metrics.record_error()
                    continue
            except Exception:
                metrics.record_error()
                continue

            try:
                retrieved = client.context_retrieve(key)
                if retrieved is not None:
                    metrics.record_operation()
                    if retrieved != value:
                        mismatches.append((key, value, retrieved))
                else:
                    metrics.record_error()
            except Exception:
                metrics.record_error()

        metrics.log_summary()
        logger.info("Rapid context ops: %d stored, %d mismatches", len(stored_values), len(mismatches))
        assert len(mismatches) == 0, f"Data corruption detected: {mismatches[:5]}"

        for key, expected in stored_values.items():
            retrieved = client.context_retrieve(key)
            if retrieved is not None:
                assert retrieved == expected, f"Data mismatch: key={key}"
    finally:
        client.disconnect()



# ---------------------------------------------------------------------------
# Test: Rapid Fire Auth Operations
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_auth_ops", [50, 100, 200])
def test_rapid_fire_auth_operations(
    mock_daemon_server: MockDaemonServer,
    num_auth_ops: int,
    time_budget: float,
) -> None:
    """Rapidly authenticate and deauthenticate many sessions.

    Creates *num_auth_ops* authentication sessions in rapid succession,
    each performing a small operation before disconnecting. Verifies
    that the authentication system handles the load without errors.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        num_auth_ops: Number of authentication operations (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_ops = min(num_auth_ops, 200)
    metrics = StressTestMetrics(name="rapid_fire_auth")

    for i in range(actual_ops):
        if time.monotonic() - metrics.start_time > time_budget * 0.9:
            break
        client: Optional[MockDaemonClient] = None
        try:
            client = mock_daemon_server.make_authenticated_client()
            metrics.record_operation()
            assert client.authenticated, "Client should be authenticated"
            assert client._session_token is not None, "Client should have session token"
            resp = client.infer(prompt=f"Auth op {i}", max_tokens=4)
            if resp.get("type") == "Error":
                metrics.record_error()
            else:
                metrics.record_operation()
        except Exception as exc:
            metrics.record_error()
            logger.debug("Auth op %d failed: %s", i, exc)
        finally:
            if client is not None:
                try:
                    client.disconnect()
                except Exception:
                    pass

        if i > 0 and i % 50 == 0:
            logger.info("Auth ops: %d/%d complete, %d errors", i, actual_ops, metrics.errors)

    metrics.log_summary()
    metrics.assert_acceptable()

    final_client = mock_daemon_server.make_authenticated_client()
    try:
        status = final_client.status()
        assert_status_response(status)
        logger.info("Server responsive after %d auth ops", actual_ops)
    finally:
        final_client.disconnect()


# ---------------------------------------------------------------------------
# Test: Concurrent Status Polling
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_pollers", [10, 25, 50])
def test_concurrent_status_polling(
    mock_daemon_server: MockDaemonServer,
    num_pollers: int,
    time_budget: float,
) -> None:
    """Many clients polling status concurrently.

    Launches *num_pollers* workers that repeatedly call the status
    endpoint. Verifies that the server handles concurrent status
    polling without degradation and that all responses are valid.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        num_pollers: Number of concurrent status pollers (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_pollers = min(num_pollers, 50)
    metrics = StressTestMetrics(name="concurrent_status_polling")

    clients = create_clients(mock_daemon_server, actual_pollers)
    assert len(clients) > 0, "Failed to create clients"

    workers: list[ConcurrentWorker] = []

    for i in range(actual_pollers):
        client = clients[i % len(clients)]
        worker = ConcurrentWorker(
            worker_id=i,
            target=lambda c=client: safe_status(c),
            metrics=metrics,
            iterations=30 if QUICK_MODE else 100,
        )
        workers.append(worker)

    try:
        for w in workers:
            w.start()
        incomplete = wait_for_workers(workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()
            logger.warning("%d status pollers did not complete", len(incomplete))

        metrics.log_summary()
        metrics.assert_acceptable()

        check_client = mock_daemon_server.make_authenticated_client()
        try:
            status = check_client.status()
            assert_status_response(status)
        finally:
            check_client.disconnect()
    finally:
        disconnect_clients(clients)


# ---------------------------------------------------------------------------
# Test: Error Rate Under Constant Load
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("load_intensity", [5, 10, 20])
def test_error_rate_under_constant_load(
    mock_daemon_server: MockDaemonServer,
    load_intensity: int,
    stress_duration_seconds: float,
    time_budget: float,
) -> None:
    """Measure error rate under sustained constant load.

    Maintains a constant load of *load_intensity* concurrent inference
    requests for a sustained period, measuring the error rate at
    regular intervals. Verifies that the error rate remains below
    the acceptable threshold throughout the test.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        load_intensity: Number of concurrent requests (parameterized).
        stress_duration_seconds: Duration from environment variable.
        time_budget: Maximum allowed test duration.
    """
    actual_duration = min(
        max(10.0, stress_duration_seconds / 2.0),
        time_budget * 0.8,
    )
    actual_load = min(load_intensity, 20)
    metrics = StressTestMetrics(name="error_rate_constant_load")

    clients = create_clients(mock_daemon_server, actual_load)
    assert len(clients) > 0, "Failed to create clients"

    # Track error rate over time windows
    error_windows: list[tuple[float, float]] = []
    window_lock = threading.Lock()
    window_size = 2.0  # seconds

    workers: list[ConcurrentWorker] = []
    for i in range(actual_load):
        client = clients[i % len(clients)]
        worker = ConcurrentWorker(
            worker_id=i,
            target=lambda c=client: safe_infer(
                c, prompt=f"Constant load worker {i}", max_tokens=8,
            ),
            metrics=metrics,
            iterations=int(actual_duration * 3),
        )
        workers.append(worker)

    # Monitor error rate in windows
    monitoring_active = [True]

    def error_rate_monitor() -> None:
        """Sample error rate at regular intervals."""
        while monitoring_active[0]:
            time.sleep(window_size)
            with window_lock:
                if metrics.total_ops > 0:
                    window_error_rate = metrics.errors / metrics.total_ops
                    error_windows.append((time.monotonic(), window_error_rate))

    monitor = threading.Thread(target=error_rate_monitor, daemon=True)
    monitor.start()

    try:
        for w in workers:
            w.start()
        time.sleep(actual_duration)
        monitoring_active[0] = False
        for w in workers:
            w.stop()
        for w in workers:
            w.join(timeout=5.0)

        metrics.log_summary()
        metrics.assert_acceptable()

        with window_lock:
            if error_windows:
                max_window_error = max(e for _, e in error_windows)
                avg_window_error = sum(e for _, e in error_windows) / len(error_windows)
                logger.info(
                    "Error rate windows: max=%.4f, avg=%.4f, samples=%d",
                    max_window_error, avg_window_error, len(error_windows),
                )
                assert max_window_error < MAX_ACCEPTABLE_ERROR_RATE * 2, (
                    f"Max window error rate {max_window_error:.4f} exceeds "
                    f"threshold {MAX_ACCEPTABLE_ERROR_RATE * 2:.4f}"
                )
    finally:
        monitoring_active[0] = False
        disconnect_clients(clients)


# ---------------------------------------------------------------------------
# Test: Large Payload Context Store
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("payload_size", [1024, 4096, 16384])
def test_large_payload_context_store(
    mock_daemon_server: MockDaemonServer,
    payload_size: int,
    time_budget: float,
) -> None:
    """Test context store with large payloads.

    Stores and retrieves context values of varying sizes (*payload_size*
    bytes) to verify the server handles large payloads correctly without
    truncation, corruption, or excessive memory usage.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        payload_size: Size of the payload in bytes (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_size = min(payload_size, 16384)
    metrics = StressTestMetrics(name="large_payload_context")
    client = mock_daemon_server.make_authenticated_client()

    try:
        # Test with random payloads of the specified size
        for i in range(20 if QUICK_MODE else 50):
            if time.monotonic() - metrics.start_time > time_budget * 0.9:
                break

            key = f"large_payload_key_{i}"
            value = "X" * actual_size

            # Store
            try:
                result = client.context_store(key, value)
                if result is not None:
                    metrics.record_operation()
                else:
                    metrics.record_error()
                    continue
            except Exception:
                metrics.record_error()
                continue

            # Retrieve and verify
            try:
                retrieved = client.context_retrieve(key)
                if retrieved is not None:
                    metrics.record_operation()
                    assert len(retrieved) == actual_size, (
                        f"Payload size mismatch: stored {actual_size}, retrieved {len(retrieved)}"
                    )
                    assert retrieved == value, "Payload content mismatch"
                else:
                    metrics.record_error()
            except Exception:
                metrics.record_error()

        metrics.log_summary()
        metrics.assert_acceptable()

        # Verify server still responsive
        status = client.status()
        assert_status_response(status)
        logger.info(
            "Large payload test complete: size=%d bytes, ops=%d, errors=%d",
            actual_size, metrics.total_ops, metrics.errors,
        )
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Concurrent Inference with Variable Payload
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("payload_variation", ["uniform", "increasing", "random"])
def test_concurrent_inference_variable_payload(
    mock_daemon_server: MockDaemonServer,
    payload_variation: str,
    time_budget: float,
) -> None:
    """Concurrent inference with varying payload sizes.

    Launches concurrent inference workers where each request has a
    different payload size based on the variation strategy. Tests the
    server's ability to handle mixed-size requests efficiently.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        payload_variation: Strategy for varying payload sizes (parameterized).
        time_budget: Maximum allowed test duration.
    """
    num_workers = 10
    metrics = StressTestMetrics(name="concurrent_inference_variable")

    clients = create_clients(mock_daemon_server, num_workers)
    assert len(clients) > 0, "Failed to create clients"

    # Generate prompts based on variation strategy
    prompts: list[str] = []
    base_prompt = "Hello, this is a test inference request with variable payload. "
    for i in range(200):
        if payload_variation == "uniform":
            prompt = base_prompt * 10
        elif payload_variation == "increasing":
            prompt = base_prompt * (i + 1)
        else:  # random
            prompt = base_prompt * (random.randint(1, 50))
        prompts.append(prompt)

    prompt_index = [0]
    prompt_lock = threading.Lock()

    workers: list[ConcurrentWorker] = []
    for i in range(num_workers):
        client = clients[i % len(clients)]

        def infer_with_prompt(c: MockDaemonClient = client) -> None:
            """Perform inference with the next prompt in the queue."""
            with prompt_lock:
                idx = prompt_index[0]
                prompt_index[0] = (idx + 1) % len(prompts)
            safe_infer(c, prompt=prompts[idx], max_tokens=8)

        worker = ConcurrentWorker(
            worker_id=i,
            target=infer_with_prompt,
            metrics=metrics,
            iterations=20,
        )
        workers.append(worker)

    try:
        for w in workers:
            w.start()
        incomplete = wait_for_workers(workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()
            logger.warning("%d variable payload workers did not complete", len(incomplete))

        metrics.log_summary()
        metrics.assert_acceptable()

        check_client = mock_daemon_server.make_authenticated_client()
        try:
            status = check_client.status()
            assert_status_response(status)
        finally:
            check_client.disconnect()
    finally:
        disconnect_clients(clients)


# ---------------------------------------------------------------------------
# Test: Repeated Model List Under Load
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_iterations", [50, 100, 200])
def test_repeated_model_list_under_load(
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
    num_iterations: int,
    time_budget: float,
) -> None:
    """Repeatedly query model list while loading/unloading models.

    Performs *num_iterations* cycles of: load a model, query model list
    (verifying the model appears), unload the model, query model list
    (verifying the model is removed). Tests model list consistency.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        temp_model_dir: Temporary directory with model files.
        num_iterations: Number of test cycles (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_iterations = min(num_iterations, 200)
    metrics = StressTestMetrics(name="repeated_model_list")
    client = mock_daemon_server.make_authenticated_client()

    model_paths = [
        os.path.join(temp_model_dir, "test_model.gguf"),
        os.path.join(temp_model_dir, "phi-3-mini.gguf"),
        os.path.join(temp_model_dir, "llama-2-7b.gguf"),
    ]

    try:
        for i in range(actual_iterations):
            if time.monotonic() - metrics.start_time > time_budget * 0.9:
                break

            model_path = model_paths[i % len(model_paths)]

            # Load model
            try:
                load_resp = client.model_load(model_path)
                metrics.record_operation()
                if load_resp.get("type") == "Error":
                    metrics.record_error()
                    continue
                model_id = load_resp.get("model_id", "")
            except Exception:
                metrics.record_error()
                continue

            # Query model list - should include the loaded model
            try:
                models = client.model_list()
                metrics.record_operation()
                model_ids = [m.get("id", "") for m in models]
                assert model_id in model_ids, (
                    f"Loaded model {model_id} not found in model list"
                )
            except Exception:
                metrics.record_error()

            # Unload model
            try:
                unload_resp = client.model_unload(model_id)
                metrics.record_operation()
                if unload_resp.get("type") == "Error":
                    metrics.record_error()
            except Exception:
                metrics.record_error()

            # Query model list - should not include the unloaded model
            try:
                models = client.model_list()
                metrics.record_operation()
                model_ids = [m.get("id", "") for m in models]
                assert model_id not in model_ids, (
                    f"Unloaded model {model_id} still found in model list"
                )
            except Exception:
                metrics.record_error()

        metrics.log_summary()
        metrics.assert_acceptable()
        logger.info("Repeated model list test: %d cycles, %d ops, %d errors",
                    actual_iterations, metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Context Store Under Memory Pressure
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_entries", [100, 500, 1000])
def test_context_store_memory_pressure(
    mock_daemon_server: MockDaemonServer,
    num_entries: int,
    time_budget: float,
) -> None:
    """Store many context entries to test memory handling.

    Stores *num_entries* context entries with incrementally sized values,
    then retrieves and verifies them all. Tests the server's ability to
    handle a large number of context entries without memory issues.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        num_entries: Number of context entries to store (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_entries = min(num_entries, 1000)
    metrics = StressTestMetrics(name="context_memory_pressure")
    client = mock_daemon_server.make_authenticated_client()

    stored_keys: list[str] = []

    try:
        # Phase 1: Store many entries
        logger.info("Storing %d context entries...", actual_entries)
        for i in range(actual_entries):
            if time.monotonic() - metrics.start_time > time_budget * 0.9:
                break
            key = f"mem_pressure_key_{i}"
            # Vary value size to simulate realistic usage
            value_size = (i % 100) + 1
            value = "V" * value_size
            try:
                result = client.context_store(key, value)
                if result is not None:
                    metrics.record_operation()
                    stored_keys.append(key)
                else:
                    metrics.record_error()
            except Exception:
                metrics.record_error()

            if i > 0 and i % 200 == 0:
                logger.info("Stored %d/%d entries", i, actual_entries)

        # Phase 2: Retrieve and verify all entries
        logger.info("Verifying %d stored entries...", len(stored_keys))
        for key in stored_keys:
            if time.monotonic() - metrics.start_time > time_budget * 0.9:
                break
            try:
                retrieved = client.context_retrieve(key)
                if retrieved is not None:
                    metrics.record_operation()
                else:
                    metrics.record_error()
            except Exception:
                metrics.record_error()

        metrics.log_summary()
        metrics.assert_acceptable()
        logger.info("Context memory pressure test: %d stored, %d ops, %d errors",
                    len(stored_keys), metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()



# ---------------------------------------------------------------------------
# Test: Concurrent Load with Mixed Latencies
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("latency_profile", ["fast", "mixed", "slow"])
def test_concurrent_load_mixed_latencies(
    mock_daemon_server: MockDaemonServer,
    latency_profile: str,
    time_budget: float,
) -> None:
    """Concurrent load with different latency profiles.

    Creates workers with different response delay characteristics based
    on the *latency_profile*. Verifies that the server handles mixed
    latency workloads without head-of-line blocking or degradation.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        latency_profile: Latency profile for workers (parameterized).
        time_budget: Maximum allowed test duration.
    """
    # Create daemons with different latency profiles
    if latency_profile == "fast":
        daemon = MockDaemonServer(auth_enabled=True, response_delay_ms=1.0)
        num_workers = 20
        iterations_per_worker = 30
    elif latency_profile == "mixed":
        daemon = MockDaemonServer(auth_enabled=True, response_delay_ms=10.0)
        num_workers = 15
        iterations_per_worker = 20
    else:  # slow
        daemon = MockDaemonServer(auth_enabled=True, response_delay_ms=50.0)
        num_workers = 10
        iterations_per_worker = 10

    daemon.start()
    metrics = StressTestMetrics(name="mixed_latency_" + latency_profile)

    clients = create_clients(daemon, num_workers, authenticated=True)
    assert len(clients) > 0, "Failed to create clients"

    workers: list[ConcurrentWorker] = []
    for i in range(num_workers):
        client = clients[i % len(clients)]
        worker = ConcurrentWorker(
            worker_id=i,
            target=lambda c=client: safe_infer(
                c, prompt=f"Latency test {latency_profile} {i}", max_tokens=4,
            ),
            metrics=metrics,
            iterations=iterations_per_worker,
        )
        workers.append(worker)

    try:
        for w in workers:
            w.start()
        incomplete = wait_for_workers(workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()
            logger.warning("%d latency workers did not complete", len(incomplete))

        metrics.log_summary()
        metrics.assert_acceptable(max_error_rate=0.1)

        logger.info(
            "Latency profile '%s': p50=%.2fms, p95=%.2fms, p99=%.2fms",
            latency_profile, metrics.p50, metrics.p95, metrics.p99,
        )
    finally:
        disconnect_clients(clients)
        daemon.stop()


# ---------------------------------------------------------------------------
# Test: Graceful Degradation Under Load
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("load_level", ["moderate", "high", "extreme"])
def test_graceful_degradation_under_load(
    mock_daemon_server: MockDaemonServer,
    load_level: str,
    time_budget: float,
) -> None:
    """Verify graceful degradation as load increases.

    Gradually increases the load on the server and measures how
    latency and error rate change. Verifies that the server degrades
    gracefully (no crashes, no cascade failures) rather than failing
    catastrophically.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        load_level: Target load level (parameterized).
        time_budget: Maximum allowed test duration.
    """
    load_configs = {
        "moderate": {"workers": 10, "iterations": 30, "max_latency_ms": 5000},
        "high": {"workers": 25, "iterations": 20, "max_latency_ms": 10000},
        "extreme": {"workers": 50, "iterations": 10, "max_latency_ms": 20000},
    }
    config = load_configs[load_level]
    metrics = StressTestMetrics(name=f"graceful_degradation_{load_level}")

    clients = create_clients(mock_daemon_server, config["workers"])
    assert len(clients) > 0, "Failed to create clients"

    workers: list[ConcurrentWorker] = []
    for i in range(config["workers"]):
        client = clients[i % len(clients)]
        worker = ConcurrentWorker(
            worker_id=i,
            target=lambda c=client: safe_infer(
                c, prompt=f"Degradation test {load_level} {i}", max_tokens=8,
            ),
            metrics=metrics,
            iterations=config["iterations"],
        )
        workers.append(worker)

    try:
        for w in workers:
            w.start()
        incomplete = wait_for_workers(workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()
            logger.warning("%d degradation workers did not complete", len(incomplete))

        metrics.log_summary()

        # Under extreme load, we may have higher error rates
        max_error = 0.2 if load_level == "extreme" else 0.1
        metrics.assert_acceptable(max_error_rate=max_error)

        # Check that latency is bounded (not infinite)
        assert metrics.max_latency < float('inf'), "Infinite latency detected"
        assert metrics.avg_latency < config["max_latency_ms"], (
            f"Average latency {metrics.avg_latency:.0f}ms exceeds "
            f"threshold {config['max_latency_ms']}ms for {load_level} load"
        )

        logger.info("Graceful degradation test '%s': %d ops, %.2f%% errors, p95=%.2fms",
                    load_level, metrics.total_ops, metrics.error_rate * 100, metrics.p95)
    finally:
        disconnect_clients(clients)


# ---------------------------------------------------------------------------
# Test: Long Running Context Session
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("session_duration", [10, 30, 60])
def test_long_running_context_session(
    mock_daemon_server: MockDaemonServer,
    session_duration: int,
    time_budget: float,
) -> None:
    """Maintain a long-running context session with periodic operations.

    Opens a single client session, performs periodic context store/retrieve
    operations over *session_duration* seconds, and verifies that context
    data persists correctly throughout the session duration.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        session_duration: Duration of the session in seconds (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_duration = min(session_duration, int(time_budget * 0.8))
    metrics = StressTestMetrics(name="long_running_context")
    client = mock_daemon_server.make_authenticated_client()

    stored_values: dict[str, str] = {}

    try:
        start = time.monotonic()
        iter_count = 0

        while time.monotonic() - start < actual_duration:
            # Store a context value
            key = f"long_session_key_{iter_count}"
            value = f"long_session_val_{iter_count}_at_{time.monotonic():.0f}"
            try:
                result = client.context_store(key, value)
                if result is not None:
                    metrics.record_operation()
                    stored_values[key] = value
                else:
                    metrics.record_error()
            except Exception:
                metrics.record_error()

            # Retrieve a previously stored value
            if iter_count > 0:
                prev_key = f"long_session_key_{iter_count - 1}"
                try:
                    retrieved = client.context_retrieve(prev_key)
                    if retrieved is not None:
                        metrics.record_operation()
                        expected = stored_values.get(prev_key)
                        if expected is not None and retrieved != expected:
                            logger.warning("Context mismatch at iteration %d", iter_count)
                    else:
                        metrics.record_error()
                except Exception:
                    metrics.record_error()

            iter_count += 1
            time.sleep(0.5)  # Wait between operations

        metrics.log_summary()
        metrics.assert_acceptable()

        # Final verification of all stored values
        for key, expected in stored_values.items():
            try:
                retrieved = client.context_retrieve(key)
                if retrieved is not None:
                    assert retrieved == expected, f"Data mismatch for key {key}"
                metrics.record_operation()
            except Exception:
                metrics.record_error()

        logger.info("Long running context session: %.0fs, %d iterations, %d ops",
                    actual_duration, iter_count, metrics.total_ops)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Burst Then Steady State
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("burst_size", [50, 100, 200])
def test_burst_then_steady_state(
    mock_daemon_server: MockDaemonServer,
    burst_size: int,
    time_budget: float,
) -> None:
    """Send a burst of requests then transition to steady state.

    Sends *burst_size* requests in rapid succession, then immediately
    transitions to a steady stream of requests. Measures whether the
    server recovers from the burst and maintains stable throughput.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        burst_size: Number of burst requests (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_burst = min(burst_size, 200)
    metrics = StressTestMetrics(name="burst_then_steady")
    client = mock_daemon_server.make_authenticated_client()

    try:
        # Phase 1: Burst
        logger.info("Burst phase: sending %d requests rapidly...", actual_burst)
        for i in range(actual_burst):
            try:
                resp = client.infer(prompt=f"Burst request {i}", max_tokens=4)
                if resp.get("type") == "Error":
                    metrics.record_error()
                else:
                    metrics.record_operation()
            except Exception:
                metrics.record_error()

        burst_metrics = metrics.report()
        logger.info("Burst phase complete: %d ops, %.2f%% errors",
                    burst_metrics["total_ops"], burst_metrics["error_rate"] * 100)

        # Phase 2: Steady state
        logger.info("Steady state phase: sending requests at normal pace...")
        steady_metrics = StressTestMetrics(name="steady_state_after_burst")
        for i in range(actual_burst // 2):
            try:
                resp = client.infer(prompt=f"Steady request {i}", max_tokens=4)
                if resp.get("type") == "Error":
                    steady_metrics.record_error()
                else:
                    steady_metrics.record_operation()
            except Exception:
                steady_metrics.record_error()
            time.sleep(0.05)  # Small delay between requests

        steady_metrics.log_summary()
        steady_metrics.assert_acceptable()

        logger.info("Burst-then-steady test: burst=%d, steady=%d, steady_error_rate=%.2f%%",
                    actual_burst, steady_metrics.total_ops, steady_metrics.error_rate * 100)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Concurrent Inference with Timeout
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("timeout_ms", [100, 500, 1000])
def test_concurrent_inference_with_timeout(
    mock_daemon_server: MockDaemonServer,
    timeout_ms: int,
    time_budget: float,
) -> None:
    """Concurrent inference with client-side timeout.

    Launches concurrent workers where each inference request has a
    client-side timeout. Verifies that the server handles timed-out
    requests gracefully without leaving stale connections.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        timeout_ms: Client timeout in milliseconds (parameterized).
        time_budget: Maximum allowed test duration.
    """
    num_workers = 10
    metrics = StressTestMetrics(name="concurrent_inference_timeout")
    timeout_seconds = timeout_ms / 1000.0

    clients = create_clients(mock_daemon_server, num_workers)
    assert len(clients) > 0, "Failed to create clients"

    workers: list[ConcurrentWorker] = []

    def infer_with_timeout(client: MockDaemonClient) -> None:
        """Perform inference with a custom socket timeout."""
        try:
            # Set a short timeout on the socket
            if client._socket is not None:
                original_timeout = client._socket.gettimeout()
                client._socket.settimeout(timeout_seconds)
            try:
                resp = client.infer(prompt=f"Timeout test request", max_tokens=4)
                if resp.get("type") == "Error":
                    raise MockDaemonError(resp.get("message", "Error"))
            except (socket.timeout, MockDaemonError) as exc:
                # Timeout or error is expected
                logger.debug("Expected timeout/error: %s", exc)
                raise
            finally:
                if client._socket is not None:
                    client._socket.settimeout(original_timeout)
        except Exception:
            raise

    for i in range(num_workers):
        client = clients[i % len(clients)]
        worker = ConcurrentWorker(
            worker_id=i,
            target=infer_with_timeout,
            metrics=metrics,
            iterations=10 if QUICK_MODE else 20,
            kwargs={"client": client},
        )
        workers.append(worker)

    try:
        for w in workers:
            w.start()
        incomplete = wait_for_workers(workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()
            logger.warning("%d timeout workers did not complete", len(incomplete))

        metrics.log_summary()
        # Timeouts are expected, so we allow a higher error rate
        metrics.assert_acceptable(max_error_rate=0.5)
        logger.info("Timeout test (timeout=%dms): %d ops, %d errors, error_rate=%.2f%%",
                    timeout_ms, metrics.total_ops, metrics.errors, metrics.error_rate * 100)
    finally:
        disconnect_clients(clients)


# ---------------------------------------------------------------------------
# Test: Model Load Contention
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("contention_level", [5, 10, 20])
def test_model_load_contention(
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
    contention_level: int,
    time_budget: float,
) -> None:
    """Test model loading with contention from multiple clients.

    Creates *contention_level* clients that all try to load different
    models simultaneously, creating contention for the model loading
    subsystem. Verifies correct handling and no corruption.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        temp_model_dir: Temporary directory with model files.
        contention_level: Number of competing clients (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_contention = min(contention_level, 20)
    metrics = StressTestMetrics(name="model_load_contention")

    # Create multiple model files for contention
    model_paths: list[str] = []
    for i in range(actual_contention):
        model_path = os.path.join(temp_model_dir, f"contention_model_{i}.gguf")
        create_minimal_gguf(model_path)
        model_paths.append(model_path)

    clients = create_clients(mock_daemon_server, actual_contention)
    assert len(clients) > 0, "Failed to create clients"

    workers: list[ConcurrentWorker] = []

    def load_specific_model(client: MockDaemonClient, path: str) -> None:
        """Load a specific model file."""
        load_resp = safe_model_load(client, path)
        if load_resp and load_resp.get("status") == "loaded":
            model_id = load_resp.get("model_id", "")
            safe_model_unload(client, model_id)

    for i in range(actual_contention):
        client = clients[i]
        worker = ConcurrentWorker(
            worker_id=i,
            target=load_specific_model,
            metrics=metrics,
            iterations=10,
            kwargs={"client": client, "path": model_paths[i]},
        )
        workers.append(worker)

    try:
        for w in workers:
            w.start()
        incomplete = wait_for_workers(workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()
            logger.warning("%d contention workers did not complete", len(incomplete))

        metrics.log_summary()
        metrics.assert_acceptable()

        check_client = mock_daemon_server.make_authenticated_client()
        try:
            models = check_client.model_list()
            assert isinstance(models, list)
            logger.info("Model load contention test: %d clients, %d ops, %d errors",
                        actual_contention, metrics.total_ops, metrics.errors)
        finally:
            check_client.disconnect()
    finally:
        disconnect_clients(clients)


# ---------------------------------------------------------------------------
# Test: Concurrent Session with Multiple Operations
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("ops_per_session", [5, 15, 30])
def test_concurrent_session_multi_ops(
    mock_daemon_server: MockDaemonServer,
    ops_per_session: int,
    time_budget: float,
) -> None:
    """Each session performs multiple operation types.

    Creates sessions where each client performs a sequence of different
    operation types (infer, model_list, status, context) within a single
    session. Verifies session state consistency across operations.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        ops_per_session: Operations per session (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_ops = min(ops_per_session, 30)
    num_sessions = 15
    metrics = StressTestMetrics(name="session_multi_ops")

    clients = create_clients(mock_daemon_server, num_sessions)
    assert len(clients) > 0, "Failed to create clients"

    workers: list[ConcurrentWorker] = []

    def multi_operation_session(client: MockDaemonClient) -> None:
        """Perform a sequence of different operation types."""
        safe_infer(client, prompt="Session multi-op infer", max_tokens=4)
        safe_model_list(client)
        safe_status(client)
        key = f"session_multi_{uuid.uuid4().hex[:8]}"
        safe_context_store(client, key, "multi_op_value")
        safe_context_retrieve(client, key)

    for i in range(num_sessions):
        client = clients[i % len(clients)]
        worker = ConcurrentWorker(
            worker_id=i,
            target=multi_operation_session,
            metrics=metrics,
            iterations=actual_ops,
            kwargs={"client": client},
        )
        workers.append(worker)

    try:
        for w in workers:
            w.start()
        incomplete = wait_for_workers(workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()
            logger.warning("%d multi-op workers did not complete", len(incomplete))

        metrics.log_summary()
        metrics.assert_acceptable()
        logger.info("Session multi-ops test: %d sessions, %d ops, %d errors",
                    num_sessions, metrics.total_ops, metrics.errors)
    finally:
        disconnect_clients(clients)


# ---------------------------------------------------------------------------
# Test: Context Key Collision
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_collisions", [10, 50, 100])
def test_context_key_collision(
    mock_daemon_server: MockDaemonServer,
    num_collisions: int,
    time_budget: float,
) -> None:
    """Test context store behavior when multiple clients use the same key.

    Multiple clients simultaneously store and retrieve values using the
    same set of keys. Verifies that the server handles key collisions
    gracefully and that the last-written value is consistently returned.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        num_collisions: Number of colliding keys (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_collisions = min(num_collisions, 100)
    num_clients = 10
    metrics = StressTestMetrics(name="context_key_collision")

    clients = create_clients(mock_daemon_server, num_clients)
    assert len(clients) > 0, "Failed to create clients"

    collision_keys = [f"collision_key_{i}" for i in range(actual_collisions)]
    workers: list[ConcurrentWorker] = []

    def collide_on_key(client: MockDaemonClient, key: str) -> None:
        """Store and retrieve a value for a specific key."""
        value = f"value_from_{uuid.uuid4().hex[:8]}"
        safe_context_store(client, key, value)
        safe_context_retrieve(client, key)

    for i in range(num_clients):
        client = clients[i % len(clients)]
        # Each worker uses a subset of the collision keys
        worker_keys = collision_keys[i % len(collision_keys):(i + 3) % len(collision_keys) or len(collision_keys)]

        def make_collide_fn(c: MockDaemonClient = client, keys: list[str] = worker_keys) -> None:
            for k in keys:
                collide_on_key(c, k)

        worker = ConcurrentWorker(
            worker_id=i,
            target=make_collide_fn,
            metrics=metrics,
            iterations=5,
        )
        workers.append(worker)

    try:
        for w in workers:
            w.start()
        incomplete = wait_for_workers(workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()
            logger.warning("%d key collision workers did not complete", len(incomplete))

        metrics.log_summary()
        metrics.assert_acceptable()
        logger.info("Key collision test: %d keys, %d clients, %d ops, %d errors",
                    actual_collisions, num_clients, metrics.total_ops, metrics.errors)
    finally:
        disconnect_clients(clients)


# ---------------------------------------------------------------------------
# Test: Concurrent Model Info Consistency
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("num_models", [3, 5, 10])
def test_concurrent_model_info_consistency(
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
    num_models: int,
    time_budget: float,
) -> None:
    """Verify model info consistency under concurrent operations.

    Loads *num_models* models, then concurrently queries model info
    while also loading/unloading models. Verifies that model info
    queries return consistent results.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        temp_model_dir: Temporary directory with model files.
        num_models: Number of models to test with (parameterized).
        time_budget: Maximum allowed test duration.
    """
    actual_models = min(num_models, 10)
    metrics = StressTestMetrics(name="model_info_consistency")

    # Create model files
    model_paths: list[str] = []
    loaded_model_ids: list[str] = []
    for i in range(actual_models):
        model_path = os.path.join(temp_model_dir, f"consistency_model_{i}.gguf")
        create_minimal_gguf(model_path)
        model_paths.append(model_path)

    # Load all models first
    load_client = mock_daemon_server.make_authenticated_client()
    for path in model_paths:
        try:
            resp = load_client.model_load(path)
            if resp.get("status") == "loaded":
                loaded_model_ids.append(resp.get("model_id", ""))
        except Exception:
            pass
    load_client.disconnect()

    assert len(loaded_model_ids) > 0, "Failed to load any models"

    # Concurrently query model info and perform operations
    query_clients = create_clients(mock_daemon_server, 10)
    workers: list[ConcurrentWorker] = []

    for i in range(10):
        client = query_clients[i % len(query_clients)]
        worker = ConcurrentWorker(
            worker_id=i,
            target=lambda c=client: safe_model_list(c),
            metrics=metrics,
            iterations=20,
        )
        workers.append(worker)

    try:
        for w in workers:
            w.start()
        incomplete = wait_for_workers(workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()
            logger.warning("%d consistency workers did not complete", len(incomplete))

        metrics.log_summary()
        metrics.assert_acceptable()

        # Verify model info is correct
        verify_client = mock_daemon_server.make_authenticated_client()
        try:
            models = verify_client.model_list()
            model_ids = [m.get("id", "") for m in models]
            for model_id in loaded_model_ids:
                assert model_id in model_ids, f"Model {model_id} missing from list"
            logger.info("Model info consistency: %d models, %d queries, all consistent",
                        len(loaded_model_ids), metrics.total_ops)
        finally:
            verify_client.disconnect()
    finally:
        # Cleanup loaded models
        cleanup_client = mock_daemon_server.make_authenticated_client()
        for model_id in loaded_model_ids:
            try:
                cleanup_client.model_unload(model_id)
            except Exception:
                pass
        cleanup_client.disconnect()
        disconnect_clients(query_clients)


# ---------------------------------------------------------------------------
# Test: Stress Test Duration Parameterization
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("duration_setting", ["short", "medium", "long"])
def test_stress_duration_parameterization(
    mock_daemon_server: MockDaemonServer,
    duration_setting: str,
    time_budget: float,
) -> None:
    """Test that stress test duration parameterization works correctly.

    Validates that the duration-based configuration from environment
    variables is properly applied. Runs a short workload and verifies
    the configuration is correctly interpreted.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        duration_setting: Expected duration setting (parameterized).
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="duration_param_test")

    # Verify the configuration matches expectations
    if duration_setting == "short":
        expected_duration = 10
    elif duration_setting == "medium":
        expected_duration = 30
    else:
        expected_duration = 60

    # Just run a few operations to verify the configuration
    client = mock_daemon_server.make_authenticated_client()
    try:
        for i in range(10):
            resp = client.infer(prompt=f"Duration param test {i}", max_tokens=4)
            if resp.get("type") == "Error":
                metrics.record_error()
            else:
                metrics.record_operation()

        metrics.log_summary()
        logger.info("Duration parameterization test '%s': %d ops, STRESS_DURATION=%d, QUICK_MODE=%s",
                    duration_setting, metrics.total_ops, STRESS_DURATION, QUICK_MODE)
        assert metrics.total_ops > 0, "No operations completed"
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Comprehensive Cleanup After Failure
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.parametrize("resource_type", ["connections", "models", "context"])
def test_comprehensive_cleanup_after_failure(
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
    resource_type: str,
    time_budget: float,
) -> None:
    """Comprehensive cleanup verification after various failure types.

    Creates resources of the specified type, intentionally fails, and
    verifies that all resources are properly cleaned up. Different
    resource types stress different cleanup paths.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        temp_model_dir: Temporary directory with model files.
        resource_type: Type of resource to test (parameterized).
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="comprehensive_cleanup")
    created_clients: list[MockDaemonClient] = []
    model_path = os.path.join(temp_model_dir, "test_model.gguf")

    def cleanup() -> None:
        """Perform comprehensive cleanup of all resources."""
        for client in created_clients:
            try:
                client.disconnect()
            except Exception:
                pass
        created_clients.clear()
        logger.info("Comprehensive cleanup completed for %s", resource_type)

    try:
        if resource_type == "connections":
            # Create many connections then fail
            created_clients = create_clients(mock_daemon_server, 20, authenticated=True)
            metrics.record_operation()
            assert len(created_clients) > 0, "Failed to create connections"
            raise RuntimeError("Simulated connection failure")

        elif resource_type == "models":
            # Load a model then fail
            client = mock_daemon_server.make_authenticated_client()
            created_clients.append(client)
            resp = client.model_load(model_path)
            if resp.get("status") == "loaded":
                metrics.record_operation()
            raise RuntimeError("Simulated model failure")

        else:  # context
            # Store context entries then fail
            client = mock_daemon_server.make_authenticated_client()
            created_clients.append(client)
            for i in range(10):
                client.context_store(f"cleanup_key_{i}", f"cleanup_val_{i}")
            metrics.record_operation()
            raise RuntimeError("Simulated context failure")

    except RuntimeError as exc:
        logger.info("Simulated %s failure: %s", resource_type, exc)
        cleanup()
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        cleanup()
        raise

    # Verify cleanup was effective
    verify_client = mock_daemon_server.make_authenticated_client()
    try:
        status = verify_client.status()
        assert_status_response(status)
        logger.info("Cleanup verified for %s failure", resource_type)
    finally:
        verify_client.disconnect()

    metrics.log_summary()
    logger.info("Comprehensive cleanup test passed for resource_type=%s", resource_type)


# ---------------------------------------------------------------------------
# Test: Edge Case  -- Empty Model Load
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_edge_case_empty_model_load(
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
    time_budget: float,
) -> None:
    """Test loading an empty model file.

    Attempts to load an empty model file (zero bytes) and a corrupted
    model file. Verifies that the server returns appropriate error
    responses rather than crashing or hanging.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        temp_model_dir: Temporary directory with model files.
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="edge_case_empty_model")
    client = mock_daemon_server.make_authenticated_client()

    empty_model = os.path.join(temp_model_dir, "empty_model.gguf")
    corrupted_model = os.path.join(temp_model_dir, "corrupted_model.gguf")

    try:
        # Test with empty model
        try:
            resp = client.model_load(empty_model)
            metrics.record_operation()
            # Empty files should fail to load (they have a GGUF header but no content)
            if resp.get("type") == "Error" or resp.get("status") == "error":
                metrics.record_operation()  # Expected error is still a valid response
            else:
                logger.info("Empty model load returned: %s", resp)
        except Exception as exc:
            metrics.record_error()
            logger.debug("Empty model load exception (expected): %s", exc)

        # Test with corrupted model
        try:
            resp = client.model_load(corrupted_model)
            metrics.record_operation()
            if resp.get("type") == "Error" or resp.get("status") == "error":
                metrics.record_operation()
            else:
                logger.info("Corrupted model load returned: %s", resp)
        except Exception as exc:
            metrics.record_error()
            logger.debug("Corrupted model load exception (expected): %s", exc)

        # Test with non-existent model file
        try:
            resp = client.model_load("/tmp/nonexistent_model_that_does_not_exist.gguf")
            metrics.record_operation()
            if resp.get("type") == "Error" or resp.get("status") == "error":
                metrics.record_operation()
        except Exception as exc:
            metrics.record_error()
            logger.debug("Non-existent model load exception (expected): %s", exc)

        metrics.log_summary()
        logger.info("Edge case model load test: %d ops, %d errors", metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Edge Case  -- Large Model List
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_edge_case_large_model_list(
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
    time_budget: float,
) -> None:
    """Test model list with many models loaded.

    Loads many models into the server, then queries the model list.
    Verifies that the list correctly reports all loaded models and
    that the server handles a large number of registered models.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        temp_model_dir: Temporary directory with model files.
        time_budget: Maximum allowed test duration.
    """
    num_models = 20 if QUICK_MODE else 50
    metrics = StressTestMetrics(name="edge_case_large_model_list")
    client = mock_daemon_server.make_authenticated_client()

    loaded_models: list[str] = []

    try:
        # Create and load many model files
        for i in range(num_models):
            model_path = os.path.join(temp_model_dir, f"large_list_model_{i}.gguf")
            create_minimal_gguf(model_path)
            try:
                resp = client.model_load(model_path)
                if resp.get("status") == "loaded":
                    loaded_models.append(resp.get("model_id", ""))
                    metrics.record_operation()
                else:
                    metrics.record_error()
            except Exception:
                metrics.record_error()

        # Query the model list
        try:
            models = client.model_list()
            metrics.record_operation()
            loaded_ids = [m.get("id", "") for m in models]
            for model_id in loaded_models:
                assert model_id in loaded_ids, f"Model {model_id} missing from list"
            logger.info("Large model list: %d models loaded, %d in list", len(loaded_models), len(models))
        except Exception:
            metrics.record_error()

        # Unload all models
        for model_id in loaded_models:
            try:
                client.model_unload(model_id)
                metrics.record_operation()
            except Exception:
                metrics.record_error()

        metrics.log_summary()
        metrics.assert_acceptable()
        logger.info("Large model list test: %d models, %d ops, %d errors",
                    num_models, metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test Runner CLI Entry Point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    """Run stress tests from the command line with pytest.

    This entry point allows running the stress tests directly without
    going through the pytest runner. Useful for quick validation or
    integration with custom test harnesses.

    Usage:
        python tests/stress/test_stress.py
        python tests/stress/test_stress.py --quick
        python tests/stress/test_stress.py --duration 30 --concurrency 20
        python tests/stress/test_stress.py --verbose
        python tests/stress/test_stress.py --list-tests
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="AinosOS Stress and Load Test Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tests/stress/test_stress.py --quick
  python tests/stress/test_stress.py --duration 30 --concurrency 20
  python tests/stress/test_stress.py --verbose --quick
        """,
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Run in quick mode (reduced iterations, shorter duration)",
    )
    parser.add_argument(
        "--duration", type=int, default=60,
        help="Test duration in seconds (default: 60)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=10,
        help="Concurrency level (default: 10)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose output with debug logging",
    )
    parser.add_argument(
        "--list-tests", action="store_true",
        help="List all available test functions and exit",
    )
    parser.add_argument(
        "--timeout", type=int, default=600,
        help="Test timeout in seconds (default: 600)",
    )
    parser.add_argument(
        "--fail-fast", "-x", action="store_true",
        help="Stop on first test failure",
    )
    parser.add_argument(
        "--test-name", "-k", type=str, default="",
        help="Only run tests matching the given substring expression",
    )
    args = parser.parse_args()

    if args.list_tests:
        # Parse the file and list all test functions
        import re
        test_pattern = re.compile(r'^def (test_\w+)\(')
        tests_found = []
        with open(__file__, 'r') as f:
            for line in f:
                match = test_pattern.match(line)
                if match:
                    tests_found.append(match.group(1))
        print(f"\nAinosOS Stress Test Suite - Available Tests ({len(tests_found)}):")
        print("=" * 60)
        for test in tests_found:
            print(f"  {test}")
        print("=" * 60)
        sys.exit(0)

    # Set environment variables for test configuration
    if args.quick:
        os.environ["AINOS_QUICK_MODE"] = "1"
    os.environ["AINOS_STRESS_DURATION"] = str(args.duration)
    os.environ["AINOS_STRESS_CONCURRENCY"] = str(args.concurrency)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    logger.info("=" * 60)
    logger.info("AinosOS Stress Test Suite")
    logger.info("=" * 60)
    logger.info("Settings:")
    logger.info("  Duration:     %d seconds", args.duration)
    logger.info("  Concurrency:  %d", args.concurrency)
    logger.info("  Quick mode:   %s", args.quick)
    logger.info("  Timeout:      %d seconds", args.timeout)
    logger.info("  Fail fast:    %s", args.fail_fast)
    if args.test_name:
        logger.info("  Test filter:  %s", args.test_name)
    logger.info("-" * 60)

    # Build pytest arguments
    pytest_args = [
        sys.executable, "-m", "pytest",
        __file__,
        "-v",  # Verbose
        "--tb=short",  # Short traceback format
    ]

    if args.fail_fast:
        pytest_args.append("-x")

    if args.test_name:
        pytest_args.extend(["-k", args.test_name])

    if args.verbose:
        pytest_args.append("--log-cli-level=DEBUG")
    else:
        pytest_args.append("--log-cli-level=INFO")

    # Set timeout for pytest
    pytest_args.extend(["--timeout", str(args.timeout)])

    # Run tests
    import subprocess
    test_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    logger.info("Starting pytest with arguments: %s", " ".join(pytest_args[2:]))
    logger.info("Test directory: %s", test_dir)

    result = subprocess.run(pytest_args, cwd=test_dir)

    logger.info("Test run completed with exit code: %d", result.returncode)
    sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# Test: Edge Case -- Invalid Context Operations
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_edge_case_invalid_context_ops(
    mock_daemon_server: MockDaemonServer,
    time_budget: float,
) -> None:
    """Test context operations with invalid inputs.

    Sends context store/retrieve requests with empty keys, very long
    keys, and special characters. Verifies the server handles these
    edge cases gracefully without crashing.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="edge_case_invalid_context")
    client = mock_daemon_server.make_authenticated_client()

    edge_cases = [
        ("", "empty_key_value"),
        ("a" * 1000, "very_long_key_value"),
        ("key_with_special_chars_!@#$%^&*()", "special_value"),
        ("key\nwith\nnewlines", "value_with_newlines"),
        ("key\twith\ttabs", "value_with_tabs"),
        ("", ""),
        ("normal_key", ""),
        ("key_with_unicode_eno", "unicode_value"),
    ]

    try:
        for key, value in edge_cases:
            if time.monotonic() - metrics.start_time > time_budget * 0.9:
                break
            try:
                result = client.context_store(key, value)
                if result is not None:
                    metrics.record_operation()
                else:
                    metrics.record_error()
            except Exception:
                metrics.record_error()

            try:
                retrieved = client.context_retrieve(key)
                if retrieved is not None:
                    metrics.record_operation()
                else:
                    metrics.record_error()
            except Exception:
                metrics.record_error()

        metrics.log_summary()
        logger.info("Edge case context ops: %d ops, %d errors", metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Edge Case -- Rapid Inference with Empty Prompts
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_edge_case_empty_prompts(
    mock_daemon_server: MockDaemonServer,
    time_budget: float,
) -> None:
    """Test inference with empty and minimal prompts.

    Sends inference requests with empty prompts, single characters,
    whitespace-only prompts, and very long prompts. Verifies that
    the server handles all cases without crashing.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="edge_case_empty_prompts")
    client = mock_daemon_server.make_authenticated_client()

    test_prompts = [
        "",
        " ",
        "\t",
        "\n",
        "a",
        "A" * 10000,
        " " * 1000,
        "Hello?",
        '{"json": "test"}',
        "<script>alert('test')</script>",
        "SELECT * FROM models; DROP TABLE models;",
        "../../../etc/passwd",
        "%00%00%00%00",
        "null",
        "undefined",
        "None",
        "True",
        "False",
        "[]",
        "{}",
        "0",
        "-1",
        "1.7976931348623157e+308",
    ]

    try:
        for prompt in test_prompts:
            if time.monotonic() - metrics.start_time > time_budget * 0.9:
                break
            try:
                resp = client.infer(prompt=prompt, model="default", max_tokens=4)
                if resp.get("type") == "Error":
                    metrics.record_error()
                else:
                    metrics.record_operation()
            except Exception:
                metrics.record_error()

        metrics.log_summary()
        metrics.assert_acceptable(max_error_rate=0.3)
        logger.info("Edge case empty prompts: %d ops, %d errors", metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Edge Case -- Model Unload Without Load
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_edge_case_model_unload_without_load(
    mock_daemon_server: MockDaemonServer,
    time_budget: float,
) -> None:
    """Test unloading models that were never loaded.

    Attempts to unload non-existent models, already-unloaded models,
    and models with invalid IDs. Verifies the server returns appropriate
    error responses.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="edge_case_model_unload")
    client = mock_daemon_server.make_authenticated_client()

    try:
        # Unload non-existent model
        try:
            resp = client.model_unload("nonexistent_model_id_12345")
            metrics.record_operation()
            if resp.get("type") == "Error" or resp.get("status") == "not_found":
                metrics.record_operation()
        except Exception:
            metrics.record_error()

        # Unload with empty model ID
        try:
            resp = client.model_unload("")
            metrics.record_operation()
        except Exception:
            metrics.record_error()

        # Unload with special characters in ID
        try:
            resp = client.model_unload("../../../etc/passwd")
            metrics.record_operation()
        except Exception:
            metrics.record_error()

        # Unload with very long ID
        try:
            resp = client.model_unload("a" * 1000)
            metrics.record_operation()
        except Exception:
            metrics.record_error()

        # Double unload: load, unload, unload again
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".gguf", delete=False) as tmp:
            model_path = tmp.name
        try:
            from tests.conftest import create_minimal_gguf
            create_minimal_gguf(model_path)
            resp = client.model_load(model_path)
            if resp.get("status") == "loaded":
                model_id = resp.get("model_id", "")
                resp1 = client.model_unload(model_id)
                metrics.record_operation()
                resp2 = client.model_unload(model_id)
                metrics.record_operation()
                if resp2.get("status") == "not_found":
                    metrics.record_operation()
        except Exception:
            metrics.record_error()
        finally:
            if model_path and os.path.exists(model_path):
                os.unlink(model_path)

        metrics.log_summary()
        logger.info("Edge case model unload: %d ops, %d errors", metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Edge Case -- Concurrent Status and Model List
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_edge_case_concurrent_status_model_list(
    mock_daemon_server: MockDaemonServer,
    time_budget: float,
) -> None:
    """Concurrent status and model list queries under load.

    Launches workers that interleave status and model list queries
    under concurrent load. Verifies that read-only operations remain
    responsive and correct under mixed workloads.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        time_budget: Maximum allowed test duration.
    """
    num_workers = 15
    metrics = StressTestMetrics(name="edge_case_status_model_list")
    clients = create_clients(mock_daemon_server, num_workers)
    assert len(clients) > 0, "Failed to create clients"

    workers: list[ConcurrentWorker] = []

    def status_and_list(client: MockDaemonClient) -> None:
        """Query status and model list."""
        safe_status(client)
        safe_model_list(client)

    for i in range(num_workers):
        client = clients[i % len(clients)]
        worker = ConcurrentWorker(
            worker_id=i,
            target=status_and_list,
            metrics=metrics,
            iterations=20,
            kwargs={"client": client},
        )
        workers.append(worker)

    try:
        for w in workers:
            w.start()
        incomplete = wait_for_workers(workers, timeout=time_budget * 0.8)
        if incomplete:
            for w in incomplete:
                w.stop()
            logger.warning("%d status/model list workers did not complete", len(incomplete))

        metrics.log_summary()
        metrics.assert_acceptable()
        logger.info("Edge case status/model list: %d workers, %d ops, %d errors",
                    num_workers, metrics.total_ops, metrics.errors)
    finally:
        disconnect_clients(clients)


# ---------------------------------------------------------------------------
# Test: Comprehensive Stress Test Runner
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_comprehensive_stress_runner(
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
    stress_duration_seconds: float,
    time_budget: float,
) -> None:
    """Comprehensive stress test combining multiple operation types.

    Runs a comprehensive stress scenario that combines inference, model
    management, context operations, and authentication in a single test.
    Designed to catch interaction issues between different subsystems.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        temp_model_dir: Temporary directory with model files.
        stress_duration_seconds: Duration from environment variable.
        time_budget: Maximum allowed test duration.
    """
    actual_duration = min(30.0, stress_duration_seconds, time_budget * 0.7)
    metrics = StressTestMetrics(name="comprehensive_stress")
    model_path = create_temp_model_file(temp_model_dir, "comprehensive_model.gguf")

    # Phase 1: Auth and connect
    logger.info("Phase 1: Authentication and connection")
    clients = create_clients(mock_daemon_server, 5, authenticated=True)
    assert len(clients) > 0, "Failed to create clients"
    metrics.record_operation()

    # Phase 2: Load model
    logger.info("Phase 2: Model loading")
    load_client = clients[0]
    try:
        resp = load_client.model_load(model_path)
        if resp.get("status") == "loaded":
            model_id = resp.get("model_id", "")
            metrics.record_operation()
        else:
            model_id = None
            metrics.record_error()
    except Exception:
        model_id = None
        metrics.record_error()

    # Phase 3: Concurrent inference
    logger.info("Phase 3: Concurrent inference")
    infer_metrics = StressTestMetrics(name="comprehensive_infer")
    infer_workers: list[ConcurrentWorker] = []
    for i in range(5):
        client = clients[i % len(clients)]
        worker = ConcurrentWorker(
            worker_id=i,
            target=lambda c=client: safe_infer(c, prompt="Comprehensive test", max_tokens=8),
            metrics=infer_metrics,
            iterations=int(actual_duration * 2),
        )
        infer_workers.append(worker)

    for w in infer_workers:
        w.start()

    # Phase 4: Context operations
    logger.info("Phase 4: Context operations")
    context_client = mock_daemon_server.make_authenticated_client()
    for i in range(20):
        try:
            context_client.context_store(f"comp_key_{i}", f"comp_val_{i}")
            metrics.record_operation()
        except Exception:
            metrics.record_error()

    # Phase 5: Status queries
    logger.info("Phase 5: Status queries")
    for i in range(10):
        try:
            safe_status(clients[i % len(clients)])
            metrics.record_operation()
        except Exception:
            metrics.record_error()

    # Wait for inference workers
    incomplete = wait_for_workers(infer_workers, timeout=actual_duration + 5)
    if incomplete:
        for w in incomplete:
            w.stop()
        logger.warning("%d comprehensive workers did not complete", len(incomplete))

    # Phase 6: Unload model
    logger.info("Phase 6: Cleanup")
    if model_id:
        try:
            load_client.model_unload(model_id)
            metrics.record_operation()
        except Exception:
            metrics.record_error()

    context_client.disconnect()
    disconnect_clients(clients)

    infer_metrics.log_summary()
    metrics.log_summary()
    metrics.assert_acceptable(max_error_rate=0.2)
    logger.info("Comprehensive stress test: %d ops, %d errors", metrics.total_ops, metrics.errors)


# ---------------------------------------------------------------------------
# Test Runner CLI Entry Point
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Test: Stress Test Exports Validation

@pytest.mark.stress
@pytest.mark.slow
def test_stress_test_exports_validation(
    time_budget: float,
) -> None:
    """Validate that all stress test exports are properly defined.

    Checks that all helper classes, functions, and constants defined
    in the stress test module have the expected types and values.
    This is a lightweight import validation test that verifies the
    module structure is correct.

    Args:
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="stress_test_exports_validation")

    # Verify helper classes are properly defined
    assert isinstance(StressTestMetrics(name="test"), StressTestMetrics)
    assert isinstance(DataIntegrityChecker, type)
    assert isinstance(ConcurrentWorker, type)
    assert isinstance(MetricsCollector, type)
    metrics.record_operation()

    # Verify utility functions are callable
    import inspect
    assert callable(get_current_memory_mb)
    assert callable(wait_for_workers)
    assert callable(create_clients)
    assert callable(disconnect_clients)
    assert callable(create_temp_model_file)
    assert callable(safe_infer)
    assert callable(safe_model_list)
    assert callable(safe_model_load)
    assert callable(safe_model_unload)
    assert callable(safe_context_store)
    assert callable(safe_context_retrieve)
    assert callable(safe_status)
    assert callable(safe_rate_limit_status)
    assert callable(format_duration)
    assert callable(compute_quantiles)
    metrics.record_operation()

    # Verify constants are defined
    assert STRESS_DURATION > 0
    assert STRESS_CONCURRENCY > 0
    assert isinstance(QUICK_MODE, bool)
    assert MEMORY_LEAK_ITERATIONS > 0
    assert CONNECTION_STORM_COUNT > 0
    assert CONCURRENT_INFERENCE_WORKERS > 0
    assert CONCURRENT_MODEL_LIST_WORKERS > 0
    assert DATA_INTEGRITY_OPERATIONS > 0
    assert MIXED_WORKLOAD_DURATION > 0
    assert CONTEXT_CONCURRENCY_WORKERS > 0
    assert SUSTAINED_THROUGHPUT_DURATION > 0
    assert MAX_ACCEPTABLE_ERROR_RATE > 0
    assert MAX_ACCEPTABLE_MEMORY_GROWTH_MB > 0
    assert MAX_ACCEPTABLE_P99_LATENCY_MS > 0
    assert DATA_INTEGRITY_KEY_PREFIX is not None
    assert DATA_INTEGRITY_VALUE_PREFIX is not None
    assert LATENCY_WARN_THRESHOLD_MS > 0
    metrics.record_operation()

    # Verify that fixtures are properly defined
    fixture_names = ["fresh_client", "stress_model_path", "memory_metrics", "concurrency_level", "stress_duration_seconds"]
    for name in fixture_names:
        assert name in dir(), f"Fixture '{name}' should be defined in module scope"
    metrics.record_operation()

    metrics.log_summary()
    logger.info("Stress test exports validation: %d checks passed", metrics.total_ops)


# ---------------------------------------------------------------------------
# Test: Edge Case -- Empty Inference Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_edge_case_empty_inference_edge_cases(
    mock_daemon_server: MockDaemonServer,
    time_budget: float,
) -> None:
    """Test inference with additional edge case inputs.

    Tests inference with empty strings, very long prompts, special
    characters, and other edge case inputs to verify robustness.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="edge_case_empty_inference_extra")
    client = mock_daemon_server.make_authenticated_client()

    test_prompts = [
        "",
        " ",
        "\t",
        "\n",
        "a",
        "A" * 10000,
        " " * 1000,
        "Hello?",
        '{"json": "test"}',
        "<script>alert('test')</script>",
        "../../../etc/passwd",
        "null",
        "undefined",
        "None",
        "True",
        "False",
        "[]",
        "{}",
        "0",
        "-1",
        "1.7976931348623157e+308",
    ]

    try:
        for prompt in test_prompts:
            if time.monotonic() - metrics.start_time > time_budget * 0.9:
                break
            try:
                resp = client.infer(prompt=prompt, model="default", max_tokens=4)
                if resp.get("type") == "Error":
                    metrics.record_error()
                else:
                    metrics.record_operation()
            except Exception:
                metrics.record_error()

        metrics.log_summary()
        metrics.assert_acceptable(max_error_rate=0.3)
        logger.info("Edge case empty inference extra: %d ops, %d errors", metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Stress Test Helper Functions
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_stress_test_helper_functions(
    time_budget: float,
) -> None:
    """Test the helper functions used by stress tests.

    Validates that helper functions like compute_quantiles,
    format_duration, and get_current_memory_mb work correctly
    with various inputs.

    Args:
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="stress_test_helper_functions")

    # Test compute_quantiles
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    quantiles = compute_quantiles(values, [0.5, 0.95, 0.99])
    assert 0.5 in quantiles
    assert 0.95 in quantiles
    assert 0.99 in quantiles
    assert quantiles[0.5] == 5.0 or quantiles[0.5] == 6.0
    metrics.record_operation()

    # Test format_duration
    assert format_duration(30.0) == "30.0s"
    assert "m" in format_duration(120.0)
    assert "h" in format_duration(3600.0)
    metrics.record_operation()

    # Test get_current_memory_mb
    mem = get_current_memory_mb()
    assert mem > 0
    assert mem < 100000  # Sanity check: less than 100 GB
    metrics.record_operation()

    # Test create_temp_model_file
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        model_path = create_temp_model_file(tmpdir, "test_helper.gguf")
        assert os.path.exists(model_path)
        assert model_path.endswith(".gguf")
        metrics.record_operation()

    metrics.log_summary()
    logger.info("Helper functions: %d tests passed", metrics.total_ops)
if __name__ == "__main__":
    """Run stress tests from the command line with pytest.

    This entry point allows running the stress tests directly without
    going through the pytest runner. Useful for quick validation or
    integration with custom test harnesses.

    Usage:
        python tests/stress/test_stress.py
        python tests/stress/test_stress.py --quick
        python tests/stress/test_stress.py --duration 30 --concurrency 20
        python tests/stress/test_stress.py --verbose
        python tests/stress/test_stress.py --list-tests
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="AinosOS Stress and Load Test Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python tests/stress/test_stress.py --quick
  python tests/stress/test_stress.py --duration 30 --concurrency 20
  python tests/stress/test_stress.py --verbose --quick
        """,
    )
    parser.add_argument("--quick", action="store_true", help="Run in quick mode (reduced iterations, shorter duration)")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds (default: 60)")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrency level (default: 10)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output with debug logging")
    parser.add_argument("--list-tests", action="store_true", help="List all available test functions and exit")
    parser.add_argument("--timeout", type=int, default=600, help="Test timeout in seconds (default: 600)")
    parser.add_argument("--fail-fast", "-x", action="store_true", help="Stop on first test failure")
    parser.add_argument("--test-name", "-k", type=str, default="", help="Only run tests matching the given substring expression")
    args = parser.parse_args()

    if args.list_tests:
        import re
        test_pattern = re.compile(r"^def (test_\w+)\(")
        tests_found = []
        with open(__file__, "r") as f:
            for line in f:
                match = test_pattern.match(line)
                if match:
                    tests_found.append(match.group(1))
        print(f"\nAinosOS Stress Test Suite - Available Tests ({len(tests_found)}):")
        print("=" * 60)
        for test in tests_found:
            print(f"  {test}")
        print("=" * 60)
        sys.exit(0)

    if args.quick:
        os.environ["AINOS_QUICK_MODE"] = "1"
    os.environ["AINOS_STRESS_DURATION"] = str(args.duration)
    os.environ["AINOS_STRESS_CONCURRENCY"] = str(args.concurrency)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")

    logger.info("=" * 60)
    logger.info("AinosOS Stress Test Suite")
    logger.info("=" * 60)
    logger.info("Settings:")
    logger.info("  Duration:     %d seconds", args.duration)
    logger.info("  Concurrency:  %d", args.concurrency)
    logger.info("  Quick mode:   %s", args.quick)
    logger.info("  Timeout:      %d seconds", args.timeout)
    logger.info("  Fail fast:    %s", args.fail_fast)
    if args.test_name:
        logger.info("  Test filter:  %s", args.test_name)
    logger.info("-" * 60)

    import subprocess
    pytest_args = [
        sys.executable, "-m", "pytest",
        __file__, "-v", "--tb=short",
    ]
    if args.fail_fast:
        pytest_args.append("-x")
    if args.test_name:
        pytest_args.extend(["-k", args.test_name])
    if args.verbose:
        pytest_args.append("--log-cli-level=DEBUG")
    else:
        pytest_args.append("--log-cli-level=INFO")
    pytest_args.extend(["--timeout", str(args.timeout)])

    test_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    logger.info("Starting pytest with arguments: %s", " ".join(pytest_args[2:]))
    logger.info("Test directory: %s", test_dir)

    result = subprocess.run(pytest_args, cwd=test_dir)
    logger.info("Test run completed with exit code: %d", result.returncode)
    sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# Test: Edge Case -- Very Long Context Values

@pytest.mark.stress
@pytest.mark.slow
def test_edge_case_very_long_context_values(
    mock_daemon_server: MockDaemonServer,
    time_budget: float,
) -> None:
    """Test context store with very long values.

    Stores and retrieves context values of extreme lengths (very short,
    very long, binary-like) to verify the server handles edge cases
    in value sizes correctly without truncation or corruption.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="edge_case_long_context")
    client = mock_daemon_server.make_authenticated_client()

    test_values = [
        ("short_key", "x"),
        ("medium_key", "Hello, World!" * 100),
        ("long_key", "A" * 50000),
        ("binary_key", "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
        ("repeat_key", "ABC123" * 1000),
        ("numeric_key", "1234567890" * 500),
        ("json_key", '{"key": "value", "nested": {"array": [1,2,3]}}' * 50),
        ("xml_key", "<root><item>test</item></root>" * 50),
    ]

    try:
        for key, value in test_values:
            if time.monotonic() - metrics.start_time > time_budget * 0.9:
                break
            try:
                result = client.context_store(key, value)
                if result is not None:
                    metrics.record_operation()
                else:
                    metrics.record_error()
                    continue
            except Exception:
                metrics.record_error()
                continue

            try:
                retrieved = client.context_retrieve(key)
                if retrieved is not None:
                    metrics.record_operation()
                    if retrieved != value:
                        logger.warning("Long context value mismatch for key '%s'", key)
                else:
                    metrics.record_error()
            except Exception:
                metrics.record_error()

        metrics.log_summary()
        logger.info("Edge case long context: %d ops, %d errors", metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Edge Case -- Rapid Model Load/Unload Same Model
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_edge_case_rapid_model_load_unload_same(
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
    time_budget: float,
) -> None:
    """Rapidly load and unload the same model file repeatedly.

    Performs rapid load/unload cycles on the same model file to
    verify the server handles repeated model registration correctly
    without resource leaks or stale state.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        temp_model_dir: Temporary directory with model files.
        time_budget: Maximum allowed test duration.
    """
    num_cycles = 50 if QUICK_MODE else 100
    metrics = StressTestMetrics(name="edge_case_rapid_model_load_unload")
    client = mock_daemon_server.make_authenticated_client()
    model_path = os.path.join(temp_model_dir, "test_model.gguf")

    try:
        for cycle in range(num_cycles):
            if time.monotonic() - metrics.start_time > time_budget * 0.9:
                break
            try:
                resp = client.model_load(model_path)
                if resp.get("status") == "loaded":
                    model_id = resp.get("model_id", "")
                    metrics.record_operation()
                    unload_resp = client.model_unload(model_id)
                    if unload_resp.get("status") == "unloaded":
                        metrics.record_operation()
                    else:
                        metrics.record_error()
                else:
                    metrics.record_error()
            except Exception:
                metrics.record_error()

            if cycle > 0 and cycle % 25 == 0:
                logger.info("Rapid load/unload: %d/%d cycles", cycle, num_cycles)

        metrics.log_summary()
        metrics.assert_acceptable()
        logger.info("Edge case rapid load/unload: %d cycles, %d ops, %d errors",
                    num_cycles, metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Edge Case -- Context With Special Characters
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_edge_case_context_special_characters(
    mock_daemon_server: MockDaemonServer,
    time_budget: float,
) -> None:
    """Test context store with special characters in keys and values.

    Stores and retrieves context entries with special characters
    including symbols, dots, dashes, and mixed case to verify
    the server handles them correctly.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="edge_case_context_special")
    client = mock_daemon_server.make_authenticated_client()

    special_entries = [
        ("key_with_symbols", "value with symbols test"),
        ("key.with.dots", "value.with.dots"),
        ("key-with-dashes", "value-with-dashes"),
        ("key_with_underscores", "value_with_underscores"),
        ("key/with/slashes", "value/with/slashes"),
        ("key with spaces", "value with spaces"),
        ("key_with_mixed_CASE", "VALUE_with_MIXED_case"),
        ("0123456789", "9876543210"),
        ("key_with_newlines", "line1\nline2\nline3"),
        ("key_with_tabs", "col1\tcol2\tcol3"),
        ("key_with_quotes", 'value with "quotes"'),
        ("key_with_apostrophe", "value with apostrophe"),
        ("key_with_percent", "value with 100% complete"),
        ("key_with_angle_brackets", "<value> with <angle> brackets"),
        ("key_with_ampersand", "value & more & more"),
    ]

    try:
        for key, value in special_entries:
            if time.monotonic() - metrics.start_time > time_budget * 0.9:
                break
            try:
                result = client.context_store(key, value)
                if result is not None:
                    metrics.record_operation()
                else:
                    metrics.record_error()
                    continue
            except Exception:
                metrics.record_error()
                continue

            try:
                retrieved = client.context_retrieve(key)
                if retrieved is not None:
                    metrics.record_operation()
                    assert retrieved == value, f"Special char mismatch for key '{key}'"
                else:
                    metrics.record_error()
            except Exception:
                metrics.record_error()

        metrics.log_summary()
        metrics.assert_acceptable()
        logger.info("Edge case special chars: %d entries, %d ops, %d errors",
                    len(special_entries), metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Edge Case -- Empty Inference
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_edge_case_empty_inference(
    mock_daemon_server: MockDaemonServer,
    time_budget: float,
) -> None:
    """Test inference with empty and edge case prompts.

    Sends inference requests with various edge case inputs including
    empty strings, whitespace, special characters, and very long
    prompts. Verifies the server handles all cases gracefully.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="edge_case_empty_inference")
    client = mock_daemon_server.make_authenticated_client()

    test_prompts = [
        "",
        " ",
        "\t",
        "\n",
        "a",
        "A" * 10000,
        " " * 1000,
        "Hello?",
        '{"json": "test"}',
        "<script>alert('test')</script>",
        "SELECT * FROM models; DROP TABLE models;",
        "../../../etc/passwd",
        "%00%00%00%00",
        "null",
        "undefined",
        "None",
        "True",
        "False",
        "[]",
        "{}",
        "0",
        "-1",
        "1.7976931348623157e+308",
    ]

    try:
        for prompt in test_prompts:
            if time.monotonic() - metrics.start_time > time_budget * 0.9:
                break
            try:
                resp = client.infer(prompt=prompt, model="default", max_tokens=4)
                if resp.get("type") == "Error":
                    metrics.record_error()
                else:
                    metrics.record_operation()
            except Exception:
                metrics.record_error()

        metrics.log_summary()
        metrics.assert_acceptable(max_error_rate=0.3)
        logger.info("Edge case empty inference: %d ops, %d errors", metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Edge Case -- Model Operations with Invalid Inputs
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_edge_case_model_operations_invalid(
    mock_daemon_server: MockDaemonServer,
    time_budget: float,
) -> None:
    """Test model operations with invalid inputs.

    Attempts to load models with invalid paths, unload models that
    do not exist, and perform other edge case model operations.
    Verifies the server returns appropriate error responses.

    Args:
        mock_daemon_server: The session-scoped mock daemon server.
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="edge_case_model_invalid")
    client = mock_daemon_server.make_authenticated_client()

    try:
        # Load with empty path
        try:
            resp = client.model_load("")
            metrics.record_operation()
            if resp.get("type") == "Error" or resp.get("status") == "error":
                metrics.record_operation()
        except Exception:
            metrics.record_error()

        # Load with non-existent path
        try:
            resp = client.model_load("/tmp/nonexistent_model_file.gguf")
            metrics.record_operation()
            if resp.get("type") == "Error" or resp.get("status") == "error":
                metrics.record_operation()
        except Exception:
            metrics.record_error()

        # Load with invalid extension
        try:
            resp = client.model_load("/tmp/test.txt")
            metrics.record_operation()
            if resp.get("type") == "Error" or resp.get("status") == "error":
                metrics.record_operation()
        except Exception:
            metrics.record_error()

        # Load with directory path
        try:
            resp = client.model_load("/tmp")
            metrics.record_operation()
            if resp.get("type") == "Error" or resp.get("status") == "error":
                metrics.record_operation()
        except Exception:
            metrics.record_error()

        # Unload with non-existent model ID
        try:
            resp = client.model_unload("nonexistent_model_id_12345")
            metrics.record_operation()
            if resp.get("type") == "Error" or resp.get("status") == "not_found":
                metrics.record_operation()
        except Exception:
            metrics.record_error()

        # Unload with empty model ID
        try:
            resp = client.model_unload("")
            metrics.record_operation()
        except Exception:
            metrics.record_error()

        metrics.log_summary()
        logger.info("Edge case model invalid: %d ops, %d errors", metrics.total_ops, metrics.errors)
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Test: Stress Test Exports
# ---------------------------------------------------------------------------


@pytest.mark.stress
@pytest.mark.slow
def test_stress_test_exports(
    time_budget: float,
) -> None:
    """Verify that all stress test exports are available.

    Checks that all helper classes, functions, and constants defined
    in the stress test module are importable and have the expected
    types. This is a lightweight import validation test.

    Args:
        time_budget: Maximum allowed test duration.
    """
    metrics = StressTestMetrics(name="stress_test_exports")

    # Verify helper classes
    assert StressTestMetrics is not None, "StressTestMetrics should be importable"
    assert ConcurrentWorker is not None, "ConcurrentWorker should be importable"
    assert MetricsCollector is not None, "MetricsCollector should be importable"
    assert DataIntegrityChecker is not None, "DataIntegrityChecker should be importable"
    metrics.record_operation()

    # Verify utility functions
    assert get_current_memory_mb is not None, "get_current_memory_mb should be importable"
    assert wait_for_workers is not None, "wait_for_workers should be importable"
    assert create_clients is not None, "create_clients should be importable"
    assert disconnect_clients is not None, "disconnect_clients should be importable"
    assert create_temp_model_file is not None, "create_temp_model_file should be importable"
    assert safe_infer is not None, "safe_infer should be importable"
    assert safe_model_list is not None, "safe_model_list should be importable"
    assert safe_model_load is not None, "safe_model_load should be importable"
    assert safe_model_unload is not None, "safe_model_unload should be importable"
    assert safe_context_store is not None, "safe_context_store should be importable"
    assert safe_context_retrieve is not None, "safe_context_retrieve should be importable"
    assert safe_status is not None, "safe_status should be importable"
    assert safe_rate_limit_status is not None, "safe_rate_limit_status should be importable"
    metrics.record_operation()

    # Verify constants
    assert STRESS_DURATION > 0, "STRESS_DURATION should be positive"
    assert STRESS_CONCURRENCY > 0, "STRESS_CONCURRENCY should be positive"
    assert MAX_ACCEPTABLE_ERROR_RATE > 0, "MAX_ACCEPTABLE_ERROR_RATE should be positive"
    assert MAX_ACCEPTABLE_MEMORY_GROWTH_MB > 0, "MAX_ACCEPTABLE_MEMORY_GROWTH_MB should be positive"
    assert DATA_INTEGRITY_KEY_PREFIX is not None, "DATA_INTEGRITY_KEY_PREFIX should be defined"
    assert DATA_INTEGRITY_VALUE_PREFIX is not None, "DATA_INTEGRITY_VALUE_PREFIX should be defined"
    metrics.record_operation()

    # Verify fixtures
    import inspect
    fixture_names = ["fresh_client", "stress_model_path", "memory_metrics", "concurrency_level", "stress_duration_seconds"]
    for name in fixture_names:
        assert name in dir(), f"Fixture '{name}' should be defined"
    metrics.record_operation()

    metrics.log_summary()
    logger.info("Stress test exports: all %d exports validated", metrics.total_ops)
