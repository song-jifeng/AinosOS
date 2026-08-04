#!/usr/bin/env python3
"""AinosOS 延迟测试 - 端到端延迟测量、各组件延迟分析、百分位统计"""

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
# 延迟测试配置
# ============================================================

@dataclass
class LatencyTestConfig:
    """延迟测试配置"""
    warmup_rounds: int = 10
    measurement_rounds: int = 100
    concurrency_levels: List[int] = field(default_factory=lambda: [1, 2, 4, 8, 16])
    payload_sizes: List[int] = field(default_factory=lambda: [10, 100, 1000, 10000, 100000])
    timeout_ms: int = 60000
    percentile_points: List[float] = field(default_factory=lambda: [50, 90, 95, 99, 99.9, 99.99])
    target_latency_us: int = 1000  # 目标延迟微秒

    # 组件延迟模拟配置
    component_latencies: Dict[str, Tuple[float, float]] = field(default_factory=lambda: {
        "network": (0.1, 0.5),      # 网络延迟 (ms) - (min, max)
        "serialization": (0.05, 0.2), # 序列化延迟
        "deserialization": (0.05, 0.2), # 反序列化延迟
        "scheduling": (0.01, 0.1),   # 调度延迟
        "inference_prep": (0.5, 2.0), # 推理准备延迟
        "token_generation": (10.0, 50.0), # 每个 Token 生成延迟
        "memory_alloc": (0.1, 1.0),  # 内存分配延迟
        "context_switch": (0.01, 0.05), # 上下文切换延迟
    })


@dataclass
class LatencyMeasurement:
    """延迟测量结果"""
    operation: str
    timestamp: float
    latency_us: int
    payload_size: int
    concurrency: int
    success: bool
    metadata: Dict = field(default_factory=dict)


@dataclass
class LatencyPercentile:
    """百分位统计"""
    p50: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    p99_9: float = 0.0
    p99_99: float = 0.0
    mean: float = 0.0
    median: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    std_dev: float = 0.0
    count: int = 0


@dataclass
class LatencyReport:
    """延迟测试报告"""
    operation: str
    config: LatencyTestConfig
    overall: LatencyPercentile = field(default_factory=LatencyPercentile)
    by_concurrency: Dict[int, LatencyPercentile] = field(default_factory=dict)
    by_payload_size: Dict[int, LatencyPercentile] = field(default_factory=dict)
    component_breakdown: Dict[str, LatencyPercentile] = field(default_factory=dict)
    measurements: List[LatencyMeasurement] = field(default_factory=list)
    violations: List[Dict] = field(default_factory=list)


# ============================================================
# 延迟模拟器
# ============================================================

class LatencySimulator:
    """延迟模拟器 - 模拟各组件延迟"""

    def __init__(self, config: LatencyTestConfig):
        self.config = config
        self.random = random.Random(42)

    def simulate_network_latency(self) -> float:
        """模拟网络延迟"""
        min_lat, max_lat = self.config.component_latencies["network"]
        return self.random.uniform(min_lat, max_lat)

    def simulate_serialization(self, size: int) -> float:
        """模拟序列化延迟"""
        base = self.config.component_latencies["serialization"][0]
        size_factor = size / 1000.0  # 每 KB 增加延迟
        return base * (1 + size_factor * 0.1)

    def simulate_deserialization(self, size: int) -> float:
        """模拟反序列化延迟"""
        base = self.config.component_latencies["deserialization"][0]
        size_factor = size / 1000.0
        return base * (1 + size_factor * 0.15)

    def simulate_inference(self, tokens: int = 1) -> float:
        """模拟推理延迟"""
        base = self.config.component_latencies["token_generation"][0]
        return base * tokens

    def simulate_full_request(self, payload_size: int, tokens: int = 10) -> Dict[str, float]:
        """模拟完整请求的各组件延迟"""
        latencies = {}

        # 网络（发送）
        latencies["network_send"] = self.simulate_network_latency()

        # 序列化
        latencies["serialization"] = self.simulate_serialization(payload_size)

        # 调度
        latencies["scheduling"] = self.random.uniform(*self.config.component_latencies["scheduling"])

        # 推理准备
        latencies["inference_prep"] = self.random.uniform(*self.config.component_latencies["inference_prep"])

        # Token 生成
        latencies["token_generation"] = self.simulate_inference(tokens)

        # 反序列化
        latencies["deserialization"] = self.simulate_deserialization(payload_size)

        # 网络（接收）
        latencies["network_recv"] = self.simulate_network_latency()

        # 总延迟
        latencies["total"] = sum(latencies.values())

        return latencies


