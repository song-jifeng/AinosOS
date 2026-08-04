#!/usr/bin/env python3
"""AinosOS 吞吐量测试 - 最大吞吐量测量、并发影响、资源使用分析"""

import json
import time
import statistics
import sys
import os
import math
import threading
import queue
import random
import unittest
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum

# ============================================================
# 吞吐量测试配置
# ============================================================

@dataclass
class ThroughputTestConfig:
    """吞吐量测试配置"""
    warmup_duration: int = 10       # 预热时间（秒）
    measurement_duration: int = 30  # 测量时间（秒）
    cooldown_duration: int = 5      # 冷却时间（秒）
    concurrency_levels: List[int] = field(default_factory=lambda: [1, 2, 4, 8, 16, 32, 64])
    batch_sizes: List[int] = field(default_factory=lambda: [1, 4, 8, 16, 32, 64])
    payload_sizes: List[int] = field(default_factory=lambda: [10, 100, 1000])
    token_counts: List[int] = field(default_factory=lambda: [10, 50, 100, 256, 512])
    target_throughput: float = 100.0  # 目标吞吐量 (requests/s)

    # 资源限制模拟
    cpu_cores: int = 8
    memory_gb: int = 32
    network_bandwidth_gbps: float = 10.0
    max_connections: int = 1024


@dataclass
class ThroughputMeasurement:
    """吞吐量测量结果"""
    operation: str
    timestamp: float
    requests_completed: int
    tokens_generated: int
    duration_seconds: float
    concurrency: int
    batch_size: int
    payload_size: int
    errors: int
    cpu_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0
    network_usage_mbps: float = 0.0


@dataclass
class ThroughputStats:
    """吞吐量统计"""
    requests_per_second: float = 0.0
    tokens_per_second: float = 0.0
    latency_ms: float = 0.0
    error_rate: float = 0.0
    cpu_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0
    network_usage_mbps: float = 0.0
    total_requests: int = 0
    total_errors: int = 0
    peak_throughput: float = 0.0
    sustained_throughput: float = 0.0


@dataclass
class ThroughputReport:
    """吞吐量测试报告"""
    operation: str
    config: ThroughputTestConfig
    overall: ThroughputStats = field(default_factory=ThroughputStats)
    by_concurrency: Dict[int, ThroughputStats] = field(default_factory=dict)
    by_batch_size: Dict[int, ThroughputStats] = field(default_factory=dict)
    by_payload_size: Dict[int, ThroughputStats] = field(default_factory=dict)
    by_token_count: Dict[int, ThroughputStats] = field(default_factory=dict)
    measurements: List[ThroughputMeasurement] = field(default_factory=list)
    resource_usage: Dict[str, List[float]] = field(default_factory=dict)
    violations: List[Dict] = field(default_factory=list)


# ============================================================
# 吞吐量模拟器
# ============================================================

class ThroughputSimulator:
    """吞吐量模拟器"""

    def __init__(self, config: ThroughputTestConfig):
        self.config = config
        self.random = random.Random(42)
        self._stop = threading.Event()

    def simulate_request(self, payload_size: int = 100, tokens: int = 50) -> float:
        """模拟单个请求的处理时间"""
        # 基础处理时间
        base_time = 0.001  # 1ms 基础

        # 负载大小影响
        payload_factor = payload_size / 1000.0  # 每 KB 增加
        base_time += payload_factor * 0.0005

        # Token 生成时间
        token_time = tokens * 0.01  # 每个 Token 10ms
        base_time += token_time

        # 随机抖动
        jitter = self.random.gauss(0, 0.001)  # 1ms 标准差
        base_time += max(0, jitter)

        return base_time

    def simulate_batch_request(self, batch_size: int, payload_size: int = 100, tokens: int = 50) -> float:
        """模拟批处理请求的处理时间"""
        single_time = self.simulate_request(payload_size, tokens)

        # 批处理加速比（亚线性）
        speedup = math.log(batch_size + 1) / math.log(2)  # log2(batch_size + 1)
        batch_time = single_time * batch_size / speedup

        # 批处理额外开销
        overhead = 0.001 * batch_size  # 每批 1ms 开销
        batch_time += overhead

        return batch_time

    def simulate_cpu_usage(self, load: float) -> float:
        """模拟 CPU 使用率"""
        # 非线性映射
        return min(100.0, load * 12.5 + random.gauss(0, 5))

    def simulate_memory_usage(self, active_requests: int) -> float:
        """模拟内存使用"""
        base = 1024  # 1GB 基础
        per_request = 64  # 每个请求 64MB
        return base + active_requests * per_request

    def simulate_network_usage(self, requests_per_sec: float, payload_size: int) -> float:
        """模拟网络使用"""
        return requests_per_sec * payload_size * 8 / 1e6  # Mbps


