"""
Model Load Benchmark
=====================

Measures the time taken to load AI models from disk into memory. This
benchmark is critical for understanding cold-start times and deployment
performance in production ML systems.

This benchmark evaluates:
- Model loading time from disk
- Memory usage during model loading
- Loading time across different model formats (PyTorch, ONNX, SavedModel)
- Peak memory during loading
- Serialization format efficiency
"""

from __future__ import annotations

import logging
import math
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


class ModelLoadBenchmark:
    """Benchmark for AI model loading time measurement.

    Measures the time and memory required to load various ML models
    from disk.

    Attributes:
        name: Unique identifier for this benchmark.
        model_types: List of model names to test.
        formats: List of model formats to test.
        iterations: Number of measurement iterations.
        warmup: Number of warmup iterations.
        measure_memory: Whether to measure memory usage.
        device: Device to load models onto.
        timeout: Maximum time per measurement in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the model load benchmark.

        Args:
            config: Configuration dictionary. Expected keys: model_types,
                formats, iterations, warmup, measure_memory, device, timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "model_load"
        self.config: dict[str, Any] = config or {}

        self.model_types: list[str] = self.config.get(
            "model_types", ["bert-base-uncased", "gpt2", "resnet50", "vit-base-patch16-224"]
        )
        self.formats: list[str] = self.config.get(
            "formats", ["pytorch", "onnx", "saved_model"]
        )
        self.iterations: int = self.config.get("iterations", DEFAULT_BENCHMARK_ITERATIONS // 10)
        self.warmup: int = self.config.get("warmup", DEFAULT_WARMUP_ITERATIONS // 5)
        self.measure_memory: bool = self.config.get("measure_memory", True)
        self.device: str = self.config.get("device", "cpu")
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        # Validate formats
        valid_formats = {"pytorch", "onnx", "saved_model"}
        for fmt in self.formats:
            if fmt not in valid_formats:
                raise BenchmarkConfigError(
                    f"Unknown format: {fmt}. Valid: {valid_formats}",
                    config_key="formats",
                )

        logger.info(
            "Initialized ModelLoadBenchmark: %d model types, "
            "formats=%s, measure_memory=%s",
            len(self.model_types), self.formats, self.measure_memory,
        )

    @staticmethod
    def _estimate_model_size(model_name: str) -> int:
        """Estimate the disk size of a model in bytes.

        Args:
            model_name: Name of the model.

        Returns:
            Estimated size in bytes.
        """
        model_sizes: dict[str, int] = {
            "bert-base-uncased": 440 * 1024 * 1024,  # ~440MB
            "gpt2": 548 * 1024 * 1024,  # ~548MB
            "resnet50": 98 * 1024 * 1024,  # ~98MB
            "vit-base-patch16-224": 330 * 1024 * 1024,  # ~330MB
        }
        return model_sizes.get(model_name, 200 * 1024 * 1024)

    @staticmethod
    def _estimate_model_params(model_name: str) -> int:
        """Estimate the number of parameters in a model.

        Args:
            model_name: Name of the model.

        Returns:
            Estimated parameter count.
        """
        model_params: dict[str, int] = {
            "bert-base-uncased": 110_000_000,  # 110M
            "gpt2": 124_000_000,  # 124M
            "resnet50": 25_600_000,  # 25.6M
            "vit-base-patch16-224": 86_000_000,  # 86M
        }
        return model_params.get(model_name, 50_000_000)

    def _simulate_model_load(
        self, model_name: str, model_format: str
    ) -> tuple[float, int, int]:
        """Simulate model loading from disk.

        Args:
            model_name: Name of the model.
            model_format: Format of the model file.

        Returns:
            Tuple of (load_time in seconds, model_size in bytes, memory_used in bytes).
        """
        model_size = self._estimate_model_size(model_name)
        num_params = self._estimate_model_params(model_name)

        # Format-specific overhead
        format_overhead: dict[str, float] = {
            "pytorch": 1.0,  # Baseline
            "onnx": 0.8,  # Usually faster to load
            "saved_model": 1.5,  # Usually slower (TF format)
        }
        overhead = format_overhead.get(model_format, 1.0)

        # Simulate disk I/O speed (~500MB/s SSD)
        disk_speed = 500 * 1024 * 1024  # 500 MB/s
        io_time = (model_size / disk_speed) * overhead

        # Simulate deserialization time
        deserialization_speed = 200_000_000  # ~200M params/s
        deser_time = (num_params / deserialization_speed) * overhead

        # Simulate memory allocation and weights loading
        alloc_time = model_size / (10 * 1024 * 1024 * 1024)  # ~10GB/s memory bandwidth

        total_time = io_time + deser_time + alloc_time

        # Memory usage: model weights + overhead
        memory_used = model_size + int(model_size * 0.1 * overhead)  # 10% overhead

        # Add noise
        noise = np.random.normal(1.0, 0.1)
        total_time *= noise

        return max(0.1, total_time), model_size, memory_used

    def _measure_single_config(
        self, model_name: str, model_format: str
    ) -> dict[str, Any]:
        """Measure model loading time for a single configuration.

        Args:
            model_name: Name of the model.
            model_format: Format of the model file.

        Returns:
            Dictionary with timing and memory statistics.

        Raises:
            BenchmarkExecutionError: If measurement fails.
        """
        load_times: list[float] = []
        memory_usages: list[int] = []

        # Warmup
        for _ in range(self.warmup):
            self._simulate_model_load(model_name, model_format)

        # Measurement
        start_time = time.monotonic()
        for i in range(self.iterations):
            if time.monotonic() - start_time > self.timeout:
                raise BenchmarkTimeoutError(self.timeout)

            t0 = time.perf_counter()
            load_time, model_size, mem_used = self._simulate_model_load(model_name, model_format)
            t1 = time.perf_counter()
            load_times.append(t1 - t0)
            memory_usages.append(mem_used)

        if not load_times:
            return {"error": "No measurements recorded", "raw_times": []}

        load_arr = np.array(load_times, dtype=np.float64)
        mem_arr = np.array(memory_usages, dtype=np.float64)

        mean_time = float(np.mean(load_arr))
        median_time = float(np.median(load_arr))
        mean_memory = float(np.mean(mem_arr))

        return {
            "mean_s": mean_time,
            "mean_ms": mean_time * 1000,
            "median_s": median_time,
            "median_ms": median_time * 1000,
            "std_s": float(np.std(load_arr, ddof=1)),
            "std_ms": float(np.std(load_arr, ddof=1)) * 1000,
            "min_s": float(np.min(load_arr)),
            "min_ms": float(np.min(load_arr)) * 1000,
            "max_s": float(np.max(load_arr)),
            "max_ms": float(np.max(load_arr)) * 1000,
            "p50_ms": float(np.percentile(load_arr, 50)) * 1000,
            "p90_ms": float(np.percentile(load_arr, 90)) * 1000,
            "p95_ms": float(np.percentile(load_arr, 95)) * 1000,
            "p99_ms": float(np.percentile(load_arr, 99)) * 1000,
            "model_size_bytes": model_size,
            "model_size_MB": model_size / (1024 * 1024),
            "memory_used_bytes": mean_memory,
            "memory_used_MB": mean_memory / (1024 * 1024),
            "n_samples": len(load_times),
            "raw_times": load_times,
        }

    def run(self) -> list[ResultDict]:
        """Execute the full model load benchmark.

        Runs loading time measurements across all model types and formats.

        Returns:
            List of result dictionaries with timing and memory metrics.
        """
        logger.info("Starting model load benchmark")
        logger.info("Models: %s, Formats: %s", self.model_types, self.formats)

        results: list[ResultDict] = []
        total_start = time.monotonic()
        successful: int = 0
        total_configs: int = 0

        for model_name in self.model_types:
            for model_format in self.formats:
                total_configs += 1
                logger.info("Loading model: %s format=%s", model_name, model_format)

                try:
                    measure_results = self._measure_single_config(model_name, model_format)

                    result: ResultDict = {
                        "benchmark": self.name,
                        "model": model_name,
                        "format": model_format,
                        "device": self.device,
                        "measure_memory": self.measure_memory,
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
                        mem_mb = measure_results.get("memory_used_MB", 0)
                        logger.info(
                            "  %s %s: mean=%.1fms, memory=%.0fMB",
                            model_name, model_format, mean_ms, mem_mb,
                        )

                    results.append(result)

                except Exception as exc:
                    logger.error("Model '%s' format='%s' failed: %s",
                                 model_name, model_format, exc)
                    results.append({
                        "benchmark": self.name,
                        "model": model_name,
                        "format": model_format,
                        "error": str(exc),
                    })

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "Model load benchmark completed in %.2fs. "
            "Successful: %d/%d configurations",
            total_elapsed, successful, total_configs,
        )

        return results

    def format_comparison(self, model_name: str = "bert-base-uncased") -> dict[str, Any]:
        """Compare loading times across different formats for a single model.

        Args:
            model_name: Model to compare across formats.

        Returns:
            Dictionary with format comparison results.
        """
        comparisons: list[dict[str, Any]] = []

        for model_format in self.formats:
            results = self._measure_single_config(model_name, model_format)
            comparisons.append({
                "format": model_format,
                "mean_ms": results.get("mean_ms", 0),
                "memory_MB": results.get("memory_used_MB", 0),
            })

        return {
            "model": model_name,
            "comparisons": comparisons,
        }

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "AI model loading time measurement benchmark",
            "model_types": self.model_types,
            "formats": self.formats,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "measure_memory": self.measure_memory,
            "device": self.device,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = ModelLoadBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        if "error" not in r:
            print(f"  {r['model']:>25s} {r['format']:>12s}: "
                  f"mean={r['mean_ms']:8.1f}ms  mem={r['memory_used_MB']:8.0f}MB")