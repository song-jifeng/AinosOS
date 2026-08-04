"""
Cache Latency Benchmark
========================

Measures the latency of accessing memory at various buffer sizes and stride
patterns to probe the cache hierarchy. By analyzing access latency across
buffer sizes that exceed L1, L2, L3 cache capacities, we can identify cache
boundaries and measure cache hit/miss latencies.

This benchmark evaluates:
- Sequential access latency at various strides
- Random access latency (pointer-chasing pattern)
- Cache line size detection
- L1/L2/L3 cache hit latencies
- TLB miss penalties
- Prefetch effectiveness
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


# Size parsing
_SIZE_UNITS: dict[str, int] = {
    "B": 1,
    "KB": 1024,
    "MB": 1024 * 1024,
    "GB": 1024 * 1024 * 1024,
}


def _parse_size(size_str: str) -> int:
    """Parse a human-readable size string into bytes.

    Args:
        size_str: Size string like "1KB", "4MB", "64B".

    Returns:
        Size in bytes as integer.

    Raises:
        ValueError: If the size string cannot be parsed.
    """
    size_str = size_str.strip().upper()
    for unit, multiplier in sorted(_SIZE_UNITS.items(), key=lambda x: -len(x[0])):
        if size_str.endswith(unit):
            try:
                return int(float(size_str[: -len(unit)]) * multiplier)
            except ValueError:
                continue
    try:
        return int(size_str)
    except ValueError:
        raise ValueError(f"Cannot parse size string: {size_str}")


def _format_bytes(n_bytes: int) -> str:
    """Format byte count to a human-readable string.

    Args:
        n_bytes: Number of bytes.

    Returns:
        Formatted string.
    """
    if n_bytes < 1024:
        return f"{n_bytes}B"
    elif n_bytes < 1024 * 1024:
        return f"{n_bytes / 1024:.1f}KB"
    elif n_bytes < 1024 * 1024 * 1024:
        return f"{n_bytes / (1024 * 1024):.1f}MB"
    else:
        return f"{n_bytes / (1024 * 1024 * 1024):.2f}GB"


class CacheLatencyBenchmark:
    """Benchmark for measuring memory access latency across the cache hierarchy.

    Uses carefully constructed access patterns to measure:
    - Cache line fill latency from L1, L2, L3
    - Main memory latency (DRAM)
    - TLB miss penalties
    - Prefetch effectiveness

    Attributes:
        name: Unique identifier for this benchmark.
        buffer_sizes: List of buffer sizes to test (human-readable strings).
        buffer_bytes: List of buffer sizes converted to bytes.
        strides: List of stride values (in elements) for access patterns.
        iterations: Number of measurement iterations per configuration.
        warmup: Number of warmup iterations.
        access_pattern: "sequential" or "random" access pattern.
        prefetch_hint: Whether to use software prefetch hints.
        timeout: Maximum time per measurement in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the cache latency benchmark.

        Args:
            config: Configuration dictionary. Expected keys: buffer_sizes,
                strides, iterations, warmup, access_pattern, prefetch_hint,
                timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "cache_latency"
        self.config: dict[str, Any] = config or {}

        size_strings: list[str] = self.config.get(
            "buffer_sizes",
            ["1KB", "4KB", "16KB", "64KB", "256KB", "1MB", "4MB", "16MB", "64MB"],
        )
        self.buffer_bytes: list[int] = [_parse_size(s) for s in size_strings]
        self.buffer_sizes: list[str] = [_format_bytes(b) for b in self.buffer_bytes]

        self.strides: list[int] = self.config.get(
            "strides", [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]
        )
        self.iterations: int = self.config.get("iterations", DEFAULT_BENCHMARK_ITERATIONS)
        self.warmup: int = self.config.get("warmup", DEFAULT_WARMUP_ITERATIONS)
        self.access_pattern: str = self.config.get("access_pattern", "random")
        self.prefetch_hint: bool = self.config.get("prefetch_hint", False)
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        # Validate
        valid_patterns = ("sequential", "random", "pointer_chasing")
        if self.access_pattern not in valid_patterns:
            raise BenchmarkConfigError(
                f"access_pattern must be one of {valid_patterns}, got {self.access_pattern}",
                config_key="access_pattern",
            )
        for s in self.strides:
            if s < 1:
                raise BenchmarkConfigError(f"Stride must be >= 1, got {s}", config_key="strides")

        # Element size for access (8 bytes = 64-bit)
        self.element_size: int = 8
        self.cache_line_size: int = 64

        logger.info(
            "Initialized CacheLatencyBenchmark: %d buffer sizes, "
            "%d strides, pattern=%s, iterations=%d",
            len(self.buffer_bytes), len(self.strides),
            self.access_pattern, self.iterations,
        )

    def _build_pointer_chain(
        self, buffer: NDArray[np.int64], stride: int
    ) -> NDArray[np.int64]:
        """Build a linked list (pointer chain) for random access latency measurement.

        Creates a randomized permutation of indices such that following the chain
        forces a full cache miss at each step.

        Args:
            buffer: The buffer array to use for storage.
            stride: Number of elements to skip between accesses.

        Returns:
            The buffer with pointer chain initialized.
        """
        n: int = len(buffer)
        n_used: int = n // stride
        if n_used < 2:
            buffer[0] = 0
            return buffer

        # Create a random permutation of indices
        rng = np.random.default_rng(42)
        indices: NDArray[np.int64] = rng.permutation(n_used).astype(np.int64)

        # Chain: each element points to the next
        for i in range(n_used - 1):
            buffer[indices[i] * stride] = indices[i + 1] * stride
        # Last element points back to first
        buffer[indices[-1] * stride] = indices[0] * stride

        return buffer

    def _measure_sequential_latency(
        self, buffer: NDArray[np.int64], stride: int
    ) -> float:
        """Measure sequential access latency with a given stride.

        Walks through the buffer with a fixed stride, summing values to
        prevent optimization.

        Args:
            buffer: The buffer to access.
            stride: Number of elements between accesses.

        Returns:
            Average access time in nanoseconds per element.
        """
        n: int = len(buffer)
        total: int = 0
        _ = buffer[0]  # touch

        t0 = time.perf_counter_ns()
        for i in range(0, n, stride):
            total += buffer[i]
        t1 = time.perf_counter_ns()

        # Prevent optimization
        if total == 0xDEADBEEF:
            logger.debug("Unlikely path")

        n_accesses: int = n // stride
        if n_accesses == 0:
            return 0.0
        return (t1 - t0) / n_accesses

    def _measure_random_latency(
        self, buffer: NDArray[np.int64], stride: int
    ) -> float:
        """Measure random access latency using pointer chasing.

        Follows a linked list through the buffer, forcing cache misses.
        This is the most accurate way to measure main memory latency.

        Args:
            buffer: The buffer with pointer chain initialized.
            stride: Stride used for the pointer chain.

        Returns:
            Average access time in nanoseconds per element.
        """
        n: int = len(buffer)
        n_used: int = n // stride
        if n_used < 2:
            return 0.0

        # Follow the chain multiple times for warmup
        idx: int = 0
        for _ in range(100):
            idx = buffer[idx]

        # Measure the chain traversal
        t0 = time.perf_counter_ns()
        n_accesses: int = 0
        idx = 0
        for _ in range(min(n_used, 10000)):
            idx = buffer[idx]
            n_accesses += 1
            if idx == 0:
                break
        t1 = time.perf_counter_ns()

        if n_accesses == 0:
            return 0.0
        return (t1 - t0) / n_accesses

    def _measure_strided_latency(
        self, buffer: NDArray[np.int64], stride: int
    ) -> float:
        """Measure strided access latency (sequential scan with stride).

        Useful for detecting cache line and TLB boundaries.

        Args:
            buffer: The buffer to access.
            stride: Number of elements between each access.

        Returns:
            Average access time in nanoseconds per element.
        """
        n: int = len(buffer)
        total: int = 0
        _ = buffer[0]

        t0 = time.perf_counter_ns()
        for i in range(0, n, stride * self.cache_line_size // self.element_size):
            total += buffer[i]
        t1 = time.perf_counter_ns()

        n_accesses = n // (stride * self.cache_line_size // self.element_size)
        if n_accesses == 0:
            return 0.0
        return (t1 - t0) / n_accesses

    def _measure_single_config(
        self, buf_size: int, stride: int
    ) -> dict[str, float | list[float] | None]:
        """Measure latency for a single buffer size and stride combination.

        Args:
            buf_size: Buffer size in bytes.
            stride: Access stride in elements.

        Returns:
            Dictionary with latency statistics.

        Raises:
            BenchmarkTimeoutError: If measurement exceeds timeout.
            BenchmarkExecutionError: If allocation fails.
        """
        num_elements: int = buf_size // self.element_size

        try:
            buffer: NDArray[np.int64] = np.zeros(num_elements, dtype=np.int64)
        except MemoryError:
            return {"error": f"Memory allocation failed for {_format_bytes(buf_size)}"}

        # Initialize pointer chain if random access
        if self.access_pattern == "pointer_chasing":
            buffer = self._build_pointer_chain(buffer, stride)

        latencies: list[float] = []

        try:
            # Warmup
            for _ in range(self.warmup):
                if self.access_pattern == "sequential":
                    _ = self._measure_sequential_latency(buffer, stride)
                elif self.access_pattern == "pointer_chasing":
                    _ = self._measure_random_latency(buffer, stride)
                else:
                    _ = self._measure_strided_latency(buffer, stride)

            # Measurement
            start_time = time.monotonic()
            for _ in range(self.iterations):
                if time.monotonic() - start_time > self.timeout:
                    raise BenchmarkTimeoutError(self.timeout)

                if self.access_pattern == "sequential":
                    lat = self._measure_sequential_latency(buffer, stride)
                elif self.access_pattern == "pointer_chasing":
                    lat = self._measure_random_latency(buffer, stride)
                else:
                    lat = self._measure_strided_latency(buffer, stride)

                if lat > 0:
                    latencies.append(lat)

        except Exception as exc:
            return {"error": str(exc), "raw_times": []}

        if not latencies:
            return {"error": "No valid measurements", "raw_times": []}

        # Compute statistics
        lat_arr: NDArray[np.float64] = np.array(latencies, dtype=np.float64)
        mean_lat: float = float(np.mean(lat_arr))
        median_lat: float = float(np.median(lat_arr))
        std_lat: float = float(np.std(lat_arr, ddof=1))
        min_lat: float = float(np.min(lat_arr))
        max_lat: float = float(np.max(lat_arr))

        # Clock cycles estimation (assuming typical 2-4 GHz CPU)
        cycles_estimate: float = mean_lat * 3.0  # rough at 3 GHz

        return {
            "mean_ns": mean_lat,
            "median_ns": median_lat,
            "std_ns": std_lat,
            "min_ns": min_lat,
            "max_ns": max_lat,
            "p50_ns": float(np.percentile(lat_arr, 50)),
            "p75_ns": float(np.percentile(lat_arr, 75)),
            "p90_ns": float(np.percentile(lat_arr, 90)),
            "p95_ns": float(np.percentile(lat_arr, 95)),
            "p99_ns": float(np.percentile(lat_arr, 99)),
            "estimated_cycles": cycles_estimate,
            "n_samples": len(latencies),
            "raw_times": latencies,
        }

    def run(self) -> list[ResultDict]:
        """Execute the full cache latency benchmark.

        Runs latency measurements across all buffer sizes and strides.

        Returns:
            List of result dictionaries with latency metrics.

        Raises:
            BenchmarkExecutionError: If all measurements fail.
        """
        logger.info("Starting cache latency benchmark")
        logger.info(
            "Buffer sizes: %d, Strides: %d, Pattern: %s",
            len(self.buffer_bytes), len(self.strides), self.access_pattern,
        )

        results: list[ResultDict] = []
        total_start = time.monotonic()
        successful: int = 0

        for buf_size, size_label in zip(self.buffer_bytes, self.buffer_sizes):
            logger.info("Benchmarking buffer size %s", size_label)

            for stride in self.strides:
                config_result = self._measure_single_config(buf_size, stride)

                result: ResultDict = {
                    "benchmark": self.name,
                    "buffer_size_bytes": buf_size,
                    "buffer_size_label": size_label,
                    "stride_elements": stride,
                    "stride_bytes": stride * self.element_size,
                    "access_pattern": self.access_pattern,
                    "prefetch_hint": self.prefetch_hint,
                }

                if "error" in config_result:
                    result["error"] = config_result["error"]
                else:
                    for key, value in config_result.items():
                        if isinstance(value, (int, float, str)):
                            result[key] = value
                        elif key == "raw_times":
                            result[key] = value  # type: ignore[assignment]
                    successful += 1

                    mean_ns = config_result.get("mean_ns", 0)
                    logger.debug(
                        "  Stride %3d: mean=%.1f ns, median=%.1f ns",
                        stride, mean_ns, config_result.get("median_ns", 0),
                    )

                results.append(result)

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "Cache latency benchmark completed in %.2fs. "
            "Successful: %d/%d configurations",
            total_elapsed, successful, len(self.buffer_bytes) * len(self.strides),
        )

        return results

    def detect_cache_sizes(self) -> dict[str, float]:
        """Detect cache sizes by analyzing latency vs buffer size.

        Runs sequential access at stride=1 across all buffer sizes to
        identify where latency increases (indicating cache misses).

        Returns:
            Dictionary with estimated cache sizes and latencies.
        """
        saved_pattern = self.access_pattern
        saved_strides = self.strides
        self.access_pattern = "sequential"
        self.strides = [1]

        results = self.run()

        self.access_pattern = saved_pattern
        self.strides = saved_strides

        # Extract latencies at each buffer size
        latencies: dict[str, float] = {}
        for r in results:
            if "mean_ns" in r and not r.get("error"):
                label = str(r["buffer_size_label"])
                latencies[label] = float(r["mean_ns"])  # type: ignore[arg-type]

        # Detect significant jumps
        sorted_sizes = sorted(latencies.keys(), key=lambda x: _parse_size(x))
        jumps: list[dict[str, Any]] = []
        prev_bw = 0.0
        for i, size_label in enumerate(sorted_sizes):
            lat = latencies[size_label]
            if i > 0:
                prev_lat = latencies[sorted_sizes[i - 1]]
                if prev_lat > 0 and lat / prev_lat > 1.5:
                    jumps.append({
                        "size": size_label,
                        "latency_ns": lat,
                        "prev_latency_ns": prev_lat,
                        "ratio": lat / prev_lat,
                    })
            prev_bw = lat

        # Estimate cache levels
        cache_info: dict[str, float] = {"l1_latency_ns": 0, "l2_latency_ns": 0, "l3_latency_ns": 0, "ram_latency_ns": 0}
        for i, jump in enumerate(jumps):
            if i == 0:
                # L1 -> L2 boundary
                cache_info["l1_latency_ns"] = jump["prev_latency_ns"]
                cache_info["l2_latency_ns"] = jump["latency_ns"]
            elif i == 1:
                # L2 -> L3 boundary
                cache_info["l3_latency_ns"] = jump["latency_ns"]
            elif i == 2:
                # L3 -> RAM boundary
                cache_info["ram_latency_ns"] = jump["latency_ns"]

        # Take first buffer size as L1 if available
        if sorted_sizes and cache_info["l1_latency_ns"] == 0:
            cache_info["l1_latency_ns"] = latencies.get(sorted_sizes[0], 0)

        # Take last buffer size as RAM if available
        if sorted_sizes and cache_info["ram_latency_ns"] == 0:
            cache_info["ram_latency_ns"] = latencies.get(sorted_sizes[-1], 0)

        return cache_info

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "Memory access latency measurement across cache hierarchy",
            "buffer_sizes": self.buffer_sizes,
            "strides": self.strides,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "access_pattern": self.access_pattern,
            "prefetch_hint": self.prefetch_hint,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = CacheLatencyBenchmark()

    # Quick cache detection
    cache_info = bench.detect_cache_sizes()
    print("Cache hierarchy estimate:")
    for key, val in cache_info.items():
        print(f"  {key}: {val:.1f} ns")

    # Full benchmark
    results = bench.run()
    print(f"\nCompleted {len(results)} benchmark runs")