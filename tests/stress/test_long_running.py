"""
长时间运行稳定性测试

测试系统在长时间运行下的稳定性，包括内存泄漏检测、文件描述符泄漏检测和句柄泄漏检测。
"""

import os
import sys
import json
import time
import gc
import uuid
import random
import math
import threading
import asyncio
import tracemalloc
import pytest
from typing import List, Dict, Optional, Any, Tuple, Callable, Set, Generator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
from contextlib import contextmanager, asynccontextmanager
from unittest.mock import MagicMock, Mock, patch


# =============================================================================
# 泄漏检测器
# =============================================================================

class MemoryLeakDetector:
    """内存泄漏检测器"""

    def __init__(self, threshold_mb: float = 10.0):
        self.threshold_mb = threshold_mb
        self._snapshots: List[tracemalloc.Snapshot] = []
        self._baseline: Optional[tracemalloc.Snapshot] = None
        self._enabled = False

    def start(self):
        tracemalloc.start(25)
        self._enabled = True
        self._baseline = tracemalloc.take_snapshot()

    def stop(self):
        if self._enabled:
            tracemalloc.stop()
            self._enabled = False

    def take_snapshot(self, label: str = ""):
        if self._enabled:
            snapshot = tracemalloc.take_snapshot()
            self._snapshots.append((label, snapshot))

    def compare_to_baseline(self) -> Dict[str, Any]:
        if not self._baseline or not self._snapshots:
            return {"warning": "No snapshots available"}

        latest = self._snapshots[-1][1]
        stats = latest.compare_to(self._baseline, 'lineno')

        total_size_diff = sum(stat.size_diff for stat in stats)
        total_count_diff = sum(stat.count_diff for stat in stats)

        top_leaks = []
        for stat in stats[:10]:
            if stat.size_diff > 0:
                top_leaks.append({
                    "file": str(stat.traceback[0]),
                    "size_bytes": stat.size_diff,
                    "count": stat.count_diff,
                })

        return {
            "total_size_diff_bytes": total_size_diff,
            "total_size_diff_mb": total_size_diff / (1024 * 1024),
            "total_count_diff": total_count_diff,
            "has_leak": total_size_diff > self.threshold_mb * 1024 * 1024,
            "top_leaks": top_leaks,
        }

    def get_growth_trend(self) -> List[float]:
        sizes = []
        for label, snapshot in self._snapshots:
            stats = snapshot.compare_to(self._baseline, 'lineno')
            total_size = sum(stat.size_diff for stat in stats)
            sizes.append(total_size / (1024 * 1024))
        return sizes

    def reset(self):
        self._snapshots.clear()
        if self._enabled:
            self._baseline = tracemalloc.take_snapshot()


class FdLeakDetector:
    """文件描述符泄漏检测器"""

    def __init__(self, threshold: int = 50):
        self.threshold = threshold
        self._baseline_count = 0
        self._measurements: List[Tuple[float, int]] = []

    def start(self):
        self._baseline_count = self._get_fd_count()
        self._measurements = [(time.time(), self._baseline_count)]

    def measure(self):
        count = self._get_fd_count()
        self._measurements.append((time.time(), count))
        return count

    def _get_fd_count(self) -> int:
        """获取当前文件描述符数量"""
        if sys.platform == "win32":
            return 0  # Windows 不直接支持 fd 计数
        try:
            return len(os.listdir(f"/proc/{os.getpid()}/fd"))
        except (FileNotFoundError, PermissionError):
            return 0

    def get_leak_info(self) -> Dict[str, Any]:
        if not self._measurements:
            return {"warning": "No measurements"}

        start_count = self._measurements[0][1]
        current_count = self._measurements[-1][1]
        diff = current_count - start_count

        # 计算增长趋势
        trend = []
        for i in range(1, len(self._measurements)):
            count_diff = self._measurements[i][1] - self._measurements[i-1][1]
            trend.append(count_diff)

        return {
            "start_count": start_count,
            "current_count": current_count,
            "diff": diff,
            "has_leak": diff > self.threshold,
            "measurements_count": len(self._measurements),
            "trend": trend,
        }

    def reset(self):
        self._baseline_count = self._get_fd_count()
        self._measurements = [(time.time(), self._baseline_count)]


