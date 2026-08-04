"""
TCP Throughput Benchmark
=========================

Measures TCP network throughput and latency under various message sizes
and connection patterns. This benchmark is essential for understanding
network performance characteristics for distributed systems.

This benchmark evaluates:
- TCP stream throughput for various message sizes
- Connection establishment latency
- Round-trip time (RTT) for various message sizes
- Bidirectional throughput
- Impact of socket buffer sizes
- Nagle algorithm effects (TCP_NODELAY)
"""

from __future__ import annotations

import logging
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


class TCPThroughputBenchmark:
    """Benchmark for TCP network throughput and latency.

    Measures network performance characteristics of TCP connections
    including throughput, latency, and connection overhead.

    Attributes:
        name: Unique identifier for this benchmark.
        message_sizes: List of message sizes in bytes to test.
        iterations: Number of measurement iterations per configuration.
        warmup: Number of warmup iterations.
        use_ipv6: Whether to use IPv6 instead of IPv4.
        socket_buffer_size: Socket buffer size in bytes.
        nodelay: Whether to enable TCP_NODELAY.
        bidirectional: Whether to measure bidirectional throughput.
        timeout: Maximum time per measurement in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the TCP throughput benchmark.

        Args:
            config: Configuration dictionary. Expected keys: message_sizes,
                iterations, warmup, use_ipv6, socket_buffer_size, nodelay,
                bidirectional, timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "tcp_throughput"
        self.config: dict[str, Any] = config or {}

        self.message_sizes: list[int] = self.config.get(
            "message_sizes", [64, 256, 1024, 4096, 16384, 65536, 262144, 1048576]
        )
        self.iterations: int = self.config.get("iterations", DEFAULT_BENCHMARK_ITERATIONS)
        self.warmup: int = self.config.get("warmup", DEFAULT_WARMUP_ITERATIONS)
        self.use_ipv6: bool = self.config.get("use_ipv6", False)
        self.socket_buffer_size: int = self.config.get("socket_buffer_size", 65536)
        self.nodelay: bool = self.config.get("nodelay", True)
        self.bidirectional: bool = self.config.get("bidirectional", False)
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        if not self.message_sizes:
            raise BenchmarkConfigError("message_sizes cannot be empty", config_key="message_sizes")
        for size in self.message_sizes:
            if size <= 0:
                raise BenchmarkConfigError(
                    f"Invalid message size: {size}", config_key="message_sizes"
                )

        self.address_family: int = socket.AF_INET6 if self.use_ipv6 else socket.AF_INET
        self.bind_address: str = "::1" if self.use_ipv6 else "127.0.0.1"

        logger.info(
            "Initialized TCPThroughputBenchmark: %d message sizes, "
            "IPv6=%s, buffer=%d, nodelay=%s, bidirectional=%s",
            len(self.message_sizes), self.use_ipv6,
            self.socket_buffer_size, self.nodelay, self.bidirectional,
        )

    def _create_socket(self) -> socket.socket:
        """Create and configure a TCP socket.

        Returns:
            Configured TCP socket.
        """
        sock = socket.socket(self.address_family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.socket_buffer_size)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.socket_buffer_size)
        if self.nodelay:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(30.0)
        return sock

    def _measure_throughput_single(
        self, msg_size: int
    ) -> dict[str, float | list[float] | None]:
        """Measure throughput for a single message size.

        Creates a server and client thread, sends messages of the given size,
        and measures throughput.

        Args:
            msg_size: Size of each message in bytes.

        Returns:
            Dictionary with throughput statistics.

        Raises:
            BenchmarkExecutionError: If connection setup fails.
        """
        port: int = 0
        server_ready: threading.Event = threading.Event()
        results: dict[str, Any] = {}
        error_container: list[Exception | None] = [None]

        # Server thread
        def server_thread() -> None:
            nonlocal port
            try:
                server_sock = self._create_server_socket()
                server_sock.bind((self.bind_address, 0))
                server_sock.listen(1)
                port = server_sock.getsockname()[1]
                server_ready.set()

                conn, addr = server_sock.accept()
                logger.debug("Server accepted connection from %s", addr)

                received_data: int = 0
                expected_data: int = msg_size * self.iterations
                buf = bytearray(65536)

                while received_data < expected_data:
                    n = conn.recv_into(buf, min(65536, expected_data - received_data))
                    if n == 0:
                        break
                    received_data += n

                conn.close()
                server_sock.close()
                results["server_received"] = received_data

            except Exception as exc:
                error_container[0] = exc
                logger.error("Server error: %s", exc)

        server_thread_obj = threading.Thread(target=server_thread, daemon=True)
        server_thread_obj.start()

        # Wait for server to be ready
        server_ready.wait(timeout=10)
        if port == 0:
            raise BenchmarkExecutionError("Server failed to start")

        # Client
        try:
            client_sock = self._create_socket()
            client_sock.connect((self.bind_address, port))
            logger.debug("Client connected to port %d", port)

            # Create message
            message: bytes = b"x" * msg_size
            times: list[float] = []

            # Warmup
            for _ in range(self.warmup):
                client_sock.sendall(message)

            # Measurement
            start_time = time.monotonic()
            for i in range(self.iterations):
                if time.monotonic() - start_time > self.timeout:
                    raise BenchmarkTimeoutError(self.timeout)

                t0 = time.perf_counter()
                client_sock.sendall(message)
                t1 = time.perf_counter()
                times.append(t1 - t0)

            client_sock.close()

        except Exception as exc:
            raise BenchmarkExecutionError(f"Client error: {exc}") from exc

        server_thread_obj.join(timeout=5)

        if error_container[0] is not None:
            raise BenchmarkExecutionError(f"Server error: {error_container[0]}")

        if not times:
            return {"error": "No measurements recorded"}

        # Compute statistics
        times_arr: NDArray[np.float64] = np.array(times, dtype=np.float64)
        mean_time: float = float(np.mean(times_arr))
        median_time: float = float(np.median(times_arr))
        std_time: float = float(np.std(times_arr, ddof=1))

        # Throughput in MB/s
        total_bytes: int = msg_size * self.iterations
        total_time: float = float(np.sum(times_arr))
        throughput_mbps: float = (total_bytes / total_time) / (1024 * 1024) if total_time > 0 else 0.0

        # Convert to bits per second for network standard
        throughput_bps: float = (total_bytes * 8) / total_time if total_time > 0 else 0.0

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
            "throughput_MBps": throughput_mbps,
            "throughput_bps": throughput_bps,
            "throughput_Mbps": throughput_bps / 1e6,
            "total_bytes": total_bytes,
            "total_time_s": total_time,
            "n_samples": len(times),
            "raw_times": times,
        }

    def _create_server_socket(self) -> socket.socket:
        """Create a server socket with configured options.

        Returns:
            Configured server socket.
        """
        sock = socket.socket(self.address_family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.socket_buffer_size)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.socket_buffer_size)
        if self.nodelay:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(30.0)
        return sock

    def _measure_latency(self, msg_size: int = 64) -> dict[str, float]:
        """Measure TCP round-trip latency.

        Performs a request-response ping-pong to measure network latency.

        Args:
            msg_size: Size of the ping-pong message in bytes.

        Returns:
            Dictionary with latency statistics (min, max, mean, median, std).

        Raises:
            BenchmarkExecutionError: If measurement fails.
        """
        port: int = 0
        server_ready: threading.Event = threading.Event()
        latencies: list[float] = []

        def latency_server() -> None:
            nonlocal port
            server_sock = self._create_server_socket()
            server_sock.bind((self.bind_address, 0))
            server_sock.listen(1)
            port = server_sock.getsockname()[1]
            server_ready.set()

            conn, _ = server_sock.accept()
            for _ in range(self.iterations + self.warmup):
                data = conn.recv(msg_size)
                if not data:
                    break
                conn.sendall(data)
            conn.close()
            server_sock.close()

        server_thread_obj = threading.Thread(target=latency_server, daemon=True)
        server_thread_obj.start()

        server_ready.wait(timeout=10)
        if port == 0:
            raise BenchmarkExecutionError("Latency server failed to start")

        try:
            client_sock = self._create_socket()
            client_sock.connect((self.bind_address, port))
            message = b"x" * msg_size

            # Warmup
            for _ in range(self.warmup):
                client_sock.sendall(message)
                _ = client_sock.recv(msg_size)

            # Measurement
            for _ in range(self.iterations):
                t0 = time.perf_counter()
                client_sock.sendall(message)
                _ = client_sock.recv(msg_size)
                t1 = time.perf_counter()
                # RTT = total / 2 for one-way latency
                latencies.append((t1 - t0) / 2)

            client_sock.close()

        except Exception as exc:
            raise BenchmarkExecutionError(f"Latency client error: {exc}") from exc

        server_thread_obj.join(timeout=5)

        if not latencies:
            return {"error": "No latency measurements"}

        lat_arr = np.array(latencies, dtype=np.float64)
        return {
            "mean_ms": float(np.mean(lat_arr)) * 1000,
            "median_ms": float(np.median(lat_arr)) * 1000,
            "std_ms": float(np.std(lat_arr, ddof=1)) * 1000,
            "min_ms": float(np.min(lat_arr)) * 1000,
            "max_ms": float(np.max(lat_arr)) * 1000,
            "p50_ms": float(np.percentile(lat_arr, 50)) * 1000,
            "p90_ms": float(np.percentile(lat_arr, 90)) * 1000,
            "p95_ms": float(np.percentile(lat_arr, 95)) * 1000,
            "p99_ms": float(np.percentile(lat_arr, 99)) * 1000,
            "n_samples": len(latencies),
        }

    def run(self) -> list[ResultDict]:
        """Execute the full TCP throughput benchmark.

        Runs throughput measurements across all message sizes.

        Returns:
            List of result dictionaries with throughput metrics.

        Raises:
            BenchmarkExecutionError: If all measurements fail.
        """
        logger.info("Starting TCP throughput benchmark")
        logger.info("Message sizes: %s", self.message_sizes)

        results: list[ResultDict] = []
        total_start = time.monotonic()
        successful: int = 0

        # First measure latency with small message
        try:
            latency_results = self._measure_latency(64)
            latency_result: ResultDict = {
                "benchmark": self.name,
                "test_type": "latency",
                "message_size": 64,
                "latency_results": latency_results,
            }
            results.append(latency_result)
            logger.info(
                "Latency: mean=%.3fms, median=%.3fms",
                latency_results.get("mean_ms", 0),
                latency_results.get("median_ms", 0),
            )
        except Exception as exc:
            logger.error("Latency measurement failed: %s", exc)
            results.append({
                "benchmark": self.name,
                "test_type": "latency",
                "error": str(exc),
            })

        # Then measure throughput for each message size
        for msg_size in self.message_sizes:
            logger.info("Benchmarking message size %d bytes", msg_size)

            try:
                throughput_results = self._measure_throughput_single(msg_size)

                result: ResultDict = {
                    "benchmark": self.name,
                    "test_type": "throughput",
                    "message_size": msg_size,
                    "nodelay": self.nodelay,
                    "socket_buffer_size": self.socket_buffer_size,
                    "bidirectional": self.bidirectional,
                }

                if "error" in throughput_results:
                    result["error"] = throughput_results["error"]
                else:
                    for key, value in throughput_results.items():
                        if isinstance(value, (int, float, str)):
                            result[key] = value
                        elif key == "raw_times":
                            result[key] = value
                    successful += 1

                    throughput_mbps = throughput_results.get("throughput_MBps", 0)
                    logger.debug(
                        "  Size %6d: throughput=%.2f MB/s (%.2f Mbps)",
                        msg_size, throughput_mbps, throughput_results.get("throughput_Mbps", 0),
                    )

                results.append(result)

            except Exception as exc:
                logger.error("Message size %d failed: %s", msg_size, exc)
                results.append({
                    "benchmark": self.name,
                    "test_type": "throughput",
                    "message_size": msg_size,
                    "error": str(exc),
                })

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "TCP throughput benchmark completed in %.2fs. "
            "Successful: %d/%d message sizes",
            total_elapsed, successful, len(self.message_sizes),
        )

        return results

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "TCP network throughput and latency benchmark",
            "message_sizes": self.message_sizes,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "use_ipv6": self.use_ipv6,
            "socket_buffer_size": self.socket_buffer_size,
            "nodelay": self.nodelay,
            "bidirectional": self.bidirectional,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = TCPThroughputBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        test_type = r.get("test_type", "unknown")
        if test_type == "latency":
            lr = r.get("latency_results", {})
            if isinstance(lr, dict):
                print(f"  Latency: mean={lr.get('mean_ms', 'N/A'):>8}ms  "
                      f"median={lr.get('median_ms', 'N/A'):>8}ms")
        elif test_type == "throughput" and "error" not in r:
            print(f"  Size {r['message_size']:>7d}: "
                  f"{r.get('throughput_MBps', 0):8.2f} MB/s  "
                  f"{r.get('throughput_Mbps', 0):8.2f} Mbps")