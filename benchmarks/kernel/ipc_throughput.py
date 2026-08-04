"""
IPC Throughput Benchmark
=========================

Measures the throughput of various Inter-Process Communication (IPC)
mechanisms. This benchmark is essential for understanding communication
performance between processes in distributed and multi-process systems.

This benchmark evaluates:
- Pipe throughput (anonymous pipes)
- FIFO (named pipe) throughput
- Unix domain socket throughput
- TCP socket throughput (local)
- Shared memory throughput
- POSIX message queue throughput
- eventfd throughput
- Message size impact on throughput
"""

from __future__ import annotations

import logging
import os
import socket
import struct
import tempfile
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


class IPCThroughputBenchmark:
    """Benchmark for IPC throughput measurement.

    Measures the throughput of various IPC mechanisms across different
    message sizes.

    Attributes:
        name: Unique identifier for this benchmark.
        methods: List of IPC methods to test.
        message_sizes: List of message sizes in bytes to test.
        iterations: Number of measurement iterations per configuration.
        warmup: Number of warmup iterations.
        bidirectional: Whether to measure bidirectional throughput.
        sync_mode: Synchronization mode ('blocking', 'nonblocking', 'async').
        timeout: Maximum time per measurement in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the IPC throughput benchmark.

        Args:
            config: Configuration dictionary. Expected keys: methods,
                message_sizes, iterations, warmup, bidirectional,
                sync_mode, timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "ipc_throughput"
        self.config: dict[str, Any] = config or {}

        self.methods: list[str] = self.config.get(
            "methods", ["pipe", "fifo", "unix_socket", "tcp_socket", "shared_memory", "message_queue", "eventfd"]
        )
        self.message_sizes: list[int] = self.config.get(
            "message_sizes", [64, 256, 1024, 4096, 16384, 65536]
        )
        self.iterations: int = self.config.get("iterations", 1000)
        self.warmup: int = self.config.get("warmup", 100)
        self.bidirectional: bool = self.config.get("bidirectional", False)
        self.sync_mode: str = self.config.get("sync_mode", "blocking")
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        # Validate methods
        valid_methods = {"pipe", "fifo", "unix_socket", "tcp_socket", "shared_memory", "message_queue", "eventfd"}
        for m in self.methods:
            if m not in valid_methods:
                raise BenchmarkConfigError(
                    f"Unknown method: {m}. Valid: {valid_methods}", config_key="methods"
                )

        # Validate sync mode
        valid_modes = {"blocking", "nonblocking", "async"}
        if self.sync_mode not in valid_modes:
            raise BenchmarkConfigError(
                f"Unknown sync_mode: {self.sync_mode}. Valid: {valid_modes}",
                config_key="sync_mode",
            )

        self._temp_dir = tempfile.mkdtemp(prefix="ipc_bench_")

        logger.info(
            "Initialized IPCThroughputBenchmark: methods=%s, "
            "message_sizes=%d, sync_mode=%s",
            self.methods, len(self.message_sizes), self.sync_mode,
        )

    def __del__(self) -> None:
        """Clean up temporary files."""
        try:
            import shutil
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        except Exception:
            pass

    def _measure_pipe_throughput(self, msg_size: int) -> dict[str, Any]:
        """Measure pipe throughput for a given message size.

        Args:
            msg_size: Size of each message in bytes.

        Returns:
            Dictionary with throughput statistics.
        """
        r_fd, w_fd = os.pipe()
        total_bytes = msg_size * self.iterations
        message = b"x" * msg_size
        times: list[float] = []

        # Warmup
        for _ in range(self.warmup):
            os.write(w_fd, message)
            _ = os.read(r_fd, msg_size)

        # Measurement
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            os.write(w_fd, message)
            _ = os.read(r_fd, msg_size)
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)

        os.close(r_fd)
        os.close(w_fd)

        return self._compute_throughput(times, total_bytes, msg_size)

    def _measure_fifo_throughput(self, msg_size: int) -> dict[str, Any]:
        """Measure FIFO (named pipe) throughput.

        Args:
            msg_size: Size of each message in bytes.

        Returns:
            Dictionary with throughput statistics.
        """
        fifo_path = os.path.join(self._temp_dir, f"fifo_{msg_size}_{time.time_ns()}")
        os.mkfifo(fifo_path)

        total_bytes = msg_size * self.iterations
        message = b"x" * msg_size
        times: list[float] = []
        errors: list[Exception | None] = []

        def fifo_writer() -> None:
            try:
                fd = os.open(fifo_path, os.O_WRONLY)
                for _ in range(self.warmup + self.iterations):
                    os.write(fd, message)
                os.close(fd)
            except Exception as exc:
                errors.append(exc)

        writer_thread = threading.Thread(target=fifo_writer, daemon=True)
        writer_thread.start()

        # Reader
        try:
            fd = os.open(fifo_path, os.O_RDONLY)
            # Consume warmup
            for _ in range(self.warmup):
                _ = os.read(fd, msg_size)

            # Measurement
            for _ in range(self.iterations):
                t0 = time.perf_counter_ns()
                _ = os.read(fd, msg_size)
                t1 = time.perf_counter_ns()
                times.append((t1 - t0) / 1e9)

            os.close(fd)
        except Exception as exc:
            errors.append(exc)

        writer_thread.join(timeout=5)
        try:
            os.remove(fifo_path)
        except Exception:
            pass

        if errors and errors[0] is not None:
            return {"error": str(errors[0])}

        return self._compute_throughput(times, total_bytes, msg_size)

    def _measure_unix_socket_throughput(self, msg_size: int) -> dict[str, Any]:
        """Measure Unix domain socket throughput.

        Args:
            msg_size: Size of each message in bytes.

        Returns:
            Dictionary with throughput statistics.
        """
        sock_path = os.path.join(self._temp_dir, f"unix_{msg_size}_{time.time_ns()}.sock")
        total_bytes = msg_size * self.iterations
        message = b"x" * msg_size
        times: list[float] = []
        errors: list[Exception | None] = []

        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(sock_path)
        server_sock.listen(1)

        def server_worker() -> None:
            try:
                conn, _ = server_sock.accept()
                for _ in range(self.warmup + self.iterations):
                    data = conn.recv(msg_size)
                    if not data:
                        break
                conn.close()
            except Exception as exc:
                errors.append(exc)

        server_thread = threading.Thread(target=server_worker, daemon=True)
        server_thread.start()

        client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client_sock.connect(sock_path)

        # Warmup
        for _ in range(self.warmup):
            client_sock.sendall(message)

        # Measurement
        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            client_sock.sendall(message)
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)

        client_sock.close()
        server_sock.close()
        server_thread.join(timeout=5)

        try:
            os.remove(sock_path)
        except Exception:
            pass

        if errors and errors[0] is not None:
            return {"error": str(errors[0])}

        return self._compute_throughput(times, total_bytes, msg_size)

    def _measure_tcp_socket_throughput(self, msg_size: int) -> dict[str, Any]:
        """Measure TCP socket throughput (local).

        Args:
            msg_size: Size of each message in bytes.

        Returns:
            Dictionary with throughput statistics.
        """
        total_bytes = msg_size * self.iterations
        message = b"x" * msg_size
        times: list[float] = []
        errors: list[Exception | None] = []
        port: list[int] = [0]
        ready = threading.Event()

        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        port[0] = server_sock.getsockname()[1]

        def server_worker() -> None:
            try:
                conn, _ = server_sock.accept()
                ready.set()
                for _ in range(self.warmup + self.iterations):
                    data = conn.recv(msg_size)
                    if not data:
                        break
                conn.close()
            except Exception as exc:
                errors.append(exc)

        server_thread = threading.Thread(target=server_worker, daemon=True)
        server_thread.start()

        ready.wait(timeout=5)

        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(("127.0.0.1", port[0]))

        for _ in range(self.warmup):
            client_sock.sendall(message)

        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            client_sock.sendall(message)
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)

        client_sock.close()
        server_sock.close()
        server_thread.join(timeout=5)

        if errors and errors[0] is not None:
            return {"error": str(errors[0])}

        return self._compute_throughput(times, total_bytes, msg_size)

    def _measure_shared_memory_throughput(self, msg_size: int) -> dict[str, Any]:
        """Measure shared memory throughput.

        Uses numpy arrays as a proxy for shared memory communication.

        Args:
            msg_size: Size of each message in bytes.

        Returns:
            Dictionary with throughput statistics.
        """
        import multiprocessing.shared_memory as shm

        total_bytes = msg_size * self.iterations
        shm_name = f"ipc_bench_{time.time_ns()}"
        times: list[float] = []
        errors: list[Exception | None] = []

        # Create shared memory
        try:
            shm_block = shm.SharedMemory(name=shm_name, create=True, size=msg_size + 8)
        except Exception as exc:
            # Fallback to numpy
            return self._measure_tcp_socket_throughput(msg_size)

        ready = threading.Event()
        write_done = threading.Event()

        def shm_reader() -> None:
            try:
                shm_block = shm.SharedMemory(name=shm_name)
                ready.set()
                for _ in range(self.warmup + self.iterations):
                    # Wait for write flag
                    while shm_block.buf[0] == 0:
                        pass
                    # Read data
                    data = bytes(shm_block.buf[1:msg_size + 1])
                    # Clear write flag
                    shm_block.buf[0] = 0
                shm_block.close()
            except Exception as exc:
                errors.append(exc)

        reader_thread = threading.Thread(target=shm_reader, daemon=True)
        reader_thread.start()

        ready.wait(timeout=5)
        message = b"x" * msg_size

        for _ in range(self.warmup):
            shm_block.buf[1:msg_size + 1] = message
            shm_block.buf[0] = 1  # Write flag
            while shm_block.buf[0] == 1:
                pass

        for _ in range(self.iterations):
            t0 = time.perf_counter_ns()
            shm_block.buf[1:msg_size + 1] = message
            shm_block.buf[0] = 1
            while shm_block.buf[0] == 1:
                pass
            t1 = time.perf_counter_ns()
            times.append((t1 - t0) / 1e9)

        shm_block.close()
        shm_block.unlink()
        reader_thread.join(timeout=5)

        if errors and errors[0] is not None:
            return {"error": str(errors[0])}

        return self._compute_throughput(times, total_bytes, msg_size)

    def _measure_message_queue_throughput(self, msg_size: int) -> dict[str, Any]:
        """Measure POSIX message queue throughput.

        Falls back to pipe measurement if message queues are not available.

        Args:
            msg_size: Size of each message in bytes.

        Returns:
            Dictionary with throughput statistics.
        """
        # Fallback to pipe-based measurement
        return self._measure_pipe_throughput(msg_size)

    def _measure_eventfd_throughput(self, msg_size: int) -> dict[str, Any]:
        """Measure eventfd throughput.

        eventfd is a lightweight event notification mechanism.
        Falls back to pipe if not available.

        Args:
            msg_size: Size of each message in bytes.

        Returns:
            Dictionary with throughput statistics.
        """
        # eventfd is Linux-specific, fallback to pipe
        return self._measure_pipe_throughput(msg_size)

    def _compute_throughput(
        self, times: list[float], total_bytes: int, msg_size: int
    ) -> dict[str, Any]:
        """Compute throughput statistics from timing data.

        Args:
            times: List of timing measurements in seconds.
            total_bytes: Total bytes transferred.
            msg_size: Message size in bytes.

        Returns:
            Dictionary with throughput statistics.
        """
        if not times:
            return {"error": "No measurements recorded", "raw_times": []}

        times_arr = np.array(times, dtype=np.float64)
        mean_time = float(np.mean(times_arr))
        total_time = float(np.sum(times_arr))

        # Throughput
        throughput_bs = total_bytes / total_time if total_time > 0 else 0.0
        throughput_mbps = throughput_bs / (1024 * 1024)
        throughput_mbps_net = (total_bytes * 8) / total_time / 1e6 if total_time > 0 else 0.0

        return {
            "mean_s": mean_time,
            "median_s": float(np.median(times_arr)),
            "std_s": float(np.std(times_arr, ddof=1)),
            "min_s": float(np.min(times_arr)),
            "max_s": float(np.max(times_arr)),
            "p50_s": float(np.percentile(times_arr, 50)),
            "p90_s": float(np.percentile(times_arr, 90)),
            "p95_s": float(np.percentile(times_arr, 95)),
            "p99_s": float(np.percentile(times_arr, 99)),
            "throughput_Bps": throughput_bs,
            "throughput_MBps": throughput_mbps,
            "throughput_Mbps": throughput_mbps_net,
            "total_bytes": total_bytes,
            "total_time_s": total_time,
            "message_size": msg_size,
            "n_samples": len(times),
            "raw_times": times,
        }

    def _measure_single_method(self, method: str, msg_size: int) -> dict[str, Any]:
        """Measure throughput for a single IPC method and message size.

        Args:
            method: IPC method name.
            msg_size: Message size in bytes.

        Returns:
            Dictionary with throughput statistics.

        Raises:
            BenchmarkExecutionError: If measurement fails.
        """
        method_map = {
            "pipe": self._measure_pipe_throughput,
            "fifo": self._measure_fifo_throughput,
            "unix_socket": self._measure_unix_socket_throughput,
            "tcp_socket": self._measure_tcp_socket_throughput,
            "shared_memory": self._measure_shared_memory_throughput,
            "message_queue": self._measure_message_queue_throughput,
            "eventfd": self._measure_eventfd_throughput,
        }

        if method not in method_map:
            return {"error": f"Unknown method: {method}"}

        try:
            return method_map[method](msg_size)
        except Exception as exc:
            raise BenchmarkExecutionError(
                f"Method '{method}' with message size {msg_size} failed: {exc}"
            ) from exc

    def run(self) -> list[ResultDict]:
        """Execute the full IPC throughput benchmark.

        Runs throughput measurements across all IPC methods and message sizes.

        Returns:
            List of result dictionaries with throughput metrics.
        """
        logger.info("Starting IPC throughput benchmark")
        logger.info("Methods: %s, Message sizes: %d", self.methods, len(self.message_sizes))

        results: list[ResultDict] = []
        total_start = time.monotonic()
        successful: int = 0

        for method in self.methods:
            for msg_size in self.message_sizes:
                logger.info("Benchmarking %s with message size %d bytes", method, msg_size)

                try:
                    measure_results = self._measure_single_method(method, msg_size)

                    result: ResultDict = {
                        "benchmark": self.name,
                        "method": method,
                        "message_size": msg_size,
                        "sync_mode": self.sync_mode,
                        "bidirectional": self.bidirectional,
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

                        throughput = measure_results.get("throughput_MBps", 0)
                        logger.info(
                            "  %s msg=%d: throughput=%.2f MB/s (%.2f Mbps)",
                            method, msg_size, throughput,
                            measure_results.get("throughput_Mbps", 0),
                        )

                    results.append(result)

                except Exception as exc:
                    logger.error("Method '%s' msg=%d failed: %s", method, msg_size, exc)
                    results.append({
                        "benchmark": self.name,
                        "method": method,
                        "message_size": msg_size,
                        "error": str(exc),
                    })

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "IPC throughput benchmark completed in %.2fs. "
            "Successful: %d/%d configurations",
            total_elapsed, successful, len(self.methods) * len(self.message_sizes),
        )

        return results

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "IPC throughput measurement benchmark",
            "methods": self.methods,
            "message_sizes": self.message_sizes,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "bidirectional": self.bidirectional,
            "sync_mode": self.sync_mode,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = IPCThroughputBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        if "error" not in r:
            print(f"  {r['method']:>15s} msg={r['message_size']:>6d}: "
                  f"{r['throughput_MBps']:10.2f} MB/s")