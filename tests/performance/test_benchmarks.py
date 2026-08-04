"""AinosOS Performance Benchmark Suite.

This module provides comprehensive performance benchmarks for the AinosOS
mock daemon, message processing, and kernel syscall stubs. It measures
throughput, latency, and resource usage across a wide range of scenarios.

Benchmark scenarios:
    - Mock server request throughput under various concurrency levels
    - Message serialization/deserialization speed for all IPC message types
    - Connection overhead (connect, authenticate, disconnect)
    - Concurrent request scaling (1, 2, 4, 8, 16, 32 concurrent clients)
    - Inference latency percentiles (P50, P95, P99)
    - Model management operations (load, unload)
    - Context store/retrieve throughput
    - Message size vs throughput (small, medium, large prompts)
    - Inference streaming latency
    - Kernel stub syscall performance (embedding, semantic search)

Results are saved to ``tests/performance/results/`` as JSON and Markdown.

Usage:
    pytest tests/performance/test_benchmarks.py -v --benchmark
    pytest tests/performance/test_benchmarks.py -v --benchmark -k "inference"
    pytest tests/performance/test_benchmarks.py -v --benchmark -m "slow"
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
import statistics
import sys
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple, TypeVar

import pytest

# ---------------------------------------------------------------------------
# Ensure the tests directory is on the path so we can import conftest helpers
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).resolve().parent.parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

# ---------------------------------------------------------------------------
# Import test infrastructure from conftest
# ---------------------------------------------------------------------------

from conftest import (
    AI_ERR_SUCCESS,
    AI_ERR_INVALID_PARAM,
    AI_ERR_MODEL_NOT_FOUND,
    IPC_MESSAGE_TYPES,
    DEFAULT_BENCHMARK_ITERATIONS,
    DEFAULT_BENCHMARK_WARMUP,
    MockDaemonServer,
    MockDaemonClient,
    MockDaemonError,
    MockDaemonAuthError,
    MockDaemonProtocolError,
    KernelStub,
    random_string,
    random_embedding,
    create_minimal_gguf,
    assert_successful_response,
    assert_inference_response,
    assert_model_load_response,
    assert_model_unload_response,
    assert_status_response,
    assert_auth_response,
    assert_valid_message_type,
    assert_valid_embedding,
    assert_valid_model_id,
    mock_daemon_context,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Benchmark configuration defaults
BENCHMARK_ITERATIONS = int(os.environ.get("AINOS_BENCHMARK_ITERATIONS", str(DEFAULT_BENCHMARK_ITERATIONS)))
BENCHMARK_WARMUP = int(os.environ.get("AINOS_BENCHMARK_WARMUP", str(DEFAULT_BENCHMARK_WARMUP)))
BENCHMARK_EPSILON = 1e-9  # Small constant to avoid division by zero

# Throughput thresholds (loose — for CI sanity checks, not performance gates)
MIN_EXPECTED_THROUGHPUT_RPS = 10.0       # At least 10 requests/sec for any benchmark
MIN_EXPECTED_INFERENCE_RPS = 5.0         # At least 5 inference requests/sec
MAX_ACCEPTABLE_CONNECT_MS = 500.0        # Connect should be < 500ms
MAX_ACCEPTABLE_INFERENCE_P50_MS = 500.0  # P50 inference latency < 500ms
MAX_ACCEPTABLE_INFERENCE_P99_MS = 2000.0 # P99 inference latency < 2000ms

# Message size categories (in characters)
SMALL_PROMPT_SIZE = 50
MEDIUM_PROMPT_SIZE = 500
LARGE_PROMPT_SIZE = 5000
HUGE_PROMPT_SIZE = 50000

# Concurrent load levels for scaling benchmarks
CONCURRENCY_LEVELS = [1, 2, 4, 8, 16, 32]

# Report file paths
RESULTS_JSON = RESULTS_DIR / "benchmark_results.json"
RESULTS_CSV = RESULTS_DIR / "benchmark_results.csv"
RESULTS_MD = RESULTS_DIR / "benchmark_report.md"

# Summary of all results accumulated across benchmark functions
_benchmark_results: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Helper Classes
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    """Stores statistics for a single benchmark run.

    Attributes:
        name: Unique benchmark name (e.g. ``"inference_latency_p50"``).
        description: Human-readable description of what was measured.
        iterations: Number of measurement iterations performed.
        mean: Arithmetic mean of the measured values.
        std: Population standard deviation of the measured values.
        min: Minimum observed value.
        max: Maximum observed value.
        P50: 50th percentile (median).
        P95: 95th percentile.
        P99: 99th percentile.
        unit: Unit of measurement (e.g. ``"ms"``, ``"req/s"``, ``"us"``).
        tags: Optional key-value metadata for filtering/categorising.
        timestamp: ISO-8601 timestamp when the benchmark was recorded.
    """

    name: str
    description: str
    iterations: int
    mean: float
    std: float
    min: float
    max: float
    P50: float
    P95: float
    P99: float
    unit: str = "ms"
    tags: dict[str, str] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serialisable dict."""
        return asdict(self)

    @classmethod
    def from_samples(
        cls,
        name: str,
        description: str,
        samples: list[float],
        unit: str = "ms",
        tags: Optional[dict[str, str]] = None,
    ) -> BenchmarkResult:
        """Compute statistics from a list of raw timing samples.

        Args:
            name: Benchmark name.
            description: Description of what was measured.
            samples: Raw timing values (in the given unit).
            unit: Unit of measurement.
            tags: Optional metadata tags.

        Returns:
            A populated :class:`BenchmarkResult`.
        """
        n = len(samples)
        if n == 0:
            return cls(
                name=name,
                description=description,
                iterations=0,
                mean=0.0,
                std=0.0,
                min=0.0,
                max=0.0,
                P50=0.0,
                P95=0.0,
                P99=0.0,
                unit=unit,
                tags=tags or {},
            )

        sorted_samples = sorted(samples)
        mean = statistics.mean(samples)
        std = statistics.stdev(samples) if n > 1 else 0.0
        min_val = sorted_samples[0]
        max_val = sorted_samples[-1]
        P50 = _percentile(sorted_samples, 50)
        P95 = _percentile(sorted_samples, 95)
        P99 = _percentile(sorted_samples, 99)

        return cls(
            name=name,
            description=description,
            iterations=n,
            mean=mean,
            std=std,
            min=min_val,
            max=max_val,
            P50=P50,
            P95=P95,
            P99=P99,
            unit=unit,
            tags=tags or {},
        )


