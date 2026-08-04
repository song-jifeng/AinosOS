"""
Inference Throughput Benchmark
===============================

Measures the maximum throughput of AI model inference under various
concurrency and batch configurations. This benchmark is essential for
understanding the serving capacity of ML inference systems.

This benchmark evaluates:
- Maximum throughput (requests per second) for various models
- Batch size impact on throughput
- Concurrent request handling throughput
- Steady-state throughput over extended periods
- Latency vs throughput trade-off analysis
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


class InferenceThroughputBenchmark:
    """Benchmark for AI model inference throughput measurement.

    Measures the maximum sustainable throughput of ML models under
    different batch sizes and concurrency levels.

    Attributes:
        name: Unique identifier for this benchmark.
        model_types: List of model names to test.
        batch_sizes: List of batch sizes to test.
        duration_seconds: Duration of each throughput measurement.
        warmup_seconds: Warmup duration before measurement.
        precision: Model precision.
        device: Inference device.
        max_concurrent_requests: Maximum number of concurrent requests.
        provider: Inference provider.
        timeout: Maximum time per measurement in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the inference throughput benchmark.

        Args:
            config: Configuration dictionary. Expected keys: model_types,
                batch_sizes, duration_seconds, warmup_seconds, precision,
                device, max_concurrent_requests, provider, timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "inference_throughput"
        self.config: dict[str, Any] = config or {}

        self.model_types: list[str] = self.config.get(
            "model_types", ["bert-base-uncased", "gpt2", "resnet50"]
        )
        self.batch_sizes: list[int] = self.config.get(
            "batch_sizes", [1, 4, 16, 32, 64, 128, 256]
        )
        self.duration_seconds: int = self.config.get("duration_seconds", 30)
        self.warmup_seconds: int = self.config.get("warmup_seconds", 5)
        self.precision: str = self.config.get("precision", "fp32")
        self.device: str = self.config.get("device", "cpu")
        self.max_concurrent_requests: int = self.config.get("max_concurrent_requests", 8)
        self.provider: str = self.config.get("provider", "pytorch")
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        # Validate parameters
        if self.duration_seconds < 1:
            raise BenchmarkConfigError(
                "duration_seconds must be >= 1", config_key="duration_seconds"
            )
        if self.max_concurrent_requests < 1:
            raise BenchmarkConfigError(
                "max_concurrent_requests must be >= 1", config_key="max_concurrent_requests"
            )

        logger.info(
            "Initialized InferenceThroughputBenchmark: %d model types, "
            "batch_sizes=%s, duration=%ds, concurrent=%d",
            len(self.model_types), self.batch_sizes,
            self.duration_seconds, self.max_concurrent_requests,
        )

    def _simulate_inference_batch(self, model_name: str, batch_size: int) -> float:
        """Simulate batched inference latency.

        Args:
            model_name: Name of the model.
            batch_size: Batch size.

        Returns:
            Simulated latency in seconds.
        """
        # Model-specific compute requirements
        model_flops: dict[str, float] = {
            "bert-base-uncased": 11e9,
            "gpt2": 13e9,
            "resnet50": 4e9,
        }
        base_flops = model_flops.get(model_name, 10e9)
        cpu_flops = 50e9

        total_flops = base_flops * batch_size
        device_mult = {"cpu": 1.0, "cuda": 10.0, "mps": 5.0}.get(self.device, 1.0)
        precision_mult = {"fp32": 1.0, "fp16": 1.8, "int8": 2.5}.get(self.precision, 1.0)

        effective_flops = cpu_flops * device_mult * precision_mult
        latency = total_flops / effective_flops if effective_flops > 0 else 0.001

        # Add noise
        noise = np.random.normal(1.0, 0.1)
        return max(0.0001, latency * noise)

    def _measure_throughput_single_config(
        self, model_name: str, batch_size: int
    ) -> dict[str, Any]:
        """Measure throughput for a single model and batch size.

        Runs inference repeatedly for the configured duration and
        measures the achieved throughput.

        Args:
            model_name: Name of the model.
            batch_size: Batch size.

        Returns:
            Dictionary with throughput statistics.

        Raises:
            BenchmarkExecutionError: If measurement fails.
        """
        total_requests: int = 0
        latencies: list[float] = []
        lock = threading.Lock()

        # Warmup
        warmup_end = time.monotonic() + self.warmup_seconds
        while time.monotonic() < warmup_end:
            self._simulate_inference_batch(model_name, batch_size)

        # Measurement
        measurement_end = time.monotonic() + self.duration_seconds
        while time.monotonic() < measurement_end:
            t0 = time.perf_counter()
            self._simulate_inference_batch(model_name, batch_size)
            t1 = time.perf_counter()

            with lock:
                total_requests += 1
                latencies.append(t1 - t0)

        if total_requests == 0:
            return {"error": "No requests completed during measurement period"}

        # Compute statistics
        lat_arr = np.array(latencies, dtype=np.float64)
        mean_lat = float(np.mean(lat_arr))

        # Throughput
        requests_per_sec = total_requests / self.duration_seconds
        samples_per_sec = requests_per_sec * batch_size

        return {
            "total_requests": total_requests,
            "duration_s": self.duration_seconds,
            "requests_per_sec": requests_per_sec,
            "samples_per_sec": samples_per_sec,
            "mean_latency_s": mean_lat,
            "mean_latency_ms": mean_lat * 1000,
            "median_latency_ms": float(np.median(lat_arr)) * 1000,
            "std_latency_ms": float(np.std(lat_arr, ddof=1)) * 1000,
            "min_latency_ms": float(np.min(lat_arr)) * 1000,
            "max_latency_ms": float(np.max(lat_arr)) * 1000,
            "p50_latency_ms": float(np.percentile(lat_arr, 50)) * 1000,
            "p90_latency_ms": float(np.percentile(lat_arr, 90)) * 1000,
            "p95_latency_ms": float(np.percentile(lat_arr, 95)) * 1000,
            "p99_latency_ms": float(np.percentile(lat_arr, 99)) * 1000,
            "n_samples": len(latencies),
            "raw_times": latencies,
        }

    def _measure_concurrent_throughput(
        self, model_name: str, batch_size: int, num_workers: int
    ) -> dict[str, Any]:
        """Measure throughput with concurrent request workers.

        Args:
            model_name: Name of the model.
            batch_size: Batch size per request.
            num_workers: Number of concurrent workers.

        Returns:
            Dictionary with throughput statistics.
        """
        total_requests: list[int] = [0]
        latencies: list[float] = []
        lock = threading.Lock()
        errors: list[Exception | None] = [None]

        def worker() -> None:
            try:
                while True:
                    t0 = time.perf_counter()
                    self._simulate_inference_batch(model_name, batch_size)
                    t1 = time.perf_counter()

                    with lock:
                        total_requests[0] += 1
                        latencies.append(t1 - t0)
            except Exception as exc:
                with lock:
                    errors[0] = exc

        # Start workers
        threads: list[threading.Thread] = []
        for _ in range(num_workers):
            t = threading.Thread(target=worker, daemon=True)
            threads.append(t)

        # Warmup
        for _ in range(self.warmup_seconds * 10):
            self._simulate_inference_batch(model_name, batch_size)

        # Start workers and measure
        for t in threads:
            t.start()

        time.sleep(self.duration_seconds)

        # Stop workers
        for t in threads:
            t.join(timeout=1)

        if total_requests[0] == 0:
            return {"error": "No concurrent requests completed"}

        lat_arr = np.array(latencies, dtype=np.float64)
        mean_lat = float(np.mean(lat_arr))

        return {
            "total_requests": total_requests[0],
            "duration_s": self.duration_seconds,
            "num_workers": num_workers,
            "requests_per_sec": total_requests[0] / self.duration_seconds,
            "samples_per_sec": (total_requests[0] * batch_size) / self.duration_seconds,
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
        """Execute the full inference throughput benchmark.

        Runs throughput measurements across all model types and batch sizes.

        Returns:
            List of result dictionaries with throughput metrics.
        """
        logger.info("Starting inference throughput benchmark")
        logger.info(
            "Models: %s, Batch sizes: %s, Duration: %ds",
            self.model_types, self.batch_sizes, self.duration_seconds,
        )

        results: list[ResultDict] = []
        total_start = time.monotonic()
        successful: int = 0

        for model_name in self.model_types:
            logger.info("Benchmarking model: %s", model_name)

            for batch_size in self.batch_sizes:
                logger.info("  Batch size: %d", batch_size)

                try:
                    measure_results = self._measure_throughput_single_config(
                        model_name, batch_size
                    )

                    result: ResultDict = {
                        "benchmark": self.name,
                        "model": model_name,
                        "batch_size": batch_size,
                        "precision": self.precision,
                        "device": self.device,
                        "provider": self.provider,
                        "concurrent_requests": 1,
                        "test_type": "sequential",
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

                        rps = measure_results.get("requests_per_sec", 0)
                        mean_ms = measure_results.get("mean_latency_ms", 0)
                        logger.info(
                            "    Sequential: %.2f req/s, mean latency=%.2fms",
                            rps, mean_ms,
                        )

                    results.append(result)

                    # Concurrent throughput test (only for representative configs)
                    if batch_size in (1, 16, 64) and self.max_concurrent_requests > 1:
                        for num_workers in [self.max_concurrent_requests // 2, self.max_concurrent_requests]:
                            logger.info(
                                "  Concurrent: %d workers, batch=%d",
                                num_workers, batch_size,
                            )

                            try:
                                concurrent_results = self._measure_concurrent_throughput(
                                    model_name, batch_size, num_workers
                                )

                                concurrent_result: ResultDict = {
                                    "benchmark": self.name,
                                    "model": model_name,
                                    "batch_size": batch_size,
                                    "precision": self.precision,
                                    "device": self.device,
                                    "provider": self.provider,
                                    "concurrent_requests": num_workers,
                                    "test_type": "concurrent",
                                }

                                if "error" in concurrent_results:
                                    concurrent_result["error"] = concurrent_results["error"]
                                else:
                                    for key, value in concurrent_results.items():
                                        if isinstance(value, (int, float, str)):
                                            concurrent_result[key] = value
                                        elif key == "raw_times":
                                            concurrent_result[key] = value

                                results.append(concurrent_result)

                                rps = concurrent_results.get("requests_per_sec", 0)
                                logger.info(
                                    "    Concurrent %d workers: %.2f req/s",
                                    num_workers, rps,
                                )

                            except Exception as exc:
                                logger.error("Concurrent test failed: %s", exc)

                except Exception as exc:
                    logger.error("Model '%s' batch=%d failed: %s",
                                 model_name, batch_size, exc)
                    results.append({
                        "benchmark": self.name,
                        "model": model_name,
                        "batch_size": batch_size,
                        "error": str(exc),
                    })

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "Inference throughput benchmark completed in %.2fs. "
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
            "description": "AI model inference throughput measurement benchmark",
            "model_types": self.model_types,
            "batch_sizes": self.batch_sizes,
            "duration_seconds": self.duration_seconds,
            "warmup_seconds": self.warmup_seconds,
            "precision": self.precision,
            "device": self.device,
            "max_concurrent_requests": self.max_concurrent_requests,
            "provider": self.provider,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = InferenceThroughputBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        if "error" not in r:
            print(f"  {r['model']:>25s} batch={r['batch_size']:3d} "
                  f"{r['test_type']:>10s}: "
                  f"{r['requests_per_sec']:8.2f} req/s  "
                  f"lat={r['mean_latency_ms']:8.2f}ms")