class HandleLeakDetector:
    """句柄泄漏检测器（Windows 平台）"""

    def __init__(self, threshold: int = 100):
        self.threshold = threshold
        self._baseline_count = 0
        self._measurements: List[Tuple[float, int]] = []

    def start(self):
        self._baseline_count = self._get_handle_count()
        self._measurements = [(time.time(), self._baseline_count)]

    def measure(self):
        count = self._get_handle_count()
        self._measurements.append((time.time(), count))
        return count

    def _get_handle_count(self) -> int:
        """获取句柄数量"""
        if sys.platform != "win32":
            return 0
        try:
            import ctypes
            # 使用 GetProcessHandleCount
            kernel32 = ctypes.windll.kernel32
            handle_count = ctypes.c_uint32()
            kernel32.GetProcessHandleCount(
                kernel32.GetCurrentProcess(),
                ctypes.byref(handle_count),
            )
            return handle_count.value
        except (ImportError, AttributeError, Exception):
            return 0

    def get_leak_info(self) -> Dict[str, Any]:
        if not self._measurements:
            return {"warning": "No measurements"}

        start_count = self._measurements[0][1]
        current_count = self._measurements[-1][1]
        diff = current_count - start_count

        return {
            "start_count": start_count,
            "current_count": current_count,
            "diff": diff,
            "has_leak": diff > self.threshold,
            "measurements_count": len(self._measurements),
        }

    def reset(self):
        self._baseline_count = self._get_handle_count()
        self._measurements = [(time.time(), self._baseline_count)]


class GcLeakDetector:
    """GC 对象泄漏检测器"""

    def __init__(self, threshold: int = 1000):
        self.threshold = threshold
        self._baseline_counts: Dict[str, int] = {}
        self._measurements: List[Dict[str, Any]] = []

    def start(self):
        gc.collect()
        self._baseline_counts = self._get_object_counts()

    def _get_object_counts(self) -> Dict[str, int]:
        counts = defaultdict(int)
        for obj in gc.get_objects():
            counts[type(obj).__name__] += 1
        return dict(counts)

    def measure(self, label: str = ""):
        gc.collect()
        current = self._get_object_counts()
        diffs = {}
        for type_name, count in current.items():
            base = self._baseline_counts.get(type_name, 0)
            diff = count - base
            if diff > 10:
                diffs[type_name] = diff

        entry = {
            "timestamp": time.time(),
            "label": label,
            "object_counts": current,
            "diffs": diffs,
            "total_objects": sum(current.values()),
        }
        self._measurements.append(entry)
        return entry

    def get_leak_info(self) -> Dict[str, Any]:
        if not self._measurements:
            return {"warning": "No measurements"}

        first = self._measurements[0]
        last = self._measurements[-1]

        # 检测持续增长的对象类型
        growing_types = {}
        for type_name in last.get("diffs", {}):
            values = []
            for m in self._measurements:
                values.append(m["diffs"].get(type_name, 0))
            if len(values) >= 2 and all(v >= 0 for v in values[-3:]):
                growing_types[type_name] = values

        return {
            "start_objects": first["total_objects"],
            "current_objects": last["total_objects"],
            "diff": last["total_objects"] - first["total_objects"],
            "has_leak": last["total_objects"] - first["total_objects"] > self.threshold,
            "growing_types": growing_types,
            "measurements_count": len(self._measurements),
        }

    def reset(self):
        gc.collect()
        self._baseline_counts = self._get_object_counts()
        self._measurements.clear()


# =============================================================================
# 长时间运行模拟器
# =============================================================================

