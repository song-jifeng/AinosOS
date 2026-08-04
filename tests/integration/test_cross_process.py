"""
跨进程通信集成测试

测试多进程环境下的 IPC 通信、并发推理、资源共享和子进程管理。
"""

import os
import sys
import time
import signal
import queue
import random
import pickle
import struct
import pytest
import multiprocessing
import threading
from multiprocessing import Process, Queue, Pipe, Lock, Value, Array, Manager
from multiprocessing.queues import Queue as MpQueue
from typing import List, Dict, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from contextlib import contextmanager
from unittest.mock import MagicMock, patch, Mock


# =============================================================================
# 测试辅助定义
# =============================================================================

class MessageType(Enum):
    """IPC 消息类型"""
    INFERENCE_REQUEST = auto()
    INFERENCE_RESPONSE = auto()
    MODEL_LOAD = auto()
    MODEL_UNLOAD = auto()
    HEARTBEAT = auto()
    SHUTDOWN = auto()
    ERROR = auto()
    RESOURCE_STATUS = auto()


@dataclass
class InferenceRequest:
    """推理请求"""
    model_id: str
    input_data: Any
    parameters: Dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    timeout: float = 30.0


@dataclass
class InferenceResponse:
    """推理响应"""
    request_id: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    memory_usage: int = 0


@dataclass
class ResourceStats:
    """资源统计"""
    pid: int
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    threads_count: int = 0
    open_fds: int = 0
    uptime_seconds: float = 0.0


# =============================================================================
# Mock 模型运行时
# =============================================================================

class MockModelRuntime:
    """模拟模型运行时环境"""

    def __init__(self, model_id: str, load_time: float = 0.1):
        self.model_id = model_id
        self.load_time = load_time
        self.is_loaded = False
        self._loaded_at: Optional[float] = None
        self._inference_count = 0
        self._total_inference_time = 0.0

    def load(self) -> bool:
        """模拟加载模型"""
        time.sleep(self.load_time)
        self.is_loaded = True
        self._loaded_at = time.time()
        return True

    def unload(self) -> bool:
        """模拟卸载模型"""
        self.is_loaded = False
        self._loaded_at = None
        return True

    def infer(self, input_data: Any, parameters: Dict[str, Any] = None) -> Any:
        """模拟推理"""
        if not self.is_loaded:
            raise RuntimeError(f"Model {self.model_id} is not loaded")

        self._inference_count += 1
        compute_time = random.uniform(0.01, 0.05)
        time.sleep(compute_time)
        self._total_inference_time += compute_time

        # 模拟不同的推理输出
        if isinstance(input_data, str):
            return f"Processed: {input_data}"
        elif isinstance(input_data, dict):
            return {k: f"processed_{v}" for k, v in input_data.items()}
        elif isinstance(input_data, list):
            return [f"item_{i}_processed" for i in range(len(input_data))]
        elif isinstance(input_data, bytes):
            return b"processed_" + input_data
        return {"result": "ok", "input_type": type(input_data).__name__}

    def get_stats(self) -> Dict[str, Any]:
        """获取运行时统计"""
        return {
            "model_id": self.model_id,
            "is_loaded": self.is_loaded,
            "inference_count": self._inference_count,
            "total_inference_time": self._total_inference_time,
            "avg_inference_time": (
                self._total_inference_time / self._inference_count
                if self._inference_count > 0 else 0
            ),
        }


class MockDaemon:
    """Mock daemon 进程，管理子进程和资源"""

    def __init__(self):
        self._runtimes: Dict[str, MockModelRuntime] = {}
        self._children: List[Dict[str, Any]] = []
        self._lock = Lock()
        self._running = False

    def start(self):
        self._running = True

    def stop(self):
        self._running = False
        for child in self._children:
            if child["process"].is_alive():
                child["process"].terminate()
        self._children.clear()
        self._runtimes.clear()

    def spawn_worker(self, worker_id: str, task: Callable, args: tuple = ()) -> Process:
        """生成工作子进程"""
        p = Process(target=task, args=args, name=f"worker-{worker_id}")
        p.daemon = True
        p.start()
        self._children.append({
            "id": worker_id,
            "process": p,
            "created_at": time.time(),
        })
        return p

    def load_model(self, model_id: str, load_time: float = 0.1) -> bool:
        """加载模型到共享运行时"""
        with self._lock:
            if model_id in self._runtimes:
                return True
            runtime = MockModelRuntime(model_id, load_time)
            runtime.load()
            self._runtimes[model_id] = runtime
            return True

    def unload_model(self, model_id: str) -> bool:
        """卸载模型"""
        with self._lock:
            if model_id not in self._runtimes:
                return False
            self._runtimes[model_id].unload()
            del self._runtimes[model_id]
            return True

    def get_runtime(self, model_id: str) -> Optional[MockModelRuntime]:
        """获取模型运行时"""
        with self._lock:
            return self._runtimes.get(model_id)

    def get_active_models(self) -> List[str]:
        with self._lock:
            return list(self._runtimes.keys())

    def get_child_count(self) -> int:
        return len(self._children)

    def broadcast(self, message: Any, timeout: float = 5.0) -> List[Any]:
        """向所有子进程广播消息"""
        results = []
        for child in self._children:
            if child["process"].is_alive():
                try:
                    results.append(message)
                except Exception:
                    results.append(None)
        return results


