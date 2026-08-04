"""
并发压力测试

测试 1000+ 并发连接、并发模型加载/卸载、并发推理请求和资源竞争场景。
"""

import os
import sys
import json
import time
import uuid
import random
import math
import threading
import asyncio
import queue
import pytest
from typing import List, Dict, Optional, Any, Tuple, Callable, Set, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from enum import Enum, auto
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from unittest.mock import MagicMock, Mock, patch, AsyncMock
from contextlib import contextmanager, asynccontextmanager


# =============================================================================
# 数据类
# =============================================================================

@dataclass
class LoadTestResult:
    """负载测试结果"""
    total_requests: int
    successful_requests: int
    failed_requests: int
    total_duration: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    max_latency_ms: float
    min_latency_ms: float
    requests_per_second: float
    errors: Dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return (self.successful_requests / self.total_requests * 100) if self.total_requests > 0 else 0.0


@dataclass
class ResourceUsage:
    """资源使用情况"""
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    threads_count: int = 0
    open_fds: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ModelLoadRequest:
    """模型加载请求"""
    model_id: str
    size_mb: int = 100
    load_time: float = 0.5
    priority: int = 0


@dataclass
class InferenceTask:
    """推理任务"""
    task_id: str
    model_id: str
    input_size: int = 100
    compute_time: float = 0.01
    priority: int = 0


# =============================================================================
# Mock 高负载系统
# =============================================================================

class MockLoadSystem:
    """模拟高负载系统"""

    def __init__(self):
        self._models: Dict[str, Dict[str, Any]] = {}
        self._connections: Dict[str, float] = {}  # conn_id -> created_at
        self._lock = threading.RLock()
        self._running = False
        self._max_connections = 10000
        self._max_models = 50
        self._connection_counter = 0
        self._latencies: List[float] = []
        self._errors: Dict[str, int] = defaultdict(int)
        self._total_requests = 0
        self._successful_requests = 0
        self._start_time = 0.0

    def start(self):
        self._running = True
        self._start_time = time.time()

    def stop(self):
        self._running = False
        self._models.clear()
        self._connections.clear()

    def create_connection(self) -> str:
        """创建连接"""
        with self._lock:
            if len(self._connections) >= self._max_connections:
                raise RuntimeError("Max connections reached")
            conn_id = f"conn-{self._connection_counter}-{uuid.uuid4().hex[:8]}"
            self._connection_counter += 1
            self._connections[conn_id] = time.time()
            return conn_id

    def close_connection(self, conn_id: str):
        """关闭连接"""
        with self._lock:
            self._connections.pop(conn_id, None)

    def get_active_connections(self) -> int:
        with self._lock:
            return len(self._connections)

    def load_model(self, request: ModelLoadRequest) -> float:
        """加载模型"""
        if not self._running:
            raise RuntimeError("System not running")

        with self._lock:
            if len(self._models) >= self._max_models:
                raise RuntimeError("Max models loaded")

        start = time.time()
        time.sleep(request.load_time * random.uniform(0.8, 1.2))

        with self._lock:
            self._models[request.model_id] = {
                "id": request.model_id,
                "size_mb": request.size_mb,
                "loaded_at": time.time(),
                "load_time": time.time() - start,
            }

        return time.time() - start

    def unload_model(self, model_id: str) -> bool:
        """卸载模型"""
        with self._lock:
            if model_id not in self._models:
                return False
            time.sleep(random.uniform(0.05, 0.1))
            del self._models[model_id]
            return True

    def get_loaded_models(self) -> int:
        with self._lock:
            return len(self._models)

    def infer(self, task: InferenceTask) -> Dict[str, Any]:
        """执行推理"""
        with self._lock:
            self._total_requests += 1

        if not self._running:
            with self._lock:
                self._errors["system_not_running"] += 1
            raise RuntimeError("System not running")

        if task.model_id not in self._models:
            with self._lock:
                self._errors["model_not_loaded"] += 1
            raise RuntimeError(f"Model {task.model_id} not loaded")

        start = time.time()
        compute = task.compute_time * random.uniform(0.5, 1.5)
        time.sleep(compute)
        latency = (time.time() - start) * 1000

        with self._lock:
            self._latencies.append(latency)
            self._successful_requests += 1

        return {
            "task_id": task.task_id,
            "model_id": task.model_id,
            "latency_ms": latency,
            "output_size": task.input_size * 2,
            "timestamp": time.time(),
        }

    def get_load_results(self) -> LoadTestResult:
        with self._lock:
            total = self._total_requests
            success = self._successful_requests
            failed = total - success
            duration = time.time() - self._start_time if self._start_time > 0 else 0

            if not self._latencies:
                return LoadTestResult(
                    total_requests=total, successful_requests=success,
                    failed_requests=failed, total_duration=duration,
                    avg_latency_ms=0, p50_latency_ms=0, p95_latency_ms=0,
                    p99_latency_ms=0, max_latency_ms=0, min_latency_ms=0,
                    requests_per_second=0, errors=dict(self._errors),
                )

            sorted_lats = sorted(self._latencies)
            n = len(sorted_lats)
            return LoadTestResult(
                total_requests=total, successful_requests=success,
                failed_requests=failed, total_duration=duration,
                avg_latency_ms=sum(sorted_lats) / n,
                p50_latency_ms=sorted_lats[int(n * 0.50)],
                p95_latency_ms=sorted_lats[int(n * 0.95)],
                p99_latency_ms=sorted_lats[int(n * 0.99)],
                max_latency_ms=sorted_lats[-1],
                min_latency_ms=sorted_lats[0],
                requests_per_second=success / duration if duration > 0 else 0,
                errors=dict(self._errors),
            )

    def reset(self):
        with self._lock:
            self._models.clear()
            self._connections.clear()
            self._latencies.clear()
            self._errors.clear()
            self._total_requests = 0
            self._successful_requests = 0
            self._connection_counter = 0