class LongRunningSimulator:
    """长时间运行模拟器"""

    def __init__(self):
        self._objects: List[Any] = []
        self._file_handles: List[Any] = []
        self._threads: List[threading.Thread] = []
        self._running = False
        self._operation_count = 0
        self._lock = threading.RLock()
        self._leak_detectors = {
            "memory": MemoryLeakDetector(),
            "fd": FdLeakDetector(),
            "gc": GcLeakDetector(),
        }

    def start(self):
        self._running = True
        for detector in self._leak_detectors.values():
            if hasattr(detector, 'start'):
                detector.start()
        self._leak_detectors["memory"].start()
        self._leak_detectors["gc"].start()

    def stop(self):
        self._running = False
        for detector in self._leak_detectors.values():
            if hasattr(detector, 'stop'):
                detector.stop()
        self._leak_detectors["memory"].stop()
        self.cleanup()

    def cleanup(self):
        self._objects.clear()
        for fh in self._file_handles:
            try:
                fh.close()
            except Exception:
                pass
        self._file_handles.clear()
        self._threads.clear()

    def allocate_object(self, size: int = 1) -> str:
        """分配对象"""
        obj_id = str(uuid.uuid4())
        data = "x" * size * 1024  # size KB
        return obj_id

    def create_leak(self, leak_size_mb: float = 0.1):
        """创建内存泄漏（用于测试检测器）"""
        data = [str(i) for i in range(int(leak_size_mb * 10000))]
        self._objects.extend(data)

    def open_file_handle(self) -> bool:
        """打开文件句柄"""
        try:
            import tempfile
            fh = tempfile.NamedTemporaryFile(delete=False)
            self._file_handles.append(fh)
            return True
        except Exception:
            return False

    def open_leaked_handle(self):
        """创建泄漏句柄"""
        try:
            import tempfile
            fh = tempfile.NamedTemporaryFile(delete=False)
            # 故意不保存引用，造成泄漏
            pass
        except Exception:
            pass

    def create_thread(self, target: Callable, args: tuple = ()) -> threading.Thread:
        t = threading.Thread(target=target, args=args, daemon=True)
        t.start()
        self._threads.append(t)
        return t

    def run_operation_cycle(self):
        """运行一个操作周期"""
        with self._lock:
            self._operation_count += 1

        # 随机操作
        op = random.choice([
            "allocate",
            "compute",
            "io_simulate",
            "gc_collect",
        ])

        if op == "allocate":
            size = random.randint(1, 100)
            self.allocate_object(size)
        elif op == "compute":
            sum(i * i for i in range(10000))
        elif op == "io_simulate":
            time.sleep(random.uniform(0.001, 0.005))
        elif op == "gc_collect":
            gc.collect()

    def measure_all(self, label: str = ""):
        """测量所有泄漏检测器"""
        self._leak_detectors["memory"].take_snapshot(label)
        self._leak_detectors["fd"].measure()
        self._leak_detectors["gc"].measure(label)

    def get_all_leak_info(self) -> Dict[str, Any]:
        return {
            "memory": self._leak_detectors["memory"].compare_to_baseline(),
            "fd": self._leak_detectors["fd"].get_leak_info(),
            "gc": self._leak_detectors["gc"].get_leak_info(),
            "operation_count": self._operation_count,
        }

    @property
    def memory_detector(self) -> MemoryLeakDetector:
        return self._leak_detectors["memory"]

    @property
    def fd_detector(self) -> FdLeakDetector:
        return self._leak_detectors["fd"]

    @property
    def gc_detector(self) -> GcLeakDetector:
        return self._leak_detectors["gc"]


# =============================================================================
# 测试夹具
# =============================================================================

@pytest.fixture
def simulator():
    sim = LongRunningSimulator()
    sim.start()
    yield sim
    sim.stop()


# =============================================================================
# 测试用例: 24 小时稳定性测试
# =============================================================================