# =============================================================================
# 测试辅助函数
# =============================================================================

def worker_process_infer(worker_id: str, model_id: str, input_queue: Queue,
                         output_queue: Queue, num_tasks: int = 10):
    """工作进程：从队列取任务并推理"""
    try:
        for i in range(num_tasks):
            try:
                data = input_queue.get(timeout=5.0)
                # 模拟推理
                time.sleep(random.uniform(0.01, 0.03))
                result = f"worker-{worker_id}-result-{i}"
                output_queue.put({
                    "worker_id": worker_id,
                    "task_id": i,
                    "input": data,
                    "output": result,
                    "success": True,
                })
            except queue.Empty:
                break
            except Exception as e:
                output_queue.put({
                    "worker_id": worker_id,
                    "task_id": i,
                    "error": str(e),
                    "success": False,
                })
    except KeyboardInterrupt:
        pass


def worker_process_resource_monitor(stats_queue: Queue, interval: float = 0.1,
                                    duration: float = 2.0):
    """工作进程：监控资源使用"""
    start = time.time()
    while time.time() - start < duration:
        stats = ResourceStats(
            pid=os.getpid(),
            cpu_percent=random.uniform(10, 80),
            memory_mb=random.uniform(100, 500),
            threads_count=random.randint(4, 16),
            open_fds=random.randint(10, 100),
            uptime_seconds=time.time() - start,
        )
        try:
            stats_queue.put(stats, timeout=1.0)
        except queue.Full:
            pass
        time.sleep(interval)


def worker_process_signal_handler(signal_queue: Queue, duration: float = 5.0):
    """工作进程：测试信号处理"""
    def sigterm_handler(signum, frame):
        signal_queue.put({"signal": signum, "received": True, "pid": os.getpid()})
        sys.exit(0)

    signal.signal(signal.SIGTERM, sigterm_handler)
    signal.signal(signal.SIGINT, sigterm_handler)

    try:
        time.sleep(duration)
    except KeyboardInterrupt:
        pass
    finally:
        signal_queue.put({"status": "exited", "pid": os.getpid()})


def worker_process_shared_resource(shared_list: list, lock: Lock,
                                   iterations: int = 100):
    """工作进程：操作共享资源"""
    for i in range(iterations):
        with lock:
            shared_list.append(f"item-{os.getpid()}-{i}")
            time.sleep(random.uniform(0.001, 0.005))


def worker_process_crash(should_crash: bool = True):
    """工作进程：模拟崩溃"""
    if should_crash:
        time.sleep(random.uniform(0.1, 0.3))
        raise RuntimeError("Simulated crash")
    time.sleep(1.0)


class CrossProcessFixture:
    """跨进程测试夹具，管理进程生命周期"""

    def __init__(self):
        self.processes: List[Process] = []
        self.queues: Dict[str, Queue] = {}
        self.daemon = MockDaemon()
        self.manager = Manager()

    def create_queue(self, name: str) -> Queue:
        q = Queue()
        self.queues[name] = q
        return q

    def start_process(self, target: Callable, args: tuple = (),
                      name: Optional[str] = None) -> Process:
        p = Process(target=target, args=args, name=name)
        p.daemon = True
        p.start()
        self.processes.append(p)
        return p

    def cleanup(self):
        for p in self.processes:
            if p.is_alive():
                p.terminate()
                p.join(timeout=2.0)
        self.processes.clear()
        self.queues.clear()
        self.daemon.stop()
        self.manager.shutdown()

    def wait_all(self, timeout: float = 10.0):
        alive = []
        for p in self.processes:
            p.join(timeout=timeout)
            if p.is_alive():
                alive.append(p)
        return alive