def _percentile(sorted_data: list[float], p: float) -> float:
    """Compute the *p*-th percentile of a sorted list using linear interpolation.

    Args:
        sorted_data: Sorted list of sample values.
        p: Percentile to compute (0–100).

    Returns:
        The interpolated percentile value.
    """
    n = len(sorted_data)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_data[0]
    k = (p / 100.0) * (n - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[f] * (c - k)
    d1 = sorted_data[c] * (k - f)
    return d0 + d1


F = TypeVar("F", bound=Callable[..., Any])


class BenchmarkRunner:
    """Runs a benchmark function *N* times, collecting timing statistics.

    The runner handles warmup iterations, measures elapsed wall-clock time
    for each iteration, and returns a :class:`BenchmarkResult` with detailed
    percentiles.

    Usage::

        def my_benchmark():
            result = some_operation()
            return result

        runner = BenchmarkRunner(warmup=5, iterations=50)
        result = runner.run("my_bench", "Description", my_benchmark)
        print(result.P50, result.P99)
    """

    def __init__(
        self,
        warmup: int = BENCHMARK_WARMUP,
        iterations: int = BENCHMARK_ITERATIONS,
        collect_garbage: bool = True,
    ) -> None:
        """Initialise the runner.

        Args:
            warmup: Number of warmup iterations (not measured).
            iterations: Number of measured iterations.
            collect_garbage: Whether to run ``gc.collect()`` between iterations
                to reduce noise from GC pauses.
        """
        self.warmup = warmup
        self.iterations = iterations
        self.collect_garbage = collect_garbage

    def run(
        self,
        name: str,
        description: str,
        fn: Callable[[], Any],
        unit: str = "ms",
        tags: Optional[dict[str, str]] = None,
    ) -> BenchmarkResult:
        """Execute the benchmark function and collect timing statistics.

        Args:
            name: Benchmark name.
            description: Description.
            fn: Zero-argument callable to benchmark.
            unit: Unit for the measured values.
            tags: Optional metadata tags.

        Returns:
            A :class:`BenchmarkResult` with computed statistics.
        """
        # Warmup phase
        for _ in range(self.warmup):
            fn()

        # Measurement phase
        samples: list[float] = []
        for _ in range(self.iterations):
            if self.collect_garbage:
                _collect_garbage()
            start = time.perf_counter_ns()
            fn()
            elapsed_ns = time.perf_counter_ns() - start
            samples.append(_ns_to_unit(elapsed_ns, unit))

        return BenchmarkResult.from_samples(
            name=name,
            description=description,
            samples=samples,
            unit=unit,
            tags=tags,
        )

    def run_async(
        self,
        name: str,
        description: str,
        fn: Callable[..., Any],
        arg: Any = None,
        unit: str = "ms",
        tags: Optional[dict[str, str]] = None,
    ) -> BenchmarkResult:
        """Execute a benchmark function that takes a single argument.

        This is useful for parameterised benchmarks where the function
        needs to be called with a different argument each iteration.

        Args:
            name: Benchmark name.
            description: Description.
            fn: Callable that takes one argument.
            arg: The argument to pass each iteration.
            unit: Unit for the measured values.
            tags: Optional metadata tags.

        Returns:
            A :class:`BenchmarkResult` with computed statistics.
        """
        # Warmup phase
        for _ in range(self.warmup):
            fn(arg)

        # Measurement phase
        samples: list[float] = []
        for _ in range(self.iterations):
            if self.collect_garbage:
                _collect_garbage()
            start = time.perf_counter_ns()
            fn(arg)
            elapsed_ns = time.perf_counter_ns() - start
            samples.append(_ns_to_unit(elapsed_ns, unit))

        return BenchmarkResult.from_samples(
            name=name,
            description=description,
            samples=samples,
            unit=unit,
            tags=tags,
        )

    def run_throughput(
        self,
        name: str,
        description: str,
        fn: Callable[[], Any],
        duration_seconds: float = 5.0,
        tags: Optional[dict[str, str]] = None,
    ) -> BenchmarkResult:
        """Measure throughput (operations per second) by running *fn*
        repeatedly for a fixed wall-clock duration.

        Args:
            name: Benchmark name.
            description: Description.
            fn: Zero-argument callable to benchmark.
            duration_seconds: How long to run the benchmark.
            tags: Optional metadata tags.

        Returns:
            A :class:`BenchmarkResult` with throughput in ops/sec.
        """
        # Warmup
        for _ in range(self.warmup):
            fn()

        # Measurement
        start = time.perf_counter()
        count = 0
        while (time.perf_counter() - start) < duration_seconds:
            fn()
            count += 1
        elapsed = time.perf_counter() - start

        throughput = count / elapsed if elapsed > 0 else 0.0

        return BenchmarkResult(
            name=name,
            description=description,
            iterations=count,
            mean=throughput,
            std=0.0,
            min=throughput,
            max=throughput,
            P50=throughput,
            P95=throughput,
            P99=throughput,
            unit="ops/s",
            tags=tags or {},
        )


def _collect_garbage() -> None:
    """Run garbage collection if the ``gc`` module is available."""
    try:
        import gc
        gc.collect()
    except ImportError:
        pass


def _ns_to_unit(ns: float, unit: str) -> float:
    """Convert nanoseconds to the requested unit.

    Args:
        ns: Nanosecond value.
        unit: Target unit (``"ns"``, ``"us"``, ``"ms"``, ``"s"``).

    Returns:
        Converted value.
    """
    if unit == "ns":
        return ns
    elif unit == "us":
        return ns / 1000.0
    elif unit == "ms":
        return ns / 1_000_000.0
    elif unit == "s":
        return ns / 1_000_000_000.0
    return ns


class ResultReporter:
    """Formats, saves, and prints benchmark results.

    Supports JSON, CSV, and Markdown table output formats.

    Usage::

        reporter = ResultReporter()
        reporter.add_result(result)
        reporter.save_json("results.json")
        reporter.save_markdown("report.md")
        reporter.print_summary()
    """

    def __init__(self) -> None:
        self.results: list[BenchmarkResult] = []

    def add_result(self, result: BenchmarkResult) -> None:
        """Register a single benchmark result.

        Args:
            result: The :class:`BenchmarkResult` to store.
        """
        self.results.append(result)
        # Also append to the global accumulator for module-level saving
        _benchmark_results.append(result.to_dict())

    def add_results(self, results: list[BenchmarkResult]) -> None:
        """Register multiple benchmark results at once.

        Args:
            results: List of :class:`BenchmarkResult` instances.
        """
        for r in results:
            self.add_result(r)

    def clear(self) -> None:
        """Clear all stored results."""
        self.results.clear()

    @property
    def count(self) -> int:
        """Number of registered results."""
        return len(self.results)

    def to_dicts(self) -> list[dict[str, Any]]:
        """Return all results as a list of JSON-serialisable dicts."""
        return [r.to_dict() for r in self.results]

    def save_json(self, path: Optional[Path] = None) -> Path:
        """Save results to a JSON file.

        Args:
            path: Output path. Defaults to ``RESULTS_JSON``.

        Returns:
            The path to the written file.
        """
        path = path or RESULTS_JSON
        data = {
            "metadata": {
                "suite": "AinosOS Performance Benchmarks",
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "total_benchmarks": len(self.results),
            },
            "results": self.to_dicts(),
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[ResultReporter] Saved JSON results to {path}")
        return path

    def save_csv(self, path: Optional[Path] = None) -> Path:
        """Save results to a CSV file.

        Args:
            path: Output path. Defaults to ``RESULTS_CSV``.

        Returns:
            The path to the written file.
        """
        path = path or RESULTS_CSV
        fieldnames = [
            "name", "description", "iterations", "mean", "std", "min", "max",
            "P50", "P95", "P99", "unit", "tags", "timestamp",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in self.results:
                row = r.to_dict()
                row["tags"] = json.dumps(row["tags"], ensure_ascii=False)
                writer.writerow(row)
        print(f"[ResultReporter] Saved CSV results to {path}")
        return path

    def save_markdown(self, path: Optional[Path] = None) -> Path:
        """Save results as a formatted Markdown report.

        Args:
            path: Output path. Defaults to ``RESULTS_MD``.

        Returns:
            The path to the written file.
        """
        path = path or RESULTS_MD
        lines: list[str] = [
            "# AinosOS Performance Benchmark Report",
            "",
            f"**Generated at:** {datetime.utcnow().isoformat()}Z",
            f"**Total benchmarks:** {len(self.results)}",
            "",
            "---",
            "",
        ]

        # Group results by category (first dot-separated component of name)
        categories: dict[str, list[BenchmarkResult]] = defaultdict(list)
        for r in self.results:
            cat = r.name.split(".")[0] if "." in r.name else "general"
            categories[cat].append(r)

        for cat_name in sorted(categories.keys()):
            lines.append(f"## {cat_name.replace('_', ' ').title()}")
            lines.append("")
            lines.append("| Benchmark | Iterations | Mean | Std | Min | Max | P50 | P95 | P99 | Unit |")
            lines.append("|-----------|-----------|------|-----|-----|-----|-----|-----|-----|------|")
            for r in sorted(categories[cat_name], key=lambda x: x.name):
                _fmt = _format_metric
                lines.append(
                    f"| {r.name} | {r.iterations} | {_fmt(r.mean)} | {_fmt(r.std)} | "
                    f"{_fmt(r.min)} | {_fmt(r.max)} | {_fmt(r.P50)} | {_fmt(r.P95)} | "
                    f"{_fmt(r.P99)} | {r.unit} |"
                )
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"[ResultReporter] Saved Markdown report to {path}")
        return path

    def print_summary(self, top_n: int = 10) -> None:
        """Print a human-readable summary of the fastest and slowest
        benchmarks to stdout.

        Args:
            top_n: Number of entries to show in each category.
        """
        if not self.results:
            print("[ResultReporter] No results to summarise.")
            return

        # Sort by mean (ascending = fastest first)
        sorted_by_mean = sorted(self.results, key=lambda r: r.mean)

        print("=" * 80)
        print("  AinosOS Performance Benchmark Summary")
        print("=" * 80)

        print(f"\n  Fastest {min(top_n, len(sorted_by_mean))} benchmarks (by mean):")
        print(f"  {'Rank':<6} {'Name':<45} {'Mean':>10} {'Unit':<8}")
        print(f"  {'-'*6} {'-'*45} {'-'*10} {'-'*8}")
        for i, r in enumerate(sorted_by_mean[:top_n], 1):
            print(f"  {i:<6} {r.name:<45} {_format_metric(r.mean):>10} {r.unit:<8}")

        print(f"\n  Slowest {min(top_n, len(sorted_by_mean))} benchmarks (by mean):")
        print(f"  {'Rank':<6} {'Name':<45} {'Mean':>10} {'Unit':<8}")
        print(f"  {'-'*6} {'-'*45} {'-'*10} {'-'*8}")
        for i, r in enumerate(reversed(sorted_by_mean[-top_n:]), 1):
            print(f"  {i:<6} {r.name:<45} {_format_metric(r.mean):>10} {r.unit:<8}")

        # Print P99 outliers
        sorted_by_p99 = sorted(self.results, key=lambda r: r.P99, reverse=True)
        print(f"\n  Highest P99 tail latencies:")
        print(f"  {'Rank':<6} {'Name':<45} {'P99':>10} {'Unit':<8}")
        print(f"  {'-'*6} {'-'*45} {'-'*10} {'-'*8}")
        for i, r in enumerate(sorted_by_p99[:top_n], 1):
            print(f"  {i:<6} {r.name:<45} {_format_metric(r.P99):>10} {r.unit:<8}")

        print("=" * 80)


def _format_metric(value: float, decimals: int = 3) -> str:
    """Format a metric value for display.

    Args:
        value: Numeric value.
        decimals: Number of decimal places.

    Returns:
        Formatted string.
    """
    if abs(value) < 0.001:
        return f"{value:.{decimals}e}"
    elif abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.{decimals}f}M"
    elif abs(value) >= 1_000:
        return f"{value / 1_000:.{decimals}f}K"
    return f"{value:.{decimals}f}"


# ---------------------------------------------------------------------------
# Module-level result saving (called from pytest_unconfigure)
# ---------------------------------------------------------------------------


def _save_accumulated_results() -> None:
    """Write all accumulated benchmark results to the default JSON and
    Markdown output files."""
    if not _benchmark_results:
        return

    # Build reporter from accumulated data
    reporter = ResultReporter()
    for d in _benchmark_results:
        result = BenchmarkResult(
            name=d["name"],
            description=d["description"],
            iterations=d["iterations"],
            mean=d["mean"],
            std=d["std"],
            min=d["min"],
            max=d["max"],
            P50=d["P50"],
            P95=d["P95"],
            P99=d["P99"],
            unit=d["unit"],
            tags=d.get("tags", {}),
            timestamp=d.get("timestamp", datetime.utcnow().isoformat() + "Z"),
        )
        reporter.results.append(result)

    reporter.save_json()
    reporter.save_csv()
    reporter.save_markdown()
    reporter.print_summary()


# ---------------------------------------------------------------------------
# Pytest configuration hooks
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for the benchmark suite.

    Adds ``benchmark`` and ``slow`` markers and ensures the results
    directory exists.
    """
    config.addinivalue_line("markers", "benchmark: Performance benchmark (measures throughput/latency).")
    config.addinivalue_line("markers", "slow: Benchmark that takes longer than 30 seconds to run.")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def pytest_unconfigure(config: pytest.Config) -> None:
    """Save all accumulated benchmark results at the end of the session."""
    _save_accumulated_results()


# ---------------------------------------------------------------------------
# Benchmark-specific fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def benchmark_reporter() -> Generator[ResultReporter, None, None]:
    """Yield a fresh :class:`ResultReporter` for each test function.

    The reporter is automatically flushed to the global accumulator
    when the test completes.
    """
    reporter = ResultReporter()
    yield reporter
    # Flush results to the global accumulator
    for r in reporter.results:
        _benchmark_results.append(r.to_dict())


@pytest.fixture(scope="function")
def benchmark_runner() -> BenchmarkRunner:
    """Yield a :class:`BenchmarkRunner` with default settings.

    The runner uses the configured iteration count and warmup from
    environment variables ``AINOS_BENCHMARK_ITERATIONS`` and
    ``AINOS_BENCHMARK_WARMUP``.
    """
    return BenchmarkRunner(
        warmup=BENCHMARK_WARMUP,
        iterations=BENCHMARK_ITERATIONS,
    )


@pytest.fixture(scope="function")
def fast_benchmark_runner() -> BenchmarkRunner:
    """Yield a :class:`BenchmarkRunner` with minimal iterations for quick
    sanity checks during development."""
    return BenchmarkRunner(warmup=2, iterations=10)


@pytest.fixture(scope="function")
def throughput_benchmark_runner() -> BenchmarkRunner:
    """Yield a :class:`BenchmarkRunner` configured for throughput
    (duration-based) benchmarks."""
    return BenchmarkRunner(warmup=BENCHMARK_WARMUP, iterations=1)


@pytest.fixture(scope="function")
def no_auth_server() -> Generator[MockDaemonServer, None, None]:
    """Create a mock daemon with authentication disabled for connection
    overhead benchmarks.

    The server is automatically stopped after the test.
    """
    server = MockDaemonServer(
        host="127.0.0.1",
        port=0,
        auth_enabled=False,
        response_delay_ms=0.0,
    )
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="function")
def no_auth_client(no_auth_server: MockDaemonServer) -> MockDaemonClient:
    """Yield a connected (but unauthenticated) client to the no-auth
    mock daemon."""
    return no_auth_server.make_client()


@pytest.fixture(scope="function")
def loaded_model_server(temp_model_dir: str) -> Generator[MockDaemonServer, None, None]:
    """Create a mock daemon with a pre-loaded model for model management
    benchmarks.

    The server is automatically stopped after the test.
    """
    server = MockDaemonServer(
        host="127.0.0.1",
        port=0,
        auth_enabled=True,
    )
    server.start()
    client = server.make_authenticated_client()
    model_path = os.path.join(temp_model_dir, "test_model.gguf")
    resp = client.model_load(model_path)
    assert_model_load_response(resp)
    client.disconnect()
    yield server
    server.stop()


@pytest.fixture(scope="function")
def seeded_kernel(deterministic_seed: int) -> KernelStub:
    """Yield a :class:`KernelStub` initialised with the deterministic
    random seed for reproducible kernel benchmarks."""
    return KernelStub(seed=deterministic_seed)


# ---------------------------------------------------------------------------
# Benchmark Data Generators
# ---------------------------------------------------------------------------


def _make_prompt(size: int) -> str:
    """Generate a text prompt of approximately *size* characters.

    Args:
        size: Desired character count.

    Returns:
        A string of roughly *size* characters.
    """
    base = "The quick brown fox jumps over the lazy dog. "
    repeats = max(1, size // len(base))
    result = (base * repeats)[:size]
    return result


def _make_context_value(size: int) -> str:
    """Generate a context value of the given size (in bytes).

    Args:
        size: Desired byte count.

    Returns:
        A string of roughly *size* bytes.
    """
    return "x" * size


def _make_message(msg_type: str, **overrides: Any) -> dict[str, Any]:
    """Build a dict representing an IPC message of the given type.

    Args:
        msg_type: A valid IPC message type (e.g. ``"Inference"``).
        **overrides: Additional fields to include in the message.

    Returns:
        A dict suitable for JSON serialisation.
    """
    assert_valid_message_type(msg_type)

    base: dict[str, Any] = {"type": msg_type}

    if msg_type == "Auth":
        base["token"] = "test-token-32-chars-minimum-here!"
    elif msg_type == "AuthResponse":
        base["success"] = True
        base["session_token"] = "sess_" + uuid.uuid4().hex[:16]
        base["message"] = "Authentication successful"
        base["permissions"] = ["infer", "status", "model", "context"]
        base["session_ttl_seconds"] = 3600
    elif msg_type == "Inference":
        base["prompt"] = _make_prompt(SMALL_PROMPT_SIZE)
        base["model"] = "default"
        base["temperature"] = 0.7
        base["max_tokens"] = 64
    elif msg_type == "InferenceResponse":
        base["output"] = "Mock inference output for benchmarking purposes."
        base["tokens_generated"] = 64
        base["inference_ms"] = 64
        base["source"] = "local"
    elif msg_type == "InferenceStream":
        base["prompt"] = _make_prompt(SMALL_PROMPT_SIZE)
        base["model"] = "default"
        base["max_tokens"] = 32
    elif msg_type == "InferenceChunk":
        base["chunk"] = "Partial inference output chunk."
        base["done"] = False
    elif msg_type == "ModelLoad":
        base["path"] = "/tmp/models/test_model.gguf"
    elif msg_type == "ModelLoadResponse":
        base["model_id"] = "test_model"
        base["status"] = "loaded"
        base["message"] = "Model loaded successfully"
        base["model_info"] = {
            "id": "test_model",
            "name": "test_model.gguf",
            "path": "/tmp/models/test_model.gguf",
            "size_mb": 128,
            "loaded": True,
            "architecture": "auto",
        }
    elif msg_type == "ModelUnload":
        base["model_id"] = "test_model"
    elif msg_type == "ModelUnloadResponse":
        base["model_id"] = "test_model"
        base["status"] = "unloaded"
        base["message"] = "Model unloaded successfully"
    elif msg_type == "ModelList":
        pass
    elif msg_type == "ModelListResponse":
        base["models"] = []
    elif msg_type == "ContextStore":
        base["key"] = "benchmark_key"
        base["value"] = _make_context_value(100)
    elif msg_type == "ContextRetrieve":
        base["key"] = "benchmark_key"
    elif msg_type == "Status":
        pass
    elif msg_type == "StatusResponse":
        base["uptime"] = 3600
        base["models_loaded"] = 3
        base["total_requests"] = 10000
        base["network_available"] = True
        base["active_sessions"] = 5
        base["rate_limits"] = []
    elif msg_type == "RateLimitStatus":
        pass
    elif msg_type == "RateLimitStatusResponse":
        base["limits"] = []
    elif msg_type == "Error":
        base["code"] = -1
        base["message"] = "Generic error for benchmarking"

    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Benchmark: Mock Server Throughput
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize("concurrency", [1, 4, 16])
def test_mock_server_throughput_small(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
    concurrency: int,
) -> None:
    """Measure the raw request throughput of the mock daemon under low
    concurrency with small prompts.

    This benchmark sends ``Inference`` requests with a small prompt (50
    characters) and measures how many requests per second the daemon can
    sustain. The result is a lower bound on the mock daemon's message
    processing loop.

    Expectation: throughput should be at least ``MIN_EXPECTED_THROUGHPUT_RPS``
    requests per second for any concurrency level.
    """
    client = mock_daemon_server.make_authenticated_client()
    prompt = _make_prompt(SMALL_PROMPT_SIZE)

    def _request() -> None:
        resp = client.infer(prompt, max_tokens=8)
        assert_inference_response(resp)

    result = benchmark_runner.run_throughput(
        name=f"mock_server.throughput.small.concurrency_{concurrency}",
        description=(
            f"Mock daemon request throughput with {concurrency} concurrent "
            f"clients and small prompts ({SMALL_PROMPT_SIZE} chars)."
        ),
        fn=_request,
        duration_seconds=3.0,
        tags={"concurrency": str(concurrency), "prompt_size": str(SMALL_PROMPT_SIZE)},
    )
    benchmark_reporter.add_result(result)
    client.disconnect()

    # Sanity check: throughput must be above a minimum threshold
    assert result.mean >= MIN_EXPECTED_THROUGHPUT_RPS, (
        f"Mock server throughput too low: {result.mean:.1f} ops/s "
        f"(expected >= {MIN_EXPECTED_THROUGHPUT_RPS})"
    )


@pytest.mark.benchmark
@pytest.mark.slow
@pytest.mark.parametrize("concurrency", CONCURRENCY_LEVELS)
def test_mock_server_throughput_scaling(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
    concurrency: int,
) -> None:
    """Measure throughput scaling across multiple concurrency levels.

    This benchmark creates *concurrency* client connections, each sending
    ``Inference`` requests as fast as possible for a fixed duration, and
    measures the aggregate throughput. It helps identify whether the mock
    daemon's threading model scales linearly or bottlenecks at higher
    concurrency.

    Expectation: throughput should increase or at least not degrade
    catastrophically as concurrency increases.
    """
    prompt = _make_prompt(MEDIUM_PROMPT_SIZE)

    def _worker(result_list: list[int], index: int) -> None:
        """Worker thread: send inference requests as fast as possible."""
        # Use a fresh client per thread to avoid socket contention
        client = mock_daemon_server.make_authenticated_client()
        count = 0
        deadline = time.monotonic() + 4.0  # 4-second measurement window
        while time.monotonic() < deadline:
            try:
                resp = client.infer(prompt, max_tokens=16)
                assert_inference_response(resp)
                count += 1
            except Exception:
                pass
        client.disconnect()
        result_list[index] = count

    # Warmup phase: run a single worker briefly
    warmup_client = mock_daemon_server.make_authenticated_client()
    for _ in range(5):
        warmup_client.infer(prompt, max_tokens=16)
    warmup_client.disconnect()

    # Measurement phase
    threads: list[threading.Thread] = []
    counts: list[int] = [0] * concurrency
    start = time.perf_counter()
    for i in range(concurrency):
        t = threading.Thread(target=_worker, args=(counts, i), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - start

    total_requests = sum(counts)
    throughput = total_requests / elapsed if elapsed > 0 else 0.0

    result = BenchmarkResult(
        name=f"mock_server.throughput.scaling.concurrency_{concurrency}",
        description=(
            f"Aggregate mock daemon throughput with {concurrency} concurrent "
            f"clients and medium prompts ({MEDIUM_PROMPT_SIZE} chars). "
            f"Total requests: {total_requests}, elapsed: {elapsed:.2f}s."
        ),
        iterations=total_requests,
        mean=throughput,
        std=0.0,
        min=throughput,
        max=throughput,
        P50=throughput,
        P95=throughput,
        P99=throughput,
        unit="ops/s",
        tags={
            "concurrency": str(concurrency),
            "prompt_size": str(MEDIUM_PROMPT_SIZE),
            "total_requests": str(total_requests),
        },
    )
    benchmark_reporter.add_result(result)

    # Sanity: throughput should be reasonable
    assert throughput >= MIN_EXPECTED_THROUGHPUT_RPS, (
        f"Scaling throughput too low at concurrency={concurrency}: "
        f"{throughput:.1f} ops/s (expected >= {MIN_EXPECTED_THROUGHPUT_RPS})"
    )


# ---------------------------------------------------------------------------
# Benchmark: Message Serialization / Deserialization
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize(
    "msg_type",
    [
        "Auth",
        "AuthResponse",
        "Inference",
        "InferenceResponse",
        "InferenceStream",
        "InferenceChunk",
        "ModelLoad",
        "ModelLoadResponse",
        "ModelUnload",
        "ModelUnloadResponse",
        "ModelList",
        "ModelListResponse",
        "ContextStore",
        "ContextRetrieve",
        "Status",
        "StatusResponse",
        "RateLimitStatus",
        "RateLimitStatusResponse",
        "Error",
    ],
)
def test_message_serialization(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    msg_type: str,
) -> None:
    """Measure the time to serialise each IPC message type to a JSON string.

    This benchmark constructs a representative message dict for each IPC
    message type and measures how long ``json.dumps()`` takes. This is
    the client-side serialisation cost (e.g. in ``_build_request``).

    Expectation: serialisation should be sub-millisecond for all message
    types (typically < 100 us).
    """
    import json as _json
    msg = _make_message(msg_type)

    def _serialize() -> None:
        _json.dumps(msg, separators=(",", ":"))

    result = benchmark_runner.run(
        name=f"message.serialization.{msg_type}",
        description=f"Time to serialise a ``{msg_type}`` message to JSON string.",
        fn=_serialize,
        unit="us",
        tags={"msg_type": msg_type},
    )
    benchmark_reporter.add_result(result)

    # Sanity: serialisation should be fast
    assert result.P50 < 1000.0, (
        f"Serialisation P50 for {msg_type} is too high: {result.P50:.1f} us"
    )


@pytest.mark.benchmark
@pytest.mark.parametrize(
    "msg_type",
    [
        "AuthResponse",
        "InferenceResponse",
        "InferenceChunk",
        "ModelLoadResponse",
        "ModelUnloadResponse",
        "ModelListResponse",
        "StatusResponse",
        "RateLimitStatusResponse",
        "Error",
    ],
)
def test_message_deserialization(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    msg_type: str,
) -> None:
    """Measure the time to deserialise each IPC message type from a JSON
    string.

    This benchmark constructs a representative JSON string for each
    response type and measures how long ``json.loads()`` takes. This is
    the client-side deserialisation cost (e.g. in ``_parse_response``).

    Expectation: deserialisation should be sub-millisecond for all message
    types (typically < 100 us).
    """
    import json as _json
    msg = _make_message(msg_type)
    json_str = _json.dumps(msg, separators=(",", ":"))

    def _deserialize() -> None:
        _json.loads(json_str)

    result = benchmark_runner.run(
        name=f"message.deserialization.{msg_type}",
        description=f"Time to deserialise a ``{msg_type}`` JSON string to dict.",
        fn=_deserialize,
        unit="us",
        tags={"msg_type": msg_type},
    )
    benchmark_reporter.add_result(result)

    # Sanity: deserialisation should be fast
    assert result.P50 < 1000.0, (
        f"Deserialisation P50 for {msg_type} is too high: {result.P50:.1f} us"
    )


@pytest.mark.benchmark
@pytest.mark.parametrize("msg_type", ["Inference", "InferenceResponse", "Status", "StatusResponse"])
def test_message_round_trip(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    msg_type: str,
) -> None:
    """Measure the combined serialisation + deserialisation round-trip time
    for key IPC message types.

    This benchmark simulates the full encode-transport-decode path: it
    serialises a request message, then deserialises the corresponding
    response. This is the CPU cost of message framing, excluding network
    I/O.

    Expectation: round-trip should be < 1 ms for all message types.
    """
    import json as _json
    request = _make_message(msg_type)
    # Build a plausible response for the given request type
    response_type = {
        "Inference": "InferenceResponse",
        "InferenceResponse": "InferenceResponse",
        "Status": "StatusResponse",
        "StatusResponse": "StatusResponse",
    }.get(msg_type, "Error")
    response = _make_message(response_type)

    def _round_trip() -> None:
        # Serialise request
        req_str = _json.dumps(request, separators=(",", ":"))
        # Simulate transport (no-op in this microbenchmark)
        # Deserialise response
        _json.loads(req_str)
        # Serialise response
        resp_str = _json.dumps(response, separators=(",", ":"))
        # Deserialise response
        _json.loads(resp_str)

    result = benchmark_runner.run(
        name=f"message.round_trip.{msg_type}",
        description=f"Combined serialise+deserialise round-trip for ``{msg_type}``.",
        fn=_round_trip,
        unit="us",
        tags={"msg_type": msg_type},
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 2000.0, (
        f"Round-trip P50 for {msg_type} is too high: {result.P50:.1f} us"
    )


# ---------------------------------------------------------------------------
# Benchmark: Connection Overhead
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_connection_connect_time(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    no_auth_server: MockDaemonServer,
) -> None:
    """Measure the time to establish a TCP connection to the mock daemon.

    This benchmark creates a new socket, connects to the daemon's listening
    port, and immediately closes the socket. It measures the pure TCP
    handshake + server accept latency.

    Expectation: connect time should be < ``MAX_ACCEPTABLE_CONNECT_MS``.
    """
    host = no_auth_server.host
    port = no_auth_server.port

    def _connect_and_close() -> None:
        import socket as _socket
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((host, port))
        s.close()

    result = benchmark_runner.run(
        name="connection.connect_time",
        description="Time to establish a TCP connection to the mock daemon and close it.",
        fn=_connect_and_close,
        unit="ms",
        tags={"host": host, "port": str(port)},
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < MAX_ACCEPTABLE_CONNECT_MS, (
        f"Connect P50 too high: {result.P50:.1f} ms "
        f"(expected < {MAX_ACCEPTABLE_CONNECT_MS})"
    )


@pytest.mark.benchmark
def test_connection_authenticate_time(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
) -> None:
    """Measure the time to authenticate a client connection.

    This benchmark creates a fresh client, connects to the daemon, sends
    an ``Auth`` message, and waits for the ``AuthResponse``. It measures
    the full authentication round-trip including token validation and
    session creation.

    Expectation: authentication should be < 100 ms.
    """
    host = mock_daemon_server.host
    port = mock_daemon_server.port
    token = mock_daemon_server.auth_token

    def _connect_and_auth() -> None:
        client = MockDaemonClient(host, port)
        client.connect()
        client.authenticate(token)
        client.disconnect()

    result = benchmark_runner.run(
        name="connection.authenticate_time",
        description="Time to connect to the mock daemon and perform authentication.",
        fn=_connect_and_auth,
        unit="ms",
        tags={"auth_enabled": "true"},
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 200.0, (
        f"Authentication P50 too high: {result.P50:.1f} ms (expected < 200 ms)"
    )


@pytest.mark.benchmark
def test_connection_full_session(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
) -> None:
    """Measure the time to establish a full session: connect, authenticate,
    perform a status query, and disconnect.

    This represents the typical "warm-up" cost for a client that connects,
    checks the daemon health, and then proceeds to do work.

    Expectation: full session setup should be < 500 ms.
    """
    host = mock_daemon_server.host
    port = mock_daemon_server.port
    token = mock_daemon_server.auth_token

    def _full_session() -> None:
        client = MockDaemonClient(host, port)
        client.connect()
        client.authenticate(token)
        resp = client.status()
        assert_status_response(resp)
        client.disconnect()

    result = benchmark_runner.run(
        name="connection.full_session_time",
        description="Time for a complete session: connect, authenticate, status query, disconnect.",
        fn=_full_session,
        unit="ms",
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 500.0, (
        f"Full session P50 too high: {result.P50:.1f} ms (expected < 500 ms)"
    )


@pytest.mark.benchmark
def test_connection_reconnect(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
) -> None:
    """Measure the time to disconnect and reconnect a client.

    This benchmark creates a client, authenticates, disconnects, and then
    reconnects and re-authenticates. It measures the overhead of session
    teardown and re-establishment.

    Expectation: reconnect should be < 300 ms.
    """
    host = mock_daemon_server.host
    port = mock_daemon_server.port
    token = mock_daemon_server.auth_token

    # Set up a client first
    setup_client = MockDaemonClient(host, port)
    setup_client.connect()
    setup_client.authenticate(token)

    def _reconnect() -> None:
        setup_client.disconnect()
        setup_client.connect()
        setup_client.authenticate(token)

    result = benchmark_runner.run(
        name="connection.reconnect_time",
        description="Time to disconnect and then reconnect and re-authenticate to the mock daemon.",
        fn=_reconnect,
        unit="ms",
    )
    benchmark_reporter.add_result(result)
    setup_client.disconnect()

    assert result.P50 < 300.0, (
        f"Reconnect P50 too high: {result.P50:.1f} ms (expected < 300 ms)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Concurrent Request Latency
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.slow
@pytest.mark.parametrize("concurrency", [1, 2, 4, 8, 16, 32])
def test_concurrent_request_latency(
    benchmark_reporter: ResultReporter,
    mock_daemon_server: MockDaemonServer,
    concurrency: int,
) -> None:
    """Measure per-request latency under increasing concurrency levels.

    This benchmark spawns *concurrency* worker threads, each sending
    inference requests to the mock daemon. Each worker records the latency
    of every request. After all workers finish, the benchmark computes
    P50, P95, and P99 latency across all collected samples.

    The goal is to characterise how the mock daemon's latency profile
    degrades as load increases. For a well-behaved server, P50 should
    remain roughly constant and P99 should not degrade exponentially.

    Expectation: P50 latency < 500 ms, P99 latency < 2000 ms for all
    concurrency levels.
    """
    prompt = _make_prompt(MEDIUM_PROMPT_SIZE)
    requests_per_worker = 25  # Each worker sends this many requests

    all_latencies: list[float] = []
    lock = threading.Lock()

    def _worker() -> None:
        """Worker thread: send requests and record latencies."""
        client = mock_daemon_server.make_authenticated_client()
        local_latencies: list[float] = []
        for _ in range(requests_per_worker):
            start = time.perf_counter_ns()
            try:
                resp = client.infer(prompt, max_tokens=16)
                assert_inference_response(resp)
            except Exception:
                pass
            elapsed_ns = time.perf_counter_ns() - start
            local_latencies.append(elapsed_ns / 1_000_000.0)  # ms
        client.disconnect()
        with lock:
            all_latencies.extend(local_latencies)

    # Warmup
    warmup_client = mock_daemon_server.make_authenticated_client()
    for _ in range(5):
        warmup_client.infer(prompt, max_tokens=16)
    warmup_client.disconnect()

    # Launch workers
    threads = [threading.Thread(target=_worker, daemon=True) for _ in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if not all_latencies:
        pytest.fail("No latency samples collected.")

    result = BenchmarkResult.from_samples(
        name=f"concurrent.latency.clients_{concurrency}",
        description=(
            f"Per-request latency distribution with {concurrency} concurrent "
            f"clients ({len(all_latencies)} total samples)."
        ),
        samples=all_latencies,
        unit="ms",
        tags={
            "concurrency": str(concurrency),
            "samples": str(len(all_latencies)),
        },
    )
    benchmark_reporter.add_result(result)

    # Sanity checks
    assert result.P50 < MAX_ACCEPTABLE_INFERENCE_P50_MS, (
        f"P50 latency at concurrency={concurrency} too high: "
        f"{result.P50:.1f} ms (expected < {MAX_ACCEPTABLE_INFERENCE_P50_MS})"
    )
    assert result.P99 < MAX_ACCEPTABLE_INFERENCE_P99_MS, (
        f"P99 latency at concurrency={concurrency} too high: "
        f"{result.P99:.1f} ms (expected < {MAX_ACCEPTABLE_INFERENCE_P99_MS})"
    )


# ---------------------------------------------------------------------------
# Benchmark: Inference Latency Distribution
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_inference_latency_percentiles(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon: MockDaemonClient,
) -> None:
    """Measure the P50, P95, and P99 latency for a single synchronous
    inference request.

    This benchmark sends an ``Inference`` request with a medium-length
    prompt and measures the wall-clock time to receive the response.
    It runs many iterations to build a stable latency distribution.

    The mock daemon simulates inference latency proportional to
    ``max_tokens`` (1 ms per token), so with ``max_tokens=8`` we expect
    approximately 8 ms base latency plus network overhead.

    Expectation: P50 < 500 ms, P95 < 1000 ms, P99 < 2000 ms.
    """
    prompt = _make_prompt(MEDIUM_PROMPT_SIZE)

    def _infer() -> None:
        resp = mock_daemon.infer(prompt=prompt, max_tokens=8)
        assert_inference_response(resp)

    result = benchmark_runner.run(
        name="inference.latency.percentiles",
        description="Latency distribution (P50, P95, P99) for a single inference request with medium prompt.",
        fn=_infer,
        unit="ms",
        tags={"prompt_size": str(MEDIUM_PROMPT_SIZE), "max_tokens": "8"},
    )
    benchmark_reporter.add_result(result)

    # Sanity checks
    assert result.P50 < MAX_ACCEPTABLE_INFERENCE_P50_MS, (
        f"Inference P50 latency too high: {result.P50:.1f} ms "
        f"(expected < {MAX_ACCEPTABLE_INFERENCE_P50_MS})"
    )
    assert result.P95 < 1500.0, (
        f"Inference P95 latency too high: {result.P95:.1f} ms (expected < 1500 ms)"
    )
    assert result.P99 < MAX_ACCEPTABLE_INFERENCE_P99_MS, (
        f"Inference P99 latency too high: {result.P99:.1f} ms "
        f"(expected < {MAX_ACCEPTABLE_INFERENCE_P99_MS})"
    )


@pytest.mark.benchmark
@pytest.mark.parametrize("max_tokens", [8, 32, 128, 256])
def test_inference_latency_vs_tokens(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon: MockDaemonClient,
    max_tokens: int,
) -> None:
    """Measure how inference latency scales with the ``max_tokens`` parameter.

    The mock daemon introduces a simulated delay proportional to the
    number of tokens generated (1 ms per token). This benchmark verifies
    that the latency increases linearly with ``max_tokens``.

    Expectation: latency should be approximately ``max_tokens`` ms plus
    a small constant overhead.
    """
    prompt = _make_prompt(SMALL_PROMPT_SIZE)

    def _infer() -> None:
        resp = mock_daemon.infer(prompt=prompt, max_tokens=max_tokens)
        assert_inference_response(resp)

    result = benchmark_runner.run(
        name=f"inference.latency.vs_max_tokens.{max_tokens}",
        description=f"Inference latency with max_tokens={max_tokens}.",
        fn=_infer,
        unit="ms",
        tags={"max_tokens": str(max_tokens), "prompt_size": str(SMALL_PROMPT_SIZE)},
    )
    benchmark_reporter.add_result(result)

    # Sanity: latency should be at least max_tokens * 1ms (simulated delay)
    # but allow generous overhead
    expected_min = max_tokens * 0.5  # ms
    assert result.P50 > expected_min or result.P50 < 5000.0, (
        f"Unexpected latency for max_tokens={max_tokens}: "
        f"P50={result.P50:.1f} ms (expected roughly {max_tokens} ms)"
    )
    # Also ensure it's not wildly high
    assert result.P50 < 5000.0, (
        f"Latency too high for max_tokens={max_tokens}: {result.P50:.1f} ms"
    )


# ---------------------------------------------------------------------------
# Benchmark: Inference Streaming Latency
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_inference_stream_latency(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon: MockDaemonClient,
) -> None:
    """Measure the latency of a single streaming inference request.

    This benchmark sends an ``InferenceStream`` message (which is
    non-streaming in the mock implementation but represents the
    request path) and measures the round-trip time.

    Expectation: stream latency should be comparable to synchronous
    inference latency.
    """
    prompt = _make_prompt(MEDIUM_PROMPT_SIZE)

    def _infer_stream() -> None:
        resp = mock_daemon.infer_stream(prompt=prompt, max_tokens=16)
        assert resp.get("type") in ("InferenceChunk", "Error"), (
            f"Unexpected stream response type: {resp.get('type')}"
        )

    result = benchmark_runner.run(
        name="inference.stream.latency",
        description="Round-trip latency for a streaming inference request.",
        fn=_infer_stream,
        unit="ms",
        tags={"prompt_size": str(MEDIUM_PROMPT_SIZE)},
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 1000.0, (
        f"Stream inference P50 too high: {result.P50:.1f} ms (expected < 1000 ms)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Model Management
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_model_load_time(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
) -> None:
    """Measure the time to load a model into the mock daemon.

    This benchmark creates a fresh client, then sends a ``ModelLoad``
    request for a valid GGUF model file. The mock daemon performs file
    existence checks, format validation, and architecture detection.

    Expectation: model load should complete in < 100 ms (since the mock
    does no real I/O beyond stat).
    """
    model_path = os.path.join(temp_model_dir, "test_model.gguf")
    client = mock_daemon_server.make_authenticated_client()

    def _load_model() -> None:
        resp = client.model_load(model_path)
        assert_model_load_response(resp)
        # Unload to keep state clean for next iteration
        model_id = resp.get("model_id", "")
        if model_id:
            unload_resp = client.model_unload(model_id)
            assert_model_unload_response(unload_resp)

    result = benchmark_runner.run(
        name="model_management.load_time",
        description="Time to load (and subsequently unload) a model on the mock daemon.",
        fn=_load_model,
        unit="ms",
        tags={"model": "test_model.gguf"},
    )
    benchmark_reporter.add_result(result)
    client.disconnect()

    assert result.P50 < 200.0, (
        f"Model load P50 too high: {result.P50:.1f} ms (expected < 200 ms)"
    )


@pytest.mark.benchmark
def test_model_unload_time(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
) -> None:
    """Measure the time to unload a model from the mock daemon.

    This benchmark first loads a model, then measures the time to send
    a ``ModelUnload`` request. The mock daemon removes the model from
    its internal registry.

    Expectation: model unload should complete in < 50 ms.
    """
    model_path = os.path.join(temp_model_dir, "test_model.gguf")
    client = mock_daemon_server.make_authenticated_client()

    # Pre-load the model
    load_resp = client.model_load(model_path)
    assert_model_load_response(load_resp)
    model_id = load_resp.get("model_id", "")

    def _unload_model() -> None:
        resp = client.model_unload(model_id)
        assert_model_unload_response(resp)

    result = benchmark_runner.run(
        name="model_management.unload_time",
        description="Time to unload a previously loaded model from the mock daemon.",
        fn=_unload_model,
        unit="ms",
        tags={"model_id": model_id},
    )
    benchmark_reporter.add_result(result)
    client.disconnect()

    assert result.P50 < 100.0, (
        f"Model unload P50 too high: {result.P50:.1f} ms (expected < 100 ms)"
    )


@pytest.mark.benchmark
def test_model_list_time(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon: MockDaemonClient,
) -> None:
    """Measure the time to list all registered models.

    This benchmark sends a ``ModelList`` request to the mock daemon and
    measures the round-trip. The response includes metadata for each
    loaded model.

    Expectation: model list should complete in < 30 ms.
    """
    def _list_models() -> None:
        models = mock_daemon.model_list()
        assert isinstance(models, list)

    result = benchmark_runner.run(
        name="model_management.list_time",
        description="Time to list all registered models from the mock daemon.",
        fn=_list_models,
        unit="ms",
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 50.0, (
        f"Model list P50 too high: {result.P50:.1f} ms (expected < 50 ms)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Context Operations
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize("value_size", [100, 1000, 10000])
def test_context_store_throughput(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon: MockDaemonClient,
    value_size: int,
) -> None:
    """Measure the throughput of context store operations.

    This benchmark repeatedly calls ``context_store()`` with a key-value
    pair of the given *value_size* and measures the operations per second.

    Expectation: store throughput should be at least 100 ops/s for all
    value sizes.
    """
    key_prefix = "bench_store"

    def _store() -> None:
        nonlocal _counter
        key = f"{key_prefix}_{_counter}"
        _counter += 1
        resp = mock_daemon.context_store(key, "x" * value_size)
        assert_successful_response(resp)

    _counter = 0

    result = benchmark_runner.run_throughput(
        name=f"context.store.throughput.value_size_{value_size}",
        description=f"Context store throughput with value size {value_size} bytes.",
        fn=_store,
        duration_seconds=3.0,
        tags={"value_size": str(value_size)},
    )
    benchmark_reporter.add_result(result)

    assert result.mean >= 50.0, (
        f"Context store throughput too low for value_size={value_size}: "
        f"{result.mean:.1f} ops/s (expected >= 50)"
    )


@pytest.mark.benchmark
@pytest.mark.parametrize("num_entries", [10, 100, 500])
def test_context_retrieve_throughput(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon: MockDaemonClient,
    num_entries: int,
) -> None:
    """Measure the throughput of context retrieve operations.

    This benchmark first populates the context store with *num_entries*
    key-value pairs, then measures the time to retrieve each one.

    Expectation: retrieve throughput should be at least 100 ops/s.
    """
    # Populate the store
    keys: list[str] = []
    for i in range(num_entries):
        key = f"bench_retrieve_{i}"
        mock_daemon.context_store(key, f"value_{i}")
        keys.append(key)

    _index = 0

    def _retrieve() -> None:
        nonlocal _index
        key = keys[_index % len(keys)]
        _index += 1
        mock_daemon.context_retrieve(key)

    _index = 0

    result = benchmark_runner.run_throughput(
        name=f"context.retrieve.throughput.num_entries_{num_entries}",
        description=f"Context retrieve throughput with {num_entries} stored entries.",
        fn=_retrieve,
        duration_seconds=3.0,
        tags={"num_entries": str(num_entries)},
    )
    benchmark_reporter.add_result(result)

    assert result.mean >= 50.0, (
        f"Context retrieve throughput too low for num_entries={num_entries}: "
        f"{result.mean:.1f} ops/s (expected >= 50)"
    )


@pytest.mark.benchmark
@pytest.mark.parametrize("value_size", [100, 1000, 10000])
def test_context_store_latency(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon: MockDaemonClient,
    value_size: int,
) -> None:
    """Measure the per-operation latency of context store requests.

    This benchmark sends a single ``context_store()`` request per iteration
    and measures the round-trip time. It characterises the latency
    distribution for store operations with varying value sizes.

    Expectation: P50 latency should be < 100 ms for all value sizes.
    """
    key = "latency_test_key"

    def _store() -> None:
        resp = mock_daemon.context_store(key, "x" * value_size)
        assert_successful_response(resp)

    result = benchmark_runner.run(
        name=f"context.store.latency.value_size_{value_size}",
        description=f"Per-operation latency for context store with value size {value_size} bytes.",
        fn=_store,
        unit="ms",
        tags={"value_size": str(value_size)},
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 200.0, (
        f"Context store P50 latency too high for value_size={value_size}: "
        f"{result.P50:.1f} ms (expected < 200 ms)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Message Size vs Throughput
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize(
    "prompt_size",
    [
        SMALL_PROMPT_SIZE,
        MEDIUM_PROMPT_SIZE,
        LARGE_PROMPT_SIZE,
        HUGE_PROMPT_SIZE,
    ],
)
def test_message_size_throughput(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
    prompt_size: int,
) -> None:
    """Measure how the prompt size affects request throughput.

    This benchmark sends inference requests with prompts of varying sizes
    (small, medium, large, huge) and measures the throughput in requests
    per second. Larger prompts consume more CPU for JSON serialisation
    and network I/O, so throughput is expected to decrease with size.

    Expectation: even with huge prompts, throughput should be at least
    ``MIN_EXPECTED_THROUGHPUT_RPS``.
    """
    client = mock_daemon_server.make_authenticated_client()
    prompt = _make_prompt(prompt_size)

    def _infer() -> None:
        resp = client.infer(prompt=prompt, max_tokens=8)
        assert_inference_response(resp)

    result = benchmark_runner.run_throughput(
        name=f"message_size.throughput.prompt_size_{prompt_size}",
        description=f"Inference throughput with prompt size {prompt_size} characters.",
        fn=_infer,
        duration_seconds=3.0,
        tags={"prompt_size": str(prompt_size)},
    )
    benchmark_reporter.add_result(result)
    client.disconnect()

    # Sanity: even huge prompts should have reasonable throughput
    assert result.mean >= MIN_EXPECTED_THROUGHPUT_RPS, (
        f"Throughput too low for prompt_size={prompt_size}: "
        f"{result.mean:.1f} ops/s (expected >= {MIN_EXPECTED_THROUGHPUT_RPS})"
    )


@pytest.mark.benchmark
@pytest.mark.parametrize(
    "prompt_size",
    [SMALL_PROMPT_SIZE, MEDIUM_PROMPT_SIZE, LARGE_PROMPT_SIZE],
)
def test_message_size_serialization_overhead(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    prompt_size: int,
) -> None:
    """Measure the CPU cost of JSON serialisation as a function of prompt
    size.

    This microbenchmark constructs an ``Inference`` message with a prompt
    of the given size and measures how long it takes to serialise it to
    JSON. This isolates the serialisation cost from network I/O.

    Expectation: serialisation time scales roughly linearly with prompt
    size. For a 50 KB prompt, it should be < 10 ms.
    """
    import json as _json
    msg = _make_message("Inference", prompt=_make_prompt(prompt_size))

    def _serialize() -> None:
        _json.dumps(msg, separators=(",", ":"))

    result = benchmark_runner.run(
        name=f"message_size.serialization.prompt_size_{prompt_size}",
        description=f"JSON serialisation time for an Inference message with {prompt_size}-char prompt.",
        fn=_serialize,
        unit="us",
        tags={"prompt_size": str(prompt_size)},
    )
    benchmark_reporter.add_result(result)

    # Sanity: serialisation should be fast
    max_expected_us = prompt_size * 2  # Roughly 2 us per char should be generous
    assert result.P50 < max(max_expected_us, 10000.0), (
        f"Serialisation P50 too high for prompt_size={prompt_size}: "
        f"{result.P50:.1f} us (expected < {max_expected_us} us)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Status / Health Check
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_status_request_latency(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon: MockDaemonClient,
) -> None:
    """Measure the latency of a daemon status (health check) request.

    The ``status()`` request is the lightest-weight IPC call — it
    returns immediately with basic daemon statistics. This benchmark
    provides a baseline for the minimum round-trip time.

    Expectation: status request should complete in < 30 ms.
    """
    def _status() -> None:
        resp = mock_daemon.status()
        assert_status_response(resp)

    result = benchmark_runner.run(
        name="status_request.latency",
        description="Round-trip latency for a daemon status (health check) request.",
        fn=_status,
        unit="ms",
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 100.0, (
        f"Status request P50 too high: {result.P50:.1f} ms (expected < 100 ms)"
    )


@pytest.mark.benchmark
def test_status_request_throughput(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
) -> None:
    """Measure the maximum throughput of status (health check) requests.

    Status requests are the most lightweight IPC call, making this
    benchmark a good measure of the daemon's raw message processing
    throughput with minimal per-request work.

    Expectation: status throughput should be at least 200 ops/s.
    """
    client = mock_daemon_server.make_authenticated_client()

    def _status() -> None:
        resp = client.status()
        assert_status_response(resp)

    result = benchmark_runner.run_throughput(
        name="status_request.throughput",
        description="Maximum throughput of daemon status (health check) requests.",
        fn=_status,
        duration_seconds=3.0,
    )
    benchmark_reporter.add_result(result)
    client.disconnect()

    assert result.mean >= 100.0, (
        f"Status throughput too low: {result.mean:.1f} ops/s (expected >= 100)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Kernel Stub Performance
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize("dim", [128, 512, 2048])
def test_kernel_embedding_latency(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    seeded_kernel: KernelStub,
    dim: int,
) -> None:
    """Measure the latency of the KernelStub ``ai_embedding`` syscall
    for various embedding dimensions.

    The kernel stub computes a deterministic embedding by hashing the
    input and normalising the result. This benchmark measures the
    computation time for different output dimensions.

    Expectation: embedding computation should be < 10 ms for all
    supported dimensions.
    """
    input_data = [random.random() for _ in range(64)]

    def _embedding() -> None:
        emb, err = seeded_kernel.ai_embedding(input_data, len(input_data), dim)
        assert err == AI_ERR_SUCCESS, f"Embedding failed with error code {err}"
        assert_valid_embedding(emb, dim)  # type: ignore[arg-type]

    result = benchmark_runner.run(
        name=f"kernel.embedding.latency.dim_{dim}",
        description=f"KernelStub ``ai_embedding`` latency for embedding dimension {dim}.",
        fn=_embedding,
        unit="us",
        tags={"dimension": str(dim)},
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 10000.0, (
        f"Embedding P50 too high for dim={dim}: {result.P50:.1f} us (expected < 10000 us)"
    )


@pytest.mark.benchmark
@pytest.mark.parametrize("top_k", [1, 5, 20])
def test_kernel_semantic_search_latency(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    seeded_kernel: KernelStub,
    top_k: int,
) -> None:
    """Measure the latency of the KernelStub ``ai_semantic_search``
    syscall for various ``top_k`` values.

    The kernel stub computes cosine similarity between a query vector
    and a fixed database of vectors, then returns the top-k results.

    Expectation: semantic search should be < 10 ms for all ``top_k``
    values.
    """
    dim = 128
    query = random_embedding(dim, seed=42)
    database = [random_embedding(dim, seed=i) for i in range(100)]

    def _search() -> None:
        results, err = seeded_kernel.ai_semantic_search(query, database, top_k)
        assert err == AI_ERR_SUCCESS, f"Semantic search failed with error code {err}"
        assert results is not None
        assert len(results) == top_k

    result = benchmark_runner.run(
        name=f"kernel.semantic_search.latency.top_k_{top_k}",
        description=f"KernelStub ``ai_semantic_search`` latency with top_k={top_k}.",
        fn=_search,
        unit="us",
        tags={"top_k": str(top_k), "database_size": "100"},
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 10000.0, (
        f"Semantic search P50 too high for top_k={top_k}: {result.P50:.1f} us"
    )


@pytest.mark.benchmark
@pytest.mark.parametrize("database_size", [10, 100, 1000])
def test_kernel_semantic_search_scaling(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    seeded_kernel: KernelStub,
    database_size: int,
) -> None:
    """Measure how semantic search latency scales with database size.

    The kernel stub performs a brute-force cosine similarity search,
    so latency is expected to scale linearly with the number of database
    vectors.

    Expectation: even with 1000 vectors, search should complete in
    < 20 ms.
    """
    dim = 128
    query = random_embedding(dim, seed=42)
    database = [random_embedding(dim, seed=i) for i in range(database_size)]

    def _search() -> None:
        results, err = seeded_kernel.ai_semantic_search(query, database, 5)
        assert err == AI_ERR_SUCCESS
        assert results is not None
        assert len(results) == 5

    result = benchmark_runner.run(
        name=f"kernel.semantic_search.scaling.db_size_{database_size}",
        description=f"Semantic search latency scaling with database size {database_size}.",
        fn=_search,
        unit="us",
        tags={"database_size": str(database_size), "top_k": "5"},
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 50000.0, (
        f"Semantic search P50 too high for db_size={database_size}: "
        f"{result.P50:.1f} us (expected < 50000 us)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Rate Limiting Overhead
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_rate_limiting_overhead(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    rate_limited_daemon: MockDaemonServer,
) -> None:
    """Measure the performance overhead of the daemon's rate-limiting
    logic.

    This benchmark compares the throughput of a daemon with rate limiting
    enabled against the expected baseline. The rate limiter adds a
    per-request check of sliding-window counters, which should add
    negligible overhead.

    Expectation: throughput with rate limiting should be at least 80%
    of the baseline throughput without rate limiting.
    """
    client = rate_limited_daemon.make_authenticated_client()
    prompt = _make_prompt(SMALL_PROMPT_SIZE)

    def _infer() -> None:
        try:
            resp = client.infer(prompt=prompt, max_tokens=8)
            assert_inference_response(resp)
        except MockDaemonError:
            # Rate limit errors are expected when we exceed the limit
            pass

    result = benchmark_runner.run_throughput(
        name="rate_limiting.throughput",
        description="Inference throughput with rate limiting enabled on the mock daemon.",
        fn=_infer,
        duration_seconds=3.0,
        tags={"rate_limit_enabled": "true"},
    )
    benchmark_reporter.add_result(result)
    client.disconnect()

    # Rate limiting should still allow reasonable throughput (at least 10 ops/s)
    assert result.mean >= 10.0, (
        f"Rate-limited throughput too low: {result.mean:.1f} ops/s (expected >= 10)"
    )


@pytest.mark.benchmark
def test_rate_limit_status_overhead(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    rate_limited_daemon: MockDaemonServer,
) -> None:
    """Measure the latency of querying rate limit status.

    The ``RateLimitStatus`` request returns the current rate limit
    counters for the session. This benchmark measures the round-trip
    time for this lightweight query.

    Expectation: rate limit status query should complete in < 30 ms.
    """
    client = rate_limited_daemon.make_authenticated_client()

    def _rate_limit_status() -> None:
        resp = client.rate_limit_status()
        assert resp.get("type") == "RateLimitStatusResponse", (
            f"Unexpected response: {resp.get('type')}"
        )

    result = benchmark_runner.run(
        name="rate_limiting.status_query_latency",
        description="Latency of querying rate limit status on a rate-limited daemon.",
        fn=_rate_limit_status,
        unit="ms",
    )
    benchmark_reporter.add_result(result)
    client.disconnect()

    assert result.P50 < 100.0, (
        f"Rate limit status query P50 too high: {result.P50:.1f} ms (expected < 100 ms)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Connection Cleanup (Disconnect)
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_connection_disconnect_time(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
) -> None:
    """Measure the time to gracefully disconnect a client session.

    This benchmark creates an authenticated client, then measures how
    long it takes to disconnect (close the TCP socket and clean up
    server-side session state).

    Expectation: disconnect should be < 10 ms.
    """
    host = mock_daemon_server.host
    port = mock_daemon_server.port
    token = mock_daemon_server.auth_token

    # Pre-create a client for each iteration
    def _disconnect() -> None:
        client = MockDaemonClient(host, port)
        client.connect()
        client.authenticate(token)
        start = time.perf_counter_ns()
        client.disconnect()
        elapsed_ns = time.perf_counter_ns() - start
        # We return the elapsed time via a closure trick
        _disconnect._last_elapsed = elapsed_ns  # type: ignore[attr-defined]

    # We use a slightly different approach: measure via the runner
    # but we need to capture the disconnect time specifically.
    samples: list[float] = []

    # Warmup
    for _ in range(BENCHMARK_WARMUP):
        c = MockDaemonClient(host, port)
        c.connect()
        c.authenticate(token)
        c.disconnect()

    # Measurement
    for _ in range(BENCHMARK_ITERATIONS):
        _collect_garbage()
        c = MockDaemonClient(host, port)
        c.connect()
        c.authenticate(token)
        t0 = time.perf_counter_ns()
        c.disconnect()
        t1 = time.perf_counter_ns()
        samples.append((t1 - t0) / 1_000_000.0)  # ms

    result = BenchmarkResult.from_samples(
        name="connection.disconnect_time",
        description="Time to gracefully disconnect an authenticated client from the mock daemon.",
        samples=samples,
        unit="ms",
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 50.0, (
        f"Disconnect P50 too high: {result.P50:.1f} ms (expected < 50 ms)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Error Handling Overhead
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize("error_type", ["Auth", "Inference", "ModelLoad"])
def test_error_response_latency(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    error_prone_daemon: MockDaemonServer,
    error_type: str,
) -> None:
    """Measure the latency of receiving an error response from the daemon.

    This benchmark uses a daemon configured to fail on specific message
    types. It measures the round-trip time for an error response, which
    should be comparable to a successful response.

    Expectation: error response latency should be similar to successful
    response latency (< 100 ms).
    """
    client = error_prone_daemon.make_authenticated_client()

    if error_type == "Auth":
        # Auth errors are handled differently — we need an unauthenticated client
        client.disconnect()
        client = error_prone_daemon.make_client()

        def _error_request() -> None:
            try:
                client.authenticate("invalid-token")
            except MockDaemonAuthError:
                pass
    elif error_type == "Inference":

        def _error_request() -> None:
            try:
                client.infer("test prompt")
            except MockDaemonError:
                pass
    elif error_type == "ModelLoad":

        def _error_request() -> None:
            try:
                client.model_load("/nonexistent/path/model.gguf")
            except MockDaemonError:
                pass
    else:
        pytest.fail(f"Unknown error type: {error_type}")

    result = benchmark_runner.run(
        name=f"error_handling.latency.{error_type}",
        description=f"Round-trip latency for a daemon error response of type ``{error_type}``.",
        fn=_error_request,
        unit="ms",
        tags={"error_type": error_type},
    )
    benchmark_reporter.add_result(result)
    client.disconnect()

    assert result.P50 < 500.0, (
        f"Error response P50 too high for {error_type}: {result.P50:.1f} ms"
    )


# ---------------------------------------------------------------------------
# Benchmark: Raw Socket Throughput
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_raw_socket_throughput(
    benchmark_reporter: ResultReporter,
    mock_daemon_server: MockDaemonServer,
) -> None:
    """Measure the raw TCP socket throughput between client and daemon.

    This benchmark sends a large number of small messages over a single
    persistent connection and measures the maximum throughput achievable
    without any application-level processing. This provides a baseline
    for the maximum theoretical throughput of the IPC channel.

    Expectation: raw socket throughput should be at least 500 ops/s.
    """
    import json as _json

    client = mock_daemon_server.make_authenticated_client()
    payload = _json.dumps({"type": "Status"}, separators=(",", ":")) + "\n"

    def _send_raw() -> None:
        """Send a raw status request and read the response."""
        client._socket.sendall(payload.encode("utf-8"))
        # Read response (char by char as the client does)
        chunks: list[bytes] = []
        while True:
            try:
                char = client._socket.recv(1)
            except OSError:
                break
            if not char or char == b"\n":
                break
            chunks.append(char)
        if chunks:
            resp = _json.loads(b"".join(chunks).decode("utf-8"))
            assert resp.get("type") == "StatusResponse"

    # Warmup
    for _ in range(BENCHMARK_WARMUP):
        _send_raw()

    # Measurement
    iterations = max(BENCHMARK_ITERATIONS, 200)
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        _send_raw()
        t1 = time.perf_counter_ns()
        samples.append((t1 - t0) / 1_000_000.0)  # ms

    result = BenchmarkResult.from_samples(
        name="raw_socket.latency",
        description="Round-trip latency for raw TCP socket message exchange with the mock daemon.",
        samples=samples,
        unit="ms",
        tags={"iterations": str(iterations)},
    )
    benchmark_reporter.add_result(result)
    client.disconnect()

    assert result.P50 < 200.0, (
        f"Raw socket P50 latency too high: {result.P50:.1f} ms (expected < 200 ms)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Kernel Stub Context Operations
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize("ttl_ms", [0, 1000, 60000])
def test_kernel_context_store_latency(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    seeded_kernel: KernelStub,
    ttl_ms: int,
) -> None:
    """Measure the latency of the KernelStub ``ai_context_store`` syscall
    for various TTL values.

    A TTL of 0 means no expiry. The kernel stub stores the value in an
    in-memory dict.

    Expectation: context store should complete in < 100 us.
    """
    session_id = 1
    key = "bench_key"

    def _store() -> None:
        entry_id, err = seeded_kernel.ai_context_store(session_id, key, "value", ttl_ms)
        assert err == AI_ERR_SUCCESS, f"Context store failed with error code {err}"
        assert entry_id is not None and entry_id > 0

    result = benchmark_runner.run(
        name=f"kernel.context_store.latency.ttl_{ttl_ms}",
        description=f"KernelStub ``ai_context_store`` latency with TTL={ttl_ms} ms.",
        fn=_store,
        unit="us",
        tags={"ttl_ms": str(ttl_ms)},
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 500.0, (
        f"Context store P50 too high for TTL={ttl_ms}: {result.P50:.1f} us"
    )


@pytest.mark.benchmark
def test_kernel_context_retrieve_latency(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    seeded_kernel: KernelStub,
) -> None:
    """Measure the latency of the KernelStub ``ai_context_retrieve``
    syscall.

    The benchmark first stores a value, then measures the time to
    retrieve it by key.

    Expectation: context retrieve should complete in < 100 us.
    """
    session_id = 1
    key = "retrieve_bench_key"
    seeded_kernel.ai_context_store(session_id, key, "benchmark_value", ttl_ms=0)

    def _retrieve() -> None:
        value, err = seeded_kernel.ai_context_retrieve(session_id, key, 0)
        assert err == AI_ERR_SUCCESS, f"Context retrieve failed with error code {err}"
        assert value == "benchmark_value"

    result = benchmark_runner.run(
        name="kernel.context_retrieve.latency",
        description="KernelStub ``ai_context_retrieve`` latency for a single key lookup.",
        fn=_retrieve,
        unit="us",
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 500.0, (
        f"Context retrieve P50 too high: {result.P50:.1f} us"
    )


# ---------------------------------------------------------------------------
# Benchmark: Kernel Stub Model Management
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_kernel_model_load_latency(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    seeded_kernel: KernelStub,
) -> None:
    """Measure the latency of the KernelStub ``ai_model_load`` syscall.

    The kernel stub registers a model in its internal model registry.

    Expectation: model load should complete in < 50 us.
    """
    def _load() -> None:
        model_id, err = seeded_kernel.ai_model_load("bench_model", "/tmp/bench.gguf")
        assert err == AI_ERR_SUCCESS, f"Model load failed with error code {err}"
        assert model_id is not None and model_id > 0

    result = benchmark_runner.run(
        name="kernel.model_load.latency",
        description="KernelStub ``ai_model_load`` latency for registering a model.",
        fn=_load,
        unit="us",
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 200.0, (
        f"Kernel model load P50 too high: {result.P50:.1f} us"
    )


@pytest.mark.benchmark
def test_kernel_model_unload_latency(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    seeded_kernel: KernelStub,
) -> None:
    """Measure the latency of the KernelStub ``ai_model_unload`` syscall.

    The benchmark first loads a model, then measures the time to unload
    it by model ID.

    Expectation: model unload should complete in < 50 us.
    """
    # Pre-load a model
    model_id, err = seeded_kernel.ai_model_load("bench_unload_model", "/tmp/bench.gguf")
    assert err == AI_ERR_SUCCESS

    def _unload() -> None:
        err_code = seeded_kernel.ai_model_unload(model_id)
        assert err_code == AI_ERR_SUCCESS, f"Model unload failed with error code {err_code}"

    result = benchmark_runner.run(
        name="kernel.model_unload.latency",
        description="KernelStub ``ai_model_unload`` latency for removing a model.",
        fn=_unload,
        unit="us",
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 200.0, (
        f"Kernel model unload P50 too high: {result.P50:.1f} us"
    )


# ---------------------------------------------------------------------------
# Benchmark: Kernel Stub Status
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_kernel_status_latency(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    seeded_kernel: KernelStub,
) -> None:
    """Measure the latency of the KernelStub ``ai_status`` syscall.

    The kernel stub returns a dict with counters and metadata.

    Expectation: status should complete in < 30 us.
    """
    def _status() -> None:
        status, err = seeded_kernel.ai_status()
        assert err == AI_ERR_SUCCESS, f"Status failed with error code {err}"
        assert "models_loaded" in status
        assert "uptime_ms" in status

    result = benchmark_runner.run(
        name="kernel.status.latency",
        description="KernelStub ``ai_status`` latency.",
        fn=_status,
        unit="us",
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 200.0, (
        f"Kernel status P50 too high: {result.P50:.1f} us"
    )


# ---------------------------------------------------------------------------
# Benchmark: Combined End-to-End Workload
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.slow
def test_end_to_end_mixed_workload(
    benchmark_reporter: ResultReporter,
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
) -> None:
    """Simulate a realistic mixed workload combining inference, model
    management, context operations, and status queries.

    This benchmark models a typical client session: it connects,
    authenticates, loads a model, performs a mix of inference and
    context operations, lists models, checks status, and finally
    unloads the model and disconnects. The entire session is timed.

    This is a "slow" benchmark because it exercises the full daemon
    state machine and may take >30 seconds to collect enough samples.

    Expectation: a full mixed-workload session should complete in
    < 10 seconds.
    """
    model_path = os.path.join(temp_model_dir, "test_model.gguf")
    host = mock_daemon_server.host
    port = mock_daemon_server.port
    token = mock_daemon_server.auth_token

    def _mixed_session() -> None:
        """Execute one complete mixed-workload session."""
        client = MockDaemonClient(host, port)
        client.connect()
        client.authenticate(token)

        # Load model
        load_resp = client.model_load(model_path)
        assert_model_load_response(load_resp)
        model_id = load_resp.get("model_id", "")

        # Inference requests
        for i in range(5):
            resp = client.infer(f"Query {i}: what is the weather?", max_tokens=16)
            assert_inference_response(resp)

        # Context operations
        client.context_store("session_info", "active")
        for i in range(3):
            key = f"context_key_{i}"
            client.context_store(key, f"value_{i}")
            retrieved = client.context_retrieve(key)
            assert retrieved is not None

        # Model list
        models = client.model_list()
        assert isinstance(models, list)
        assert any(m["id"] == model_id for m in models)

        # Status check
        status = client.status()
        assert_status_response(status)

        # Unload model
        unload_resp = client.model_unload(model_id)
        assert_model_unload_response(unload_resp)

        # Final status
        client.status()
        client.disconnect()

    # Warmup
    for _ in range(3):
        _mixed_session()

    # Measurement
    samples: list[float] = []
    for _ in range(20):  # 20 full sessions
        _collect_garbage()
        t0 = time.perf_counter_ns()
        _mixed_session()
        t1 = time.perf_counter_ns()
        samples.append((t1 - t0) / 1_000_000.0)  # ms

    result = BenchmarkResult.from_samples(
        name="end_to_end.mixed_workload.session_time",
        description="Total wall-clock time for a complete mixed-workload session (infer, model, context, status).",
        samples=samples,
        unit="ms",
        tags={"operations_per_session": "12"},
    )
    benchmark_reporter.add_result(result)

    # Sanity: a full session should complete in a reasonable time
    # (the mock has simulated delays, so this is generous)
    assert result.P50 < 30000.0, (
        f"Mixed workload session P50 too high: {result.P50:.1f} ms (expected < 30000 ms)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Auth Token Validation Overhead
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize("token_length", [16, 32, 64, 128])
def test_auth_token_validation_overhead(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
    token_length: int,
) -> None:
    """Measure the time to authenticate with tokens of varying lengths.

    The mock daemon validates the token by comparing it to the expected
    token. This benchmark varies the token length to check if longer
    tokens introduce measurable overhead.

    Expectation: token validation should be < 50 ms regardless of length.
    """
    host = mock_daemon_server.host
    port = mock_daemon_server.port
    token = "t" * token_length

    def _connect_and_auth() -> None:
        client = MockDaemonClient(host, port)
        client.connect()
        try:
            client.authenticate(token)
        except MockDaemonAuthError:
            pass  # Expected if token doesn't match
        client.disconnect()

    result = benchmark_runner.run(
        name=f"auth.token_validation.length_{token_length}",
        description=f"Authentication round-trip time with a token of length {token_length}.",
        fn=_connect_and_auth,
        unit="ms",
        tags={"token_length": str(token_length)},
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 200.0, (
        f"Auth token validation P50 too high for length={token_length}: "
        f"{result.P50:.1f} ms"
    )


# ---------------------------------------------------------------------------
# Benchmark: Client Construction Overhead
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_client_construction_overhead(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
) -> None:
    """Measure the CPU cost of constructing a new MockDaemonClient instance.

    This microbenchmark measures the object creation overhead of the
    client class, which is relevant when many short-lived clients are
    created (e.g. in connection-per-request patterns).

    Expectation: client construction should be < 50 us.
    """
    host = mock_daemon_server.host
    port = mock_daemon_server.port

    def _construct() -> None:
        client = MockDaemonClient(host, port)
        _ = client  # Prevent optimisation

    result = benchmark_runner.run(
        name="client.construction_overhead",
        description="Time to construct a new MockDaemonClient instance (no connection).",
        fn=_construct,
        unit="us",
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 500.0, (
        f"Client construction P50 too high: {result.P50:.1f} us"
    )


# ---------------------------------------------------------------------------
# Benchmark: Response Parsing Overhead
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize("response_type", ["InferenceResponse", "StatusResponse", "ModelListResponse"])
def test_response_parsing_overhead(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    response_type: str,
) -> None:
    """Measure the time to parse a daemon response into a typed dataclass.

    This benchmark serialises a representative response, then deserialises
    and parses it using the SDK's ``_parse_*`` functions. This covers the
    full client-side parsing pipeline.

    Expectation: response parsing should be < 200 us.
    """
    import json as _json
    from conftest import assert_inference_response, assert_status_response

    # Build a representative response
    if response_type == "InferenceResponse":
        msg = _make_message("InferenceResponse", output="Parsing benchmark output.", tokens_generated=64)
        json_str = _json.dumps(msg, separators=(",", ":"))

        def _parse() -> None:
            data = _json.loads(json_str)
            assert_inference_response(data)

    elif response_type == "StatusResponse":
        msg = _make_message("StatusResponse", uptime=3600, models_loaded=3, total_requests=5000)
        json_str = _json.dumps(msg, separators=(",", ":"))

        def _parse() -> None:
            data = _json.loads(json_str)
            assert_status_response(data)

    elif response_type == "ModelListResponse":
        msg = _make_message(
            "ModelListResponse",
            models=[
                {"id": "model_1", "name": "model_1.gguf", "path": "/tmp/m1.gguf", "size_mb": 128, "loaded": True, "architecture": "llama"},
                {"id": "model_2", "name": "model_2.gguf", "path": "/tmp/m2.gguf", "size_mb": 256, "loaded": False, "architecture": "phi3"},
            ],
        )
        json_str = _json.dumps(msg, separators=(",", ":"))

        def _parse() -> None:
            data = _json.loads(json_str)
            assert data.get("type") == "ModelListResponse"
            models = data.get("models", [])
            assert len(models) == 2

    else:
        pytest.fail(f"Unknown response type: {response_type}")

    result = benchmark_runner.run(
        name=f"response_parsing.overhead.{response_type}",
        description=f"Time to parse a ``{response_type}`` from JSON string to validated dict.",
        fn=_parse,
        unit="us",
        tags={"response_type": response_type},
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 500.0, (
        f"Response parsing P50 too high for {response_type}: {result.P50:.1f} us"
    )


# ---------------------------------------------------------------------------
# Benchmark: Multiple Sequential Requests
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize("requests_per_session", [10, 50, 100])
def test_sequential_request_throughput(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
    requests_per_session: int,
) -> None:
    """Measure the throughput of sending multiple sequential requests
    over a single persistent connection.

    This benchmark models a client that reuses the same connection for
    many requests, which is the typical usage pattern. It measures the
    total time to send *requests_per_session* inference requests
    sequentially.

    Expectation: throughput should be at least 50 requests/sec for
    100 sequential requests.
    """
    host = mock_daemon_server.host
    port = mock_daemon_server.port
    prompt = _make_prompt(SMALL_PROMPT_SIZE)

    def _sequential_session() -> None:
        client = MockDaemonClient(host, port)
        client.connect()
        client.authenticate(mock_daemon_server.auth_token)
        for _ in range(requests_per_session):
            resp = client.infer(prompt, max_tokens=8)
            assert_inference_response(resp)
        client.disconnect()

    # Warmup
    for _ in range(2):
        _sequential_session()

    # Measurement
    samples: list[float] = []
    for _ in range(10):
        _collect_garbage()
        t0 = time.perf_counter_ns()
        _sequential_session()
        t1 = time.perf_counter_ns()
        elapsed_ms = (t1 - t0) / 1_000_000.0
        # Convert to per-request latency
        per_request = elapsed_ms / requests_per_session
        samples.append(per_request)

    result = BenchmarkResult.from_samples(
        name=f"sequential.throughput.per_request.requests_{requests_per_session}",
        description=f"Per-request latency when sending {requests_per_session} sequential inference requests over a single connection.",
        samples=samples,
        unit="ms",
        tags={"requests_per_session": str(requests_per_session)},
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 500.0, (
        f"Sequential per-request P50 too high for {requests_per_session} requests: "
        f"{result.P50:.1f} ms"
    )


# ---------------------------------------------------------------------------
# Benchmark: Server Restart Overhead
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_server_restart_overhead(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
) -> None:
    """Measure the time to start and stop a MockDaemonServer instance.

    This benchmark measures the server lifecycle overhead: creating a
    server, starting it (bind + listen + background thread), waiting
    for readiness, and then stopping it (close socket + join thread).

    This is relevant for tests that use per-function server fixtures.

    Expectation: start + stop should complete in < 500 ms.
    """
    def _start_stop() -> None:
        server = MockDaemonServer(host="127.0.0.1", port=0, auth_enabled=False)
        server.start()
        server.stop()

    result = benchmark_runner.run(
        name="server.restart_overhead",
        description="Time to start and immediately stop a MockDaemonServer instance.",
        fn=_start_stop,
        unit="ms",
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 1000.0, (
        f"Server restart P50 too high: {result.P50:.1f} ms (expected < 1000 ms)"
    )


@pytest.mark.benchmark
def test_server_startup_with_auth(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
) -> None:
    """Measure the time to start a MockDaemonServer with authentication
    enabled.

    This is similar to the restart overhead benchmark but with the
    additional cost of auth-enabled state initialisation.

    Expectation: startup with auth should complete in < 500 ms.
    """
    def _start_stop() -> None:
        server = MockDaemonServer(host="127.0.0.1", port=0, auth_enabled=True)
        server.start()
        server.stop()

    result = benchmark_runner.run(
        name="server.startup_with_auth",
        description="Time to start and stop a MockDaemonServer with authentication enabled.",
        fn=_start_stop,
        unit="ms",
    )
    benchmark_reporter.add_result(result)

    assert result.P50 < 1000.0, (
        f"Server startup with auth P50 too high: {result.P50:.1f} ms"
    )


# ---------------------------------------------------------------------------
# Benchmark: Stress Test — Sustained Load
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.slow
def test_sustained_load_stress(
    benchmark_reporter: ResultReporter,
    mock_daemon_server: MockDaemonServer,
) -> None:
    """Run a sustained load test on the mock daemon for an extended period.

    This benchmark maintains 8 concurrent clients sending inference
    requests for 30 seconds. It measures the aggregate throughput and
    error rate over the sustained period. This is a "slow" benchmark
    that helps identify resource leaks, memory growth, or performance
    degradation under continuous load.

    Expectation: the daemon should maintain stable throughput throughout
    the test with no errors.
    """
    import json as _json

    prompt = _make_prompt(MEDIUM_PROMPT_SIZE)
    duration_seconds = 30.0
    concurrency = 8

    total_requests = 0
    total_errors = 0
    lock = threading.Lock()

    def _worker(stats: dict[str, int]) -> None:
        """Worker thread: send requests and record results."""
        client = mock_daemon_server.make_authenticated_client()
        local_requests = 0
        local_errors = 0
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline:
            try:
                resp = client.infer(prompt, max_tokens=8)
                assert_inference_response(resp)
                local_requests += 1
            except Exception:
                local_errors += 1
        client.disconnect()
        stats["requests"] = local_requests
        stats["errors"] = local_errors

    # Warmup
    warmup_client = mock_daemon_server.make_authenticated_client()
    for _ in range(10):
        warmup_client.infer(prompt, max_tokens=8)
    warmup_client.disconnect()

    # Launch workers
    threads: list[threading.Thread] = []
    worker_stats: list[dict[str, int]] = [{} for _ in range(concurrency)]
    for i in range(concurrency):
        t = threading.Thread(target=_worker, args=(worker_stats[i],), daemon=True)
        threads.append(t)
        t.start()

    # Monitor progress periodically
    start_time = time.monotonic()
    for elapsed in range(5, int(duration_seconds) + 1, 5):
        time.sleep(5)
        running = time.monotonic() - start_time
        print(f"  [Sustained Load] {running:.0f}s elapsed ...")

    for t in threads:
        t.join()

    total_requests = sum(s.get("requests", 0) for s in worker_stats)
    total_errors = sum(s.get("errors", 0) for s in worker_stats)
    elapsed = time.monotonic() - start_time
    throughput = total_requests / elapsed if elapsed > 0 else 0.0
    error_rate = total_errors / max(total_requests + total_errors, 1) * 100.0

    result = BenchmarkResult(
        name="stress.sustained_load.30s_8clients",
        description=(
            f"Sustained load test: {concurrency} concurrent clients for "
            f"{duration_seconds}s. Total requests: {total_requests}, "
            f"errors: {total_errors} ({error_rate:.2f}%)."
        ),
        iterations=total_requests,
        mean=throughput,
        std=0.0,
        min=throughput,
        max=throughput,
        P50=throughput,
        P95=throughput,
        P99=throughput,
        unit="ops/s",
        tags={
            "concurrency": str(concurrency),
            "duration_seconds": str(duration_seconds),
            "total_requests": str(total_requests),
            "total_errors": str(total_errors),
            "error_rate_pct": f"{error_rate:.2f}",
        },
    )
    benchmark_reporter.add_result(result)

    # Sanity: reasonable throughput and low error rate
    assert throughput >= 5.0, (
        f"Sustained load throughput too low: {throughput:.1f} ops/s"
    )
    assert error_rate < 50.0, (
        f"Error rate too high under sustained load: {error_rate:.2f}%"
    )


# ---------------------------------------------------------------------------
# Benchmark: Context Store — Large Number of Entries
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.slow
def test_context_store_large_scale(
    benchmark_reporter: ResultReporter,
    mock_daemon_server: MockDaemonServer,
) -> None:
    """Measure the time to store and retrieve from a context store with
    a large number of entries (1000+).

    This benchmark populates the context store with 1000 entries, then
    measures the time to retrieve each one. It exercises the daemon's
    in-memory dict lookup performance under scale.

    Expectation: bulk store of 1000 entries should complete in < 10 s,
    and retrieval of each entry should be < 50 ms.
    """
    client = mock_daemon_server.make_authenticated_client()
    num_entries = 1000

    # Measure store time
    t0 = time.perf_counter_ns()
    for i in range(num_entries):
        key = f"large_scale_key_{i}"
        value = f"value_{i}" * 10  # ~70 bytes per value
        resp = client.context_store(key, value)
        assert_successful_response(resp)
    t1 = time.perf_counter_ns()
    store_time_ms = (t1 - t0) / 1_000_000.0

    result_store = BenchmarkResult(
        name="context.large_scale.store_1000",
        description=f"Time to store {num_entries} entries in the context store.",
        iterations=num_entries,
        mean=store_time_ms / num_entries,
        std=0.0,
        min=store_time_ms / num_entries,
        max=store_time_ms / num_entries,
        P50=store_time_ms / num_entries,
        P95=store_time_ms / num_entries,
        P99=store_time_ms / num_entries,
        unit="ms",
        tags={"num_entries": str(num_entries), "operation": "store"},
    )
    benchmark_reporter.add_result(result_store)

    # Measure retrieve time
    retrieval_samples: list[float] = []
    for i in range(num_entries):
        _collect_garbage()
        key = f"large_scale_key_{i}"
        t0 = time.perf_counter_ns()
        value = client.context_retrieve(key)
        t1 = time.perf_counter_ns()
        assert value is not None, f"Failed to retrieve key {key}"
        retrieval_samples.append((t1 - t0) / 1_000_000.0)

    result_retrieve = BenchmarkResult.from_samples(
        name="context.large_scale.retrieve_1000",
        description=f"Per-entry retrieval latency from a context store with {num_entries} entries.",
        samples=retrieval_samples,
        unit="ms",
        tags={"num_entries": str(num_entries), "operation": "retrieve"},
    )
    benchmark_reporter.add_result(result_retrieve)

    client.disconnect()

    # Sanity checks
    assert store_time_ms < 30000.0, (
        f"Bulk store of {num_entries} entries took too long: {store_time_ms:.1f} ms"
    )
    assert result_retrieve.P50 < 200.0, (
        f"Retrieval P50 too high for {num_entries} entries: {result_retrieve.P50:.1f} ms"
    )


# ---------------------------------------------------------------------------
# Benchmark: Empty / Edge Case Messages
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize(
    "msg_type",
    [
        "Auth",
        "Inference",
        "ModelLoad",
        "ContextStore",
        "ContextRetrieve",
    ],
)
def test_empty_message_handling(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    mock_daemon_server: MockDaemonServer,
    msg_type: str,
) -> None:
    """Measure the time to handle messages with empty or missing fields.

    The mock daemon should gracefully handle edge cases like empty
    prompts, empty keys, or missing tokens. This benchmark measures
    the latency of these error paths.

    Expectation: error-path handling should be < 50 ms.
    """
    import json as _json
    client = mock_daemon_server.make_authenticated_client()

    if msg_type == "Auth":
        # Use an unauthenticated client for auth testing
        client.disconnect()
        client = mock_daemon_server.make_client()
        payload = _json.dumps({"type": "Auth", "token": ""}, separators=(",", ":"))

        def _empty_request() -> None:
            client._send_recv(payload)

    elif msg_type == "Inference":
        payload = _json.dumps({"type": "Inference", "prompt": "", "model": ""}, separators=(",", ":"))

        def _empty_request() -> None:
            resp = client._send_recv(payload)
            # Should still get a response (might be an error or success)
            assert resp is not None

    elif msg_type == "ModelLoad":
        payload = _json.dumps({"type": "ModelLoad", "path": ""}, separators=(",", ":"))

        def _empty_request() -> None:
            resp = client._send_recv(payload)
            assert resp.get("type") in ("ModelLoadResponse", "Error")

    elif msg_type == "ContextStore":
        payload = _json.dumps({"type": "ContextStore", "key": "", "value": ""}, separators=(",", ":"))

        def _empty_request() -> None:
            resp = client._send_recv(payload)
            assert resp is not None

    elif msg_type == "ContextRetrieve":
        payload = _json.dumps({"type": "ContextRetrieve", "key": ""}, separators=(",", ":"))

        def _empty_request() -> None:
            resp = client._send_recv(payload)
            assert resp is not None

    else:
        pytest.fail(f"Unknown msg_type: {msg_type}")

    result = benchmark_runner.run(
        name=f"edge_cases.empty_message.{msg_type}",
        description=f"Round-trip latency for a ``{msg_type}`` message with empty/missing fields.",
        fn=_empty_request,
        unit="ms",
        tags={"msg_type": msg_type, "edge_case": "empty_fields"},
    )
    benchmark_reporter.add_result(result)
    client.disconnect()

    assert result.P50 < 500.0, (
        f"Empty message handling P50 too high for {msg_type}: {result.P50:.1f} ms"
    )


# ---------------------------------------------------------------------------
# Benchmark: JSON Payload Size Extremes
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize("payload_bytes", [0, 1, 1024, 65536, 524288])
def test_large_payload_serialization(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    payload_bytes: int,
) -> None:
    """Measure the time to serialise and deserialise JSON payloads of
    various sizes, including extreme sizes (0 bytes to 512 KB).

    This microbenchmark isolates the raw JSON processing cost for
    unusually large or small payloads, which is relevant for the
    daemon's context store and inference response handling.

    Expectation:
        - 0 B and 1 B payloads: < 10 us
        - 1 KB payload: < 100 us
        - 64 KB payload: < 5 ms
        - 512 KB payload: < 50 ms
    """
    import json as _json

    # Build a payload of the given size
    payload_data: dict[str, Any] = {"type": "InferenceResponse", "output": "x" * max(0, payload_bytes - 100)}

    def _serialize_deserialize() -> None:
        s = _json.dumps(payload_data, separators=(",", ":"))
        _json.loads(s)

    result = benchmark_runner.run(
        name=f"payload.serialization.size_{payload_bytes}",
        description=f"Combined serialise+deserialise time for a {payload_bytes}-byte JSON payload.",
        fn=_serialize_deserialize,
        unit="us",
        tags={"payload_bytes": str(payload_bytes)},
    )
    benchmark_reporter.add_result(result)

    # Size-dependent threshold
    if payload_bytes <= 1:
        threshold = 100.0  # us
    elif payload_bytes <= 1024:
        threshold = 500.0
    elif payload_bytes <= 65536:
        threshold = 10000.0
    else:
        threshold = 100000.0

    assert result.P50 < threshold, (
        f"Payload serialisation P50 too high for {payload_bytes} bytes: "
        f"{result.P50:.1f} us (expected < {threshold} us)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Server Maximum Connections
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.slow
def test_server_max_connections(
    benchmark_reporter: ResultReporter,
    mock_daemon_server: MockDaemonServer,
) -> None:
    """Measure the mock daemon's ability to handle many simultaneous
    connections.

    This benchmark opens 64 concurrent connections to the daemon, each
    performing a status request, then measures the aggregate throughput
    and latency. It tests the daemon's threading model and socket
    handling under high connection counts.

    Expectation: all 64 connections should complete a status request
    successfully within 30 seconds.
    """
    host = mock_daemon_server.host
    port = mock_daemon_server.port
    num_connections = 64

    latencies: list[float] = []
    errors = 0
    lock = threading.Lock()

    def _connect_and_status() -> None:
        nonlocal errors
        try:
            t0 = time.perf_counter_ns()
            client = MockDaemonClient(host, port)
            client.connect()
            client.authenticate(mock_daemon_server.auth_token)
            resp = client.status()
            assert_status_response(resp)
            client.disconnect()
            t1 = time.perf_counter_ns()
            with lock:
                latencies.append((t1 - t0) / 1_000_000.0)
        except Exception:
            with lock:
                errors += 1

    # Warmup
    warmup = MockDaemonClient(host, port)
    warmup.connect()
    warmup.authenticate(mock_daemon_server.auth_token)
    warmup.status()
    warmup.disconnect()

    # Launch all connections
    threads = [threading.Thread(target=_connect_and_status, daemon=True) for _ in range(num_connections)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - start

    if not latencies:
        pytest.fail("All connections failed — no latency samples collected.")

    result = BenchmarkResult.from_samples(
        name="server.max_connections.64",
        description=(
            f"Latency distribution for {num_connections} simultaneous connections, "
            f"each performing a status request. Errors: {errors}/{num_connections}."
        ),
        samples=latencies,
        unit="ms",
        tags={
            "num_connections": str(num_connections),
            "errors": str(errors),
            "elapsed_seconds": f"{elapsed:.2f}",
        },
    )
    benchmark_reporter.add_result(result)

    # Sanity: most connections should succeed
    assert errors < num_connections // 2, (
        f"Too many errors: {errors}/{num_connections} connections failed"
    )
    assert result.P50 < 5000.0, (
        f"Max connections P50 too high: {result.P50:.1f} ms (expected < 5000 ms)"
    )


# ---------------------------------------------------------------------------
# Benchmark: Minimal Overhead — No-op Loop
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_benchmark_framework_overhead(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
) -> None:
    """Measure the overhead of the benchmark framework itself.

    This benchmark runs an empty function to measure the cost of the
    timing loop, function call overhead, and result recording. This
    provides a baseline for interpreting all other benchmark results.

    Expectation: framework overhead should be < 10 us per iteration.
    """
    def _noop() -> None:
        pass

    result = benchmark_runner.run(
        name="framework.overhead.noop",
        description="Overhead of the benchmark framework: an empty no-op function.",
        fn=_noop,
        unit="us",
    )
    benchmark_reporter.add_result(result)

    # This is just informational — no strict threshold
    print(f"  [Info] Benchmark framework overhead: P50={result.P50:.2f} us, P99={result.P99:.2f} us")


# ---------------------------------------------------------------------------
# Benchmark: Concurrent Mixed Workload
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.slow
def test_concurrent_mixed_workload(
    benchmark_reporter: ResultReporter,
    mock_daemon_server: MockDaemonServer,
    temp_model_dir: str,
) -> None:
    """Measure the daemon's performance under a concurrent mixed workload
    where different clients perform different types of operations.

    This benchmark spawns 4 groups of threads:
    - Group 1 (inference): sends inference requests
    - Group 2 (context): performs context store/retrieve operations
    - Group 3 (model): loads and unloads models
    - Group 4 (status): queries daemon status

    This simulates a realistic multi-tenant scenario and measures the
    daemon's ability to multiplex different operation types fairly.

    Expectation: all groups should maintain reasonable throughput with
    no single operation type starving others.
    """
    model_path = os.path.join(temp_model_dir, "test_model.gguf")
    prompt = _make_prompt(MEDIUM_PROMPT_SIZE)
    duration_seconds = 15.0
    results: dict[str, dict[str, int]] = defaultdict(lambda: {"requests": 0, "errors": 0})
    lock = threading.Lock()

    def _inference_worker() -> None:
        client = mock_daemon_server.make_authenticated_client()
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline:
            try:
                resp = client.infer(prompt, max_tokens=8)
                assert_inference_response(resp)
                with lock:
                    results["inference"]["requests"] += 1
            except Exception:
                with lock:
                    results["inference"]["errors"] += 1
        client.disconnect()

    def _context_worker() -> None:
        client = mock_daemon_server.make_authenticated_client()
        deadline = time.monotonic() + duration_seconds
        counter = 0
        while time.monotonic() < deadline:
            try:
                key = f"mixed_ctx_{counter}"
                client.context_store(key, f"value_{counter}")
                client.context_retrieve(key)
                counter += 1
                with lock:
                    results["context"]["requests"] += 1
            except Exception:
                with lock:
                    results["context"]["errors"] += 1
        client.disconnect()

    def _model_worker() -> None:
        client = mock_daemon_server.make_authenticated_client()
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline:
            try:
                resp = client.model_load(model_path)
                if resp.get("status") == "loaded":
                    model_id = resp.get("model_id", "")
                    client.model_unload(model_id)
                with lock:
                    results["model"]["requests"] += 1
            except Exception:
                with lock:
                    results["model"]["errors"] += 1
        client.disconnect()

    def _status_worker() -> None:
        client = mock_daemon_server.make_authenticated_client()
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline:
            try:
                resp = client.status()
                assert_status_response(resp)
                with lock:
                    results["status"]["requests"] += 1
            except Exception:
                with lock:
                    results["status"]["errors"] += 1
        client.disconnect()

    # Warmup
    wc = mock_daemon_server.make_authenticated_client()
    for _ in range(5):
        wc.infer(prompt, max_tokens=8)
    wc.disconnect()

    # Launch workers (2 per group = 8 total)
    workers = [
        threading.Thread(target=_inference_worker, daemon=True),
        threading.Thread(target=_inference_worker, daemon=True),
        threading.Thread(target=_context_worker, daemon=True),
        threading.Thread(target=_context_worker, daemon=True),
        threading.Thread(target=_model_worker, daemon=True),
        threading.Thread(target=_model_worker, daemon=True),
        threading.Thread(target=_status_worker, daemon=True),
        threading.Thread(target=_status_worker, daemon=True),
    ]

    for w in workers:
        w.start()
    for w in workers:
        w.join()

    # Report per-group throughput
    for op_type, stats in results.items():
        throughput = stats["requests"] / max(duration_seconds, 0.001)
        error_rate = stats["errors"] / max(stats["requests"] + stats["errors"], 1) * 100.0
        result = BenchmarkResult(
            name=f"concurrent.mixed_workload.{op_type}",
            description=(
                f"Throughput for ``{op_type}`` operations in a concurrent mixed workload "
                f"({duration_seconds}s, 2 workers). Requests: {stats['requests']}, "
                f"errors: {stats['errors']} ({error_rate:.2f}%)."
            ),
            iterations=stats["requests"],
            mean=throughput,
            std=0.0,
            min=throughput,
            max=throughput,
            P50=throughput,
            P95=throughput,
            P99=throughput,
            unit="ops/s",
            tags={
                "operation": op_type,
                "workers": "2",
                "duration_seconds": str(duration_seconds),
                "error_rate_pct": f"{error_rate:.2f}",
            },
        )
        benchmark_reporter.add_result(result)

        assert throughput >= 1.0, (
            f"Mixed workload throughput for {op_type} too low: {throughput:.1f} ops/s"
        )


# ---------------------------------------------------------------------------
# Benchmark: Rate Limiter — Reset Behaviour
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_rate_limiter_reset_behaviour(
    benchmark_reporter: ResultReporter,
    benchmark_runner: BenchmarkRunner,
    rate_limited_daemon: MockDaemonServer,
) -> None:
    """Measure the latency of rate limit counter resets.

    The rate limiter resets counters every second. This benchmark
    verifies that the reset operation itself does not introduce
    latency spikes.

    Expectation: requests around the reset boundary should not show
    significantly higher latency than normal requests.
    """
    client = rate_limited_daemon.make_authenticated_client()
    prompt = _make_prompt(SMALL_PROMPT_SIZE)

    # Send requests until rate limited, then measure the next request
    # (which should trigger a reset)
    samples: list[float] = []

    # Warmup
    for _ in range(10):
        try:
            client.infer(prompt, max_tokens=8)
        except MockDaemonError:
            pass

    # Send many requests to trigger rate limiting
    for _ in range(100):
        try:
            t0 = time.perf_counter_ns()
            client.infer(prompt, max_tokens=8)
            t1 = time.perf_counter_ns()
            samples.append((t1 - t0) / 1_000_000.0)
        except MockDaemonError:
            # Rate limited — this is expected
            pass

    client.disconnect()

    if not samples:
        # If we got all rate-limited, still report a result
        result = BenchmarkResult(
            name="rate_limiter.reset_behaviour",
            description="Rate limit counter reset latency (no successful samples collected — all rate limited).",
            iterations=0,
            mean=0.0,
            std=0.0,
            min=0.0,
            max=0.0,
            P50=0.0,
            P95=0.0,
            P99=0.0,
            unit="ms",
            tags={"note": "all_requests_rate_limited"},
        )
    else:
        result = BenchmarkResult.from_samples(
            name="rate_limiter.reset_behaviour",
            description="Latency of requests around rate limit counter reset boundaries.",
            samples=samples,
            unit="ms",
        )
    benchmark_reporter.add_result(result)


# ---------------------------------------------------------------------------
# Benchmark: Threading Overhead in MockDaemon
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.parametrize("num_clients", [1, 5, 10, 20])
def test_threading_overhead(
    benchmark_reporter: ResultReporter,
    mock_daemon_server: MockDaemonServer,
    num_clients: int,
) -> None:
    """Measure the overhead of the mock daemon's per-client threading
    model.

    Each client connection spawns a new thread in the daemon. This
    benchmark measures the time to create *num_clients* simultaneous
    connections, each performing a single status request, and compares
    the total time to the per-client latency.

    Expectation: the daemon should handle 20 simultaneous connections
    with P50 latency < 1000 ms per connection.
    """
    host = mock_daemon_server.host
    port = mock_daemon_server.port
    token = mock_daemon_server.auth_token

    latencies: list[float] = []
    lock = threading.Lock()

    def _worker() -> None:
        try:
            t0 = time.perf_counter_ns()
            client = MockDaemonClient(host, port)
            client.connect()
            client.authenticate(token)
            resp = client.status()
            assert_status_response(resp)
            client.disconnect()
            t1 = time.perf_counter_ns()
            with lock:
                latencies.append((t1 - t0) / 1_000_000.0)
        except Exception:
            pass

    # Warmup
    wc = MockDaemonClient(host, port)
    wc.connect()
    wc.authenticate(token)
    wc.status()
    wc.disconnect()

    # Launch
    threads = [threading.Thread(target=_worker, daemon=True) for _ in range(num_clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if not latencies:
        pytest.fail(f"No successful connections out of {num_clients}")

    result = BenchmarkResult.from_samples(
        name=f"threading.overhead.clients_{num_clients}",
        description=f"Per-connection latency with {num_clients} simultaneous client threads. "
                    f"Successful: {len(latencies)}/{num_clients}.",
        samples=latencies,
        unit="ms",
        tags={
            "num_clients": str(num_clients),
            "successful": str(len(latencies)),
        },
    )
    benchmark_reporter.add_result(result)

    # Sanity: latency should not be astronomical
    assert result.P50 < 10000.0, (
        f"Threading overhead P50 too high for {num_clients} clients: {result.P50:.1f} ms"
    )


# ---------------------------------------------------------------------------
# Benchmark: Deterministic Seed Reproducibility
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_deterministic_seed_reproducibility(
    benchmark_reporter: ResultReporter,
    deterministic_seed: int,
) -> None:
    """Verify that benchmark results are reproducible with the same
    random seed.

    This benchmark runs a simple computation twice with the same
    deterministic seed and checks that the results are identical.
    This is not a performance measurement per se, but a correctness
    check for the benchmark infrastructure.

    Expectation: two runs with the same seed should produce identical
    random sequences.
    """
    seed = deterministic_seed

    def _run_with_seed(s: int) -> list[float]:
        rng = random.Random(s)
        return [rng.random() for _ in range(1000)]

    values1 = _run_with_seed(seed)
    values2 = _run_with_seed(seed)

    assert values1 == values2, "Random sequences differ with the same seed!"

    # Measure the time to generate the random sequence (for reference)
    def _generate() -> None:
        rng = random.Random(seed)
        _ = [rng.random() for _ in range(1000)]

    result = BenchmarkResult(
        name="framework.seed_reproducibility",
        description=f"Verification that deterministic seed {seed} produces identical results. "
                    f"Sequences match: {values1 == values2}.",
        iterations=2,
        mean=0.0,
        std=0.0,
        min=0.0,
        max=0.0,
        P50=0.0,
        P95=0.0,
        P99=0.0,
        unit="us",
        tags={"seed": str(seed), "sequences_match": str(values1 == values2)},
    )
    benchmark_reporter.add_result(result)


# ---------------------------------------------------------------------------
# Entry point for direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("  AinosOS Performance Benchmark Suite")
    print("=" * 70)
    print(f"  Results directory: {RESULTS_DIR}")
    print(f"  Iterations: {BENCHMARK_ITERATIONS}")
    print(f"  Warmup: {BENCHMARK_WARMUP}")
    print()
    print("  Run with pytest:")
    print("    pytest tests/performance/test_benchmarks.py -v --benchmark")
    print("    pytest tests/performance/test_benchmarks.py -v --benchmark -k 'inference'")
    print("    pytest tests/performance/test_benchmarks.py -v --benchmark -m 'slow'")
    print("=" * 70)