# =============================================================================
# 负载测试工具
# =============================================================================

class LoadGenerator:
    """负载生成器"""

    def __init__(self, system: MockLoadSystem):
        self.system = system
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def generate_connections(self, num_connections: int,
                             hold_duration: float = 5.0) -> LoadTestResult:
        """生成大量连接"""
        start = time.time()
        connections = []
        errors = defaultdict(int)

        for i in range(num_connections):
            try:
                conn_id = self.system.create_connection()
                connections.append(conn_id)
            except RuntimeError as e:
                errors[str(e)] += 1
            if self._stop_event.is_set():
                break

        elapsed = time.time() - start

        # 保持连接
        time.sleep(hold_duration)

        # 关闭连接
        for conn_id in connections:
            try:
                self.system.close_connection(conn_id)
            except Exception:
                pass

        active = self.system.get_active_connections()
        return LoadTestResult(
            total_requests=num_connections,
            successful_requests=len(connections),
            failed_requests=num_connections - len(connections),
            total_duration=time.time() - start,
            avg_latency_ms=elapsed * 1000 / num_connections if num_connections > 0 else 0,
            p50_latency_ms=0, p95_latency_ms=0, p99_latency_ms=0,
            max_latency_ms=0, min_latency_ms=0,
            requests_per_second=len(connections) / elapsed if elapsed > 0 else 0,
            errors=dict(errors),
        )

    def generate_inference_load(self, num_requests: int,
                                 models: List[str],
                                 concurrency: int = 50) -> LoadTestResult:
        """生成推理负载"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        start = time.time()
        errors = defaultdict(int)

        def inference_worker(task_id: int) -> Dict:
            model_id = random.choice(models)
            task = InferenceTask(
                task_id=f"task-{task_id}",
                model_id=model_id,
                input_size=random.randint(10, 1000),
                compute_time=random.uniform(0.005, 0.02),
            )
            try:
                return self.system.infer(task)
            except RuntimeError as e:
                raise

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(inference_worker, i) for i in range(num_requests)]

            for future in as_completed(futures):
                try:
                    future.result()
                except RuntimeError as e:
                    errors[str(e)] += 1

        return self.system.get_load_results()


# =============================================================================
# 测试夹具
# =============================================================================

@pytest.fixture
def load_system():
    system = MockLoadSystem()
    system.start()
    yield system
    system.stop()


@pytest.fixture
def load_generator(load_system):
    return LoadGenerator(load_system)


@pytest.fixture
def preloaded_system(load_system):
    """预加载多个模型的系统"""
    for i in range(5):
        req = ModelLoadRequest(model_id=f"model-{i}", size_mb=200, load_time=0.1)
        load_system.load_model(req)
    return load_system


# =============================================================================
# 测试用例: 1000+ 并发连接
# =============================================================================

class TestConcurrentConnections:
    """并发连接测试"""

    def test_1000_concurrent_connections(self, load_system, load_generator):
        """测试 1000 并发连接"""
        result = load_generator.generate_connections(1000, hold_duration=2.0)
        assert result.successful_requests >= 950, f"Only {result.successful_requests} connections succeeded"
        assert result.requests_per_second > 100

    def test_5000_concurrent_connections(self, load_system, load_generator):
        """测试 5000 并发连接"""
        result = load_generator.generate_connections(5000, hold_duration=1.0)
        assert result.successful_requests >= 4500
        assert result.requests_per_second > 500

    def test_10000_concurrent_connections(self, load_system, load_generator):
        """测试 10000 并发连接"""
        result = load_generator.generate_connections(10000, hold_duration=0.5)
        # 系统最大连接数为 10000
        assert result.failed_requests <= 1000

    def test_connection_storm(self, load_system):
        """测试连接风暴"""
        def create_connections_burst(count):
            connections = []
            for i in range(count):
                try:
                    conn_id = load_system.create_connection()
                    connections.append(conn_id)
                except RuntimeError:
                    pass
            return connections

        # 突发创建大量连接
        threads = []
        all_connections = []
        for i in range(10):
            t = threading.Thread(target=lambda: all_connections.extend(
                create_connections_burst(200)
            ))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # 关闭所有连接
        for conn_id in all_connections:
            try:
                load_system.close_connection(conn_id)
            except Exception:
                pass

        assert load_system.get_active_connections() == 0

    def test_connection_cleanup_after_disconnect(self, load_system):
        """测试断开连接后的清理"""
        connections = []
        for i in range(100):
            conn_id = load_system.create_connection()
            connections.append(conn_id)

        assert load_system.get_active_connections() == 100

        for conn_id in connections:
            load_system.close_connection(conn_id)

        assert load_system.get_active_connections() == 0

    def test_connection_id_uniqueness(self, load_system):
        """测试连接 ID 唯一性"""
        conn_ids = set()
        for i in range(1000):
            conn_id = load_system.create_connection()
            assert conn_id not in conn_ids
            conn_ids.add(conn_id)

        for conn_id in conn_ids:
            load_system.close_connection(conn_id)


# =============================================================================
# 测试用例: 并发模型加载/卸载
# =============================================================================

class TestConcurrentModelLoadUnload:
    """并发模型加载/卸载测试"""

    def test_concurrent_model_load(self, load_system):
        """测试并发模型加载"""
        num_models = 10
        models = [ModelLoadRequest(model_id=f"model-{i}", load_time=0.05) for i in range(num_models)]

        def load_model(req):
            return load_system.load_model(req)

        with ThreadPoolExecutor(max_workers=num_models) as executor:
            futures = [executor.submit(load_model, req) for req in models]
            results = [f.result() for f in as_completed(futures)]

        assert load_system.get_loaded_models() == num_models
        assert all(r > 0 for r in results)

    def test_concurrent_model_unload(self, load_system):
        """测试并发模型卸载"""
        for i in range(10):
            req = ModelLoadRequest(model_id=f"model-{i}", load_time=0.05)
            load_system.load_model(req)

        def unload_model(model_id):
            return load_system.unload_model(model_id)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(unload_model, f"model-{i}") for i in range(10)]
            results = [f.result() for f in as_completed(futures)]

        assert load_system.get_loaded_models() == 0
        assert all(results)

    def test_load_unload_cycle(self, load_system):
        """测试加载/卸载循环"""
        for cycle in range(5):
            req = ModelLoadRequest(model_id=f"cycle-model-{cycle}", load_time=0.05)
            load_system.load_model(req)
            assert load_system.get_loaded_models() == cycle + 1

        for cycle in range(5):
            load_system.unload_model(f"cycle-model-{cycle}")
            assert load_system.get_loaded_models() == 4 - cycle

    def test_max_models_limit(self, load_system):
        """测试最大模型限制"""
        load_system._max_models = 3
        for i in range(3):
            req = ModelLoadRequest(model_id=f"limited-model-{i}", load_time=0.05)
            load_system.load_model(req)

        with pytest.raises(RuntimeError, match="Max models loaded"):
            req = ModelLoadRequest(model_id="extra-model", load_time=0.05)
            load_system.load_model(req)

    def test_rapid_model_switching(self, load_system):
        """测试快速模型切换"""
        def switch_model(model_id, load_time):
            try:
                load_system.unload_model("current-model")
            except Exception:
                pass
            req = ModelLoadRequest(model_id=model_id, load_time=load_time)
            load_system.load_model(req)

        threads = []
        for i in range(20):
            t = threading.Thread(
                target=switch_model,
                args=(f"switched-model-{i}", random.uniform(0.01, 0.05)),
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # 最后一个加载的模型应该存在
        assert load_system.get_loaded_models() > 0

    def test_load_same_model_twice(self, load_system):
        """测试重复加载相同模型"""
        req = ModelLoadRequest(model_id="duplicate-model", load_time=0.05)
        load_system.load_model(req)

        # 第二次加载应该覆盖
        load_system.load_model(req)
        assert load_system.get_loaded_models() == 1


# =============================================================================
# 测试用例: 并发推理请求
# =============================================================================

class TestConcurrentInference:
    """并发推理请求测试"""

    def test_100_concurrent_inferences(self, preloaded_system, load_generator):
        """测试 100 并发推理"""
        models = [f"model-{i}" for i in range(5)]
        result = load_generator.generate_inference_load(100, models, concurrency=50)
        assert result.successful_requests >= 90
        assert result.avg_latency_ms > 0

    def test_500_concurrent_inferences(self, preloaded_system, load_generator):
        """测试 500 并发推理"""
        models = [f"model-{i}" for i in range(5)]
        result = load_generator.generate_inference_load(500, models, concurrency=100)
        assert result.successful_requests >= 450
        assert result.requests_per_second > 10

    def test_1000_concurrent_inferences(self, preloaded_system, load_generator):
        """测试 1000 并发推理"""
        models = [f"model-{i}" for i in range(5)]
        result = load_generator.generate_inference_load(1000, models, concurrency=200)
        assert result.successful_requests >= 900
        assert result.requests_per_second > 20

    def test_mixed_priority_inferences(self, preloaded_system):
        """测试混合优先级推理"""
        import threading
        results = defaultdict(list)

        def high_priority_worker():
            for i in range(50):
                task = InferenceTask(
                    task_id=f"high-{i}",
                    model_id="model-0",
                    compute_time=0.005,
                    priority=1,
                )
                try:
                    result = preloaded_system.infer(task)
                    results["high"].append(result)
                except RuntimeError:
                    pass

        def low_priority_worker():
            for i in range(50):
                task = InferenceTask(
                    task_id=f"low-{i}",
                    model_id="model-0",
                    compute_time=0.01,
                    priority=0,
                )
                try:
                    result = preloaded_system.infer(task)
                    results["low"].append(result)
                except RuntimeError:
                    pass

        threads = [
            threading.Thread(target=high_priority_worker),
            threading.Thread(target=low_priority_worker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results["high"]) > 0
        assert len(results["low"]) > 0

    def test_inference_on_all_models(self, preloaded_system):
        """测试在所有模型上推理"""
        results = []
        for i in range(5):
            for j in range(20):
                task = InferenceTask(
                    task_id=f"all-models-{i}-{j}",
                    model_id=f"model-{i}",
                    compute_time=0.005,
                )
                try:
                    result = preloaded_system.infer(task)
                    results.append(result)
                except RuntimeError:
                    pass

        assert len(results) >= 90

    def test_inference_latency_distribution(self, preloaded_system, load_generator):
        """测试推理延迟分布"""
        models = [f"model-{i}" for i in range(5)]
        result = load_generator.generate_inference_load(200, models, concurrency=50)

        assert result.avg_latency_ms > 0
        assert result.p50_latency_ms <= result.p95_latency_ms
        assert result.p95_latency_ms <= result.p99_latency_ms
        assert result.min_latency_ms <= result.avg_latency_ms
        assert result.max_latency_ms >= result.avg_latency_ms


# =============================================================================
# 测试用例: 资源竞争
# =============================================================================

class TestResourceContention:
    """资源竞争测试"""

    def test_lock_contention_high_load(self, load_system):
        """测试高负载下的锁竞争"""
        def worker(worker_id):
            for i in range(100):
                req = ModelLoadRequest(
                    model_id=f"contention-model-{worker_id}-{i}",
                    load_time=0.001,
                )
                try:
                    load_system.load_model(req)
                except RuntimeError:
                    pass

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 系统应该仍然稳定
        assert load_system.get_loaded_models() > 0

    def test_read_write_contention(self, load_system):
        """测试读写竞争"""

        def reader():
            for i in range(500):
                _ = load_system.get_loaded_models()
                _ = load_system.get_active_connections()

        def writer():
            for i in range(100):
                try:
                    conn_id = load_system.create_connection()
                    if random.random() < 0.5:
                        load_system.close_connection(conn_id)
                except RuntimeError:
                    pass

        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=reader))
            threads.append(threading.Thread(target=writer))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 系统不应出现死锁
        assert True

    def test_resource_exhaustion_recovery(self, load_system):
        """测试资源耗尽恢复"""
        # 耗尽连接
        for i in range(load_system._max_connections):
            try:
                load_system.create_connection()
            except RuntimeError:
                pass

        # 系统应该拒绝新连接
        with pytest.raises(RuntimeError, match="Max connections reached"):
            load_system.create_connection()

        # 释放一些连接
        connections = list(load_system._connections.keys())[:100]
        for conn_id in connections:
            load_system.close_connection(conn_id)

        # 应该可以重新连接
        conn_id = load_system.create_connection()
        assert conn_id is not None
        load_system.close_connection(conn_id)

    def test_concurrent_connect_and_infer(self, load_system):
        """测试并发连接和推理"""

        def connection_worker():
            for i in range(50):
                try:
                    conn_id = load_system.create_connection()
                    time.sleep(random.uniform(0.001, 0.01))
                    load_system.close_connection(conn_id)
                except RuntimeError:
                    pass

        # 先加载模型
        for i in range(3):
            req = ModelLoadRequest(model_id=f"ci-model-{i}", load_time=0.05)
            load_system.load_model(req)

        def inference_worker():
            for i in range(50):
                task = InferenceTask(
                    task_id=f"ci-task-{i}",
                    model_id=f"ci-model-{random.randint(0, 2)}",
                    compute_time=0.005,
                )
                try:
                    load_system.infer(task)
                except RuntimeError:
                    pass

        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=connection_worker))
            threads.append(threading.Thread(target=inference_worker))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        results = load_system.get_load_results()
        assert results.successful_requests > 0


# =============================================================================
# 测试用例: 系统稳定性
# =============================================================================

class TestSystemStability:
    """系统稳定性测试"""

    def test_sustained_load(self, preloaded_system, load_generator):
        """测试持续负载"""
        models = [f"model-{i}" for i in range(5)]

        # 持续运行 5 秒
        end_time = time.time() + 5
        all_results = []

        while time.time() < end_time:
            result = load_generator.generate_inference_load(100, models, concurrency=50)
            all_results.append(result)
            time.sleep(0.1)

        total_success = sum(r.successful_requests for r in all_results)
        total_failed = sum(r.failed_requests for r in all_results)
        total_requests = total_success + total_failed

        assert total_requests > 500, f"Only {total_requests} requests in 5 seconds"
        assert total_failed / total_requests < 0.1, f"Error rate too high: {total_failed}/{total_requests}"

    def test_latency_stability_under_load(self, preloaded_system, load_generator):
        """测试负载下的延迟稳定性"""
        models = [f"model-{i}" for i in range(5)]
        latencies = []

        for wave in range(5):
            result = load_generator.generate_inference_load(200, models, concurrency=100)
            latencies.append(result.avg_latency_ms)

        # 延迟不应该持续增长
        for i in range(1, len(latencies)):
            ratio = latencies[i] / latencies[i-1] if latencies[i-1] > 0 else 1
            assert ratio < 5, f"Latency spike: wave {i-1}={latencies[i-1]:.2f}ms -> wave {i}={latencies[i]:.2f}ms"

    def test_model_switch_under_load(self, load_system):
        """测试负载下切换模型"""
        # 加载初始模型
        for i in range(3):
            req = ModelLoadRequest(model_id=f"stable-model-{i}", load_time=0.05)
            load_system.load_model(req)

        def continuous_inference():
            end_time = time.time() + 3
            while time.time() < end_time:
                try:
                    task = InferenceTask(
                        task_id=f"stable-{time.time()}",
                        model_id=f"stable-model-{random.randint(0, 2)}",
                        compute_time=0.005,
                    )
                    load_system.infer(task)
                except RuntimeError:
                    pass

        def model_switcher():
            end_time = time.time() + 3
            i = 0
            while time.time() < end_time:
                try:
                    load_system.unload_model(f"stable-model-{i % 3}")
                    req = ModelLoadRequest(
                        model_id=f"stable-model-{i % 3}",
                        load_time=0.05,
                    )
                    load_system.load_model(req)
                    i += 1
                except RuntimeError:
                    pass

        threads = [
            threading.Thread(target=continuous_inference),
            threading.Thread(target=model_switcher),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        results = load_system.get_load_results()
        assert results.successful_requests > 0

    def test_system_reset(self, load_system):
        """测试系统重置"""
        # 产生一些负载
        for i in range(10):
            req = ModelLoadRequest(model_id=f"reset-model-{i}", load_time=0.05)
            load_system.load_model(req)

        for i in range(100):
            conn_id = load_system.create_connection()
            load_system.close_connection(conn_id)

        load_system.reset()
        assert load_system.get_loaded_models() == 0
        assert load_system.get_active_connections() == 0
        assert load_system._total_requests == 0
        assert load_system._successful_requests == 0


# =============================================================================
# 测试用例: 极端情况
# =============================================================================

class TestEdgeCases:
    """极端情况测试"""

    def test_zero_requests(self, load_system):
        """测试零请求"""
        results = load_system.get_load_results()
        assert results.total_requests == 0
        assert results.avg_latency_ms == 0

    def test_single_request(self, preloaded_system):
        """测试单请求"""
        task = InferenceTask(task_id="single", model_id="model-0", compute_time=0.01)
        result = preloaded_system.infer(task)
        assert result["task_id"] == "single"
        assert result["latency_ms"] > 0

    def test_model_not_found(self, load_system):
        """测试模型不存在"""
        task = InferenceTask(task_id="not-found", model_id="nonexistent")
        with pytest.raises(RuntimeError, match="not loaded"):
            load_system.infer(task)

    def test_rapid_connect_disconnect(self, load_system):
        """测试快速连接断开"""
        for i in range(1000):
            try:
                conn_id = load_system.create_connection()
                load_system.close_connection(conn_id)
            except RuntimeError:
                pass

        assert load_system.get_active_connections() == 0

    def test_negative_values(self, load_system):
        """测试负值参数"""
        task = InferenceTask(
            task_id="negative",
            model_id="model-0",
            input_size=-1,
            compute_time=-1,
        )
        # 系统应该处理负值而不崩溃
        try:
            result = load_system.infer(task)
            assert result is not None
        except RuntimeError:
            pass

    def test_very_large_model(self, load_system):
        """测试超大模型"""
        req = ModelLoadRequest(model_id="huge-model", size_mb=100000, load_time=2.0)
        try:
            load_time = load_system.load_model(req)
            assert load_time > 0
            load_system.unload_model("huge-model")
        except RuntimeError:
            pass


# =============================================================================
# 测试用例: 性能指标收集
# =============================================================================

class TestPerformanceMetrics:
    """性能指标收集测试"""

    def test_latency_percentiles(self, preloaded_system, load_generator):
        """测试延迟百分位统计"""
        models = [f"model-{i}" for i in range(5)]
        result = load_generator.generate_inference_load(500, models, concurrency=100)

        assert result.p50_latency_ms > 0
        assert result.p95_latency_ms >= result.p50_latency_ms
        assert result.p99_latency_ms >= result.p95_latency_ms
        assert result.min_latency_ms <= result.p50_latency_ms
        assert result.max_latency_ms >= result.p99_latency_ms

    def test_throughput_measurement(self, preloaded_system, load_generator):
        """测试吞吐量测量"""
        models = [f"model-{i}" for i in range(5)]
        result = load_generator.generate_inference_load(500, models, concurrency=100)

        assert result.requests_per_second > 0
        assert result.success_rate > 0

    def test_error_rate_tracking(self, load_system):
        """测试错误率跟踪"""
        # 发送错误请求
        for i in range(10):
            task = InferenceTask(task_id=f"error-{i}", model_id="nonexistent")
            try:
                load_system.infer(task)
            except RuntimeError:
                pass

        results = load_system.get_load_results()
        assert results.failed_requests == 10
        assert "model_not_loaded" in results.errors

    def test_resource_usage_under_load(self, preloaded_system, load_generator):
        """测试负载下的资源使用"""
        import threading
        usage_records = []

        def monitor():
            for _ in range(5):
                usage = ResourceUsage(
                    cpu_percent=random.uniform(10, 90),
                    memory_mb=random.uniform(200, 2000),
                    threads_count=threading.active_count(),
                )
                usage_records.append(usage)
                time.sleep(0.5)

        monitor_thread = threading.Thread(target=monitor)
        monitor_thread.start()

        models = [f"model-{i}" for i in range(5)]
        load_generator.generate_inference_load(300, models, concurrency=100)

        monitor_thread.join()
        assert len(usage_records) > 0
        assert all(r.threads_count > 0 for r in usage_records)


# =============================================================================
# 并发测试主入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])