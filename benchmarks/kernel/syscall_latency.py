"""
Syscall Latency Benchmark
==========================

Measures the latency of various system calls on the host operating system.
This benchmark is critical for understanding OS-level overhead and is
essential for optimizing latency-sensitive applications.

This benchmark evaluates:
- getpid/gettid latency (simple syscalls)
- clock_gettime latency (timestamp overhead)
- nanosleep latency (timing precision)
- File I/O syscalls (read, write, open, close)
- stat syscall latency (filesystem metadata)
- mmap/munmap latency (memory mapping)
- vDSO vs full syscall comparison
"""

from __future__ import annotations

import logging
import os
import time
import tempfile
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


class SyscallLatencyBenchmark:
    """Benchmark for measuring system call latency.

    Uses various techniques to measure the time taken by individual system
    calls, helping identify OS-level overhead.

    Attributes:
        name: Unique identifier for this benchmark.
        syscalls: List of syscall names to benchmark.
        iterations: Number of measurement iterations per syscall.
        warmup: Number of warmup iterations.
        measure_empty: Whether to measure empty loop overhead.
        use_vdso: Whether to use vDSO-accelerated calls when available.
        timeout: Maximum time per measurement in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the syscall latency benchmark.

        Args:
            config: Configuration dictionary. Expected keys: syscalls,
                iterations, warmup, measure_empty, use_vdso, timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "syscall_latency"
        self.config: dict[str, Any] = config or {}

        self.syscalls: list[str] = self.config.get(
            "syscalls", [
                "getpid", "gettid", "clock_gettime", "nanosleep",
                "read", "write", "open", "close", "stat", "mmap",
            ]
        )
        self.iterations: int = self.config.get("iterations", 10000)
        self.warmup: int = self.config.get("warmup", 1000)
        self.measure_empty: bool = self.config.get("measure_empty", True)
        self.use_vdso: bool = self.config.get("use_vdso", True)
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        # Validate syscalls
        valid_syscalls: set[str] = {
            "getpid", "gettid", "clock_gettime", "nanosleep",
            "read", "write", "open", "close", "stat", "mmap",
            "getcpu", "sched_yield", "getrandom", "dup",
        }
        for sc in self.syscalls:
            if sc not in valid_syscalls:
                logger.warning("Unknown syscall '%s', will attempt to benchmark anyway", sc)

        # Create temp file for I/O syscalls
        self._temp_dir: str = tempfile.mkdtemp(prefix="syscall_bench_")
        self._temp_file: str = os.path.join(self._temp_dir, "benchmark_file")
        with open(self._temp_file, "wb") as f:
            f.write(b"x" * 4096)

        logger.info(
            "Initialized SyscallLatencyBenchmark: %d syscalls, "
            "iterations=%d, warmup=%d, vdso=%s",
            len(self.syscalls), self.iterations, self.warmup, self.use_vdso,
        )

    def __del__(self) -> None:
        """Clean up temporary files."""
        try:
            if os.path.exists(self._temp_file):
                os.remove(self._temp_file)
            if os.path.exists(self._temp_dir):
                os.rmdir(self._temp_dir)
        except Exception:
            pass

    def _measure_getpid(self) -> list[float]:
        """Measure getpid() syscall latency.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            _ = os.getpid()
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)
        return times

    def _measure_gettid(self) -> list[float]:
        """Measure gettid() syscall latency.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            _ = os.getpid()  # Use getpid as proxy for gettid
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)
        return times

    def _measure_clock_gettime(self) -> list[float]:
        """Measure clock_gettime() syscall latency.

        Uses time.time() which typically uses vDSO-accelerated
        clock_gettime on modern Linux.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            _ = time.time()
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)
        return times

    def _measure_nanosleep(self) -> list[float]:
        """Measure nanosleep() syscall latency.

        Measures the minimum sleep duration achievable.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            time.sleep(0)  # sleep(0) yields the thread
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)
        return times

    def _measure_read(self) -> list[float]:
        """Measure read() syscall latency.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        data = b"x" * 64
        for _ in range(self.iterations):
            try:
                fd = os.open(self._temp_file, os.O_RDONLY)
                t0 = time.perf_counter_ns()
                _ = os.read(fd, 64)
                t1 = time.perf_counter_ns()
                os.close(fd)
                times.append((t1 - t0) / 1e9)
            except Exception:
                continue
        return times

    def _measure_write(self) -> list[float]:
        """Measure write() syscall latency.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        data = b"x" * 64
        for _ in range(self.iterations):
            try:
                fd = os.open(self._temp_file, os.O_WRONLY)
                os.lseek(fd, 0, os.SEEK_SET)
                t0 = time.perf_counter_ns()
                os.write(fd, data)
                t1 = time.perf_counter_ns()
                os.close(fd)
                times.append((t1 - t0) / 1e9)
            except Exception:
                continue
        return times

    def _measure_open(self) -> list[float]:
        """Measure open() syscall latency.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            try:
                fd = os.open(self._temp_file, os.O_RDONLY)
            except Exception:
                continue
            t1 = time.perf_counter_ns()
            os.close(fd)
            times.append((t1 - t0) / 1e9)
        return times

    def _measure_close(self) -> list[float]:
        """Measure close() syscall latency.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        for _ in range(self.iterations):
            try:
                fd = os.open(self._temp_file, os.O_RDONLY)
                t0 = time.perf_counter_ns()
                os.close(fd)
                t1 = time.perf_counter_ns()
                times.append((t1 - t0) / 1e9)
            except Exception:
                continue
        return times

    def _measure_stat(self) -> list[float]:
        """Measure stat() syscall latency.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            _ = os.stat(self._temp_file)
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)
        return times

    def _measure_mmap(self) -> list[float]:
        """Measure mmap() and munmap() syscall latency.

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        import mmap
        for _ in range(self.iterations):
            try:
                fd = os.open(self._temp_file, os.O_RDONLY)
                t0 = time.perf_counter_ns()
                m = mmap.mmap(fd, 4096, access=mmap.ACCESS_READ)
                t1 = time.perf_counter_ns()
                m.close()
                os.close(fd)
                times.append((t1 - t0) / 1e9)
            except Exception:
                continue
        return times

    def _measure_empty_loop(self) -> list[float]:
        """Measure empty loop overhead (baseline).

        Returns:
            List of timing measurements in seconds.
        """
        times: list[float] = []
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            # Minimal work
            _ = 1 + 1
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)
        return times

    def _measure_single_syscall(self, syscall_name: str) -> dict[str, Any]:
        """Measure latency for a single syscall.

        Args:
            syscall_name: Name of the syscall to measure.

        Returns:
            Dictionary with timing statistics.

        Raises:
            BenchmarkExecutionError: If measurement fails.
        """
        # Map syscall name to measurement method
        measure_map: dict[str, Any] = {
            "getpid": self._measure_getpid,
            "gettid": self._measure_gettid,
            "clock_gettime": self._measure_clock_gettime,
            "nanosleep": self._measure_nanosleep,
            "read": self._measure_read,
            "write": self._measure_write,
            "open": self._measure_open,
            "close": self._measure_close,
            "stat": self._measure_stat,
            "mmap": self._measure_mmap,
        }

        if syscall_name not in measure_map:
            logger.warning("No measurement method for syscall '%s'", syscall_name)
            return {"error": f"No measurement method for '{syscall_name}'"}

        # Warmup
        for _ in range(self.warmup):
            try:
                _ = measure_map[syscall_name]()
            except Exception:
                pass

        # Measurement
        try:
            raw_times = measure_map[syscall_name]()
        except Exception as exc:
            raise BenchmarkExecutionError(
                f"Syscall '{syscall_name}' measurement failed: {exc}"
            ) from exc

        if not raw_times:
            return {"error": "No measurements recorded", "raw_times": []}

        raw_times_arr = np.array(raw_times, dtype=np.float64)
        mean_time = float(np.mean(raw_times_arr))
        median_time = float(np.median(raw_times_arr))
        std_time = float(np.std(raw_times_arr, ddof=1))

        # Convert to nanoseconds for readability
        mean_ns = mean_time * 1e9
        median_ns = median_time * 1e9

        return {
            "mean_s": mean_time,
            "mean_ns": mean_ns,
            "median_s": median_time,
            "median_ns": median_ns,
            "std_s": std_time,
            "std_ns": std_time * 1e9,
            "min_s": float(np.min(raw_times_arr)),
            "min_ns": float(np.min(raw_times_arr)) * 1e9,
            "max_s": float(np.max(raw_times_arr)),
            "max_ns": float(np.max(raw_times_arr)) * 1e9,
            "p50_ns": float(np.percentile(raw_times_arr, 50)) * 1e9,
            "p90_ns": float(np.percentile(raw_times_arr, 90)) * 1e9,
            "p95_ns": float(np.percentile(raw_times_arr, 95)) * 1e9,
            "p99_ns": float(np.percentile(raw_times_arr, 99)) * 1e9,
            "p999_ns": float(np.percentile(raw_times_arr, 99.9)) * 1e9,
            "n_samples": len(raw_times),
            "raw_times": raw_times,
        }

    def run(self) -> list[ResultDict]:
        """Execute the full syscall latency benchmark.

        Runs latency measurements for all configured syscalls.

        Returns:
            List of result dictionaries with latency metrics.

        Raises:
            BenchmarkExecutionError: If all measurements fail.
        """
        logger.info("Starting syscall latency benchmark")
        logger.info("Syscalls: %s", self.syscalls)

        results: list[ResultDict] = []
        total_start = time.monotonic()
        successful: int = 0

        # Measure empty loop baseline
        if self.measure_empty:
            logger.info("Measuring empty loop baseline")
            try:
                empty_results = self._measure_single_syscall("getpid")  # Any method works
                # Actually measure empty loop
                empty_times = self._measure_empty_loop()
                if empty_times:
                    empty_arr = np.array(empty_times, dtype=np.float64)
                    empty_result: ResultDict = {
                        "benchmark": self.name,
                        "syscall": "empty_loop",
                        "mean_ns": float(np.mean(empty_arr)) * 1e9,
                        "median_ns": float(np.median(empty_arr)) * 1e9,
                        "std_ns": float(np.std(empty_arr, ddof=1)) * 1e9,
                        "n_samples": len(empty_times),
                        "raw_times": empty_times,
                    }
                    results.append(empty_result)
                    logger.info("  Empty loop baseline: %.1f ns", empty_result["mean_ns"])
            except Exception as exc:
                logger.error("Empty loop measurement failed: %s", exc)

        # Measure each syscall
        for syscall_name in self.syscalls:
            logger.info("Benchmarking syscall: %s", syscall_name)

            try:
                syscall_results = self._measure_single_syscall(syscall_name)

                result: ResultDict = {
                    "benchmark": self.name,
                    "syscall": syscall_name,
                    "use_vdso": self.use_vdso,
                }

                if "error" in syscall_results:
                    result["error"] = syscall_results["error"]
                else:
                    for key, value in syscall_results.items():
                        if isinstance(value, (int, float, str)):
                            result[key] = value
                        elif key == "raw_times":
                            result[key] = value
                    successful += 1

                    mean_ns = syscall_results.get("mean_ns", 0)
                    p99_ns = syscall_results.get("p99_ns", 0)
                    logger.info(
                        "  %s: mean=%.1f ns, p99=%.1f ns",
                        syscall_name, mean_ns, p99_ns,
                    )

                results.append(result)

            except Exception as exc:
                logger.error("Syscall '%s' failed: %s", syscall_name, exc)
                results.append({
                    "benchmark": self.name,
                    "syscall": syscall_name,
                    "error": str(exc),
                })

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "Syscall latency benchmark completed in %.2fs. "
            "Successful: %d/%d syscalls",
            total_elapsed, successful, len(self.syscalls),
        )

        return results

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "System call latency measurement benchmark",
            "syscalls": self.syscalls,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "measure_empty": self.measure_empty,
            "use_vdso": self.use_vdso,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = SyscallLatencyBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        if "error" not in r:
            print(f"  {r['syscall']:>15s}: mean={r['mean_ns']:8.1f}ns  "
                  f"median={r['median_ns']:8.1f}ns  p99={r['p99_ns']:8.1f}ns")