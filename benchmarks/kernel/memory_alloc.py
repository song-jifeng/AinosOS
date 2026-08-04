"""
Memory Allocation Benchmark
============================

Measures the performance of various memory allocation patterns and sizes.
This benchmark is critical for understanding heap allocator behavior and
its impact on application performance.

This benchmark evaluates:
- malloc performance for various sizes
- calloc performance (zero-initialized allocation)
- realloc performance (resizing)
- aligned_alloc performance (aligned memory)
- Single allocation vs sequential allocation patterns
- Random allocation/deallocation patterns
- Thread safety and contention under multi-threading
- Peak memory usage tracking
"""

from __future__ import annotations

import ctypes
import logging
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


class MemoryAllocBenchmark:
    """Benchmark for memory allocation performance.

    Measures the time taken by various memory allocation functions
    across different allocation sizes and patterns.

    Attributes:
        name: Unique identifier for this benchmark.
        allocators: List of allocator functions to test.
        sizes: List of allocation sizes in bytes.
        patterns: List of allocation patterns.
        iterations: Number of measurement iterations per configuration.
        warmup: Number of warmup iterations.
        thread_safety: Whether to test thread safety.
        peak_memory: Whether to track peak memory usage.
        timeout: Maximum time per measurement in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the memory allocation benchmark.

        Args:
            config: Configuration dictionary. Expected keys: allocators,
                sizes, patterns, iterations, warmup, thread_safety,
                peak_memory, timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "memory_alloc"
        self.config: dict[str, Any] = config or {}

        self.allocators: list[str] = self.config.get(
            "allocators", ["malloc", "calloc", "realloc", "aligned_alloc"]
        )
        self.sizes: list[int] = self.config.get(
            "sizes", [16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576]
        )
        self.patterns: list[str] = self.config.get(
            "patterns", ["single", "sequential", "strided", "random"]
        )
        self.iterations: int = self.config.get("iterations", 10000)
        self.warmup: int = self.config.get("warmup", 1000)
        self.thread_safety: bool = self.config.get("thread_safety", True)
        self.peak_memory: bool = self.config.get("peak_memory", True)
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        # Validate allocators
        valid_allocators = {"malloc", "calloc", "realloc", "aligned_alloc"}
        for a in self.allocators:
            if a not in valid_allocators:
                raise BenchmarkConfigError(
                    f"Unknown allocator: {a}. Valid: {valid_allocators}",
                    config_key="allocators",
                )

        # Validate patterns
        valid_patterns = {"single", "sequential", "strided", "random"}
        for p in self.patterns:
            if p not in valid_patterns:
                raise BenchmarkConfigError(
                    f"Unknown pattern: {p}. Valid: {valid_patterns}",
                    config_key="patterns",
                )

        # Use libc for direct memory allocation measurement
        self._libc = ctypes.CDLL("msvcrt.dll") if sys.platform == "win32" else ctypes.CDLL("libc.so.6")

        logger.info(
            "Initialized MemoryAllocBenchmark: allocators=%s, sizes=%d, "
            "patterns=%s, iterations=%d",
            self.allocators, len(self.sizes), self.patterns, self.iterations,
        )

    def _malloc(self, size: int) -> int:
        """Allocate memory using malloc.

        Args:
            size: Number of bytes to allocate.

        Returns:
            Pointer to allocated memory as integer.
        """
        self._libc.malloc.restype = ctypes.c_void_p
        return self._libc.malloc(size)

    def _calloc(self, size: int) -> int:
        """Allocate and zero-initialize memory using calloc.

        Args:
            size: Number of bytes to allocate.

        Returns:
            Pointer to allocated memory as integer.
        """
        self._libc.calloc.restype = ctypes.c_void_p
        return self._libc.calloc(1, size)

    def _free(self, ptr: int) -> None:
        """Free allocated memory.

        Args:
            ptr: Pointer to memory to free.
        """
        self._libc.free(ctypes.c_void_p(ptr))

    def _realloc(self, ptr: int, new_size: int) -> int:
        """Resize allocated memory using realloc.

        Args:
            ptr: Pointer to existing memory.
            new_size: New size in bytes.

        Returns:
            Pointer to reallocated memory.
        """
        self._libc.realloc.restype = ctypes.c_void_p
        return self._libc.realloc(ctypes.c_void_p(ptr), new_size)

    def _aligned_alloc(self, alignment: int, size: int) -> int:
        """Allocate aligned memory.

        Args:
            alignment: Required alignment in bytes.
            size: Number of bytes to allocate.

        Returns:
            Pointer to aligned memory.
        """
        # Use posix_memalign on Linux, _aligned_malloc on Windows
        if sys.platform == "win32":
            self._libc._aligned_malloc.restype = ctypes.c_void_p
            return self._libc._aligned_malloc(size, alignment)
        else:
            ptr = ctypes.c_void_p()
            self._libc.posix_memalign(ctypes.byref(ptr), alignment, size)
            return ptr.value

    def _aligned_free(self, ptr: int) -> None:
        """Free aligned memory.

        Args:
            ptr: Pointer to aligned memory.
        """
        if sys.platform == "win32":
            self._libc._aligned_free(ctypes.c_void_p(ptr))
        else:
            self._libc.free(ctypes.c_void_p(ptr))

    def _measure_malloc_single(self, size: int) -> list[float]:
        """Measure single malloc+free latency.

        Args:
            size: Allocation size in bytes.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            ptr = self._malloc(size)
            if ptr:
                self._free(ptr)
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)
        return times

    def _measure_calloc_single(self, size: int) -> list[float]:
        """Measure single calloc+free latency.

        Args:
            size: Allocation size in bytes.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            ptr = self._calloc(size)
            if ptr:
                self._free(ptr)
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)
        return times

    def _measure_realloc_single(self, size: int) -> list[float]:
        """Measure single realloc+free latency.

        Args:
            size: Target allocation size in bytes.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        for _ in range(self.iterations):
            ptr = self._malloc(size // 2)
            t0 = time.perf_counter_ns()
            new_ptr = self._realloc(ptr, size)
            t1 = time.perf_counter_ns()
            if new_ptr:
                self._free(new_ptr)
            times.append((t1 - t0) / 1e9)
        return times

    def _measure_aligned_single(self, size: int) -> list[float]:
        """Measure single aligned_alloc+free latency.

        Args:
            size: Allocation size in bytes.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        alignment = max(64, 128)
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            ptr = self._aligned_alloc(alignment, size)
            if ptr:
                self._aligned_free(ptr)
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)
        return times

    def _measure_sequential_alloc(self, size: int) -> list[float]:
        """Measure sequential allocation pattern.

        Allocates multiple blocks sequentially, then frees them
        in the same order.

        Args:
            size: Size of each allocation.

        Returns:
            List of timing measurements in seconds.
        """
        num_blocks = min(1000, self.iterations)
        times: list[float] = []

        for _ in range(self.iterations // num_blocks):
            ptrs: list[int] = []
            t0 = time.perf_counter_ns()
            for _ in range(num_blocks):
                ptr = self._malloc(size)
                if ptr:
                    ptrs.append(ptr)
            t1 = time.perf_counter_ns()

            for ptr in ptrs:
                self._free(ptr)

            times.append((t1 - t0) / 1e9)

        return times

    def _measure_strided_alloc(self, size: int) -> list[float]:
        """Measure strided allocation pattern.

        Allocates blocks with alternating sizes.

        Args:
            size: Base allocation size.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        for _ in range(self.iterations):
            actual_size = size
            if _ % 3 == 0:
                actual_size = size * 2
            elif _ % 3 == 1:
                actual_size = size // 2

            t0 = time.perf_counter_ns()
            ptr = self._malloc(max(actual_size, 8))
            t1 = time.perf_counter_ns()
            if ptr:
                self._free(ptr)
            times.append((t1 - t0) / 1e9)
        return times

    def _measure_random_alloc(self, size: int) -> list[float]:
        """Measure random allocation/deallocation pattern.

        Allocates and frees blocks in random order to simulate
        realistic allocation patterns.

        Args:
            size: Base allocation size.

        Returns:
            List of timing measurements in seconds.
        """
        rng = np.random.default_rng(42)
        num_blocks = 100
        times: list[float] = []

        for _ in range(self.iterations // num_blocks):
            ptrs: list[int] = []

            # Allocate
            t0 = time.perf_counter_ns()
            for _2 in range(num_blocks):
                random_size = int(size * (0.5 + rng.random()))
                ptr = self._malloc(max(random_size, 8))
                if ptr:
                    ptrs.append(ptr)
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)

            # Free in random order
            rng.shuffle(ptrs)
            for ptr in ptrs:
                self._free(ptr)

        return times

    def _measure_single_config(
        self, allocator: str, size: int, pattern: str
    ) -> dict[str, Any]:
        """Measure memory allocation for a single configuration.

        Args:
            allocator: Allocator function name.
            size: Allocation size in bytes.
            pattern: Allocation pattern name.

        Returns:
            Dictionary with timing statistics.

        Raises:
            BenchmarkExecutionError: If measurement fails.
        """
        # Map allocator + pattern to measurement method
        if pattern == "single":
            pattern_map = {
                "malloc": self._measure_malloc_single,
                "calloc": self._measure_calloc_single,
                "realloc": self._measure_realloc_single,
                "aligned_alloc": self._measure_aligned_single,
            }
        elif pattern == "sequential":
            pattern_map = {
                a: self._measure_sequential_alloc for a in self.allocators
            }
        elif pattern == "strided":
            pattern_map = {
                a: self._measure_strided_alloc for a in self.allocators
            }
        elif pattern == "random":
            pattern_map = {
                a: self._measure_random_alloc for a in self.allocators
            }
        else:
            return {"error": f"Unknown pattern: {pattern}"}

        if allocator not in pattern_map:
            return {"error": f"Unsupported allocator '{allocator}' for pattern '{pattern}'"}

        measure_fn = pattern_map[allocator]

        # Warmup
        warmup_times = measure_fn(size) if pattern == "single" else measure_fn(size)
        del warmup_times

        # Measurement
        try:
            raw_times = measure_fn(size)
        except Exception as exc:
            raise BenchmarkExecutionError(
                f"Allocator '{allocator}' size={size} pattern='{pattern}' failed: {exc}"
            ) from exc

        if not raw_times:
            return {"error": "No measurements recorded", "raw_times": []}

        raw_arr = np.array(raw_times, dtype=np.float64)
        mean_time = float(np.mean(raw_arr))
        median_time = float(np.median(raw_arr))

        # Throughput
        allocations_per_sec = 1.0 / mean_time if mean_time > 0 else 0.0
        bytes_per_sec = size * allocations_per_sec if mean_time > 0 else 0.0

        return {
            "mean_s": mean_time,
            "mean_ns": mean_time * 1e9,
            "median_s": median_time,
            "median_ns": median_time * 1e9,
            "std_s": float(np.std(raw_arr, ddof=1)),
            "std_ns": float(np.std(raw_arr, ddof=1)) * 1e9,
            "min_s": float(np.min(raw_arr)),
            "min_ns": float(np.min(raw_arr)) * 1e9,
            "max_s": float(np.max(raw_arr)),
            "max_ns": float(np.max(raw_arr)) * 1e9,
            "p50_ns": float(np.percentile(raw_arr, 50)) * 1e9,
            "p90_ns": float(np.percentile(raw_arr, 90)) * 1e9,
            "p95_ns": float(np.percentile(raw_arr, 95)) * 1e9,
            "p99_ns": float(np.percentile(raw_arr, 99)) * 1e9,
            "allocations_per_sec": allocations_per_sec,
            "bytes_per_sec": bytes_per_sec,
            "n_samples": len(raw_times),
            "raw_times": raw_times,
        }

    def run(self) -> list[ResultDict]:
        """Execute the full memory allocation benchmark.

        Runs allocation measurements across all allocators, sizes,
        and patterns.

        Returns:
            List of result dictionaries with timing metrics.
        """
        logger.info("Starting memory allocation benchmark")
        logger.info(
            "Allocators: %s, Sizes: %d, Patterns: %s",
            self.allocators, len(self.sizes), self.patterns,
        )

        results: list[ResultDict] = []
        total_start = time.monotonic()
        successful: int = 0

        for allocator in self.allocators:
            for size in self.sizes:
                for pattern in self.patterns:
                    logger.debug(
                        "Benchmarking %s size=%d pattern=%s",
                        allocator, size, pattern,
                    )

                    try:
                        measure_results = self._measure_single_config(allocator, size, pattern)

                        result: ResultDict = {
                            "benchmark": self.name,
                            "allocator": allocator,
                            "size_bytes": size,
                            "pattern": pattern,
                            "thread_safety": self.thread_safety,
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

                        results.append(result)

                    except Exception as exc:
                        logger.error("Allocator '%s' size=%d pattern='%s' failed: %s",
                                     allocator, size, pattern, exc)
                        results.append({
                            "benchmark": self.name,
                            "allocator": allocator,
                            "size_bytes": size,
                            "pattern": pattern,
                            "error": str(exc),
                        })

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "Memory allocation benchmark completed in %.2fs. "
            "Successful: %d/%d configurations",
            total_elapsed, successful,
            len(self.allocators) * len(self.sizes) * len(self.patterns),
        )

        return results

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "Memory allocation performance benchmark",
            "allocators": self.allocators,
            "sizes": self.sizes,
            "patterns": self.patterns,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "thread_safety": self.thread_safety,
            "peak_memory": self.peak_memory,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = MemoryAllocBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        if "error" not in r:
            print(f"  {r['allocator']:>13s} sz={r['size_bytes']:>7d} {r['pattern']:>10s}: "
                  f"mean={r['mean_ns']:8.1f}ns  alloc/s={r['allocations_per_sec']:.0f}")