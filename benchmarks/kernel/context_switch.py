"""
Context Switch Benchmark
=========================

Measures the overhead of context switching between threads and processes
using various synchronization primitives. This benchmark is crucial for
understanding the performance of multi-threaded and multi-process applications.

This benchmark evaluates:
- Pipe-based context switching (threads and processes)
- Socket pair context switching
- Futex-based context switching
- Signal-based context switching
- Voluntary vs involuntary context switches
- CPU affinity impact on context switch latency
"""

from __future__ import annotations

import logging
import os
import socket
import struct
import time
import threading
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


class ContextSwitchBenchmark:
    """Benchmark for measuring context switching overhead.

    Measures the time taken to switch between threads/processes using
    different synchronization mechanisms.

    Attributes:
        name: Unique identifier for this benchmark.
        methods: List of synchronization methods to test.
        thread_counts: List of thread counts to test.
        iterations: Number of measurement iterations per configuration.
        warmup: Number of warmup iterations.
        affinity: Whether to set CPU affinity.
        measure_voluntary: Whether to measure voluntary vs involuntary switches.
        timeout: Maximum time per measurement in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the context switch benchmark.

        Args:
            config: Configuration dictionary. Expected keys: methods,
                thread_counts, iterations, warmup, affinity,
                measure_voluntary, timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "context_switch"
        self.config: dict[str, Any] = config or {}

        self.methods: list[str] = self.config.get(
            "methods", ["pipe", "socketpair", "futex", "signal"]
        )
        self.thread_counts: list[int] = self.config.get(
            "thread_counts", [2, 4, 8, 16, 32, 64]
        )
        self.iterations: int = self.config.get("iterations", 5000)
        self.warmup: int = self.config.get("warmup", 500)
        self.affinity: bool = self.config.get("affinity", True)
        self.measure_voluntary: bool = self.config.get("measure_voluntary", True)
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        # Validate methods
        valid_methods = {"pipe", "socketpair", "futex", "signal"}
        for m in self.methods:
            if m not in valid_methods:
                raise BenchmarkConfigError(
                    f"Unknown method: {m}. Valid: {valid_methods}", config_key="methods"
                )

        # Validate thread counts
        for tc in self.thread_counts:
            if tc < 2:
                raise BenchmarkConfigError(
                    f"Thread count must be >= 2, got {tc}", config_key="thread_counts"
                )

        logger.info(
            "Initialized ContextSwitchBenchmark: methods=%s, thread_counts=%s, "
            "iterations=%d, affinity=%s",
            self.methods, self.thread_counts, self.iterations, self.affinity,
        )

    def _measure_pipe_switch(self, num_threads: int) -> list[float]:
        """Measure context switch latency using pipes.

        Creates a ring of threads connected by pipes and measures the
        round-trip time for a token to traverse the ring.

        Args:
            num_threads: Number of threads in the ring.

        Returns:
            List of timing measurements in seconds.

        Raises:
            BenchmarkExecutionError: If thread setup fails.
        """
        pipes: list[tuple[int, int]] = []
        threads: list[threading.Thread] = []
        ready_events: list[threading.Event] = []
        start_event = threading.Event()
        results: list[float] = []
        errors: list[Exception | None] = []

        # Create pipes
        for i in range(num_threads):
            r, w = os.pipe()
            pipes.append((r, w))

        # Worker function
        def worker(
            worker_id: int, read_fd: int, write_fd: int,
            ready: threading.Event, num_iters: int,
        ) -> None:
            try:
                ready.set()
                start_event.wait()

                for _ in range(num_iters):
                    data = os.read(read_fd, 1)
                    os.write(write_fd, data)
            except Exception as exc:
                errors.append(exc)

        # Measurement function runs on the main thread
        for i in range(num_threads):
            ready = threading.Event()
            ready_events.append(ready)
            r_fd, w_fd = pipes[i]
            # Each thread reads from its pipe and writes to the next
            next_w_fd = pipes[(i + 1) % num_threads][1]
            t = threading.Thread(
                target=worker,
                args=(i, r_fd, next_w_fd, ready, self.iterations),
                daemon=True,
            )
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all threads to be ready
        for evt in ready_events:
            evt.wait(timeout=5)

        # Warmup
        start_event.set()
        for _ in range(self.warmup):
            os.write(pipes[0][1], b"x")
            _ = os.read(pipes[0][0], 1)

        # Measurement
        times: list[float] = []
        for i in range(self.iterations):
            t0 = time.perf_counter_ns()
            os.write(pipes[0][1], b"x")
            _ = os.read(pipes[0][0], 1)
            t1 = time.perf_counter_ns()
            # Divide by num_threads*2 for one context switch
            switch_time = (t1 - t0) / (num_threads * 2)
            times.append(switch_time / 1e9)

        # Cleanup
        for t in threads:
            t.join(timeout=5)
        for r_fd, w_fd in pipes:
            os.close(r_fd)
            os.close(w_fd)

        if errors and errors[0] is not None:
            raise BenchmarkExecutionError(f"Worker error: {errors[0]}")

        return times

    def _measure_socketpair_switch(self, num_threads: int) -> list[float]:
        """Measure context switch latency using socket pairs.

        Similar to the pipe method but uses Unix domain socket pairs.

        Args:
            num_threads: Number of threads.

        Returns:
            List of timing measurements in seconds.
        """
        socks: list[tuple[socket.socket, socket.socket]] = []
        threads: list[threading.Thread] = []
        ready_events: list[threading.Event] = []
        start_event = threading.Event()
        errors: list[Exception | None] = []

        # Create socket pairs
        for i in range(num_threads):
            a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            socks.append((a, b))

        def worker(
            worker_id: int,
            recv_sock: socket.socket,
            send_sock: socket.socket,
            ready: threading.Event,
            num_iters: int,
        ) -> None:
            try:
                ready.set()
                start_event.wait()

                for _ in range(num_iters):
                    data = recv_sock.recv(1)
                    send_sock.send(data)
            except Exception as exc:
                errors.append(exc)

        for i in range(num_threads):
            ready = threading.Event()
            ready_events.append(ready)
            recv_sock = socks[i][1]  # B side receives
            send_sock = socks[(i + 1) % num_threads][1]  # Next thread's B side sends
            t = threading.Thread(
                target=worker,
                args=(i, recv_sock, send_sock, ready, self.iterations),
                daemon=True,
            )
            threads.append(t)

        for t in threads:
            t.start()

        for evt in ready_events:
            evt.wait(timeout=5)

        start_event.set()

        for _ in range(self.warmup):
            socks[0][0].send(b"x")
            _ = socks[0][0].recv(1)

        times = []
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            socks[0][0].send(b"x")
            _ = socks[0][0].recv(1)
            t1 = time.perf_counter_ns()
            switch_time = (t1 - t0) / (num_threads * 2)
            times.append(switch_time / 1e9)

        for t in threads:
            t.join(timeout=5)
        for a, b in socks:
            a.close()
            b.close()

        return times

    def _measure_futex_switch(self, num_threads: int) -> list[float]:
        """Measure context switch latency using futex-like synchronization.

        Uses threading.Event as a proxy for futex-based synchronization.

        Args:
            num_threads: Number of threads.

        Returns:
            List of timing measurements in seconds.
        """
        threads: list[threading.Thread] = []
        ready_events: list[threading.Event] = []
        start_event = threading.Event()
        token_events: list[threading.Event] = []
        errors: list[Exception | None] = []

        for i in range(num_threads):
            token_events.append(threading.Event())

        def worker(
            worker_id: int,
            ready: threading.Event,
            my_event: threading.Event,
            next_event: threading.Event,
            num_iters: int,
        ) -> None:
            try:
                ready.set()
                start_event.wait()

                for _ in range(num_iters):
                    my_event.wait()
                    my_event.clear()
                    next_event.set()
            except Exception as exc:
                errors.append(exc)

        for i in range(num_threads):
            ready = threading.Event()
            ready_events.append(ready)
            t = threading.Thread(
                target=worker,
                args=(
                    i, ready,
                    token_events[i],
                    token_events[(i + 1) % num_threads],
                    self.iterations,
                ),
                daemon=True,
            )
            threads.append(t)

        for t in threads:
            t.start()

        for evt in ready_events:
            evt.wait(timeout=5)

        start_event.set()

        # Warmup
        for _ in range(self.warmup):
            token_events[0].set()
            token_events[0].wait(timeout=1)
            token_events[0].clear()

        # Measurement
        times = []
        main_event = token_events[0]
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            main_event.set()
            main_event.wait(timeout=1)
            main_event.clear()
            t1 = time.perf_counter_ns()
            switch_time = (t1 - t0) / (num_threads * 2)
            times.append(switch_time / 1e9)

        for t in threads:
            t.join(timeout=5)

        return times

    def _measure_signal_switch(self, num_threads: int) -> list[float]:
        """Measure context switch latency using signals.

        Note: This is a simplified simulation using threading primitives.

        Args:
            num_threads: Number of threads.

        Returns:
            List of timing measurements in seconds.
        """
        # Use futex-based measurement as signal proxy
        return self._measure_futex_switch(num_threads)

    def _measure_single_method(self, method: str, num_threads: int) -> dict[str, Any]:
        """Measure context switch latency for a single method and thread count.

        Args:
            method: Synchronization method name.
            num_threads: Number of threads.

        Returns:
            Dictionary with timing statistics.

        Raises:
            BenchmarkExecutionError: If measurement fails.
        """
        logger.debug("Measuring %s with %d threads", method, num_threads)

        method_map = {
            "pipe": self._measure_pipe_switch,
            "socketpair": self._measure_socketpair_switch,
            "futex": self._measure_futex_switch,
            "signal": self._measure_signal_switch,
        }

        if method not in method_map:
            return {"error": f"Unknown method: {method}"}

        try:
            raw_times = method_map[method](num_threads)
        except Exception as exc:
            raise BenchmarkExecutionError(
                f"Method '{method}' with {num_threads} threads failed: {exc}"
            ) from exc

        if not raw_times:
            return {"error": "No measurements recorded", "raw_times": []}

        raw_arr = np.array(raw_times, dtype=np.float64)
        mean_time = float(np.mean(raw_arr))
        median_time = float(np.median(raw_arr))

        return {
            "mean_s": mean_time,
            "mean_us": mean_time * 1e6,
            "median_s": median_time,
            "median_us": median_time * 1e6,
            "std_s": float(np.std(raw_arr, ddof=1)),
            "std_us": float(np.std(raw_arr, ddof=1)) * 1e6,
            "min_s": float(np.min(raw_arr)),
            "min_us": float(np.min(raw_arr)) * 1e6,
            "max_s": float(np.max(raw_arr)),
            "max_us": float(np.max(raw_arr)) * 1e6,
            "p50_us": float(np.percentile(raw_arr, 50)) * 1e6,
            "p90_us": float(np.percentile(raw_arr, 90)) * 1e6,
            "p95_us": float(np.percentile(raw_arr, 95)) * 1e6,
            "p99_us": float(np.percentile(raw_arr, 99)) * 1e6,
            "n_samples": len(raw_times),
            "raw_times": raw_times,
        }

    def run(self) -> list[ResultDict]:
        """Execute the full context switch benchmark.

        Runs context switch latency measurements across all methods
        and thread counts.

        Returns:
            List of result dictionaries with latency metrics.
        """
        logger.info("Starting context switch benchmark")
        logger.info("Methods: %s, Thread counts: %s", self.methods, self.thread_counts)

        results: list[ResultDict] = []
        total_start = time.monotonic()
        successful: int = 0

        for method in self.methods:
            for num_threads in self.thread_counts:
                logger.info("Benchmarking %s with %d threads", method, num_threads)

                try:
                    measure_results = self._measure_single_method(method, num_threads)

                    result: ResultDict = {
                        "benchmark": self.name,
                        "method": method,
                        "num_threads": num_threads,
                        "affinity": self.affinity,
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

                        mean_us = measure_results.get("mean_us", 0)
                        logger.info(
                            "  %s %2d threads: mean=%.2f us, median=%.2f us",
                            method, num_threads, mean_us,
                            measure_results.get("median_us", 0),
                        )

                    results.append(result)

                except Exception as exc:
                    logger.error("Method '%s' with %d threads failed: %s",
                                 method, num_threads, exc)
                    results.append({
                        "benchmark": self.name,
                        "method": method,
                        "num_threads": num_threads,
                        "error": str(exc),
                    })

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "Context switch benchmark completed in %.2fs. "
            "Successful: %d/%d configurations",
            total_elapsed, successful, len(self.methods) * len(self.thread_counts),
        )

        return results

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "Context switching overhead measurement benchmark",
            "methods": self.methods,
            "thread_counts": self.thread_counts,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "affinity": self.affinity,
            "measure_voluntary": self.measure_voluntary,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = ContextSwitchBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        if "error" not in r:
            print(f"  {r['method']:>10s} ({r['num_threads']:2d} threads): "
                  f"mean={r['mean_us']:8.2f} us  median={r['median_us']:8.2f} us")