# ============================================================
# 吞吐量测试器
# ============================================================

class ThroughputTester:
    """吞吐量测试器"""

    def __init__(self, config: Optional[ThroughputTestConfig] = None):
        self.config = config or ThroughputTestConfig()
        self.simulator = ThroughputSimulator(self.config)
        self.results: Dict[str, ThroughputReport] = {}
        self._stop = threading.Event()

    def test_max_throughput(self, operation: str = "max_throughput") -> ThroughputReport:
        """测试最大吞吐量"""
        print(f"\n测试最大吞吐量: {operation}")
        report = ThroughputReport(operation=operation, config=self.config)
        measurements = []

        # 逐步增加负载直到达到瓶颈
        for concurrency in self.config.concurrency_levels:
            print(f"  并发级别: {concurrency}")
            stats = self._run_load_test(
                concurrency=concurrency,
                duration=self.config.measurement_duration
            )
            report.by_concurrency[concurrency] = stats
            measurements.extend(stats.measurements)

            print(f"    吞吐量: {stats.requests_per_second:.1f} req/s, "
                  f"延迟: {stats.latency_ms:.1f}ms, "
                  f"错误率: {stats.error_rate:.2f}%")

            # 如果错误率过高，停止测试
            if stats.error_rate > 10.0:
                print(f"  错误率过高 ({stats.error_rate:.1f}%)，停止测试")
                break

        # 找到最大吞吐量
        best = max(report.by_concurrency.values(), key=lambda s: s.requests_per_second)
        report.overall = best

        # 检查是否满足目标吞吐量
        if best.requests_per_second < self.config.target_throughput:
            report.violations.append({
                "type": "throughput_violation",
                "actual": best.requests_per_second,
                "target": self.config.target_throughput
            })

        report.measurements = measurements
        self.results[operation] = report
        return report

    def test_batch_throughput(self) -> ThroughputReport:
        """测试批处理吞吐量"""
        print("\n测试批处理吞吐量")
        report = ThroughputReport(operation="batch_throughput", config=self.config)

        for batch_size in self.config.batch_sizes:
            print(f"  批次大小: {batch_size}")
            measurements = []
            start_time = time.time()
            completed = 0
            errors = 0
            total_tokens = 0

            while time.time() - start_time < self.config.measurement_duration:
                try:
                    process_time = self.simulator.simulate_batch_request(batch_size)
                    time.sleep(max(0, process_time))
                    completed += batch_size
                    total_tokens += batch_size * 50  # 假设每个请求 50 tokens
                except Exception:
                    errors += 1

            duration = time.time() - start_time
            stats = ThroughputStats(
                requests_per_second=completed / duration,
                tokens_per_second=total_tokens / duration,
                latency_ms=(duration / completed * 1000) if completed > 0 else 0,
                error_rate=errors / (completed + errors) * 100 if (completed + errors) > 0 else 0,
                total_requests=completed,
                total_errors=errors,
                peak_throughput=completed / duration,
                sustained_throughput=completed / duration
            )
            report.by_batch_size[batch_size] = stats

            print(f"    吞吐量: {stats.requests_per_second:.1f} req/s, "
                  f"Token/s: {stats.tokens_per_second:.0f}")

        return report

    def test_payload_throughput(self) -> ThroughputReport:
        """测试不同负载大小的吞吐量"""
        print("\n测试负载大小对吞吐量的影响")
        report = ThroughputReport(operation="payload_throughput", config=self.config)

        for size in self.config.payload_sizes:
            print(f"  负载大小: {size} bytes")
            measurements = []
            start_time = time.time()
            completed = 0
            errors = 0

            while time.time() - start_time < self.config.measurement_duration:
                try:
                    process_time = self.simulator.simulate_request(payload_size=size)
                    time.sleep(max(0, process_time))
                    completed += 1
                except Exception:
                    errors += 1

            duration = time.time() - start_time
            stats = ThroughputStats(
                requests_per_second=completed / duration,
                latency_ms=(duration / completed * 1000) if completed > 0 else 0,
                error_rate=errors / (completed + errors) * 100 if (completed + errors) > 0 else 0,
                total_requests=completed,
                total_errors=errors
            )
            report.by_payload_size[size] = stats

            print(f"    吞吐量: {stats.requests_per_second:.1f} req/s, "
                  f"延迟: {stats.latency_ms:.1f}ms")

        return report

    def test_token_throughput(self) -> ThroughputReport:
        """测试不同 Token 数量的吞吐量"""
        print("\n测试 Token 数量对吞吐量的影响")
        report = ThroughputReport(operation="token_throughput", config=self.config)

        for tokens in self.config.token_counts:
            print(f"  Token 数: {tokens}")
            start_time = time.time()
            completed = 0
            total_tokens = 0
            errors = 0

            while time.time() - start_time < self.config.measurement_duration:
                try:
                    process_time = self.simulator.simulate_request(tokens=tokens)
                    time.sleep(max(0, process_time))
                    completed += 1
                    total_tokens += tokens
                except Exception:
                    errors += 1

            duration = time.time() - start_time
            stats = ThroughputStats(
                requests_per_second=completed / duration,
                tokens_per_second=total_tokens / duration,
                error_rate=errors / (completed + errors) * 100 if (completed + errors) > 0 else 0,
                total_requests=completed,
                total_errors=errors
            )
            report.by_token_count[tokens] = stats

            print(f"    请求吞吐量: {stats.requests_per_second:.1f} req/s, "
                  f"Token 吞吐量: {stats.tokens_per_second:.0f} tokens/s")

        return report

    def test_resource_usage(self) -> Dict[str, Any]:
        """测试资源使用情况"""
        print("\n测试资源使用情况")
        resource_usage = {
            "cpu": [],
            "memory": [],
            "network": []
        }

        # 模拟不同负载下的资源使用
        for concurrency in [1, 8, 32, 64]:
            print(f"  并发 {concurrency}:")
            active_requests = concurrency
            load = concurrency / 8.0  # 相对 8 核心

            cpu = self.simulator.simulate_cpu_usage(load)
            memory = self.simulator.simulate_memory_usage(active_requests)

            # 估计吞吐量
            process_time = self.simulator.simulate_request()
            estimated_rps = 1.0 / process_time * concurrency
            network = self.simulator.simulate_network_usage(estimated_rps, 1000)

            resource_usage["cpu"].append({"concurrency": concurrency, "usage": cpu})
            resource_usage["memory"].append({"concurrency": concurrency, "usage": memory})
            resource_usage["network"].append({"concurrency": concurrency, "usage": network})

            print(f"      CPU: {cpu:.1f}%, 内存: {memory:.0f}MB, 网络: {network:.1f}Mbps")

        return resource_usage

    def test_scalability(self) -> Dict[str, Any]:
        """测试可扩展性"""
        print("\n测试可扩展性")
        scalability = {
            "linear_scalability": 0.0,  # 1.0 = 完美线性
            "efficiency": [],
            "bottleneck_concurrency": 0
        }

        base_throughput = 0
        efficiencies = []

        for concurrency in self.config.concurrency_levels:
            stats = self._run_load_test(
                concurrency=concurrency,
                duration=self.config.measurement_duration // 2
            )

            if concurrency == 1:
                base_throughput = stats.requests_per_second

            if base_throughput > 0:
                # 计算效率（相对于单线程）
                expected = base_throughput * concurrency
                actual = stats.requests_per_second
                efficiency = actual / expected if expected > 0 else 0
                efficiencies.append({
                    "concurrency": concurrency,
                    "efficiency": efficiency,
                    "throughput": actual
                })

                print(f"  并发 {concurrency}: 效率={efficiency:.2f}, "
                      f"吞吐量={actual:.1f} req/s")

        # 计算线性可扩展性
        if efficiencies:
            scalability["linear_scalability"] = (
                efficiencies[-1]["efficiency"] if len(efficiencies) > 0 else 0
            )
            scalability["efficiency"] = efficiencies

            # 找到瓶颈点（效率开始低于 0.8）
            for e in efficiencies:
                if e["efficiency"] < 0.8:
                    scalability["bottleneck_concurrency"] = e["concurrency"]
                    break

        return scalability

    def test_sustained_throughput(self, duration: int = 120) -> ThroughputStats:
        """测试持续吞吐量（长时间运行）"""
        print(f"\n测试持续吞吐量 ({duration}秒)")
        start_time = time.time()
        measurements = []
        window_size = 10  # 10 秒窗口

        while time.time() - start_time < duration:
            window_start = time.time()
            completed = 0
            errors = 0

            while time.time() - window_start < window_size:
                try:
                    process_time = self.simulator.simulate_request()
                    time.sleep(max(0, process_time))
                    completed += 1
                except Exception:
                    errors += 1

            elapsed = time.time() - window_start
            measurements.append({
                "time": time.time() - start_time,
                "throughput": completed / elapsed,
                "errors": errors
            })

        # 计算统计
        throughputs = [m["throughput"] for m in measurements]
        stats = ThroughputStats(
            requests_per_second=statistics.mean(throughputs),
            total_requests=sum(m["throughput"] * window_size for m in measurements),
            total_errors=sum(m["errors"] for m in measurements),
            peak_throughput=max(throughputs),
            sustained_throughput=statistics.median(throughputs)
        )

        print(f"  平均吞吐量: {stats.requests_per_second:.1f} req/s")
        print(f"  峰值吞吐量: {stats.peak_throughput:.1f} req/s")
        print(f"  持续吞吐量: {stats.sustained_throughput:.1f} req/s")
        print(f"  总错误: {stats.total_errors}")

        return stats

    def _run_load_test(self, concurrency: int, duration: int) -> ThroughputStats:
        """运行负载测试"""
        start_time = time.time()
        completed = 0
        errors = 0
        total_tokens = 0
        measurements = []
        latencies = []

        def worker():
            nonlocal completed, errors, total_tokens
            while time.time() - start_time < duration:
                try:
                    req_start = time.time()
                    process_time = self.simulator.simulate_request()
                    time.sleep(max(0, process_time))
                    req_latency = (time.time() - req_start) * 1000  # ms
                    latencies.append(req_latency)
                    completed += 1
                    total_tokens += 50
                except Exception:
                    errors += 1

        threads = []
        for _ in range(concurrency):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        elapsed = time.time() - start_time
        avg_latency = statistics.mean(latencies) if latencies else 0

        stats = ThroughputStats(
            requests_per_second=completed / elapsed if elapsed > 0 else 0,
            tokens_per_second=total_tokens / elapsed if elapsed > 0 else 0,
            latency_ms=avg_latency,
            error_rate=errors / (completed + errors) * 100 if (completed + errors) > 0 else 0,
            cpu_usage_percent=self.simulator.simulate_cpu_usage(concurrency / 8.0),
            memory_usage_mb=self.simulator.simulate_memory_usage(concurrency),
            total_requests=completed,
            total_errors=errors,
            peak_throughput=completed / elapsed,
            sustained_throughput=completed / elapsed
        )

        return stats

    def generate_report(self) -> Dict[str, Any]:
        """生成完整测试报告"""
        report = {
            "config": {
                "warmup_duration": self.config.warmup_duration,
                "measurement_duration": self.config.measurement_duration,
                "concurrency_levels": self.config.concurrency_levels,
                "batch_sizes": self.config.batch_sizes,
                "target_throughput": self.config.target_throughput,
                "cpu_cores": self.config.cpu_cores,
                "memory_gb": self.config.memory_gb,
            },
            "results": {},
            "violations": [],
            "recommendations": []
        }

        for name, result in self.results.items():
            report["results"][name] = {
                "overall_throughput": result.overall.requests_per_second,
                "peak_throughput": result.overall.peak_throughput,
                "sustained_throughput": result.overall.sustained_throughput,
                "avg_latency_ms": result.overall.latency_ms,
                "error_rate": result.overall.error_rate,
                "total_requests": result.overall.total_requests,
                "tokens_per_second": result.overall.tokens_per_second
            }
            report["violations"].extend(result.violations)

        if not report["violations"]:
            report["recommendations"].append("所有吞吐量指标在目标范围内")
        else:
            for v in report["violations"]:
                report["recommendations"].append(
                    f"吞吐量 {v.get('actual', 0):.1f} req/s 低于目标 {v.get('target', 0)} req/s"
                )

        return report

    def run_all(self) -> Dict[str, Any]:
        """运行所有测试"""
        print("=" * 60)
        print("AinosOS 吞吐量测试")
        print("=" * 60)

        # 1. 最大吞吐量
        self.test_max_throughput()

        # 2. 批处理吞吐量
        self.test_batch_throughput()

        # 3. 负载大小影响
        self.test_payload_throughput()

        # 4. Token 吞吐量
        self.test_token_throughput()

        # 5. 资源使用
        self.test_resource_usage()

        # 6. 可扩展性
        self.test_scalability()

        # 7. 持续吞吐量
        self.test_sustained_throughput(30)

        # 生成报告
        report = self.generate_report()

        print("\n" + "=" * 60)
        print("吞吐量测试完成!")
        print(f"违规项: {len(report['violations'])}")
        print(f"建议: {len(report['recommendations'])}")

        return report


