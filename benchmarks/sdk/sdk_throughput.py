"""
SDK Throughput Benchmark
=========================

Measures and compares the throughput of various LLM SDK implementations
under different concurrency levels. This benchmark is essential for
understanding the maximum request handling capacity of SDKs.

This benchmark evaluates:
- Maximum throughput (requests per second) for each SDK
- Concurrent request handling
- Steady-state throughput measurement
- Operation type impact on throughput
- SDK overhead under load
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks import (
    BenchmarkConfigError,
    BenchmarkExecutionError,
    BenchmarkTimeoutError,
    DEFAULT_BENCHMARK_ITERATIONS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_WARMUP_ITERATIONS,
    ResultDict,
)

logger = logging.getLogger(__name__)


class SDKThroughputBenchmark:
    """Benchmark for SDK throughput comparison.

    Measures the maximum throughput achievable by different SDKs
    under various concurrency levels.

    Attributes:
        name: Unique identifier for this benchmark.
        sdks: List of SDK languages to test.
        concurrent_requests: List of concurrency levels to test.
        duration_seconds: Duration of each throughput measurement.
        warmup_seconds: Warmup duration.
        operations: List of operations to benchmark.
        target_rps: Target requests per second (None for max).
        timeout: Maximum time per measurement.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the SDK throughput benchmark.

        Args:
            config: Configuration dictionary. Expected keys: sdks,
                concurrent_requests, duration_seconds, warmup_seconds,
                operations, target_rps, timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "sdk_throughput"
        self.config: dict[str, Any] = config or {}

        self.sdks: list[str] = self.config.get(
            "sdks", ["python", "nodejs", "go", "rust", "java"]
        )
        self.concurrent_requests: list[int] = self.config.get(
            "concurrent_requests", [1, 4, 8, 16, 32, 64]
        )
        self.duration_seconds: int = self.config.get("duration_seconds", 30)
        self.warmup_seconds: int = self.config.get("warmup_seconds", 5)
        self.operations: list[str] = self.config.get("operations", ["completion", "embedding"])
        self.target_rps: int | None = self.config.get("target_rps")
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        # Validate parameters
        if self.duration_seconds < 1:
            raise BenchmarkConfigError(
                "duration_seconds must be >= 1", config_key="duration_seconds"
            )

        logger.info(
            "Initialized SDKThroughputBenchmark: SDKs=%s, "
            "concurrent=%s, duration=%ds, target_rps=%s",
            self.sdks, self.concurrent_requests,
            self.duration_seconds, self.target_rps,
        )

    def _simulate_sdk_request(self, sdk: str, operation: str) -> float:
        """Simulate a single SDK request latency.

        Args:
            sdk: SDK language name.
            operation: Operation name.

        Returns:
            Simulated latency in seconds.
        """
        sdk_base: dict[str, float] = {
            "python": 0.05,
            "nodejs": 0.03,
            "go": 0.02,
            "rust": 0.01,
            "java": 0.04,
        }
        base = sdk_base.get(sdk, 0.03)

        op_time: dict[str, float] = {
            "completion": 1.0,
            "embedding": 0.3,
        }
        op_delay = op_time.get(operation, 0.5)

        total = base + op_delay

        # Add noise
        noise = np.random.normal(1.0, 0.15)
        return max(0.001, total * noise)

    def _measure_sequential_throughput(
        self, sdk: str, operation: str
    ) -> dict[str, Any]:
        """Measure sequential throughput for a single SDK.

        Args:
            sdk: SDK language name.
            operation: Operation name.

        Returns:
            Dictionary with throughput statistics.
        """
        warmup_end = time.monotonic() + self.warmup_seconds
        while time.monotonic() < warmup_end:
            self._simulate_sdk_request(sdk, operation)

        total_requests = 0
        latencies: list[float] = []

        measurement_end = time.monotonic() + self.duration_seconds
        while time.monotonic() < measurement_end:
            t0 = time.perf_counter()
            self._simulate_sdk_request(sdk, operation)
            t1 = time.perf_counter()
            total_requests += 1
            latencies.append(t1 - t0)

        if total_requests == 0:
            return {"error": "No requests completed"}

        lat_arr = np.array(latencies, dtype=np.float64)
        mean_lat = float(np.mean(lat_arr))

        return {
            "total_requests": total_requests,
            "duration_s": self.duration_seconds,
            "requests_per_sec": total_requests / self.duration_seconds,
            "mean_latency_ms": mean_lat * 1000,
            "median_latency_ms": float(np.median(lat_arr)) * 1000,
            "max_latency_ms": float(np.max(lat_arr)) * 1000,
            "p50_latency_ms": float(np.percentile(lat_arr, 50)) * 1000,
            "p90_latency_ms": float(np.percentile(lat_arr, 90)) * 1000,
            "p95_latency_ms": float(np.percentile(lat_arr, 95)) * 1000,
            "p99_latency_ms": float(np.percentile(lat_arr, 99)) * 1000,
            "n_samples": len(latencies),
            "raw_times": latencies,
        }

    def _measure_concurrent_throughput(
        self, sdk: str, operation: str, num_workers: int
    ) -> dict[str, Any]:
        """Measure concurrent throughput for a single SDK.

        Args:
            sdk: SDK language name.
            operation: Operation name.
            num_workers: Number of concurrent workers.

        Returns:
            Dictionary with throughput statistics.
        """
        total_requests: list[int] = [0]
        latencies: list[float] = []
        lock = threading.Lock()

        def worker() -> None:
            while True:
                t0 = time.perf_counter()
                self._simulate_sdk_request(sdk, operation)
                t1 = time.perf_counter()

                with lock:
                    total_requests[0] += 1
                    latencies.append(t1 - t0)

        # Start workers
        threads: list[threading.Thread] = []
        for _ in range(num_workers):
            t = threading.Thread(target=worker, daemon=True)
            threads.append(t)

        # Warmup
        for _ in range(self.warmup_seconds * 10):
            self._simulate_sdk_request(sdk, operation)

        # Start and measure
        for t in threads:
            t.start()

        time.sleep(self.duration_seconds)

        if total_requests[0] == 0:
            return {"error": "No concurrent requests completed"}

        lat_arr = np.array(latencies, dtype=np.float64)
        mean_lat = float(np.mean(lat_arr))

        return {
            "total_requests": total_requests[0],
            "duration_s": self.duration_seconds,
            "num_workers": num_workers,
            "requests_per_sec": total_requests[0] / self.duration_seconds,
            "mean_latency_ms": mean_lat * 1000,
            "median_latency_ms": float(np.median(lat_arr)) * 1000,
            "p50_latency_ms": float(np.percentile(lat_arr, 50)) * 1000,
            "p90_latency_ms": float(np.percentile(lat_arr, 90)) * 1000,
            "p95_latency_ms": float(np.percentile(lat_arr, 95)) * 1000,
            "p99_latency_ms": float(np.percentile(lat_arr, 99)) * 1000,
            "n_samples": len(latencies),
            "raw_times": latencies,
        }

    def run(self) -> list[ResultDict]:
        """Execute the full SDK throughput benchmark.

        Runs throughput measurements across all SDKs, operations,
        and concurrency levels.

        Returns:
            List of result dictionaries with throughput metrics.
        """
        logger.info("Starting SDK throughput benchmark")
        logger.info(
            "SDKs: %s, Operations: %s, Concurrency: %s",
            self.sdks, self.operations, self.concurrent_requests,
        )

        results: list[ResultDict] = []
        total_start = time.monotonic()
        successful: int = 0

        for sdk in self.sdks:
            logger.info("Benchmarking SDK: %s", sdk)

            for operation in self.operations:
                # Sequential test
                logger.info("  Sequential %s", operation)
                try:
                    seq_results = self._measure_sequential_throughput(sdk, operation)

                    seq_result: ResultDict = {
                        "benchmark": self.name,
                        "sdk": sdk,
                        "operation": operation,
                        "concurrent_requests": 1,
                        "test_type": "sequential",
                    }

                    if "error" in seq_results:
                        seq_result["error"] = seq_results["error"]
                    else:
                        for key, value in seq_results.items():
                            if isinstance(value, (int, float, str)):
                                seq_result[key] = value
                            elif key == "raw_times":
                                seq_result[key] = value
                        successful += 1

                        rps = seq_results.get("requests_per_sec", 0)
                        logger.info("    Sequential: %.2f req/s", rps)

                    results.append(seq_result)

                except Exception as exc:
                    logger.error("SDK '%s' sequential '%s' failed: %s", sdk, operation, exc)
                    results.append({
                        "benchmark": self.name,
                        "sdk": sdk,
                        "operation": operation,
                        "concurrent_requests": 1,
                        "error": str(exc),
                    })

                # Concurrent tests
                for num_workers in self.concurrent_requests:
                    if num_workers == 1:
                        continue

                    logger.info("  Concurrent %s with %d workers", operation, num_workers)
                    try:
                        conc_results = self._measure_concurrent_throughput(
                            sdk, operation, num_workers
                        )

                        conc_result: ResultDict = {
                            "benchmark": self.name,
                            "sdk": sdk,
                            "operation": operation,
                            "concurrent_requests": num_workers,
                            "test_type": "concurrent",
                        }

                        if "error" in conc_results:
                            conc_result["error"] = conc_results["error"]
                        else:
                            for key, value in conc_results.items():
                                if isinstance(value, (int, float, str)):
                                    conc_result[key] = value
                                elif key == "raw_times":
                                    conc_result[key] = value
                            successful += 1

                            rps = conc_results.get("requests_per_sec", 0)
                            logger.info("    Concurrent %d: %.2f req/s", num_workers, rps)

                        results.append(conc_result)

                    except Exception as exc:
                        logger.error("SDK '%s' concurrent '%s' %d failed: %s",
                                     sdk, operation, num_workers, exc)
                        results.append({
                            "benchmark": self.name,
                            "sdk": sdk,
                            "operation": operation,
                            "concurrent_requests": num_workers,
                            "error": str(exc),
                        })

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "SDK throughput benchmark completed in %.2fs. "
            "Successful: %d configurations",
            total_elapsed, successful,
        )

        return results

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "SDK throughput comparison benchmark",
            "sdks": self.sdks,
            "concurrent_requests": self.concurrent_requests,
            "duration_seconds": self.duration_seconds,
            "warmup_seconds": self.warmup_seconds,
            "operations": self.operations,
            "target_rps": self.target_rps,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = SDKThroughputBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        if "error" not in r:
            print(f"  {r['sdk']:>8s} {r['operation']:>10s} "
                  f"conc={r['concurrent_requests']:2d}: "
                  f"{r['requests_per_sec']:8.2f} req/s")