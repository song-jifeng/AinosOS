#!/usr/bin/env python3
"""
Ainos OS - IPC 性能基准测试脚本

测量 IPC 往返延迟和推理吞吐量，输出 JSON 格式结果，
便于 CI 系统比较不同版本的性能变化。

用法:
    python benchmark.py                          # 默认连接 127.0.0.1:9500
    python benchmark.py --target 10.0.0.1:9500   # 指定目标地址
    python benchmark.py --inference-only         # 只跑推理测试
    python benchmark.py --latency-only           # 只跑延迟测试
    python benchmark.py --output results.json    # 输出到文件
"""

import argparse
import json
import socket
import sys
import time
import statistics
from datetime import datetime, timezone


# Default target
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9500


def send_request(host: str, port: int, req_type: str, payload: dict | None = None,
                 timeout: float = 10.0) -> dict:
    """Send an IPC request and receive the response.

    Args:
        host: Server hostname or IP.
        port: Server port.
        req_type: IPC message type (e.g. "Status", "Inference").
        payload: Optional additional fields for the message.
        timeout: Socket timeout in seconds.

    Returns:
        Parsed JSON response as a dict.

    Raises:
        socket.timeout: If the request times out.
        ConnectionError: If the connection fails.
        json.JSONDecodeError: If the response is not valid JSON.
    """
    msg = {"type": req_type}
    if payload:
        msg.update(payload)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))

        response = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            response += chunk
            if b"\n" in response:
                break
        return json.loads(response.decode("utf-8").strip())
    finally:
        s.close()


def measure_latency(host: str, port: int, iterations: int = 100,
                    warmup: int = 10) -> dict:
    """Measure IPC round-trip latency using Status requests.

    Sends ``iterations`` Status requests and records the round-trip time
    for each. The first ``warmup`` requests are discarded to allow JIT
    and connection warmup effects to settle.

    Args:
        host: Server hostname or IP.
        port: Server port.
        iterations: Number of requests to send (after warmup).
        warmup: Number of initial requests to discard.

    Returns:
        Dict with latency statistics:
        - min_ms, max_ms, mean_ms, median_ms, p95_ms, p99_ms, stddev_ms
        - total_requests: number of successful measurements
        - errors: number of failed requests
    """
    latencies = []
    errors = 0
    total = iterations + warmup

    print(f"  Warming up ({warmup} requests)...", end=" ", flush=True)
    for i in range(total):
        start = time.perf_counter()
        try:
            resp = send_request(host, port, "Status", timeout=10)
            elapsed = (time.perf_counter() - start) * 1000  # ms
            if resp.get("type") == "StatusResponse":
                if i >= warmup:
                    latencies.append(elapsed)
                if i == warmup:
                    print(f"done. Measuring ({iterations} requests)...", end=" ", flush=True)
            else:
                errors += 1
        except Exception:
            errors += 1
    print("done.")

    if not latencies:
        return {
            "error": "No successful measurements",
            "total_requests": 0,
            "errors": errors,
        }

    latencies.sort()
    n = len(latencies)
    p95_idx = max(0, int(n * 0.95) - 1)
    p99_idx = max(0, int(n * 0.99) - 1)

    return {
        "min_ms": round(min(latencies), 3),
        "max_ms": round(max(latencies), 3),
        "mean_ms": round(statistics.mean(latencies), 3),
        "median_ms": round(statistics.median(latencies), 3),
        "p95_ms": round(latencies[p95_idx], 3),
        "p99_ms": round(latencies[p99_idx], 3),
        "stddev_ms": round(statistics.stdev(latencies), 3) if n > 1 else 0.0,
        "total_requests": n,
        "errors": errors,
    }


def measure_throughput(host: str, port: int, duration_secs: int = 10,
                       concurrency: int = 1) -> dict:
    """Measure inference throughput in queries per second (QPS).

    Sends Inference requests in a loop for ``duration_secs`` seconds and
    counts successful completions.

    Args:
        host: Server hostname or IP.
        port: Server port.
        duration_secs: How long to run the benchmark (seconds).
        concurrency: Number of concurrent connections (1 = sequential).

    Returns:
        Dict with throughput statistics:
        - qps: queries per second (completed / elapsed)
        - total_requests: number of completed requests
        - errors: number of failed requests
        - duration_secs: actual elapsed time
        - avg_latency_ms: average latency per request
        - min_latency_ms, max_latency_ms
    """
    prompt = "请用一句话介绍Ainos OS。"
    latencies = []
    errors = 0
    completed = 0

    print(f"  Measuring throughput for {duration_secs}s (concurrency={concurrency})...",
          end=" ", flush=True)

    deadline = time.monotonic() + duration_secs

    while time.monotonic() < deadline:
        start = time.perf_counter()
        try:
            resp = send_request(host, port, "Inference", {
                "model": "default",
                "prompt": prompt,
                "temperature": 0.7,
                "max_tokens": 50,
            }, timeout=15)
            elapsed = (time.perf_counter() - start) * 1000
            if resp.get("type") == "InferenceResponse":
                completed += 1
                latencies.append(elapsed)
            else:
                errors += 1
        except Exception:
            errors += 1

    actual_duration = time.monotonic() - (deadline - duration_secs)
    print(f"done. ({completed} requests in {actual_duration:.1f}s)")

    qps = completed / actual_duration if actual_duration > 0 else 0.0

    result = {
        "qps": round(qps, 2),
        "total_requests": completed,
        "errors": errors,
        "duration_secs": round(actual_duration, 2),
    }

    if latencies:
        result["avg_latency_ms"] = round(statistics.mean(latencies), 2)
        result["min_latency_ms"] = round(min(latencies), 2)
        result["max_latency_ms"] = round(max(latencies), 2)
        result["median_latency_ms"] = round(statistics.median(latencies), 2)
    else:
        result["avg_latency_ms"] = 0.0
        result["min_latency_ms"] = 0.0
        result["max_latency_ms"] = 0.0
        result["median_latency_ms"] = 0.0

    return result


