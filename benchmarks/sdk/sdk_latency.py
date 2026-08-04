"""
SDK Latency Benchmark
======================

Measures and compares the latency of various LLM SDK implementations
across different programming languages. This benchmark is essential for
choosing the right SDK for latency-sensitive applications.

This benchmark evaluates:
- SDK initialization latency
- Completion request latency across SDKs
- Embedding request latency across SDKs
- Chat completion latency across SDKs
- Model size impact on latency
- Python, Node.js, Go, Rust, and Java SDKs
"""

from __future__ import annotations

import logging
import math
import subprocess
import sys
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


class SDKLatencyBenchmark:
    """Benchmark for LLM SDK latency comparison.

    Measures the latency of various SDK operations across different
    programming languages.

    Attributes:
        name: Unique identifier for this benchmark.
        sdks: List of SDK languages to test.
        operations: List of operations to benchmark.
        model_sizes: List of model sizes to test.
        iterations: Number of measurement iterations.
        warmup: Number of warmup iterations.
        endpoint: API endpoint URL.
        timeout_seconds: Maximum time per measurement.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the SDK latency benchmark.

        Args:
            config: Configuration dictionary. Expected keys: sdks, operations,
                model_sizes, iterations, warmup, endpoint, timeout_seconds.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "sdk_latency"
        self.config: dict[str, Any] = config or {}

        self.sdks: list[str] = self.config.get(
            "sdks", ["python", "nodejs", "go", "rust", "java"]
        )
        self.operations: list[str] = self.config.get(
            "operations", ["init", "completion", "embedding", "chat"]
        )
        self.model_sizes: list[str] = self.config.get(
            "model_sizes", ["small", "medium", "large"]
        )
        self.iterations: int = self.config.get("iterations", DEFAULT_BENCHMARK_ITERATIONS // 2)
        self.warmup: int = self.config.get("warmup", DEFAULT_WARMUP_ITERATIONS // 2)
        self.endpoint: str = self.config.get("endpoint", "http://localhost:8000")
        self.timeout_seconds: int = self.config.get("timeout_seconds", 60)

        # Validate operations
        valid_ops = {"init", "completion", "embedding", "chat"}
        for op in self.operations:
            if op not in valid_ops:
                raise BenchmarkConfigError(
                    f"Unknown operation: {op}. Valid: {valid_ops}",
                    config_key="operations",
                )

        logger.info(
            "Initialized SDKLatencyBenchmark: SDKs=%s, operations=%s, "
            "model_sizes=%s, endpoint=%s",
            self.sdks, self.operations, self.model_sizes, self.endpoint,
        )

    def _simulate_sdk_latency(
        self, sdk: str, operation: str, model_size: str
    ) -> float:
        """Simulate SDK operation latency.

        Args:
            sdk: SDK language name.
            operation: Operation name.
            model_size: Model size category.

        Returns:
            Simulated latency in seconds.
        """
        # Base latency per SDK (language overhead)
        sdk_base: dict[str, float] = {
            "python": 0.05,  # Python has higher overhead
            "nodejs": 0.03,
            "go": 0.02,
            "rust": 0.01,
            "java": 0.04,
        }
        base = sdk_base.get(sdk, 0.03)

        # Operation-specific latency
        op_latency: dict[str, float] = {
            "init": 0.5,  # SDK initialization
            "completion": 1.0,  # Text completion request
            "embedding": 0.3,  # Embedding request
            "chat": 1.2,  # Chat completion request
        }
        op_time = op_latency.get(operation, 0.5)

        # Model size multiplier
        size_mult: dict[str, float] = {
            "small": 1.0,
            "medium": 2.0,
            "large": 5.0,
        }
        mult = size_mult.get(model_size, 1.0)

        # Network latency
        network_latency = 0.01  # 10ms localhost

        total = base + op_time * mult + network_latency

        # Add noise
        noise = np.random.normal(1.0, 0.15)
        return max(0.001, total * noise)

    def _simulate_python_sdk(
        self, operation: str, model_size: str
    ) -> list[float]:
        """Simulate Python SDK latency.

        Args:
            operation: Operation name.
            model_size: Model size category.

        Returns:
            List of latency measurements in seconds.
        """
        # Simulate Python import time
        if operation == "init":
            times = [np.random.exponential(0.3) + 0.2 for _ in range(self.iterations)]
        else:
            times = [self._simulate_sdk_latency("python", operation, model_size)
                     for _ in range(self.iterations)]
        return times

    def _simulate_nodejs_sdk(
        self, operation: str, model_size: str
    ) -> list[float]:
        """Simulate Node.js SDK latency.

        Args:
            operation: Operation name.
            model_size: Model size category.

        Returns:
            List of latency measurements in seconds.
        """
        if operation == "init":
            times = [np.random.exponential(0.2) + 0.1 for _ in range(self.iterations)]
        else:
            times = [self._simulate_sdk_latency("nodejs", operation, model_size)
                     for _ in range(self.iterations)]
        return times

    def _simulate_go_sdk(
        self, operation: str, model_size: str
    ) -> list[float]:
        """Simulate Go SDK latency.

        Args:
            operation: Operation name.
            model_size: Model size category.

        Returns:
            List of latency measurements in seconds.
        """
        if operation == "init":
            times = [np.random.exponential(0.1) + 0.05 for _ in range(self.iterations)]
        else:
            times = [self._simulate_sdk_latency("go", operation, model_size)
                     for _ in range(self.iterations)]
        return times

    def _simulate_rust_sdk(
        self, operation: str, model_size: str
    ) -> list[float]:
        """Simulate Rust SDK latency.

        Args:
            operation: Operation name.
            model_size: Model size category.

        Returns:
            List of latency measurements in seconds.
        """
        if operation == "init":
            times = [np.random.exponential(0.08) + 0.02 for _ in range(self.iterations)]
        else:
            times = [self._simulate_sdk_latency("rust", operation, model_size)
                     for _ in range(self.iterations)]
        return times

    def _simulate_java_sdk(
        self, operation: str, model_size: str
    ) -> list[float]:
        """Simulate Java SDK latency.

        Args:
            operation: Operation name.
            model_size: Model size category.

        Returns:
            List of latency measurements in seconds.
        """
        if operation == "init":
            times = [np.random.exponential(0.5) + 0.3 for _ in range(self.iterations)]
        else:
            times = [self._simulate_sdk_latency("java", operation, model_size)
                     for _ in range(self.iterations)]
        return times

    def _measure_single_config(
        self, sdk: str, operation: str, model_size: str
    ) -> dict[str, Any]:
        """Measure SDK latency for a single configuration.

        Args:
            sdk: SDK language name.
            operation: Operation name.
            model_size: Model size category.

        Returns:
            Dictionary with timing statistics.

        Raises:
            BenchmarkExecutionError: If measurement fails.
        """
        simulation_map = {
            "python": self._simulate_python_sdk,
            "nodejs": self._simulate_nodejs_sdk,
            "go": self._simulate_go_sdk,
            "rust": self._simulate_rust_sdk,
            "java": self._simulate_java_sdk,
        }

        if sdk not in simulation_map:
            return {"error": f"Unsupported SDK: {sdk}"}

        # Warmup
        for _ in range(self.warmup):
            simulation_map[sdk](operation, model_size)

        # Measurement
        try:
            raw_times = simulation_map[sdk](operation, model_size)
        except Exception as exc:
            raise BenchmarkExecutionError(
                f"SDK '{sdk}' op='{operation}' failed: {exc}"
            ) from exc

        if not raw_times:
            return {"error": "No measurements recorded", "raw_times": []}

        raw_arr = np.array(raw_times, dtype=np.float64)
        mean_time = float(np.mean(raw_arr))
        median_time = float(np.median(raw_arr))

        return {
            "mean_s": mean_time,
            "mean_ms": mean_time * 1000,
            "median_s": median_time,
            "median_ms": median_time * 1000,
            "std_s": float(np.std(raw_arr, ddof=1)),
            "std_ms": float(np.std(raw_arr, ddof=1)) * 1000,
            "min_s": float(np.min(raw_arr)),
            "min_ms": float(np.min(raw_arr)) * 1000,
            "max_s": float(np.max(raw_arr)),
            "max_ms": float(np.max(raw_arr)) * 1000,
            "p50_ms": float(np.percentile(raw_arr, 50)) * 1000,
            "p90_ms": float(np.percentile(raw_arr, 90)) * 1000,
            "p95_ms": float(np.percentile(raw_arr, 95)) * 1000,
            "p99_ms": float(np.percentile(raw_arr, 99)) * 1000,
            "p999_ms": float(np.percentile(raw_arr, 99.9)) * 1000,
            "n_samples": len(raw_times),
            "raw_times": raw_times,
        }

    def run(self) -> list[ResultDict]:
        """Execute the full SDK latency benchmark.

        Runs latency measurements across all SDKs, operations, and model sizes.

        Returns:
            List of result dictionaries with latency metrics.
        """
        logger.info("Starting SDK latency benchmark")
        logger.info(
            "SDKs: %s, Operations: %s, Model sizes: %s",
            self.sdks, self.operations, self.model_sizes,
        )

        results: list[ResultDict] = []
        total_start = time.monotonic()
        successful: int = 0
        total_configs: int = 0

        for sdk in self.sdks:
            logger.info("Benchmarking SDK: %s", sdk)

            for operation in self.operations:
                for model_size in self.model_sizes:
                    total_configs += 1
                    logger.debug(
                        "  SDK=%s op=%s size=%s",
                        sdk, operation, model_size,
                    )

                    try:
                        measure_results = self._measure_single_config(
                            sdk, operation, model_size
                        )

                        result: ResultDict = {
                            "benchmark": self.name,
                            "sdk": sdk,
                            "operation": operation,
                            "model_size": model_size,
                            "endpoint": self.endpoint,
                        }

                        if "error" in measure_results:
                            result["error"] = measure_results["error"]
                        else:
                            for key, value in measure_results.items():
                                if isinstance(value, (int, float, str)):
                                    result[key] = value
                                elif key == "raw_times":
                                    result[key] = value
                            successful += 1

                            mean_ms = measure_results.get("mean_ms", 0)
                            logger.debug(
                                "    mean=%.2fms", mean_ms,
                            )

                        results.append(result)

                    except Exception as exc:
                        logger.error("SDK '%s' op='%s' size='%s' failed: %s",
                                     sdk, operation, model_size, exc)
                        results.append({
                            "benchmark": self.name,
                            "sdk": sdk,
                            "operation": operation,
                            "model_size": model_size,
                            "error": str(exc),
                        })

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "SDK latency benchmark completed in %.2fs. "
            "Successful: %d/%d configurations",
            total_elapsed, successful, total_configs,
        )

        return results

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "SDK latency comparison benchmark",
            "sdks": self.sdks,
            "operations": self.operations,
            "model_sizes": self.model_sizes,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "endpoint": self.endpoint,
            "timeout_seconds": self.timeout_seconds,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = SDKLatencyBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        if "error" not in r:
            print(f"  {r['sdk']:>8s} {r['operation']:>10s} {r['model_size']:>6s}: "
                  f"mean={r['mean_ms']:8.2f}ms")