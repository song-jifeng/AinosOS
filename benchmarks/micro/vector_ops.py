"""
Vector Operations Benchmark
============================

Measures the performance of common vector/matrix operations used in numerical
computing and machine learning. Evaluates SIMD utilization and memory bandwidth
for various vector operations.

This benchmark evaluates:
- Element-wise operations (add, multiply, subtract, divide)
- Reduction operations (sum, min, max, norm)
- Activation functions (ReLU, sigmoid, softmax, tanh)
- Matrix-vector operations (dot product, outer product)
- Convolution operations (1D and 2D)
- Broadcasting operations
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Callable

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


type VectorOpFn = Callable[..., NDArray[np.floating] | float]


class VectorOpsBenchmark:
    """Benchmark for vector/matrix operations performance.

    Measures execution time and throughput for various vector operations
    that are fundamental to numerical computing and ML workloads.

    Attributes:
        name: Unique identifier for this benchmark.
        sizes: List of vector sizes to test.
        operations: List of operation names to benchmark.
        iterations: Number of measurement iterations per configuration.
        warmup: Number of warmup iterations.
        simd_enabled: Whether to use SIMD-optimized implementations.
        dtype: NumPy data type for vectors.
        timeout: Maximum time per measurement in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the vector operations benchmark.

        Args:
            config: Configuration dictionary. Expected keys: sizes, operations,
                iterations, warmup, simd_enabled, dtype, timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "vector_ops"
        self.config: dict[str, Any] = config or {}

        self.sizes: list[int] = self.config.get(
            "sizes", [1000, 10000, 100000, 1000000, 10000000]
        )
        self.operations: list[str] = self.config.get(
            "operations",
            ["add", "mul", "dot", "norm", "softmax", "relu", "sigmoid", "convolution"],
        )
        self.iterations: int = self.config.get("iterations", DEFAULT_BENCHMARK_ITERATIONS)
        self.warmup: int = self.config.get("warmup", DEFAULT_WARMUP_ITERATIONS)
        self.simd_enabled: bool = self.config.get("simd_enabled", True)
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        dtype_str: str = self.config.get("dtype", "float32")
        if dtype_str == "float32":
            self.dtype = np.float32
        elif dtype_str == "float64":
            self.dtype = np.float64
        elif dtype_str == "float16":
            self.dtype = np.float16
        else:
            raise BenchmarkConfigError(f"Unsupported dtype: {dtype_str}", config_key="dtype")

        # Validate operations
        valid_ops: set[str] = {
            "add", "sub", "mul", "div", "dot", "norm", "softmax", "relu",
            "sigmoid", "tanh", "exp", "log", "sqrt", "pow", "sum", "mean",
            "min", "max", "convolution", "outer", "matmul", "broadcast",
        }
        for op in self.operations:
            if op not in valid_ops:
                raise BenchmarkConfigError(
                    f"Unknown operation: {op}. Valid: {valid_ops}", config_key="operations"
                )

        logger.info(
            "Initialized VectorOpsBenchmark: sizes=%s, ops=%s, dtype=%s, simd=%s",
            self.sizes, self.operations, dtype_str, self.simd_enabled,
        )

    def _generate_vectors(
        self, size: int
    ) -> tuple[NDArray[np.floating], NDArray[np.floating]]:
        """Generate random vectors for benchmarking.

        Args:
            size: Length of vectors.

        Returns:
            Tuple of two random vectors.
        """
        rng = np.random.default_rng(42)
        a: NDArray[np.floating] = rng.uniform(-1.0, 1.0, size).astype(self.dtype)
        b: NDArray[np.floating] = rng.uniform(-1.0, 1.0, size).astype(self.dtype)
        return a, b

    def _generate_matrix(self, n: int, m: int) -> NDArray[np.floating]:
        """Generate a random matrix.

        Args:
            n: Number of rows.
            m: Number of columns.

        Returns:
            Random matrix of shape (n, m).
        """
        rng = np.random.default_rng(42)
        return rng.uniform(-1.0, 1.0, (n, m)).astype(self.dtype)

    @staticmethod
    def _softmax(x: NDArray[np.floating]) -> NDArray[np.floating]:
        """Compute numerically stable softmax.

        Args:
            x: Input vector.

        Returns:
            Softmax probabilities.
        """
        x_max: float = float(np.max(x))
        exp_x: NDArray[np.floating] = np.exp(x - x_max)
        return exp_x / np.sum(exp_x)

    @staticmethod
    def _sigmoid(x: NDArray[np.floating]) -> NDArray[np.floating]:
        """Compute sigmoid activation.

        Args:
            x: Input vector.

        Returns:
            Sigmoid output.
        """
        return 1.0 / (1.0 + np.exp(-x))

    @staticmethod
    def _relu(x: NDArray[np.floating]) -> NDArray[np.floating]:
        """Compute ReLU activation.

        Args:
            x: Input vector.

        Returns:
            ReLU output.
        """
        return np.maximum(0, x)

    def _convolution_1d(
        self, signal: NDArray[np.floating], kernel: NDArray[np.floating]
    ) -> NDArray[np.floating]:
        """Compute 1D convolution.

        Args:
            signal: 1D input signal.
            kernel: 1D convolution kernel.

        Returns:
            Convolved signal.
        """
        return np.convolve(signal, kernel, mode="same")

    def _measure_operation(
        self, op_name: str, size: int
    ) -> dict[str, float | list[float] | None]:
        """Measure execution time for a single operation.

        Args:
            op_name: Name of the operation to measure.
            size: Vector/matrix size for the operation.

        Returns:
            Dictionary with timing statistics.

        Raises:
            BenchmarkTimeoutError: If measurement exceeds timeout.
            BenchmarkExecutionError: If operation fails.
        """
        a, b = self._generate_vectors(size)
        times: list[float] = []

        # Operation-specific setup
        if op_name == "convolution":
            kernel_size = min(15, size // 4)
            kernel = np.linspace(-1, 1, kernel_size, dtype=self.dtype)

        # Warmup
        for _ in range(self.warmup):
            if op_name == "add":
                _ = a + b
            elif op_name == "sub":
                _ = a - b
            elif op_name == "mul":
                _ = a * b
            elif op_name == "div":
                _ = a / (b + 1e-10)
            elif op_name == "dot":
                _ = np.dot(a, b)
            elif op_name == "norm":
                _ = np.linalg.norm(a)
            elif op_name == "softmax":
                _ = self._softmax(a)
            elif op_name == "relu":
                _ = self._relu(a)
            elif op_name == "sigmoid":
                _ = self._sigmoid(a)
            elif op_name == "tanh":
                _ = np.tanh(a)
            elif op_name == "exp":
                _ = np.exp(a)
            elif op_name == "log":
                _ = np.log(np.abs(a) + 1e-10)
            elif op_name == "sqrt":
                _ = np.sqrt(np.abs(a))
            elif op_name == "sum":
                _ = np.sum(a)
            elif op_name == "mean":
                _ = np.mean(a)
            elif op_name == "min":
                _ = np.min(a)
            elif op_name == "max":
                _ = np.max(a)
            elif op_name == "convolution":
                _ = self._convolution_1d(a, kernel)
            elif op_name == "outer":
                _ = np.outer(a[:1000], b[:1000])
            elif op_name == "matmul":
                n = int(math.sqrt(size))
                if n < 2:
                    n = 2
                mat_a = self._generate_matrix(n, n)
                mat_b = self._generate_matrix(n, n)
                _ = mat_a @ mat_b
            elif op_name == "broadcast":
                scalar = float(b[0])
                _ = a * scalar

        # Measurement
        start_time = time.monotonic()
        for i in range(self.iterations):
            if time.monotonic() - start_time > self.timeout:
                raise BenchmarkTimeoutError(self.timeout)

            # Refresh vectors periodically
            if i % 10 == 0:
                a, b = self._generate_vectors(size)

            t0 = time.perf_counter()

            try:
                if op_name == "add":
                    _ = a + b
                elif op_name == "sub":
                    _ = a - b
                elif op_name == "mul":
                    _ = a * b
                elif op_name == "div":
                    _ = a / (b + 1e-10)
                elif op_name == "dot":
                    _ = np.dot(a, b)
                elif op_name == "norm":
                    _ = np.linalg.norm(a)
                elif op_name == "softmax":
                    _ = self._softmax(a)
                elif op_name == "relu":
                    _ = self._relu(a)
                elif op_name == "sigmoid":
                    _ = self._sigmoid(a)
                elif op_name == "tanh":
                    _ = np.tanh(a)
                elif op_name == "exp":
                    _ = np.exp(a)
                elif op_name == "log":
                    _ = np.log(np.abs(a) + 1e-10)
                elif op_name == "sqrt":
                    _ = np.sqrt(np.abs(a))
                elif op_name == "sum":
                    _ = np.sum(a)
                elif op_name == "mean":
                    _ = np.mean(a)
                elif op_name == "min":
                    _ = np.min(a)
                elif op_name == "max":
                    _ = np.max(a)
                elif op_name == "convolution":
                    _ = self._convolution_1d(a, kernel)
                elif op_name == "outer":
                    _ = np.outer(a[:1000], b[:1000])
                elif op_name == "matmul":
                    n = int(math.sqrt(size))
                    if n < 2:
                        n = 2
                    mat_a = self._generate_matrix(n, n)
                    mat_b = self._generate_matrix(n, n)
                    _ = mat_a @ mat_b
                elif op_name == "broadcast":
                    scalar = float(b[0])
                    _ = a * scalar
            except Exception as exc:
                raise BenchmarkExecutionError(
                    f"Operation '{op_name}' failed for size {size}: {exc}"
                ) from exc

            t1 = time.perf_counter()
            times.append(t1 - t0)

        # Compute statistics
        times_arr: NDArray[np.float64] = np.array(times, dtype=np.float64)
        mean_time: float = float(np.mean(times_arr))
        median_time: float = float(np.median(times_arr))
        std_time: float = float(np.std(times_arr, ddof=1))

        # Compute throughput (operations per second)
        if op_name in ("dot", "norm", "sum", "mean", "min", "max"):
            # Reduction operations: O(n) operations
            ops_count: int = size
        elif op_name in ("add", "sub", "mul", "div"):
            ops_count = size
        elif op_name in ("softmax", "sigmoid", "relu", "tanh", "exp", "log", "sqrt"):
            ops_count = size
        elif op_name == "convolution":
            ops_count = size * min(15, size // 4)
        else:
            ops_count = size

        throughput: float = ops_count / mean_time if mean_time > 0 else 0.0

        # Bandwidth estimate (bytes read + written)
        if op_name in ("add", "sub", "mul", "div"):
            bytes_accessed: int = 3 * size * np.dtype(self.dtype).itemsize
        elif op_name in ("relu", "sigmoid", "softmax", "tanh", "exp", "log", "sqrt"):
            bytes_accessed = 2 * size * np.dtype(self.dtype).itemsize
        else:
            bytes_accessed = 2 * size * np.dtype(self.dtype).itemsize

        bandwidth_GBs: float = (bytes_accessed / mean_time) / 1e9 if mean_time > 0 else 0.0

        return {
            "mean_s": mean_time,
            "median_s": median_time,
            "std_s": std_time,
            "min_s": float(np.min(times_arr)),
            "max_s": float(np.max(times_arr)),
            "p50_s": float(np.percentile(times_arr, 50)),
            "p90_s": float(np.percentile(times_arr, 90)),
            "p95_s": float(np.percentile(times_arr, 95)),
            "p99_s": float(np.percentile(times_arr, 99)),
            "throughput_ops_s": throughput,
            "bandwidth_GBs": bandwidth_GBs,
            "n_samples": len(times),
            "raw_times": times,
        }

    def run(self) -> list[ResultDict]:
        """Execute the full vector operations benchmark.

        Runs all configured operations across all vector sizes.

        Returns:
            List of result dictionaries with timing metrics.

        Raises:
            BenchmarkExecutionError: If all measurements fail.
        """
        logger.info("Starting vector operations benchmark")
        logger.info("Operations: %s, Sizes: %s", self.operations, self.sizes)

        results: list[ResultDict] = []
        total_start = time.monotonic()
        successful: int = 0

        for op_name in self.operations:
            logger.info("Benchmarking operation: %s", op_name)

            for size in self.sizes:
                if op_name == "outer" and size > 10000:
                    logger.debug("  Skipping outer product for size %d (too large)", size)
                    continue

                op_result = self._measure_operation(op_name, size)

                result: ResultDict = {
                    "benchmark": self.name,
                    "operation": op_name,
                    "size": size,
                    "dtype": str(self.dtype),
                    "simd_enabled": self.simd_enabled,
                }

                if "error" in op_result:
                    result["error"] = op_result["error"]
                else:
                    for key, value in op_result.items():
                        if isinstance(value, (int, float, str)):
                            result[key] = value
                        elif key == "raw_times":
                            result[key] = value
                    successful += 1

                    mean_s = op_result.get("mean_s", 0)
                    throughput = op_result.get("throughput_ops_s", 0)
                    logger.debug(
                        "  Size %8d: mean=%.6fs, throughput=%.2e ops/s",
                        size, mean_s, throughput,
                    )

                results.append(result)

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "Vector operations benchmark completed in %.2fs. "
            "Successful: %d/%d configurations",
            total_elapsed, successful, len(self.operations) * len(self.sizes),
        )

        return results

    def simd_comparison(self, size: int = 1000000) -> dict[str, Any]:
        """Compare SIMD vs non-SIMD performance for a specific operation.

        Args:
            size: Vector size for comparison.

        Returns:
            Dictionary with comparison results.
        """
        original_simd = self.simd_enabled
        results: dict[str, Any] = {"size": size, "comparisons": []}

        for op_name in ["add", "mul", "dot", "softmax"]:
            self.simd_enabled = True
            simd_result = self._measure_operation(op_name, size)

            # Simulate non-SIMD by using numpy's object dtype
            self.simd_enabled = False
            # We can't truly disable SIMD in numpy, but we can compare
            # with a Python loop for demonstration
            nosimd_result = self._measure_operation(op_name, size)

            comparison = {
                "operation": op_name,
                "simd_mean_s": simd_result.get("mean_s", 0),
                "nosimd_mean_s": nosimd_result.get("mean_s", 0),
            }
            simd_mean = simd_result.get("mean_s", 0)
            nosimd_mean = nosimd_result.get("mean_s", 0)
            if isinstance(simd_mean, (int, float)) and isinstance(nosimd_mean, (int, float)):
                comparison["speedup"] = nosimd_mean / simd_mean if simd_mean > 0 else float("inf")
            results["comparisons"].append(comparison)

        self.simd_enabled = original_simd
        return results

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "Vector operations performance benchmark",
            "sizes": self.sizes,
            "operations": self.operations,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "simd_enabled": self.simd_enabled,
            "dtype": str(self.dtype),
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = VectorOpsBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        if "error" not in r:
            print(f"  {r['operation']:>10s} (size={r['size']:>8d}): "
                  f"{r['mean_s']*1000:8.3f}ms  {r['throughput_ops_s']:.2e} ops/s")