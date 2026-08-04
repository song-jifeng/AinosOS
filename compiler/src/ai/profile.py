"""
AI 编译器工具链 - 性能分析引导优化
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class ProfileSample:
    """性能分析样本"""
    function_name: str
    block_name: str
    execution_count: int = 0
    total_time: float = 0.0
    min_time: float = float('inf')
    max_time: float = 0.0
    avg_time: float = 0.0
    cache_misses: int = 0
    branch_mispredictions: int = 0

    def record(self, elapsed: float) -> None:
        """记录一次执行"""
        self.execution_count += 1
        self.total_time += elapsed
        self.min_time = min(self.min_time, elapsed)
        self.max_time = max(self.max_time, elapsed)
        self.avg_time = self.total_time / self.execution_count


@dataclass
class ProfileData:
    """性能分析数据"""
    samples: dict[str, ProfileSample] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    total_execution_time: float = 0.0
    hot_functions: list[str] = field(default_factory=list)
    cold_functions: list[str] = field(default_factory=list)

    def add_sample(self, key: str, sample: ProfileSample) -> None:
        """添加样本"""
        if key in self.samples:
            existing = self.samples[key]
            existing.execution_count += sample.execution_count
            existing.total_time += sample.total_time
            existing.min_time = min(existing.min_time, sample.min_time)
            existing.max_time = max(existing.max_time, sample.max_time)
            existing.avg_time = existing.total_time / existing.execution_count
        else:
            self.samples[key] = sample

    def get_hot_functions(self, threshold: float = 0.1) -> list[str]:
        """获取热点函数（占总执行时间比例超过 threshold 的函数）"""
        if not self.samples:
            return []
        total = sum(s.total_time for s in self.samples.values())
        if total == 0:
            return []
        hot = []
        for key, sample in self.samples.items():
            ratio = sample.total_time / total
            if ratio >= threshold:
                hot.append(key)
        return sorted(hot, key=lambda k: self.samples[k].total_time, reverse=True)

    def get_cold_functions(self, threshold: float = 0.01) -> list[str]:
        """获取冷函数"""
        if not self.samples:
            return []
        total = sum(s.total_time for s in self.samples.values())
        if total == 0:
            return []
        cold = []
        for key, sample in self.samples.items():
            ratio = sample.total_time / total
            if ratio <= threshold:
                cold.append(key)
        return sorted(cold, key=lambda k: self.samples[k].total_time)

    def summary(self) -> str:
        """生成性能分析摘要"""
        lines = ["性能分析摘要:"]
        lines.append(f"  总执行时间: {self.total_execution_time:.6f}s")
        lines.append(f"  采样数: {len(self.samples)}")
        lines.append(f"  热点函数: {', '.join(self.get_hot_functions())}")
        lines.append(f"  冷函数: {', '.join(self.get_cold_functions())}")
        lines.append("")
        lines.append("  函数执行详情:")
        for key in sorted(self.samples.keys(), key=lambda k: self.samples[k].total_time, reverse=True):
            s = self.samples[key]
            lines.append(f"    {key}: count={s.execution_count}, total={s.total_time:.6f}s, "
                         f"avg={s.avg_time:.6f}s, min={s.min_time:.6f}s, max={s.max_time:.6f}s")
        return "\n".join(lines)


class Profiler:
    """性能分析器"""

    def __init__(self):
        self.data: ProfileData = ProfileData()
        self._enabled: bool = False
        self._timers: dict[str, float] = {}

    def start(self) -> None:
        """启动性能分析"""
        self._enabled = True
        self.data.start_time = time.time()
        self.data = ProfileData()

    def stop(self) -> ProfileData:
        """停止性能分析"""
        self._enabled = False
        self.data.end_time = time.time()
        self.data.total_execution_time = self.data.end_time - self.data.start_time
        self.data.hot_functions = self.data.get_hot_functions()
        self.data.cold_functions = self.data.get_cold_functions()
        return self.data

    def begin_sample(self, function_name: str, block_name: str = "") -> None:
        """开始采样"""
        if not self._enabled:
            return
        key = f"{function_name}:{block_name}" if block_name else function_name
        self._timers[key] = time.perf_counter()

    def end_sample(self, function_name: str, block_name: str = "") -> None:
        """结束采样"""
        if not self._enabled:
            return
        key = f"{function_name}:{block_name}" if block_name else function_name
        if key in self._timers:
            elapsed = time.perf_counter() - self._timers[key]
            if key not in self.data.samples:
                self.data.samples[key] = ProfileSample(function_name, block_name)
            self.data.samples[key].record(elapsed)
            del self._timers[key]

    def reset(self) -> None:
        """重置性能分析器"""
        self.data = ProfileData()
        self._timers.clear()

    @property
    def is_enabled(self) -> bool:
        return self._enabled


class ProfileGuidedOptimizer:
    """性能分析引导优化器"""

    def __init__(self, profile_data: Optional[ProfileData] = None):
        self.profile_data = profile_data or ProfileData()

    def set_profile_data(self, data: ProfileData) -> None:
        """设置性能分析数据"""
        self.profile_data = data

    def get_optimization_hints(self) -> dict[str, Any]:
        """获取优化提示"""
        hints = {
            "inline_candidates": [],
            "unroll_candidates": [],
            "cold_functions": [],
            "hot_loops": [],
        }

        if not self.profile_data.samples:
            return hints

        total_time = sum(s.total_time for s in self.profile_data.samples.values())
        if total_time == 0:
            return hints

        for key, sample in self.profile_data.samples.items():
            ratio = sample.total_time / total_time
            if ratio > 0.2:
                hints["hot_loops"].append(key)
            if ratio > 0.1 and sample.execution_count > 100:
                hints["inline_candidates"].append(key)
            if ratio < 0.01:
                hints["cold_functions"].append(key)
            if sample.execution_count > 1000:
                hints["unroll_candidates"].append(key)

        return hints

    def should_inline(self, function_name: str) -> bool:
        """检查函数是否应该内联"""
        for key, sample in self.profile_data.samples.items():
            if function_name in key:
                if sample.execution_count > 100 and sample.total_time > 0.01:
                    return True
        return False

    def should_unroll(self, loop_key: str) -> bool:
        """检查循环是否应该展开"""
        if loop_key in self.profile_data.samples:
            sample = self.profile_data.samples[loop_key]
            return sample.execution_count > 500
        return False

    def get_function_importance(self, function_name: str) -> float:
        """获取函数重要性分数"""
        total_time = sum(s.total_time for s in self.profile_data.samples.values())
        if total_time == 0:
            return 0.0
        func_time = sum(
            s.total_time for key, s in self.profile_data.samples.items()
            if function_name in key
        )
        return func_time / total_time


class SimulatedProfiler:
    """模拟性能分析器（用于测试）"""

    @staticmethod
    def generate_mock_data() -> ProfileData:
        """生成模拟性能分析数据"""
        data = ProfileData()
        data.start_time = 0.0
        data.end_time = 10.0
        data.total_execution_time = 10.0

        samples = [
            ("matmul", 100, 5.0),
            ("conv2d", 50, 2.5),
            ("relu", 200, 1.0),
            ("softmax", 30, 0.8),
            ("init_tensor", 20, 0.3),
            ("reshape", 15, 0.2),
            ("transpose", 10, 0.1),
            ("helper", 5, 0.05),
        ]

        for name, count, total in samples:
            sample = ProfileSample(name, "")
            for _ in range(count):
                avg = total / count if count > 0 else 0
                sample.record(avg)
            data.samples[name] = sample

        data.hot_functions = data.get_hot_functions()
        return data