@pytest.fixture
def cross_process_fixture():
    fixture = CrossProcessFixture()
    fixture.daemon.start()
    yield fixture
    fixture.cleanup()


# =============================================================================
# 测试用例：多进程并发推理
# =============================================================================

class TestMultiProcessConcurrentInference:
    """多进程并发推理测试"""

    def test_single_worker_inference(self, cross_process_fixture):
        """测试单个工作进程执行推理"""
        input_q = cross_process_fixture.create_queue("input")
        output_q = cross_process_fixture.create_queue("output")

        p = cross_process_fixture.start_process(
            worker_process_infer,
            args=("worker-1", "model-a", input_q, output_q, 5),
            name="single-worker",
        )

        for i in range(5):
            input_q.put(f"task-{i}")

        p.join(timeout=10.0)
        assert not p.is_alive()

        results = []
        while not output_q.empty():
            results.append(output_q.get_nowait())

        assert len(results) == 5
        for r in results:
            assert r["success"] is True
            assert r["worker_id"] == "worker-1"
            assert "output" in r

    def test_multiple_workers_concurrent(self, cross_process_fixture):
        """测试多个工作进程并发推理"""
        num_workers = 4
        tasks_per_worker = 10
        input_q = cross_process_fixture.create_queue("input")
        output_q = cross_process_fixture.create_queue("output")

        processes = []
        for i in range(num_workers):
            p = cross_process_fixture.start_process(
                worker_process_infer,
                args=(f"worker-{i}", "model-b", input_q, output_q, tasks_per_worker),
                name=f"worker-{i}",
            )
            processes.append(p)

        total_tasks = num_workers * tasks_per_worker
        for i in range(total_tasks):
            input_q.put(f"task-{i}")

        for p in processes:
            p.join(timeout=15.0)

        results = []
        while not output_q.empty():
            try:
                results.append(output_q.get_nowait())
            except queue.Empty:
                break

        assert len(results) == total_tasks
        worker_ids = set(r["worker_id"] for r in results)
        assert len(worker_ids) == num_workers

    def test_worker_load_balancing(self, cross_process_fixture):
        """测试任务在多个工作进程间负载均衡"""
        num_workers = 3
        tasks_per_worker = 20
        output_q = cross_process_fixture.create_queue("output")

        # 每个工作进程有自己的输入队列
        input_queues = []
        for i in range(num_workers):
            q = cross_process_fixture.create_queue(f"input-{i}")
            input_queues.append(q)
            cross_process_fixture.start_process(
                worker_process_infer,
                args=(f"worker-{i}", "model-c", q, output_q, tasks_per_worker),
                name=f"balancer-{i}",
            )

        # 按 round-robin 分配任务
        for i in range(num_workers * tasks_per_worker):
            input_queues[i % num_workers].put(f"task-{i}")

        alive = cross_process_fixture.wait_all(timeout=20.0)
        assert len(alive) == 0

        results = []
        while not output_q.empty():
            try:
                results.append(output_q.get_nowait())
            except queue.Empty:
                break

        assert len(results) == num_workers * tasks_per_worker
        counts = {}
        for r in results:
            counts[r["worker_id"]] = counts.get(r["worker_id"], 0) + 1
        # 每个 worker 处理的任务数应该相近
        task_counts = list(counts.values())
        assert max(task_counts) - min(task_counts) <= 2

    def test_worker_crash_recovery(self, cross_process_fixture):
        """测试工作进程崩溃后的恢复"""
        output_q = cross_process_fixture.create_queue("output")

        # 启动一个会崩溃的 worker
        p = cross_process_fixture.start_process(
            worker_process_crash,
            args=(True,),
            name="crash-worker",
        )
        p.join(timeout=5.0)
        assert not p.is_alive()
        assert p.exitcode != 0

        # 启动一个新的正常 worker
        input_q = cross_process_fixture.create_queue("input-recovery")
        p2 = cross_process_fixture.start_process(
            worker_process_infer,
            args=("worker-recovery", "model-d", input_q, output_q, 3),
            name="recovery-worker",
        )
        for i in range(3):
            input_q.put(f"recovery-task-{i}")

        p2.join(timeout=10.0)
        assert not p2.is_alive()
        assert p2.exitcode == 0

    def test_worker_pool_throughput(self, cross_process_fixture):
        """测试工作进程池吞吐量"""
        import time
        num_workers = 6
        tasks_per_worker = 50
        total_tasks = num_workers * tasks_per_worker

        input_q = cross_process_fixture.create_queue("throughput-input")
        output_q = cross_process_fixture.create_queue("throughput-output")

        for i in range(num_workers):
            cross_process_fixture.start_process(
                worker_process_infer,
                args=(f"worker-{i}", "model-e", input_q, output_q, tasks_per_worker),
                name=f"throughput-{i}",
            )

        for i in range(total_tasks):
            input_q.put(f"task-{i}")

        start = time.time()
        cross_process_fixture.wait_all(timeout=30.0)
        elapsed = time.time() - start

        throughput = total_tasks / elapsed
        assert throughput > 10, f"Throughput too low: {throughput:.2f} tasks/sec"
        assert elapsed < 30.0, f"Timeout: {elapsed:.2f}s"