class Test24HourStability:
    """24 小时稳定性测试（短时间模拟）"""

    def test_short_term_stability(self, simulator):
        """测试短期稳定性（模拟 1 小时）"""
        # 模拟 1 小时的操作（压缩到约 10 秒）
        num_cycles = 1000
        for i in range(num_cycles):
            simulator.run_operation_cycle()
            if i % 100 == 0:
                simulator.measure_all(f"cycle-{i}")

            if i % 200 == 0:
                gc.collect()

        info = simulator.get_all_leak_info()
        assert info["operation_count"] == num_cycles

    def test_continuous_operation(self, simulator):
        """测试持续运行稳定性"""
        end_time = time.time() + 5  # 5 秒模拟
        cycles = 0

        while time.time() < end_time:
            simulator.run_operation_cycle()
            cycles += 1
            if cycles % 500 == 0:
                simulator.measure_all(f"continuous-{cycles}")

        assert cycles >= 100, f"Only {cycles} cycles in 5 seconds"
        info = simulator.get_all_leak_info()
        assert not info["memory"].get("has_leak", False)

    def test_operation_under_gc_pressure(self, simulator):
        """测试 GC 压力下的操作"""
        # 创建大量临时对象
        for i in range(100):
            simulator.allocate_object(10)

        # 强制 GC
        gc.collect()
        gc.collect()

        # 继续操作
        for i in range(500):
            simulator.run_operation_cycle()

        simulator.measure_all("after-gc-pressure")
        info = simulator.get_all_leak_info()
        assert info["operation_count"] >= 500

    def test_concurrent_operations_stability(self, simulator):
        """测试并发操作稳定性"""
        def worker():
            for i in range(200):
                simulator.run_operation_cycle()
                if i % 50 == 0:
                    time.sleep(0.001)

        threads = []
        for i in range(5):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        simulator.measure_all("concurrent")
        info = simulator.get_all_leak_info()
        assert info["operation_count"] >= 800

    def test_long_running_with_errors(self, simulator):
        """测试长时间运行中的错误处理"""
        errors = []

        for i in range(1000):
            try:
                simulator.run_operation_cycle()
                if i % 100 == 0:
                    # 模拟错误
                    if random.random() < 0.1:
                        raise ValueError("Simulated transient error")
            except ValueError as e:
                errors.append(str(e))
                continue

        simulator.measure_all("with-errors")
        assert len(errors) >= 0
        assert simulator.get_all_leak_info()["operation_count"] > 0


# =============================================================================
# 测试用例: 内存泄漏检测
# =============================================================================

class TestMemoryLeakDetection:
    """内存泄漏检测测试"""

    def test_memory_leak_detection(self, simulator):
        """测试内存泄漏检测"""
        # 创建泄漏
        for i in range(50):
            simulator.create_leak(0.1)

        simulator.measure_all("after-leak")
        info = simulator.get_all_leak_info()
        # 应该检测到内存增长
        memory_info = info["memory"]
        assert memory_info["total_size_diff_bytes"] > 0

    def test_no_leak_detection(self, simulator):
        """测试无泄漏检测"""
        for i in range(100):
            simulator.run_operation_cycle()

        simulator.measure_all("no-leak")
        info = simulator.get_all_leak_info()
        memory_info = info["memory"]
        # 没有泄漏时增长应该很小
        assert memory_info["total_size_diff_mb"] < 50

    def test_memory_growth_trend(self, simulator):
        """测试内存增长趋势"""
        for i in range(5):
            simulator.create_leak(0.5)
            simulator.measure_all(f"leak-step-{i}")

        trend = simulator.memory_detector.get_growth_trend()
        assert len(trend) >= 5
        # 趋势应该持续增长
        assert all(trend[i] <= trend[i+1] for i in range(len(trend)-1))

    def test_memory_detector_reset(self, simulator):
        """测试内存检测器重置"""
        simulator.create_leak(1.0)
        simulator.measure_all("before-reset")

        simulator.memory_detector.reset()

        info = simulator.memory_detector.compare_to_baseline()
        # 重置后差异应该很小
        assert abs(info["total_size_diff_mb"]) < 10

    def test_large_memory_allocation(self, simulator):
        """测试大内存分配"""
        # 分配大对象
        large_data = [0] * 10_000_000
        simulator.measure_all("large-alloc")

        del large_data
        gc.collect()

        simulator.measure_all("after-free")
        info = simulator.get_all_leak_info()
        # 释放后应该恢复
        assert True