def check_daemon_health(host: str, port: int) -> dict:
    """Check if the daemon is running and return basic status."""
    try:
        resp = send_request(host, port, "Status", timeout=5)
        if resp.get("type") == "StatusResponse":
            return {
                "alive": True,
                "uptime_secs": resp.get("uptime", 0),
                "models_loaded": resp.get("models_loaded", 0),
                "total_requests": resp.get("total_requests", 0),
                "network_available": resp.get("network_available", False),
            }
        return {"alive": False, "error": f"Unexpected response: {resp}"}
    except Exception as e:
        return {"alive": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Ainos OS IPC Benchmark Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--target", "-t",
        default=f"{DEFAULT_HOST}:{DEFAULT_PORT}",
        help=f"Daemon address (default: {DEFAULT_HOST}:{DEFAULT_PORT})",
    )
    parser.add_argument(
        "--latency-only", "-l",
        action="store_true",
        help="Run only latency benchmark",
    )
    parser.add_argument(
        "--inference-only", "-i",
        action="store_true",
        help="Run only inference throughput benchmark",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Write results to JSON file",
    )
    parser.add_argument(
        "--latency-iterations", type=int, default=100,
        help="Number of latency measurements (default: 100)",
    )
    parser.add_argument(
        "--throughput-duration", type=int, default=10,
        help="Throughput measurement duration in seconds (default: 10)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print detailed progress",
    )

    args = parser.parse_args()

    # Parse host:port
    if ":" in args.target:
        host, port_str = args.target.rsplit(":", 1)
        port = int(port_str)
    else:
        host = args.target
        port = DEFAULT_PORT

    print(f"{'=' * 60}")
    print(f"  Ainos OS IPC Benchmark")
    print(f"{'=' * 60}")
    print(f"  Target:    {host}:{port}")
    print(f"  Time:      {datetime.now(timezone.utc).isoformat()}")
    print()

    # Check daemon health
    print("[1/3] Checking daemon health...")
    health = check_daemon_health(host, port)
    if health["alive"]:
        print(f"  Daemon is alive (uptime={health['uptime_secs']}s, "
              f"models={health['models_loaded']}, "
              f"requests={health['total_requests']})")
    else:
        print(f"  [ERROR] Daemon not reachable: {health.get('error', 'unknown')}")
        print("\n  Make sure ai-daemon is running on the target address.")
        sys.exit(1)

    run_latency = not args.inference_only
    run_throughput = not args.latency_only

    results = {
        "benchmark": {
            "tool": "ainos-benchmark",
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "target": {
            "host": host,
            "port": port,
        },
        "daemon": health,
        "latency": None,
        "throughput": None,
    }

    # Latency benchmark
    if run_latency:
        print(f"\n[2/3] Latency benchmark ({args.latency_iterations} iterations)...")
        latency_result = measure_latency(host, port, iterations=args.latency_iterations)
        if "error" in latency_result:
            print(f"  [ERROR] {latency_result['error']}")
        else:
            print(f"  Min:     {latency_result['min_ms']:>8.3f} ms")
            print(f"  Max:     {latency_result['max_ms']:>8.3f} ms")
            print(f"  Mean:    {latency_result['mean_ms']:>8.3f} ms")
            print(f"  Median:  {latency_result['median_ms']:>8.3f} ms")
            print(f"  P95:     {latency_result['p95_ms']:>8.3f} ms")
            print(f"  P99:     {latency_result['p99_ms']:>8.3f} ms")
            print(f"  StdDev:  {latency_result['stddev_ms']:>8.3f} ms")
        results["latency"] = latency_result

    # Throughput benchmark
    if run_throughput:
        print(f"\n[3/3] Throughput benchmark ({args.throughput_duration}s)...")
        tp_result = measure_throughput(host, port, duration_secs=args.throughput_duration)
        if "error" in tp_result:
            print(f"  [ERROR] {tp_result['error']}")
        else:
            print(f"  QPS:              {tp_result['qps']:>8.2f} req/s")
            print(f"  Total requests:   {tp_result['total_requests']:>8}")
            print(f"  Errors:           {tp_result['errors']:>8}")
            print(f"  Avg latency:      {tp_result['avg_latency_ms']:>8.2f} ms")
            print(f"  Median latency:   {tp_result['median_latency_ms']:>8.2f} ms")
        results["throughput"] = tp_result

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  Summary")
    print(f"{'=' * 60}")

    if run_latency and latency_result and "error" not in latency_result:
        print(f"  Latency:  mean={latency_result['mean_ms']:.2f}ms  "
              f"p95={latency_result['p95_ms']:.2f}ms  "
              f"p99={latency_result['p99_ms']:.2f}ms")
    if run_throughput and tp_result and "error" not in tp_result:
        print(f"  Throughput: {tp_result['qps']:.2f} qps  "
              f"({tp_result['total_requests']} requests in "
              f"{tp_result['duration_secs']}s)")

    # Output JSON
    output_json = json.dumps(results, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"\n  Results written to: {args.output}")
    else:
        print(f"\n  Raw JSON:")
        print(output_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())