# =============================================================================
# 测试用例：进程间资源共享
# =============================================================================

class TestInterProcessResourceSharing:
    """进程间资源共享测试"""

    def test_shared_memory_via_manager(self, cross_process_fixture):
        """测试通过 Manager 共享内存"""
        manager = cross_process_fixture.manager
        shared_dict = manager.dict()
        shared_list = manager.list()
        lock = manager.Lock()

        num_workers = 3
        iterations = 50

        processes = []
        for i in range(num_workers):
            p = cross_process_fixture.start_process(
                worker_process_shared_resource,
                args=(shared_list, lock, iterations),
                name=f"shared-{i}",
            )
            processes.append(p)

        for p in processes:
            p.join(timeout=15.0)

        # 验证共享资源
        assert len(shared_list) == num_workers * iterations
        # 所有元素应该都有正确的前缀
        for item in shared_list:
            assert item.startswith("item-")

    def test_shared_value_and_array(self, cross_process_fixture):
        """测试共享数值和数组"""
        shared_counter = Value('i', 0)
        shared_flag = Value('b', True)
        shared_array = Array('d', [0.0] * 100)
        lock = Lock()

        def increment_counter(counter, arr, lock, idx, count=100):
            for _ in range(count):
                with lock:
                    counter.value += 1
                    arr[idx] = counter.value
                time.sleep(random.uniform(0.001, 0.005))

        processes = []
        for i in range(5):
            p = cross_process_fixture.start_process(
                increment_counter,
                args=(shared_counter, shared_array, lock, i, 50),
                name=f"counter-{i}",
            )
            processes.append(p)

        for p in processes:
            p.join(timeout=10.0)

        assert shared_counter.value == 250  # 5 * 50
        assert shared_flag.value is True

    def test_pipe_communication(self, cross_process_fixture):
        """测试 Pipe 双向通信"""

        def pipe_server(conn, num_messages: int):
            received = []
            for _ in range(num_messages):
                if conn.poll(2.0):
                    msg = conn.recv()
                    received.append(msg)
                    conn.send({"echo": msg, "pid": os.getpid()})
            conn.close()
            return received

        parent_conn, child_conn = Pipe()
        num_messages = 20

        p = cross_process_fixture.start_process(
            pipe_server,
            args=(child_conn, num_messages),
            name="pipe-server",
        )

        for i in range(num_messages):
            parent_conn.send({"seq": i, "data": f"message-{i}"})
            if parent_conn.poll(2.0):
                response = parent_conn.recv()
                assert "echo" in response
                assert response["echo"]["seq"] == i

        p.join(timeout=5.0)
        parent_conn.close()

    def test_resource_cleanup_on_exit(self, cross_process_fixture):
        """测试进程退出时资源清理"""
        manager = cross_process_fixture.manager
        shared_set = manager.list()
        lock = manager.Lock()

        def worker_with_cleanup(shared, lock, wid):
            try:
                with lock:
                    shared.append(f"start-{wid}")
                # 模拟工作
                time.sleep(random.uniform(0.2, 0.5))
                with lock:
                    shared.append(f"end-{wid}")
            finally:
                with lock:
                    shared.append(f"cleanup-{wid}")

        processes = []
        for i in range(4):
            p = cross_process_fixture.start_process(
                worker_with_cleanup,
                args=(shared_set, lock, i),
                name=f"cleanup-{i}",
            )
            processes.append(p)

        for p in processes:
            p.join(timeout=5.0)

        # 验证所有进程都执行了清理
        cleanup_count = sum(1 for item in shared_set if item.startswith("cleanup-"))
        assert cleanup_count == 4