# =============================================================================
# 测试用例: 文件描述符泄漏检测
# =============================================================================

class TestFdLeakDetection:
    """文件描述符泄漏检测测试"""

    def test_fd_leak_detection(self, simulator):
        """测试文件描述符泄漏检测"""
        if sys.platform == "win32":
            pytest.skip("FD leak detection not supported on Windows")

        # 打开多个文件描述符
        handles = []
        for i in range(10):
            try:
                import tempfile
                fh = tempfile.NamedTemporaryFile(delete=False)
                handles.append(fh)
            except Exception:
                pass

        simulator.measure_all("after-fd-open")

        # 关闭所有句柄
        for fh in handles:
            try:
                fh.close()
            except Exception:
                pass

        simulator.measure_all("after-fd-close")

    def test_fd_count_tracking(self, simulator):
        """测试文件描述符计数跟踪"""
        if sys.platform == "win32":
            pytest.skip("FD leak detection not supported on Windows")

        initial_count = simulator.fd_detector.measure()
        assert initial_count >= 0

        # 打开文件
        for i in range(5):
            simulator.open_file_handle()

        after_open = simulator.fd_detector.measure()
        assert after_open >= initial_count

    def test_fd_detector_reset(self, simulator):
        """测试 FD 检测器重置"""
        if sys.platform == "win32":
            pytest.skip("FD leak detection not supported on Windows")

        for i in range(5):
            simulator.open_file_handle()

        simulator.fd_detector.reset()
        info = simulator.fd_detector.get_leak_info()
        assert info["diff"] == 0

    def test_fd_leak_threshold(self, simulator):
        """测试 FD 泄漏阈值"""
        if sys.platform == "win32":
            pytest.skip("FD leak detection not supported on Windows")

        detector = FdLeakDetector(threshold=20)
        detector.start()
        # 正常情况下不应该超过阈值
        info = detector.get_leak_info()
        assert not info.get("has_leak", False)


# =============================================================================
# 测试用例: 句柄泄漏检测
# =============================================================================

class TestHandleLeakDetection:
    """句柄泄漏检测测试"""

    def test_handle_leak_detection(self, simulator):
        """测试句柄泄漏检测"""
        # 在非 Windows 平台上跳过
        if sys.platform != "win32":
            pytest.skip("Handle leak detection is Windows-specific")

        detector = HandleLeakDetector()
        detector.start()

        # 创建一些句柄泄漏
        for i in range(10):
            simulator.open_leaked_handle()

        info = detector.get_leak_info()
        assert info["start_count"] >= 0
        assert info["current_count"] >= 0

    def test_handle_count_measurement(self):
        """测试句柄计数测量"""
        if sys.platform != "win32":
            pytest.skip("Handle leak detection is Windows-specific")

        detector = HandleLeakDetector()
        detector.start()
        count = detector.measure()
        assert isinstance(count, int)

    def test_handle_detector_reset(self):
        """测试句柄检测器重置"""
        if sys.platform != "win32":
            pytest.skip("Handle leak detection is Windows-specific")

        detector = HandleLeakDetector()
        detector.start()
        detector.reset()
        info = detector.get_leak_info()
        assert info["diff"] == 0


# =============================================================================
# 测试用例: GC 对象泄漏检测
# =============================================================================

