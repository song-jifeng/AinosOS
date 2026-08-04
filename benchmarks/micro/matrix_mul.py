"""
Matrix Multiplication Benchmark
================================

Measures the performance of matrix multiplication operations across various
matrix sizes. Supports both naive Python implementations and optimized BLAS-backed
operations via NumPy.

This benchmark evaluates:
- Small matrix performance (64x64, 128x128) - typically cache-resident
- Medium matrix performance (256x256, 512x512) - memory-bound
- Large matrix performance (1024x1024, 2048x2048) - compute-bound
- Block-based multiplication for cache efficiency
- Multi-threaded scaling (if available)
"""

from __future__ import annotations

import logging
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


class MatrixMultiplicationBenchmark:
    """Benchmark for matrix multiplication performance across different sizes.

    This benchmark measures the time taken to multiply two matrices of varying
    sizes, using both naive and optimized (BLAS) implementations. It provides
    detailed statistics including GFLOP/s throughput.

    Attributes:
        name: Unique identifier for this benchmark.
        sizes: List of matrix dimensions to test (N x N).
        iterations: Number of measurement iterations per size.
        warmup: Number of warmup iterations before measurement.
        dtype: NumPy data type for matrices.
        use_blas: Whether to use BLAS-optimized matmul.
        block_size: Block size for cache-friendly multiplication.
        num_threads: Number of threads for BLAS (None = auto).
        timeout: Maximum time per size in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the matrix multiplication benchmark.

        Args:
            config: Configuration dictionary, typically from config.yaml.
                Expected keys: sizes, iterations, warmup, dtype, use_blas,
                block_size, num_threads, timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "matrix_mul"
        self.config: dict[str, Any] = config or {}

        self.sizes: list[int] = self.config.get("sizes", [64, 128, 256, 512, 1024, 2048])
        self.iterations: int = self.config.get("iterations", DEFAULT_BENCHMARK_ITERATIONS)
        self.warmup: int = self.config.get("warmup", DEFAULT_WARMUP_ITERATIONS)
        self.use_blas: bool = self.config.get("use_blas", True)
        self.block_size: int = self.config.get("block_size", 32)
        self.num_threads: int | None = self.config.get("num_threads")
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        dtype_str: str = self.config.get("dtype", "float64")
        if dtype_str == "float64":
            self.dtype = np.float64
        elif dtype_str == "float32":
            self.dtype = np.float32
        elif dtype_str == "float16":
            self.dtype = np.float16
        elif dtype_str == "int64":
            self.dtype = np.int64
        elif dtype_str == "int32":
            self.dtype = np.int32
        else:
            raise BenchmarkConfigError(f"Unsupported dtype: {dtype_str}", config_key="dtype")

        if not self.sizes:
            raise BenchmarkConfigError("Sizes list must not be empty", config_key="sizes")
        if self.iterations < 1:
            raise BenchmarkConfigError("Iterations must be >= 1", config_key="iterations")
        if self.warmup < 0:
            raise BenchmarkConfigError("Warmup must be >= 0", config_key="warmup")

        # Configure BLAS threading
        if self.num_threads is not None:
            try:
                import os
                os.environ["OMP_NUM_THREADS"] = str(self.num_threads)
                os.environ["MKL_NUM_THREADS"] = str(self.num_threads)
                os.environ["OPENBLAS_NUM_THREADS"] = str(self.num_threads)
            except Exception:
                logger.warning("Failed to set BLAS thread count")

        # Validate sizes
        for s in self.sizes:
            if s <= 0:
                raise BenchmarkConfigError(f"Invalid matrix size: {s}", config_key="sizes")
            if s & (s - 1) != 0:
                logger.warning(f"Size {s} is not a power of 2; performance may vary")

        logger.info(
            "Initialized MatrixMultiplicationBenchmark: sizes=%s, dtype=%s, "
            "iterations=%d, warmup=%d, blas=%s",
            self.sizes, dtype_str, self.iterations, self.warmup, self.use_blas,
        )

    def _generate_matrices(self, size: int) -> tuple[NDArray[np.floating], NDArray[np.floating]]:
        """Generate random matrices for benchmarking.

        Creates two matrices A and B of shape (size, size) with random values
        drawn from a uniform distribution.

        Args:
            size: Dimension of the square matrices.

        Returns:
            Tuple of (matrix A, matrix B) as NumPy arrays.
        """
        rng = np.random.default_rng(42)
        a: NDArray[np.floating] = rng.uniform(-1.0, 1.0, (size, size)).astype(self.dtype)
        b: NDArray[np.floating] = rng.uniform(-1.0, 1.0, (size, size)).astype(self.dtype)
        return a, b

    def _blocked_matmul(
        self, a: NDArray[np.floating], b: NDArray[np.floating], block_size: int
    ) -> NDArray[np.floating]:
        """Perform blocked (tiled) matrix multiplication for cache efficiency.

        Implements a cache-friendly blocked matrix multiplication algorithm.
        The matrices are divided into blocks of size block_size x block_size
        to improve cache locality.

        Args:
            a: First input matrix of shape (N, N).
            b: Second input matrix of shape (N, N).
            block_size: Size of each tile/block.

        Returns:
            Result matrix of shape (N, N).
        """
        n: int = a.shape[0]
        c: NDArray[np.floating] = np.zeros((n, n), dtype=self.dtype)

        for i in range(0, n, block_size):
            i_end: int = min(i + block_size, n)
            for j in range(0, n, block_size):
                j_end: int = min(j + block_size, n)
                # Accumulate block result
                acc: NDArray[np.floating] = np.zeros(
                    (i_end - i, j_end - j), dtype=self.dtype
                )
                for k in range(0, n, block_size):
                    k_end: int = min(k + block_size, n)
                    # acc += A[i:i_end, k:k_end] @ B[k:k_end, j:j_end]
                    acc += a[i:i_end, k:k_end] @ b[k:k_end, j:j_end]
                c[i:i_end, j:j_end] = acc

        return c

    def _measure_single_size(
        self, size: int
    ) -> tuple[list[float], dict[str, float]]:
        """Measure multiplication time for a single matrix size.

        Performs warmup iterations followed by timed measurement iterations.
        Returns both raw timing data and computed statistics.

        Args:
            size: Dimension of the square matrices to multiply.

        Returns:
            Tuple of (raw_times list, statistics dict).
            Statistics include: mean, median, std, min, max, p50, p90, p95, p99, gflops.

        Raises:
            BenchmarkTimeoutError: If total time exceeds timeout.
            BenchmarkExecutionError: If multiplication fails.
        """
        a, b = self._generate_matrices(size)
        times: list[float] = []

        # Verify result shape
        expected_shape: tuple[int, int] = (size, size)

        # Warmup
        logger.debug("Warming up for size %d (%d iterations)", size, self.warmup)
        for _ in range(self.warmup):
            if self.use_blas:
                _ = a @ b
            else:
                _ = self._blocked_matmul(a, b, self.block_size)

        # Measurement
        logger.debug("Measuring for size %d (%d iterations)", size, self.iterations)
        start_time: float = time.monotonic()
        for i in range(self.iterations):
            # Check timeout
            elapsed: float = time.monotonic() - start_time
            if elapsed > self.timeout:
                raise BenchmarkTimeoutError(self.timeout)

            # Generate fresh matrices for each iteration to avoid cache effects
            if i % 5 == 0:
                a, b = self._generate_matrices(size)

            t0: float = time.perf_counter()
            try:
                if self.use_blas:
                    c: NDArray[np.floating] = a @ b
                else:
                    c = self._blocked_matmul(a, b, self.block_size)
            except Exception as exc:
                raise BenchmarkExecutionError(
                    f"Matrix multiplication failed for size {size}: {exc}"
                ) from exc

            t1: float = time.perf_counter()

            # Validate output shape
            if c.shape != expected_shape:
                raise BenchmarkExecutionError(
                    f"Output shape {c.shape} != expected {expected_shape}"
                )

            times.append(t1 - t0)

        # Compute statistics
        times_arr: NDArray[np.float64] = np.array(times, dtype=np.float64)
        stats: dict[str, float] = self._compute_statistics(times_arr, size)

        return times, stats

    def _compute_statistics(
        self, times: NDArray[np.float64], size: int
    ) -> dict[str, float]:
        """Compute comprehensive statistics from timing data.

        Args:
            times: Array of timing measurements in seconds.
            size: Matrix dimension used for GFLOP/s calculation.

        Returns:
            Dictionary of statistical metrics.
        """
        n: int = len(times)
        mean: float = float(np.mean(times))
        median: float = float(np.median(times))
        std: float = float(np.std(times, ddof=1))
        variance: float = float(np.var(times, ddof=1))
        minimum: float = float(np.min(times))
        maximum: float = float(np.max(times))
        data_range: float = maximum - minimum

        # Percentiles
        p50: float = float(np.percentile(times, 50))
        p75: float = float(np.percentile(times, 75))
        p90: float = float(np.percentile(times, 90))
        p95: float = float(np.percentile(times, 95))
        p99: float = float(np.percentile(times, 99))
        p999: float = float(np.percentile(times, 99.9))

        # GFLOP/s calculation: 2*N^3 - N^2 operations for square matmul
        ops: float = 2.0 * size**3 - size**2
        gflops: float = ops / (mean * 1e9) if mean > 0 else 0.0

        # Coefficient of variation
        cv: float = std / mean if mean > 0 else 0.0

        # Confidence interval (95%)
        z_score: float = 1.96
        ci_lower: float = mean - z_score * (std / np.sqrt(n))
        ci_upper: float = mean + z_score * (std / np.sqrt(n))

        return {
            "mean_s": mean,
            "median_s": median,
            "std_s": std,
            "variance_s": variance,
            "min_s": minimum,
            "max_s": maximum,
            "range_s": data_range,
            "p50_s": p50,
            "p75_s": p75,
            "p90_s": p90,
            "p95_s": p95,
            "p99_s": p99,
            "p999_s": p999,
            "gflops": gflops,
            "cv": cv,
            "ci_lower_s": ci_lower,
            "ci_upper_s": ci_upper,
            "n": n,
        }

    def run(self) -> list[ResultDict]:
        """Execute the full matrix multiplication benchmark.

        Runs the benchmark across all configured matrix sizes and returns
        comprehensive results including raw timing data, statistics, and
        configuration metadata.

        Returns:
            List of result dictionaries, one per matrix size. Each dict
            contains: name, size, dtype, raw_times, and all statistics.

        Raises:
            BenchmarkExecutionError: If a benchmark run fails critically.
            BenchmarkTimeoutError: If a run exceeds timeout.
        """
        logger.info("Starting matrix multiplication benchmark")
        logger.info("Sizes: %s, dtype: %s, BLAS: %s", self.sizes, self.dtype, self.use_blas)

        results: list[ResultDict] = []
        total_start: float = time.monotonic()

        for size in self.sizes:
            logger.info("Benchmarking size %dx%d", size, size)
            try:
                raw_times, stats = self._measure_single_size(size)

                result: ResultDict = {
                    "benchmark": self.name,
                    "size": size,
                    "dtype": str(self.dtype),
                    "use_blas": self.use_blas,
                    "block_size": self.block_size if not self.use_blas else None,
                    "num_threads": self.num_threads,
                    "raw_times": raw_times,
                    **stats,
                }
                results.append(result)

                logger.info(
                    "Size %d: mean=%.6fs, median=%.6fs, std=%.6fs, GFLOPS=%.2f",
                    size, stats["mean_s"], stats["median_s"], stats["std_s"], stats["gflops"],
                )

            except BenchmarkTimeoutError:
                logger.warning("Size %d timed out after %ds", size, self.timeout)
                results.append({
                    "benchmark": self.name,
                    "size": size,
                    "dtype": str(self.dtype),
                    "error": f"Timeout after {self.timeout}s",
                    "raw_times": [],
                })
                break

            except Exception as exc:
                logger.error("Size %d failed: %s", size, exc)
                results.append({
                    "benchmark": self.name,
                    "size": size,
                    "dtype": str(self.dtype),
                    "error": str(exc),
                    "raw_times": [],
                })

        total_elapsed: float = time.monotonic() - total_start
        logger.info(
            "Matrix multiplication benchmark completed in %.2fs. "
            "Ran %d/%d sizes successfully.",
            total_elapsed,
            sum(1 for r in results if "error" not in r),
            len(self.sizes),
        )

        return results

    def run_blocked_comparison(self, size: int = 512) -> dict[str, Any]:
        """Compare blocked vs non-blocked matrix multiplication.

        Performs a detailed comparison between naive blocked multiplication
        and BLAS-optimized multiplication for a given matrix size.

        Args:
            size: Matrix dimension for the comparison.

        Returns:
            Dictionary with comparison results including timing breakdowns
            for both methods.
        """
        logger.info("Running blocked vs BLAS comparison for size %d", size)

        a, b = self._generate_matrices(size)

        # BLAS measurement
        blas_times: list[float] = []
        for _ in range(self.warmup):
            _ = a @ b
        for _ in range(self.iterations):
            t0 = time.perf_counter()
            _ = a @ b
            t1 = time.perf_counter()
            blas_times.append(t1 - t0)

        # Blocked measurement
        blocked_times: list[float] = []
        for _ in range(self.warmup):
            _ = self._blocked_matmul(a, b, self.block_size)
        for _ in range(self.iterations):
            t0 = time.perf_counter()
            _ = self._blocked_matmul(a, b, self.block_size)
            t1 = time.perf_counter()
            blocked_times.append(t1 - t0)

        ops: float = 2.0 * size**3 - size**2
        blas_mean: float = float(np.mean(blas_times))
        blocked_mean: float = float(np.mean(blocked_times))

        return {
            "size": size,
            "blas_mean_s": blas_mean,
            "blas_gflops": ops / (blas_mean * 1e9),
            "blas_std_s": float(np.std(blas_times, ddof=1)),
            "blocked_mean_s": blocked_mean,
            "blocked_gflops": ops / (blocked_mean * 1e9),
            "blocked_std_s": float(np.std(blocked_times, ddof=1)),
            "speedup": blocked_mean / blas_mean if blas_mean > 0 else float("inf"),
            "block_size": self.block_size,
        }

    def profile_memory_usage(self, size: int = 1024) -> dict[str, Any]:
        """Profile memory usage during matrix multiplication.

        Measures the memory footprint of matrices and intermediate results
        for a given size. Useful for understanding memory requirements.

        Args:
            size: Matrix dimension to profile.

        Returns:
            Dictionary with memory usage metrics in bytes.
        """
        a, b = self._generate_matrices(size)
        bytes_per_element: int = np.dtype(self.dtype).itemsize

        matrix_bytes: int = size * size * bytes_per_element
        result_bytes: int = matrix_bytes  # square result

        # Measure peak memory during multiplication
        import tracemalloc
        tracemalloc.start()
        _ = a @ b
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        return {
            "size": size,
            "dtype": str(self.dtype),
            "bytes_per_element": bytes_per_element,
            "matrix_a_bytes": matrix_bytes,
            "matrix_b_bytes": matrix_bytes,
            "result_bytes": result_bytes,
            "total_input_bytes": 2 * matrix_bytes,
            "peak_memory_bytes": peak,
            "current_memory_bytes": current,
            "overhead_bytes": peak - 2 * matrix_bytes - result_bytes,
        }

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "Matrix multiplication performance across various sizes",
            "sizes": self.sizes,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "dtype": str(self.dtype),
            "use_blas": self.use_blas,
            "block_size": self.block_size,
            "num_threads": self.num_threads,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = MatrixMultiplicationBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    # Print summary
    for r in results:
        if "error" not in r:
            print(f"  Size {r['size']:4d}: {r['mean_s']*1000:8.3f}ms  {r['gflops']:8.2f} GFLOPS")
        else:
            print(f"  Size {r['size']:4d}: ERROR - {r['error']}")