# =============================================================================
# 测试用例：子进程管理
# =============================================================================

class TestChildProcessManagement:
    """子进程管理测试"""

    def test_process_spawn_and_join(self, cross_process_fixture):
        """测试进程的创建和等待"""
        p = cross_process_fixture.start_process(
            worker_process_infer,
            args=("test", "model", Queue(), Queue(), 3),
            name="spawn-test",
        )
        assert p.is_alive()
        assert p.pid > 0
        assert p.name == "spawn-test"

        p.join(timeout=5.0)
        assert not p.is_alive()
        assert p.exitcode == 0

    def test_multiple_process_spawn(self, cross_process_fixture):
        """测试批量创建多个进程"""
        num_processes = 10
        processes = []

        for i in range(num_processes):
            p = cross_process_fixture.start_process(
                time.sleep,
                args=(0.5,),
                name=f"batch-{i}",
            )
            processes.append(p)

        assert len(cross_process_fixture.processes) == num_processes
        for p in processes:
            assert p.is_alive()
            assert p.pid > 0
            assert p.name.startswith("batch-")

        cross_process_fixture.wait_all(timeout=5.0)
        for p in processes:
            assert not p.is_alive()

    def test_process_termination(self, cross_process_fixture):
        """测试进程终止"""
        p = cross_process_fixture.start_process(
            time.sleep,
            args=(10,),
            name="terminate-test",
        )
        assert p.is_alive()

        p.terminate()
        p.join(timeout=3.0)
        assert not p.is_alive()
        assert p.exitcode != 0

    def test_daemon_process_cleanup(self, cross_process_fixture):
        """测试 daemon 进程的自动清理"""
        p = cross_process_fixture.start_process(
            time.sleep,
            args=(100,),
            name="daemon-test",
        )
        p.daemon = True
        assert p.is_alive()

        # 清理应该会终止 daemon 进程
        cross_process_fixture.cleanup()
        assert not p.is_alive()

    def test_process_exit_code(self, cross_process_fixture):
        """测试进程退出码"""

        def exit_with_code(code: int):
            sys.exit(code)

        p = cross_process_fixture.start_process(exit_with_code, args=(0,))
        p.join(timeout=5.0)
        assert p.exitcode == 0

        p = cross_process_fixture.start_process(exit_with_code, args=(42,))
        p.join(timeout=5.0)
        assert p.exitcode == 42

    def test_process_priority(self, cross_process_fixture):
        """测试进程优先级设置"""
        # 在 Windows 上测试优先级
        import subprocess
        try:
            p = cross_process_fixture.start_process(
                time.sleep,
                args=(0.5,),
                name="priority-test",
            )
            if hasattr(p, "nice"):
                original_nice = p.nice
                p.nice = 10
                assert p.nice == 10
            p.join(timeout=2.0)
        except (AttributeError, NotImplementedError):
            pass  # 某些平台不支持

    def test_process_tree_management(self, cross_process_fixture):
        """测试进程树管理"""

        def parent_worker(level: int, max_depth: int, results: list, lock):
            with lock:
                results.append(f"level-{level}-pid-{os.getpid()}")
            if level < max_depth:
                child = Process(target=parent_worker,
                                args=(level + 1, max_depth, results, lock))
                child.start()
                child.join()

        manager = cross_process_fixture.manager
        results = manager.list()
        lock = manager.Lock()

        p = cross_process_fixture.start_process(
            parent_worker,
            args=(0, 3, results, lock),
            name="process-tree",
        )
        p.join(timeout=10.0)

        assert len(results) == 4
        for i, r in enumerate(results):
            assert f"level-{i}" in r


# =============================================================================
# 测试用例：信号处理
# =============================================================================