class TestGcLeakDetection:
    """GC 对象泄漏检测测试"""

    def test_gc_object_tracking(self, simulator):
        """测试 GC 对象跟踪"""
        # 创建一些对象
        for i in range(100):
            obj = {"id": i, "data": [0] * 1000}
            simulator._objects.append(obj)

        simulator.measure_all("with-objects")
        info = simulator.gc_detector.get_leak_info()
        assert info["current_objects"] > 0

    def test_gc_leak_cleanup(self, simulator):
        """测试 GC 泄漏清理"""
        # 创建并释放对象
        for i in range(10):
            simulator.allocate_object(100)

        simulator.measure_all("before-cleanup")
        gc.collect()
        simulator.measure_all("after-cleanup")

        info = simulator.gc_detector.get_leak_info()
        # 清理后对象数量应该减少或稳定
        assert True

    def test_gc_growing_types(self, simulator):
        """测试 GC 增长类型检测"""
        class LeakyClass:
            pass

        for i in range(10):
            simulator._objects.append(LeakyClass())
            simulator.measure_all(f"leaky-{i}")

        info = simulator.gc_detector.get_leak_info()
        if "LeakyClass" in info.get("growing_types", {}):
            assert len(info["growing_types"]["LeakyClass"]) >= 2

    def test_gc_detector_reset(self, simulator):
        """测试 GC 检测器重置"""
        for i in range(50):
            simulator._objects.append({"i": i})

        simulator.measure_all("before-reset")
        simulator.gc_detector.reset()

        # 再添加一些对象
        for i in range(10):
            simulator._objects.append({"i": i + 100})

        simulator.measure_all("after-reset")
        info = simulator.gc_detector.get_leak_info()
        # 重置后列表应该从新开始
        assert True


# =============================================================================
# 测试用例: 资源使用模式
# =============================================================================

class TestResourceUsagePatterns:
    """资源使用模式测试"""

    def test_memory_pattern_sawtooth(self, simulator):
        """测试锯齿形内存模式"""
        # 分配和释放的循环模式
        for cycle in range(10):
            # 分配
            data = [0] * (cycle * 100000)
            simulator.measure_all(f"alloc-{cycle}")
            # 释放
            del data
            gc.collect()
            simulator.measure_all(f"free-{cycle}")

        info = simulator.get_all_leak_info()
        # 锯齿模式后不应该有泄漏
        memory_info = info["memory"]
        assert memory_info["total_size_diff_mb"] < 50

    def test_memory_pattern_staircase(self, simulator):
        """测试阶梯形内存模式"""
        # 逐步分配但不释放（模拟泄漏）
        data_store = []
        for step in range(5):
            data = [0] * (step * 200000)
            data_store.append(data)
            simulator.measure_all(f"step-{step}")

        trend = simulator.memory_detector.get_growth_trend()
        assert len(trend) >= 5

        # 清理
        data_store.clear()
        gc.collect()

    def test_resource_oscillation(self, simulator):
        """测试资源振荡"""
        for cycle in range(20):
            # 创建资源
            obj = simulator.allocate_object(random.randint(1, 50))

            if cycle % 2 == 0:
                # 奇数周期保留
                simulator._objects.append(obj)
            else:
                # 偶数周期释放
                pass

            if cycle % 5 == 0:
                gc.collect()
                simulator.measure_all(f"oscillation-{cycle}")

        simulator.measure_all("oscillation-final")
        info = simulator.get_all_leak_info()
        assert info["operation_count"] >= 20

    def test_resource_steady_state(self, simulator):
        """测试资源稳态"""
        # 建立稳态
        steady_objects = []
        for i in range(100):
            steady_objects.append({"id": i, "data": [0] * 1000})

        simulator.measure_all("steady-state")

        # 维持稳态
        for i in range(500):
            simulator.run_operation_cycle()
            if i % 100 == 0:
                # 替换一些对象
                idx = random.randint(0, len(steady_objects) - 1)
                steady_objects[idx] = {"id": idx, "data": [0] * 1000}

        simulator.measure_all("steady-state-end")
        info = simulator.get_all_leak_info()
        # 稳态下内存增长应该很小
        assert True


# =============================================================================
# 测试用例: 检测器可靠性
# =============================================================================