# ============================================================
# 单元测试
# ============================================================

class TestThroughput(unittest.TestCase):
    """吞吐量测试单元测试"""

    def setUp(self):
        self.config = ThroughputTestConfig(
            warmup_duration=2,
            measurement_duration=5,
            concurrency_levels=[1, 2, 4],
            batch_sizes=[1, 4, 8],
            payload_sizes=[100],
            token_counts=[10, 50]
        )
        self.tester = ThroughputTester(self.config)

    def test_max_throughput(self):
        """测试最大吞吐量"""
        report = self.tester.test_max_throughput()
        for concurrency in self.config.concurrency_levels:
            if concurrency in report.by_concurrency:
                stats = report.by_concurrency[concurrency]
                self.assertGreater(stats.total_requests, 0)

    def test_batch_throughput(self):
        """测试批处理吞吐量"""
        report = self.tester.test_batch_throughput()
        for batch_size in self.config.batch_sizes:
            self.assertIn(batch_size, report.by_batch_size)

    def test_payload_throughput(self):
        """测试负载大小对吞吐量的影响"""
        report = self.tester.test_payload_throughput()
        for size in self.config.payload_sizes:
            self.assertIn(size, report.by_payload_size)

    def test_token_throughput(self):
        """测试 Token 吞吐量"""
        report = self.tester.test_token_throughput()
        for tokens in self.config.token_counts:
            self.assertIn(tokens, report.by_token_count)

    def test_resource_usage(self):
        """测试资源使用"""
        usage = self.tester.test_resource_usage()
        self.assertIn("cpu", usage)
        self.assertIn("memory", usage)
        self.assertIn("network", usage)

    def test_scalability(self):
        """测试可扩展性"""
        scalability = self.tester.test_scalability()
        self.assertIn("linear_scalability", scalability)
        self.assertIn("efficiency", scalability)

    def test_sustained_throughput(self):
        """测试持续吞吐量"""
        stats = self.tester.test_sustained_throughput(10)
        self.assertGreater(stats.total_requests, 0)
        self.assertGreater(stats.requests_per_second, 0)

    def test_concurrent_workers(self):
        """测试并发工作线程"""
        concurrency = 4
        start = time.time()
        completed = 0

        def worker():
            nonlocal completed
            for _ in range(10):
                self.tester.simulator.simulate_request()
                completed += 1

        threads = [threading.Thread(target=worker) for _ in range(concurrency)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(completed, concurrency * 10)


# ============================================================
# 主入口
# ============================================================

def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="AinosOS 吞吐量测试")
    parser.add_argument("--warmup", type=int, default=10, help="预热时间（秒）")
    parser.add_argument("--duration", type=int, default=30, help="测量时间（秒）")
    parser.add_argument("--concurrency", type=str, default="1,2,4,8,16,32,64", help="并发级别列表")
    parser.add_argument("--batch-sizes", type=str, default="1,4,8,16,32,64", help="批次大小列表")
    parser.add_argument("--target", type=float, default=100.0, help="目标吞吐量 (req/s)")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--unittest", action="store_true", help="运行单元测试")

    args = parser.parse_args()

    if args.unittest:
        unittest.main(argv=[sys.argv[0]])
        return

    config = ThroughputTestConfig(
        warmup_duration=args.warmup,
        measurement_duration=args.duration,
        concurrency_levels=[int(x) for x in args.concurrency.split(",")],
        batch_sizes=[int(x) for x in args.batch_sizes.split(",")],
        target_throughput=args.target
    )

    tester = ThroughputTester(config)
    report = tester.run_all()

    if report["violations"]:
        print(f"\n发现 {len(report['violations'])} 个违规:")
        for v in report["violations"]:
            print(f"  - {v}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())