class TestSignalHandling:
    """信号处理测试"""

    def test_sigterm_handling(self, cross_process_fixture):
        """测试 SIGTERM 信号处理"""
        signal_queue = cross_process_fixture.create_queue("signals")

        p = cross_process_fixture.start_process(
            worker_process_signal_handler,
            args=(signal_queue, 5.0),
            name="signal-test",
        )

        time.sleep(0.3)  # 等待子进程启动
        os.kill(p.pid, signal.SIGTERM)
        p.join(timeout=3.0)

        assert not p.is_alive()
        # 在 Windows 下 SIGTERM 可能不同
        if sys.platform != "win32":
            result = signal_queue.get(timeout=1.0)
            assert result["received"] is True
            assert result["pid"] == p.pid

    def test_signal_ignore(self, cross_process_fixture):
        """测试忽略信号"""

        def worker_ignore_signal():
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(2)
            signal_queue.put("still-alive")

        signal_queue = cross_process_fixture.create_queue("sig-ignore")
        p = cross_process_fixture.start_process(worker_ignore_signal)
        time.sleep(0.3)
        os.kill(p.pid, signal.SIGTERM)
        time.sleep(0.5)
        assert p.is_alive()
        p.terminate()
        p.join(timeout=2.0)

    def test_signal_propagation_to_children(self, cross_process_fixture):
        """测试信号向子进程传播"""

        def parent_with_children():
            children = []
            for i in range(3):
                child = Process(target=time.sleep, args=(10,), name=f"child-{i}")
                child.daemon = True
                child.start()
                children.append(child)

            def handler(signum, frame):
                for c in children:
                    if c.is_alive():
                        c.terminate()
                sys.exit(0)

            signal.signal(signal.SIGTERM, handler)
            signal.pause()

        p = cross_process_fixture.start_process(parent_with_children)
        time.sleep(0.5)
        os.kill(p.pid, signal.SIGTERM)
        p.join(timeout=5.0)
        assert not p.is_alive()

    def test_signal_queue_not_blocking(self, cross_process_fixture):
        """测试信号处理不阻塞主进程"""

        def worker_no_block():
            def handler(signum, frame):
                handled_at = time.time()
                signal_queue.put(handled_at)

            signal_queue = multiprocessing.Queue()
            signal.signal(signal.SIGTERM, handler)
            time.sleep(1)

        q = cross_process_fixture.create_queue("no-block")
        p = cross_process_fixture.start_process(worker_no_block)
        time.sleep(0.2)
        os.kill(p.pid, signal.SIGTERM)
        p.join(timeout=3.0)
        assert not p.is_alive()


# =============================================================================
# 测试用例：IPC 通信协议
# =============================================================================

class TestIPCProtocol:
    """IPC 通信协议测试"""

    def test_message_serialization(self):
        """测试消息序列化/反序列化"""
        original = {
            "type": "inference_request",
            "model_id": "test-model",
            "input": "hello world",
            "parameters": {"temperature": 0.7, "max_tokens": 100},
            "request_id": "req-001",
            "timestamp": time.time(),
        }

        serialized = pickle.dumps(original)
        deserialized = pickle.loads(serialized)

        assert deserialized == original
        assert len(serialized) < 1024  # 合理的消息大小

    def test_message_format_validation(self):
        """测试消息格式验证"""
        valid_messages = [
            {"type": "request", "id": "1", "data": "test"},
            {"type": "response", "id": "2", "data": {"result": "ok"}},
            {"type": "error", "id": "3", "error": "timeout"},
            {"type": "heartbeat", "id": "4", "timestamp": time.time()},
        ]

        invalid_messages = [
            None,
            "not a dict",
            12345,
            {"type": "unknown"},
            {},
            {"type": "request"},  # 缺少 id
        ]

        for msg in valid_messages:
            assert isinstance(msg, dict)
            assert "type" in msg
            assert "id" in msg

        for msg in invalid_messages:
            if isinstance(msg, dict):
                assert "type" not in msg or "id" not in msg

    def test_message_ordering(self, cross_process_fixture):
        """测试消息顺序保证"""

        def ordered_sender(q: Queue, num_messages: int):
            for i in range(num_messages):
                q.put({"seq": i, "value": f"msg-{i}"})
                time.sleep(random.uniform(0.001, 0.01))

        q = cross_process_fixture.create_queue("ordering")
        p = cross_process_fixture.start_process(
            ordered_sender, args=(q, 100), name="ordered-sender"
        )
        p.join(timeout=10.0)

        received = []
        while not q.empty():
            try:
                received.append(q.get_nowait())
            except queue.Empty:
                break

        assert len(received) == 100
        for i, msg in enumerate(received):
            assert msg["seq"] == i

    def test_large_message_transfer(self, cross_process_fixture):
        """测试大消息传输"""

        def large_message_sender(q: Queue, size: int):
            large_data = {
                "data": "x" * size,
                "metadata": {"size": size, "timestamp": time.time()},
            }
            q.put(large_data)

        q = cross_process_fixture.create_queue("large-msg")
        p = cross_process_fixture.start_process(
            large_message_sender, args=(q, 10 * 1024 * 1024),  # 10MB
            name="large-sender",
        )
        p.join(timeout=10.0)

        msg = q.get(timeout=5.0)
        assert len(msg["data"]) == 10 * 1024 * 1024