# ============================================================
# 延迟测试器
# ============================================================

class LatencyTester:
    """延迟测试器"""

    def __init__(self, config: Optional[LatencyTestConfig] = None):
        self.config = config or LatencyTestConfig()
        self.simulator = LatencySimulator(self.config)
        self.results: Dict[str, LatencyReport] = {}

    def measure_latency(self, operation: str, func: Callable, *args, **kwargs) -> LatencyMeasurement:
        """测量单次操作延迟"""
        start = time.perf_counter_ns()
        try:
            result = func(*args, **kwargs)
            success = True
        except Exception as e:
            result = str(e)
            success = False

        end = time.perf_counter_ns()
        latency_us = (end - start) // 1000

        return LatencyMeasurement(
            operation=operation,
            timestamp=time.time(),
            latency_us=latency_us,
            payload_size=kwargs.get("payload_size", 0),
            concurrency=kwargs.get("concurrency", 1),
            success=success,
            metadata={"result": str(result)[:100] if result else ""}
        )

    def calculate_percentiles(self, latencies: List[float]) -> LatencyPercentile:
        """计算百分位统计"""
        if not latencies:
            return LatencyPercentile()

        sorted_latencies = sorted(latencies)
        n = len(sorted_latencies)

        p = LatencyPercentile()
        p.count = n
        p.min_val = sorted_latencies[0]
        p.max_val = sorted_latencies[-1]
        p.mean = statistics.mean(sorted_latencies)
        p.median = sorted_latencies[n // 2]

        if n > 1:
            p.std_dev = statistics.stdev(sorted_latencies)

        for percentile in self.config.percentile_points:
            idx = int(n * percentile / 100.0)
            idx = min(idx, n - 1)
            if percentile == 50:
                p.p50 = sorted_latencies[idx]
            elif percentile == 90:
                p.p90 = sorted_latencies[idx]
            elif percentile == 95:
                p.p95 = sorted_latencies[idx]
            elif percentile == 99:
                p.p99 = sorted_latencies[idx]
            elif percentile == 99.9:
                p.p99_9 = sorted_latencies[idx]
            elif percentile == 99.99:
                p.p99_99 = sorted_latencies[idx]

        return p

    def test_end_to_end_latency(self, operation: str = "end_to_end") -> LatencyReport:
        """测试端到端延迟"""
        print(f"\n测试端到端延迟: {operation}")
        report = LatencyReport(operation=operation, config=self.config)
        measurements = []

        # 预热
        print(f"  预热 ({self.config.warmup_rounds} 轮)...")
        for i in range(self.config.warmup_rounds):
            self.simulator.simulate_full_request(100)

        # 测量
        print(f"  测量 ({self.config.measurement_rounds} 轮)...")
        for i in range(self.config.measurement_rounds):
            payload_size = random.choice(self.config.payload_sizes)
            latencies = self.simulator.simulate_full_request(payload_size)

            measurement = LatencyMeasurement(
                operation=operation,
                timestamp=time.time(),
                latency_us=int(latencies["total"] * 1000),  # 转换为微秒
                payload_size=payload_size,
                concurrency=1,
                success=True
            )
            measurements.append(measurement)

        # 统计分析
        latencies_us = [m.latency_us for m in measurements]
        report.overall = self.calculate_percentiles(latencies_us)
        report.measurements = measurements

        self._print_percentiles("  端到端", report.overall)

        # 检查是否满足目标延迟
        if report.overall.p99 > self.config.target_latency_us * 1000:
            report.violations.append({
                "type": "latency_violation",
                "metric": "p99",
                "actual": report.overall.p99,
                "target": self.config.target_latency_us * 1000
            })

        self.results[operation] = report
        return report

    def test_concurrency_impact(self) -> LatencyReport:
        """测试并发对延迟的影响"""
        print("\n测试并发对延迟的影响")
        report = LatencyReport(operation="concurrency_impact", config=self.config)

        for concurrency in self.config.concurrency_levels:
            print(f"  并发级别: {concurrency}")
            measurements = []

            # 预热
            for _ in range(self.config.warmup_rounds):
                self.simulator.simulate_full_request(100)

            # 使用线程池模拟并发
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = []
                for _ in range(self.config.measurement_rounds):
                    future = executor.submit(
                        self.simulator.simulate_full_request,
                        random.choice(self.config.payload_sizes)
                    )
                    futures.append(future)

                for future in as_completed(futures):
                    try:
                        latencies = future.result()
                        measurement = LatencyMeasurement(
                            operation="concurrency_test",
                            timestamp=time.time(),
                            latency_us=int(latencies["total"] * 1000),
                            payload_size=100,
                            concurrency=concurrency,
                            success=True
                        )
                        measurements.append(measurement)
                    except Exception as e:
                        print(f"    错误: {e}")

            latencies_us = [m.latency_us for m in measurements]
            percentile = self.calculate_percentiles(latencies_us)
            report.by_concurrency[concurrency] = percentile

            self._print_percentiles(f"  并发 {concurrency}", percentile)

        return report

    def test_payload_size_impact(self) -> LatencyReport:
        """测试负载大小对延迟的影响"""
        print("\n测试负载大小对延迟的影响")
        report = LatencyReport(operation="payload_size_impact", config=self.config)

        for size in self.config.payload_sizes:
            print(f"  负载大小: {size} bytes")
            measurements = []

            for _ in range(self.config.measurement_rounds):
                latencies = self.simulator.simulate_full_request(size)
                measurement = LatencyMeasurement(
                    operation="payload_size_test",
                    timestamp=time.time(),
                    latency_us=int(latencies["total"] * 1000),
                    payload_size=size,
                    concurrency=1,
                    success=True
                )
                measurements.append(measurement)

            latencies_us = [m.latency_us for m in measurements]
            percentile = self.calculate_percentiles(latencies_us)
            report.by_payload_size[size] = percentile

            self._print_percentiles(f"  负载 {size}", percentile)

        return report

    def test_component_breakdown(self) -> LatencyReport:
        """测试各组件延迟分解"""
        print("\n测试各组件延迟分解")
        report = LatencyReport(operation="component_breakdown", config=self.config)
        component_latencies: Dict[str, List[float]] = defaultdict(list)

        for _ in range(self.config.measurement_rounds):
            latencies = self.simulator.simulate_full_request(1000)

            for component, latency in latencies.items():
                if component != "total":
                    component_latencies[component].append(latency * 1000)  # 转换为微秒

        for component, latencies in component_latencies.items():
            percentile = self.calculate_percentiles(latencies)
            report.component_breakdown[component] = percentile

            self._print_percentiles(f"  {component}", percentile)

        return report

    def test_latency_distribution(self) -> Dict[str, Any]:
        """测试延迟分布"""
        print("\n测试延迟分布")
        distribution = {
            "under_1ms": 0,
            "1ms_to_5ms": 0,
            "5ms_to_10ms": 0,
            "10ms_to_50ms": 0,
            "50ms_to_100ms": 0,
            "100ms_to_500ms": 0,
            "over_500ms": 0,
            "total": 0
        }

        for _ in range(self.config.measurement_rounds * 10):
            latencies = self.simulator.simulate_full_request(100)
            total_ms = latencies["total"]

            if total_ms < 1:
                distribution["under_1ms"] += 1
            elif total_ms < 5:
                distribution["1ms_to_5ms"] += 1
            elif total_ms < 10:
                distribution["5ms_to_10ms"] += 1
            elif total_ms < 50:
                distribution["10ms_to_50ms"] += 1
            elif total_ms < 100:
                distribution["50ms_to_100ms"] += 1
            elif total_ms < 500:
                distribution["100ms_to_500ms"] += 1
            else:
                distribution["over_500ms"] += 1

            distribution["total"] += 1

        print(f"  延迟分布 ({distribution['total']} 样本):")
        for category, count in distribution.items():
            if category != "total" and count > 0:
                pct = count / distribution["total"] * 100
                print(f"    {category}: {count} ({pct:.1f}%)")

        return distribution

    def test_latency_jitter(self) -> Dict[str, float]:
        """测试延迟抖动"""
        print("\n测试延迟抖动")
        consecutive_latencies = []

        for _ in range(1000):
            latencies = self.simulator.simulate_full_request(100)
            consecutive_latencies.append(latencies["total"])

        # 计算抖动
        jitters = []
        for i in range(1, len(consecutive_latencies)):
            jitter = abs(consecutive_latencies[i] - consecutive_latencies[i-1])
            jitters.append(jitter)

        jitter_stats = {
            "avg_jitter_ms": statistics.mean(jitters),
            "max_jitter_ms": max(jitters),
            "min_jitter_ms": min(jitters),
            "jitter_std": statistics.stdev(jitters) if len(jitters) > 1 else 0,
            "jitter_p99": sorted(jitters)[int(len(jitters) * 0.99)]
        }

        print(f"  平均抖动: {jitter_stats['avg_jitter_ms']:.3f}ms")
        print(f"  最大抖动: {jitter_stats['max_jitter_ms']:.3f}ms")
        print(f"  P99 抖动: {jitter_stats['jitter_p99']:.3f}ms")

        return jitter_stats

    def test_latency_stability(self, duration_seconds: int = 60) -> Dict[str, Any]:
        """测试延迟稳定性（长时间运行）"""
        print(f"\n测试延迟稳定性 ({duration_seconds}秒)")
        start_time = time.time()
        latencies_over_time = []

        while time.time() - start_time < duration_seconds:
            latencies = self.simulator.simulate_full_request(100)
            latencies_over_time.append({
                "time": time.time() - start_time,
                "latency_ms": latencies["total"]
            })

        # 分析稳定性
        latency_values = [l["latency_ms"] for l in latencies_over_time]
        stability = {
            "samples": len(latency_values),
            "mean": statistics.mean(latency_values),
            "std": statistics.stdev(latency_values) if len(latency_values) > 1 else 0,
            "min": min(latency_values),
            "max": max(latency_values),
            "coefficient_of_variation": (
                statistics.stdev(latency_values) / statistics.mean(latency_values)
                if len(latency_values) > 1 and statistics.mean(latency_values) > 0
                else 0
            )
        }

        print(f"  样本数: {stability['samples']}")
        print(f"  平均延迟: {stability['mean']:.3f}ms")
        print(f"  标准差: {stability['std']:.3f}ms")
        print(f"  变异系数: {stability['coefficient_of_variation']:.3f}")

        return stability

    def _print_percentiles(self, prefix: str, p: LatencyPercentile):
        """打印百分位统计"""
        print(f"{prefix}: "
              f"avg={p.mean:.1f}us, "
              f"p50={p.p50:.1f}us, "
              f"p90={p.p90:.1f}us, "
              f"p95={p.p95:.1f}us, "
              f"p99={p.p99:.1f}us, "
              f"min={p.min_val:.1f}us, "
              f"max={p.max_val:.1f}us")

    def generate_report(self) -> Dict[str, Any]:
        """生成完整测试报告"""
        report = {
            "config": {
                "warmup_rounds": self.config.warmup_rounds,
                "measurement_rounds": self.config.measurement_rounds,
                "concurrency_levels": self.config.concurrency_levels,
                "payload_sizes": self.config.payload_sizes,
                "target_latency_us": self.config.target_latency_us,
            },
            "results": {},
            "violations": [],
            "recommendations": []
        }

        # 汇总结果
        for name, result in self.results.items():
            report["results"][name] = {
                "overall": {
                    "mean_us": result.overall.mean,
                    "p50_us": result.overall.p50,
                    "p90_us": result.overall.p90,
                    "p99_us": result.overall.p99,
                    "min_us": result.overall.min_val,
                    "max_us": result.overall.max_val,
                    "std_dev_us": result.overall.std_dev,
                    "count": result.overall.count
                }
            }
            report["violations"].extend(result.violations)

        # 生成建议
        for name, result in self.results.items():
            if result.overall.p99 > self.config.target_latency_us * 1000:
                report["recommendations"].append(
                    f"{name}: P99 延迟 ({result.overall.p99:.0f}us) 超过目标 ({self.config.target_latency_us * 1000}us)"
                )

        if not report["recommendations"]:
            report["recommendations"].append("所有延迟指标在目标范围内")

        return report

    def run_all(self) -> Dict[str, Any]:
        """运行所有测试"""
        print("=" * 60)
        print("AinosOS 延迟测试")
        print("=" * 60)

        # 1. 端到端延迟
        self.test_end_to_end_latency("sync_inference")

        # 2. 并发影响
        self.test_concurrency_impact()

        # 3. 负载大小影响
        self.test_payload_size_impact()

        # 4. 组件延迟分解
        self.test_component_breakdown()

        # 5. 延迟分布
        self.test_latency_distribution()

        # 6. 延迟抖动
        self.test_latency_jitter()

        # 7. 延迟稳定性
        self.test_latency_stability(30)

        # 生成报告
        report = self.generate_report()

        print("\n" + "=" * 60)
        print("延迟测试完成!")
        print(f"违规项: {len(report['violations'])}")
        print(f"建议: {len(report['recommendations'])}")

        return report


# ============================================================
# 单元测试
# ============================================================

class TestLatency(unittest.TestCase):
    """延迟测试单元测试"""

    def setUp(self):
        self.config = LatencyTestConfig(
            warmup_rounds=5,
            measurement_rounds=20,
            concurrency_levels=[1, 2, 4],
            payload_sizes=[100, 1000]
        )
        self.tester = LatencyTester(self.config)

    def test_end_to_end_latency(self):
        """测试端到端延迟测量"""
        report = self.tester.test_end_to_end_latency()
        self.assertGreater(report.overall.count, 0)
        self.assertGreater(report.overall.mean, 0)

    def test_concurrency_impact(self):
        """测试并发影响"""
        report = self.tester.test_concurrency_impact()
        for concurrency in self.config.concurrency_levels:
            self.assertIn(concurrency, report.by_concurrency)

    def test_payload_size_impact(self):
        """测试负载大小影响"""
        report = self.tester.test_payload_size_impact()
        for size in self.config.payload_sizes:
            self.assertIn(size, report.by_payload_size)

    def test_component_breakdown(self):
        """测试组件分解"""
        report = self.tester.test_component_breakdown()
        self.assertIn("total", report.component_breakdown)

    def test_percentile_calculation(self):
        """测试百分位计算"""
        latencies = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        p = self.tester.calculate_percentiles(latencies)
        self.assertAlmostEqual(p.p50, 5.5, delta=1.0)
        self.assertAlmostEqual(p.p90, 9.5, delta=1.0)
        self.assertAlmostEqual(p.min_val, 1.0)
        self.assertAlmostEqual(p.max_val, 10.0)

    def test_empty_latencies(self):
        """测试空延迟列表"""
        p = self.tester.calculate_percentiles([])
        self.assertEqual(p.count, 0)

    def test_single_latency(self):
        """测试单延迟值"""
        p = self.tester.calculate_percentiles([42.0])
        self.assertEqual(p.count, 1)
        self.assertAlmostEqual(p.mean, 42.0)

    def test_latency_distribution(self):
        """测试延迟分布"""
        distribution = self.tester.test_latency_distribution()
        self.assertGreater(distribution["total"], 0)

    def test_latency_jitter(self):
        """测试延迟抖动"""
        jitter = self.tester.test_latency_jitter()
        self.assertGreater(jitter["avg_jitter_ms"], 0)

    def test_latency_stability(self):
        """测试延迟稳定性"""
        stability = self.tester.test_latency_stability(5)
        self.assertGreater(stability["samples"], 0)
        self.assertGreater(stability["mean"], 0)


# ============================================================
# 主入口
# ============================================================

def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="AinosOS 延迟测试")
    parser.add_argument("--warmup", type=int, default=10, help="预热轮数")
    parser.add_argument("--rounds", type=int, default=100, help="测量轮数")
    parser.add_argument("--concurrency", type=str, default="1,2,4,8,16", help="并发级别列表")
    parser.add_argument("--payloads", type=str, default="10,100,1000,10000,100000", help="负载大小列表")
    parser.add_argument("--target", type=int, default=1000, help="目标延迟 (us)")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--unittest", action="store_true", help="运行单元测试")

    args = parser.parse_args()

    if args.unittest:
        unittest.main(argv=[sys.argv[0]])
        return

    config = LatencyTestConfig(
        warmup_rounds=args.warmup,
        measurement_rounds=args.rounds,
        concurrency_levels=[int(x) for x in args.concurrency.split(",")],
        payload_sizes=[int(x) for x in args.payloads.split(",")],
        target_latency_us=args.target
    )

    tester = LatencyTester(config)
    report = tester.run_all()

    if report["violations"]:
        print(f"\n发现 {len(report['violations'])} 个违规:")
        for v in report["violations"]:
            print(f"  - {v}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())