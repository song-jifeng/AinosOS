"""
Memory Bandwidth Benchmark
===========================

Measures the achievable memory bandwidth of the system by performing sequential
and random read/write operations on buffers of varying sizes. This benchmark
helps identify the memory hierarchy characteristics including L1/L2/L3 cache
bandwidth and main memory bandwidth.

This benchmark evaluates:
- Sequential read bandwidth at various buffer sizes
- Sequential write bandwidth at various buffer sizes
- Copy bandwidth (read + write simultaneously)
- Random access patterns vs sequential access patterns
- Cache hierarchy effects (cache line fills, TLB misses)
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


# Size parsing helper
_SIZE_UNITS: dict[str, int] = {
    "B": 1,
    "KB": 1024,
    "MB": 1024 * 1024,
    "GB": 1024 * 1024 * 1024,
    "K": 1024,
    "M": 1024 * 1024,
    "G": 1024 * 1024 * 1024,
}


def _parse_size(size_str: str) -> int:
    """Parse a human-readable size string into bytes.

    Args:
        size_str: Size string like "1KB", "4MB", "64B", "1GB".

    Returns:
        Size in bytes as integer.

    Raises:
        ValueError: If the size string cannot be parsed.
    """
    size_str = size_str.strip().upper()
    for unit, multiplier in sorted(_SIZE_UNITS.items(), key=lambda x: -len(x[0])):
        if size_str.endswith(unit):
            numeric_part = size_str[: -len(unit)]
            try:
                return int(float(numeric_part) * multiplier)
            except ValueError:
                raise ValueError(f"Cannot parse size string: {size_str}")
    try:
        return int(size_str)
    except ValueError:
        raise ValueError(f"Cannot parse size string: {size_str}")


class MemoryBandwidthBenchmark:
    """Benchmark for measuring memory bandwidth across the memory hierarchy.

    Measures achievable read, write, and copy bandwidth for various buffer sizes
    to characterize the memory subsystem performance.

    Attributes:
        name: Unique identifier for this benchmark.
        buffer_sizes: List of buffer sizes to test (human-readable strings).
        buffer_bytes: List of buffer sizes converted to bytes.
        operations: List of operations to perform (read, write, copy, read_write).
        iterations: Number of measurement iterations per buffer size.
        warmup: Number of warmup iterations before measurement.
        sequential: Whether to use sequential access patterns.
        random_access_ratio: Fraction of accesses that are random vs sequential.
        timeout: Maximum time per measurement in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the memory bandwidth benchmark.

        Args:
            config: Configuration dictionary. Expected keys: buffer_sizes,
                operations, iterations, warmup, sequential, random_access_ratio,
                timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "memory_bandwidth"
        self.config: dict[str, Any] = config or {}

        size_strings: list[str] = self.config.get(
            "buffer_sizes",
            ["1KB", "4KB", "16KB", "64KB", "256KB", "1MB", "4MB", "16MB", "64MB", "256MB"],
        )
        self.buffer_bytes: list[int] = [_parse_size(s) for s in size_strings]
        self.buffer_sizes: list[str] = [self._format_bytes(b) for b in self.buffer_bytes]

        self.operations: list[str] = self.config.get(
            "operations", ["read", "write", "copy", "read_write"]
        )
        self.iterations: int = self.config.get("iterations", DEFAULT_BENCHMARK_ITERATIONS)
        self.warmup: int = self.config.get("warmup", DEFAULT_WARMUP_ITERATIONS)
        self.sequential: bool = self.config.get("sequential", True)
        self.random_access_ratio: float = self.config.get("random_access_ratio", 0.1)
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        # Validate
        for op in self.operations:
            if op not in ("read", "write", "copy", "read_write"):
                raise BenchmarkConfigError(f"Unknown operation: {op}", config_key="operations")
        if not 0.0 <= self.random_access_ratio <= 1.0:
            raise BenchmarkConfigError(
                "random_access_ratio must be in [0, 1]", config_key="random_access_ratio"
            )

        # Determine cache line size (usually 64 bytes)
        self.cache_line_size: int = 64

        logger.info(
            "Initialized MemoryBandwidthBenchmark: %d buffer sizes, "
            "operations=%s, iterations=%d",
            len(self.buffer_bytes), self.operations, self.iterations,
        )

    @staticmethod
    def _format_bytes(n_bytes: int) -> str:
        """Format byte count to a human-readable string.

        Args:
            n_bytes: Number of bytes.

        Returns:
            Formatted string (e.g., "1.00KB", "4.00MB").
        """
        if n_bytes < 1024:
            return f"{n_bytes}B"
        elif n_bytes < 1024 * 1024:
            return f"{n_bytes / 1024:.1f}KB"
        elif n_bytes < 1024 * 1024 * 1024:
            return f"{n_bytes / (1024 * 1024):.1f}MB"
        else:
            return f"{n_bytes / (1024 * 1024 * 1024):.2f}GB"

    def _allocate_buffer(self, size: int) -> NDArray[np.uint8]:
        """Allocate a byte buffer of the given size.

        Uses NumPy's allocation which respects page boundaries.

        Args:
            size: Buffer size in bytes.

        Returns:
            Zero-initialized byte buffer.
        """
        return np.zeros(size, dtype=np.uint8)

    def _measure_read_bandwidth(self, buffer: NDArray[np.uint8]) -> float:
        """Measure sequential read bandwidth for a buffer.

        Performs a sequential read of every element in the buffer, summing
        values to prevent compiler optimization from removing the read.

        Args:
            buffer: The buffer to read from.

        Returns:
            Time in seconds for the read operation.
        """
        view: NDArray[np.uint64] = buffer.view(np.uint64)
        _ = np.sum(view)
        t0 = time.perf_counter()
        _ = np.sum(view)
        t1 = time.perf_counter()
        return t1 - t0

    def _measure_write_bandwidth(self, buffer: NDArray[np.uint8]) -> float:
        """Measure sequential write bandwidth for a buffer.

        Writes a pattern to every element of the buffer.

        Args:
            buffer: The buffer to write to.

        Returns:
            Time in seconds for the write operation.
        """
        pattern: int = 0xAA
        t0 = time.perf_counter()
        buffer[:] = pattern
        t1 = time.perf_counter()
        return t1 - t0

    def _measure_copy_bandwidth(
        self, src: NDArray[np.uint8], dst: NDArray[np.uint8]
    ) -> float:
        """Measure sequential copy bandwidth (read + write).

        Copies data from source buffer to destination buffer.

        Args:
            src: Source buffer to read from.
            dst: Destination buffer to write to.

        Returns:
            Time in seconds for the copy operation.
        """
        t0 = time.perf_counter()
        dst[:] = src[:]
        t1 = time.perf_counter()
        return t1 - t0

    def _measure_read_write_bandwidth(self, buffer: NDArray[np.uint8]) -> float:
        """Measure combined read-write bandwidth.

        Reads each element, adds a value, and writes it back (in-place update).

        Args:
            buffer: The buffer to read from and write to.

        Returns:
            Time in seconds for the read-modify-write operation.
        """
        value: int = 1
        t0 = time.perf_counter()
        buffer[:] = buffer[:] + value
        t1 = time.perf_counter()
        return t1 - t0

    def _measure_random_access_read(self, buffer: NDArray[np.uint8]) -> float:
        """Measure random access read bandwidth.

        Reads from random positions in the buffer using a random walk pattern
        to minimize cache line reuse.

        Args:
            buffer: The buffer to read from.

        Returns:
            Time in seconds for the random read operation.
        """
        n: int = len(buffer)
        if n <= 1:
            return 0.0

        # Generate random walk indices using deterministic sequence
        rng = np.random.default_rng(42)
        indices: NDArray[np.int64] = rng.integers(0, n, min(n, 100000), dtype=np.int64)

        # Touch first to bring into memory
        _ = buffer[indices].sum()

        t0 = time.perf_counter()
        _ = buffer[indices].sum()
        t1 = time.perf_counter()
        return t1 - t0

    def _measure_single_buffer(
        self, buf_size: int
    ) -> dict[str, dict[str, float | list[float]]]:
        """Measure all operations for a single buffer size.

        Args:
            buf_size: Buffer size in bytes.

        Returns:
            Nested dictionary mapping operation names to their results.
            Each result contains: mean, median, std, min, max, bandwidth_GBs,
            and raw_times.

        Raises:
            BenchmarkTimeoutError: If measurement exceeds timeout.
            BenchmarkExecutionError: If measurement fails.
        """
        results: dict[str, dict[str, float | list[float]]] = {}

        try:
            buf: NDArray[np.uint8] = self._allocate_buffer(buf_size)
            # Touch memory to ensure physical pages are allocated
            buf.fill(0)
        except MemoryError:
            logger.warning("Cannot allocate buffer of size %d bytes", buf_size)
            for op in self.operations:
                results[op] = {"error": f"Memory allocation failed for {buf_size} bytes"}
            return results

        for operation in self.operations:
            logger.debug("Measuring %s for buffer size %s", operation, self._format_bytes(buf_size))

            times: list[float] = []

            try:
                # Warmup
                for _ in range(self.warmup):
                    if operation == "read":
                        _ = self._measure_read_bandwidth(buf)
                    elif operation == "write":
                        _ = self._measure_write_bandwidth(buf)
                    elif operation == "copy":
                        dst = self._allocate_buffer(buf_size)
                        _ = self._measure_copy_bandwidth(buf, dst)
                    elif operation == "read_write":
                        _ = self._measure_read_write_bandwidth(buf)

                # Measurement
                total_start = time.monotonic()
                for i in range(self.iterations):
                    if time.monotonic() - total_start > self.timeout:
                        raise BenchmarkTimeoutError(self.timeout)

                    if operation == "read":
                        t = self._measure_read_bandwidth(buf)
                    elif operation == "write":
                        t = self._measure_write_bandwidth(buf)
                    elif operation == "copy":
                        dst = self._allocate_buffer(buf_size)
                        t = self._measure_copy_bandwidth(buf, dst)
                    elif operation == "read_write":
                        t = self._measure_read_write_bandwidth(buf)
                    else:
                        raise BenchmarkExecutionError(f"Unknown operation: {operation}")

                    times.append(t)

                # Also measure random access for comparison
                random_times: list[float] = []
                if self.random_access_ratio > 0:
                    for _ in range(min(self.iterations, 20)):
                        rt = self._measure_random_access_read(buf)
                        random_times.append(rt)

            except Exception as exc:
                logger.error("Operation %s failed for buffer %s: %s",
                             operation, self._format_bytes(buf_size), exc)
                results[operation] = {"error": str(exc), "raw_times": []}
                continue

            # Compute statistics
            times_arr: NDArray[np.float64] = np.array(times, dtype=np.float64)
            mean_time: float = float(np.mean(times_arr))
            median_time: float = float(np.median(times_arr))
            std_time: float = float(np.std(times_arr, ddof=1))

            # Bandwidth in GB/s (accounting for operation type)
            if operation == "read":
                bytes_accessed: int = buf_size
            elif operation == "write":
                bytes_accessed = buf_size
            elif operation == "copy":
                bytes_accessed = 2 * buf_size  # read + write
            elif operation == "read_write":
                bytes_accessed = 2 * buf_size  # read + write
            else:
                bytes_accessed = buf_size

            bandwidth_GBs: float = (bytes_accessed / mean_time) / 1e9 if mean_time > 0 else 0.0

            stat: dict[str, float | list[float]] = {
                "mean_s": mean_time,
                "median_s": median_time,
                "std_s": std_time,
                "min_s": float(np.min(times_arr)),
                "max_s": float(np.max(times_arr)),
                "p50_s": float(np.percentile(times_arr, 50)),
                "p90_s": float(np.percentile(times_arr, 90)),
                "p95_s": float(np.percentile(times_arr, 95)),
                "p99_s": float(np.percentile(times_arr, 99)),
                "bandwidth_GBs": bandwidth_GBs,
                "bytes_accessed": bytes_accessed,
                "raw_times": times,
            }

            if random_times:
                random_arr = np.array(random_times, dtype=np.float64)
                random_mean = float(np.mean(random_arr))
                stat["random_read_mean_s"] = random_mean
                stat["random_read_bandwidth_GBs"] = (buf_size / random_mean) / 1e9 if random_mean > 0 else 0.0

            results[operation] = stat

            logger.debug(
                "  %s: mean=%.6fs, bandwidth=%.2f GB/s",
                operation, mean_time, bandwidth_GBs,
            )

        return results

    def run(self) -> list[ResultDict]:
        """Execute the full memory bandwidth benchmark.

        Runs bandwidth measurements across all buffer sizes and operations.

        Returns:
            List of result dictionaries, one per buffer size. Each contains
            per-operation metrics and bandwidth calculations.

        Raises:
            BenchmarkExecutionError: If all measurements fail.
        """
        logger.info("Starting memory bandwidth benchmark")
        logger.info(
            "Buffer sizes: %d, Operations: %s, Sequential: %s",
            len(self.buffer_bytes), self.operations, self.sequential,
        )

        results: list[ResultDict] = []
        total_start: float = time.monotonic()
        successful: int = 0

        for buf_size, size_label in zip(self.buffer_bytes, self.buffer_sizes):
            logger.info("Benchmarking buffer size %s", size_label)

            ops_results = self._measure_single_buffer(buf_size)

            result: ResultDict = {
                "benchmark": self.name,
                "buffer_size_bytes": buf_size,
                "buffer_size_label": size_label,
                "sequential": self.sequential,
                "random_access_ratio": self.random_access_ratio,
            }

            for op_name, op_data in ops_results.items():
                if isinstance(op_data, dict):
                    for key, value in op_data.items():
                        result[f"{op_name}_{key}"] = value
                else:
                    result[op_name] = op_data

            if any("error" not in str(v) for v in ops_results.values()):
                successful += 1

            results.append(result)

            bw_values: list[float] = []
            for op in self.operations:
                bw_key = f"{op}_bandwidth_GBs"
                if bw_key in result and result[bw_key] is not None:
                    bw_values.append(float(result[bw_key]))  # type: ignore[arg-type]

            if bw_values:
                logger.info("  Bandwidths: %s GB/s", ", ".join(f"{bw:.2f}" for bw in bw_values))

        total_elapsed: float = time.monotonic() - total_start
        logger.info(
            "Memory bandwidth benchmark completed in %.2fs. "
            "Successful: %d/%d buffer sizes",
            total_elapsed, successful, len(self.buffer_bytes),
        )

        return results

    def analyze_cache_hierarchy(self) -> dict[str, Any]:
        """Analyze the memory/cache hierarchy by detecting bandwidth drops.

        By examining how bandwidth changes with buffer size, this method
        attempts to identify cache levels (L1, L2, L3) and main memory.

        Returns:
            Dictionary with detected cache hierarchy information.
        """
        # Run sequential read across all buffer sizes
        saved_ops = self.operations
        self.operations = ["read"]
        saved_iterations = self.iterations
        self.iterations = max(10, self.iterations // 5)

        results = self.run()

        # Restore settings
        self.operations = saved_ops
        self.iterations = saved_iterations

        # Analyze bandwidth drops
        bandwidths: list[float] = []
        for r in results:
            bw = r.get("read_bandwidth_GBs", 0.0)
            if isinstance(bw, (int, float)):
                bandwidths.append(float(bw))
            else:
                bandwidths.append(0.0)

        # Detect significant drops (>20% reduction)
        drops: list[dict[str, Any]] = []
        for i in range(1, len(bandwidths)):
            if bandwidths[i - 1] > 0:
                ratio: float = bandwidths[i] / bandwidths[i - 1]
                if ratio < 0.8:  # 20% drop
                    drops.append({
                        "from_size": self.buffer_sizes[i - 1],
                        "to_size": self.buffer_sizes[i],
                        "from_bandwidth_GBs": bandwidths[i - 1],
                        "to_bandwidth_GBs": bandwidths[i],
                        "drop_ratio": 1.0 - ratio,
                    })

        # Estimate cache sizes based on buffer sizes where drops occur
        cache_estimate: dict[str, int] = {}
        for i, drop in enumerate(drops):
            level = i + 1
            if level == 1:
                cache_estimate["L1_cache_bytes"] = self.buffer_bytes[i] // 2
            elif level == 2:
                cache_estimate["L2_cache_bytes"] = self.buffer_bytes[i] // 2
            elif level == 3:
                cache_estimate["L3_cache_bytes"] = self.buffer_bytes[i] // 2

        # Compute peak bandwidth (fastest read)
        peak_bw: float = max(bandwidths) if bandwidths else 0.0

        return {
            "peak_read_bandwidth_GBs": peak_bw,
            "cache_drops": drops,
            "cache_estimate": cache_estimate,
            "buffer_sizes": self.buffer_sizes,
            "bandwidths_GBs": bandwidths,
        }

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "Memory bandwidth measurement across the memory hierarchy",
            "buffer_sizes": self.buffer_sizes,
            "operations": self.operations,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "sequential": self.sequential,
            "random_access_ratio": self.random_access_ratio,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = MemoryBandwidthBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        label = r["buffer_size_label"]
        bws = []
        for op in bench.operations:
            bw = r.get(f"{op}_bandwidth_GBs")
            if bw:
                bws.append(f"{op}={bw:.2f}GB/s")
        print(f"  {label:>8s}: {', '.join(bws)}")