# =============================================================================
# 测试用例：daemon 进程管理
# =============================================================================

class TestDaemonProcessManagement:
    """Daemon 进程管理测试"""

    def test_daemon_start_stop(self, cross_process_fixture):
        """测试 daemon 启动和停止"""
        daemon = cross_process_fixture.daemon
        assert daemon._running is True

        daemon.stop()
        assert daemon._running is False
        assert len(daemon._children) == 0

    def test_daemon_model_lifecycle(self, cross_process_fixture):
        """测试 daemon 的模型生命周期管理"""
        daemon = cross_process_fixture.daemon

        assert daemon.load_model("model-1", load_time=0.05) is True
        assert "model-1" in daemon.get_active_models()

        runtime = daemon.get_runtime("model-1")
        assert runtime is not None
        assert runtime.is_loaded is True

        assert daemon.unload_model("model-1") is True
        assert "model-1" not in daemon.get_active_models()

    def test_daemon_spawn_workers(self, cross_process_fixture):
        """测试 daemon 创建工作进程"""
        daemon = cross_process_fixture.daemon

        def dummy_worker():
            time.sleep(1)

        p = daemon.spawn_worker("test-worker", dummy_worker)
        assert p.is_alive()
        assert daemon.get_child_count() == 1

        p.join(timeout=3.0)
        assert not p.is_alive()

    def test_daemon_resource_isolation(self, cross_process_fixture):
        """测试 daemon 资源隔离"""
        daemon = cross_process_fixture.daemon

        daemon.load_model("model-a")
        daemon.load_model("model-b")

        runtime_a = daemon.get_runtime("model-a")
        runtime_b = daemon.get_runtime("model-b")

        assert runtime_a is not runtime_b
        assert runtime_a.model_id == "model-a"
        assert runtime_b.model_id == "model-b"

        result_a = runtime_a.infer("test")
        result_b = runtime_b.infer("test")
        assert result_a == result_b  # 相同输入应该产生相同输出


# =============================================================================
# 测试用例：并发控制
# =============================================================================

class TestConcurrencyControl:
    """并发控制测试"""

    def test_lock_contention(self, cross_process_fixture):
        """测试锁竞争"""
        counter = Value('i', 0)
        lock = Lock()

        def contended_worker(counter, lock, iterations=200):
            for _ in range(iterations):
                with lock:
                    current = counter.value
                    time.sleep(random.uniform(0.0001, 0.001))
                    counter.value = current + 1

        processes = []
        for i in range(5):
            p = cross_process_fixture.start_process(
                contended_worker, args=(counter, lock, 100),
                name=f"contention-{i}",
            )
            processes.append(p)

        for p in processes:
            p.join(timeout=15.0)

        assert counter.value == 500  # 5 * 100

    def test_rlock_reentrancy(self, cross_process_fixture):
        """测试可重入锁"""

        def reentrant_worker(results: list, lock: Lock):
            with lock:
                results.append("first")
                with lock:  # 重入
                    results.append("second")
            results.append("after")

        manager = cross_process_fixture.manager
        results = manager.list()
        lock = manager.RLock()

        p = cross_process_fixture.start_process(
            reentrant_worker, args=(results, lock),
            name="reentrant",
        )
        p.join(timeout=5.0)

        assert len(results) == 3
        assert results[0] == "first"
        assert results[1] == "second"
        assert results[2] == "after"

    def test_semaphore_limited_access(self, cross_process_fixture):
        """测试信号量限制访问"""
        semaphore = multiprocessing.Semaphore(2)
        active_count = Value('i', 0)
        max_active = Value('i', 0)
        lock = Lock()

        def sem_worker(sem, active, max_active, lock):
            with sem:
                with lock:
                    active.value += 1
                    if active.value > max_active.value:
                        max_active.value = active.value
                time.sleep(random.uniform(0.1, 0.3))
                with lock:
                    active.value -= 1

        processes = []
        for i in range(10):
            p = cross_process_fixture.start_process(
                sem_worker, args=(semaphore, active_count, max_active, lock),
                name=f"sem-{i}",
            )
            processes.append(p)

        for p in processes:
            p.join(timeout=10.0)

        # 最大并发数不应该超过 2
        assert max_active.value <= 2

    def test_event_synchronization(self, cross_process_fixture):
        """测试事件同步"""
        event = multiprocessing.Event()
        results = cross_process_fixture.manager.list()

        def waiter(event, results, wid):
            results.append(f"waiting-{wid}")
            event.wait(timeout=5.0)
            results.append(f"proceeding-{wid}")

        def setter(event, delay=0.5):
            time.sleep(delay)
            event.set()

        for i in range(3):
            cross_process_fixture.start_process(
                waiter, args=(event, results, i),
                name=f"waiter-{i}",
            )

        cross_process_fixture.start_process(
            setter, args=(event, 0.3),
            name="setter",
        )

        cross_process_fixture.wait_all(timeout=5.0)

        assert any("waiting" in r for r in results)
        assert any("proceeding" in r for r in results)

    def test_barrier_synchronization(self, cross_process_fixture):
        """测试屏障同步"""
        barrier = multiprocessing.Barrier(3, timeout=5)
        results = cross_process_fixture.manager.list()

        def barrier_worker(barrier, results, wid):
            import time
            time.sleep(random.uniform(0.1, 0.5))
            results.append(f"reached-{wid}")
            barrier.wait()
            results.append(f"passed-{wid}")

        for i in range(3):
            cross_process_fixture.start_process(
                barrier_worker, args=(barrier, results, i),
                name=f"barrier-{i}",
            )

        cross_process_fixture.wait_all(timeout=10.0)

        # 所有进程都应该在屏障前等待
        reached = [r for r in results if r.startswith("reached-")]
        passed = [r for r in results if r.startswith("passed-")]
        assert len(reached) == 3
        assert len(passed) == 3