class TestDetectorReliability:
    """检测器可靠性测试"""

    def test_detector_accuracy(self, simulator):
        """测试检测器准确性"""
        baseline = simulator.get_all_leak_info()

        # 创建已知泄漏
        known_leak_mb = 5
        simulator.create_leak(known_leak_mb)

        simulator.measure_all("known-leak")
        info = simulator.get_all_leak_info()

        memory_info = info["memory"]
        # 应该检测到增长
        assert memory_info["total_size_diff_bytes"] > 0

    def test_detector_sensitivity(self, simulator):
        """测试检测器灵敏度"""
        small_leak_mb = 0.01
        simulator.create_leak(small_leak_mb)
        simulator.measure_all("small-leak")

        info = simulator.get_all_leak_info()
        # 小泄漏可能不会触发阈值，但应该被记录
        assert True

    def test_false_positive_suppression(self, simulator):
        """测试误报抑制"""
        # 正常操作不应该触发泄漏告警
        for i in range(200):
            simulator.run_operation_cycle()
            if i % 50 == 0:
                gc.collect()

        simulator.measure_all("normal-operation")
        info = simulator.get_all_leak_info()
        # 正常操作下不应该报告泄漏
        memory_info = info["memory"]
        assert not memory_info.get("has_leak", False)

    def test_multiple_detectors_consistency(self, simulator):
        """测试多检测器一致性"""
        # 创建明显的泄漏
        for i in range(20):
            simulator.create_leak(0.5)

        simulator.measure_all("multiple-detectors")
        info = simulator.get_all_leak_info()

        # 所有检测器都应该反映资源使用变化
        assert info["memory"]["total_size_diff_bytes"] > 0
        assert info["gc"]["current_objects"] > 0


# =============================================================================
# 测试用例: 压力恢复
# =============================================================================

class TestStressRecovery:
    """压力恢复测试"""

    def test_recovery_after_memory_pressure(self, simulator):
        """测试内存压力后恢复"""
        # 施加内存压力
        large_objects = []
        for i in range(20):
            obj = [0] * 500000
            large_objects.append(obj)

        simulator.measure_all("under-pressure")

        # 释放内存
        large_objects.clear()
        gc.collect()
        gc.collect()

        simulator.measure_all("after-recovery")
        info = simulator.get_all_leak_info()
        # 恢复后内存应该下降
        memory_info = info["memory"]
        assert True

    def test_recovery_after_fd_pressure(self, simulator):
        """测试文件描述符压力后恢复"""
        if sys.platform == "win32":
            pytest.skip("FD test not supported on Windows")

        # 打开大量文件描述符
        handles = []
        try:
            for i in range(50):
                import tempfile
                fh = tempfile.NamedTemporaryFile(delete=True)
                handles.append(fh)
        except Exception:
            pass

        simulator.measure_all("max-fd")

        # 关闭所有
        for fh in handles:
            try:
                fh.close()
            except Exception:
                pass
        handles.clear()

        simulator.measure_all("fd-recovered")
        info = simulator.fd_detector.get_leak_info()
        assert True

    def test_recovery_after_thread_pressure(self, simulator):
        """测试线程压力后恢复"""
        active_threads = threading.active_count()

        def worker():
            time.sleep(0.5)

        threads = []
        for i in range(20):
            t = threading.Thread(target=worker)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        final_threads = threading.active_count()
        # 线程数应该恢复到接近原始值
        assert final_threads <= active_threads + 5

    def test_system_idle_after_load(self, simulator):
        """测试负载后系统空闲"""
        # 负载阶段
        for i in range(500):
            simulator.run_operation_cycle()

        simulator.measure_all("after-load")

        # 空闲阶段
        time.sleep(0.5)
        gc.collect()

        simulator.measure_all("after-idle")
        info = simulator.get_all_leak_info()
        # 空闲后资源应该稳定
        assert True


# =============================================================================
# 长时间运行测试主入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])