# =============================================================================
# 测试用例：超时和错误处理
# =============================================================================

class TestTimeoutAndErrorHandling:
    """超时和错误处理测试"""

    def test_worker_timeout(self, cross_process_fixture):
        """测试工作进程超时"""

        def slow_worker(q: Queue):
            time.sleep(10)  # 长时间运行
            q.put("done")

        q = cross_process_fixture.create_queue("timeout")
        p = cross_process_fixture.start_process(slow_worker, args=(q,))

        # 等待超时
        p.join(timeout=2.0)
        assert p.is_alive()  # 进程应该还在运行

        p.terminate()
        p.join(timeout=2.0)
        assert not p.is_alive()

    def test_queue_timeout(self, cross_process_fixture):
        """测试队列操作超时"""
        q = cross_process_fixture.create_queue("timeout-queue")

        start = time.time()
        try:
            q.get(timeout=0.5)
            pytest.fail("Should have raised queue.Empty")
        except queue.Empty:
            elapsed = time.time() - start
            assert 0.4 <= elapsed <= 1.0

    def test_error_propagation(self, cross_process_fixture):
        """测试错误传播"""

        def error_worker(q: Queue):
            try:
                raise ValueError("Worker error occurred")
            except ValueError as e:
                q.put({"error": str(e), "type": "ValueError"})

        q = cross_process_fixture.create_queue("errors")
        p = cross_process_fixture.start_process(error_worker, args=(q,))
        p.join(timeout=5.0)

        error_info = q.get(timeout=1.0)
        assert "error" in error_info
        assert "Worker error" in error_info["error"]

    def test_worker_exception_logging(self, cross_process_fixture):
        """测试工作进程异常日志记录"""

        def exception_worker():
            raise RuntimeError("Critical failure")

        p = cross_process_fixture.start_process(exception_worker)
        p.join(timeout=5.0)

        assert p.exitcode != 0

    def test_graceful_shutdown_on_error(self, cross_process_fixture):
        """测试错误时的优雅关闭"""

        def worker_with_cleanup(q: Queue):
            try:
                raise RuntimeError("Something went wrong")
            except RuntimeError:
                q.put("cleaning_up")
            finally:
                q.put("shutdown_complete")

        q = cross_process_fixture.create_queue("graceful")
        p = cross_process_fixture.start_process(worker_with_cleanup, args=(q,))
        p.join(timeout=5.0)

        msgs = []
        while not q.empty():
            try:
                msgs.append(q.get_nowait())
            except queue.Empty:
                break

        assert "cleaning_up" in msgs
        assert "shutdown_complete" in msgs


# =============================================================================
# 跨进程测试主入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])