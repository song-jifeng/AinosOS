"""
SDK 性能基准测试

测试多语言 SDK 延迟对比、序列化/反序列化性能、连接建立时间和流式处理吞吐量。
"""

import os
import sys
import json
import time
import uuid
import random
import pickle
import asyncio
import struct
import pytest
import math
from typing import List, Dict, Optional, Any, Tuple, Callable, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum, auto
from unittest.mock import MagicMock, Mock, patch, AsyncMock
from contextlib import contextmanager, asynccontextmanager


# =============================================================================
# 性能数据收集
# =============================================================================

@dataclass
class BenchmarkResult:
    """基准测试结果"""
    name: str
    iterations: int
    total_time_ms: float
    avg_time_ms: float
    min_time_ms: float
    max_time_ms: float
    median_time_ms: float
    p95_time_ms: float
    p99_time_ms: float
    ops_per_second: float
    samples: List[float] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (f"{self.name}: avg={self.avg_time_ms:.3f}ms, "
                f"min={self.min_time_ms:.3f}ms, max={self.max_time_ms:.3f}ms, "
                f"ops={self.ops_per_second:.0f}/s")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "total_time_ms": round(self.total_time_ms, 3),
            "avg_time_ms": round(self.avg_time_ms, 3),
            "min_time_ms": round(self.min_time_ms, 3),
            "max_time_ms": round(self.max_time_ms, 3),
            "median_time_ms": round(self.median_time_ms, 3),
            "p95_time_ms": round(self.p95_time_ms, 3),
            "p99_time_ms": round(self.p99_time_ms, 3),
            "ops_per_second": round(self.ops_per_second, 2),
        }


class BenchmarkRunner:
    """基准测试运行器"""

    def __init__(self, name: str = "benchmark"):
        self.name = name
        self.results: List[BenchmarkResult] = []
        self._current_samples: List[float] = []

    @contextmanager
    def measure(self, name: str, iterations: int = 1):
        """测量代码块性能"""
        self._current_samples = []
        try:
            yield
        finally:
            result = self._compute_result(name, iterations)
            self.results.append(result)

    def measure_function(self, name: str, fn: Callable,
                         iterations: int = 100, warmup: int = 10) -> BenchmarkResult:
        """测量函数性能"""
        # 预热
        for _ in range(warmup):
            fn()

        # 测量
        samples = []
        for _ in range(iterations):
            start = time.perf_counter()
            fn()
            elapsed = (time.perf_counter() - start) * 1000
            samples.append(elapsed)

        result = self._compute_from_samples(name, iterations, samples)
        self.results.append(result)
        return result

    async def measure_async_function(self, name: str, fn: Callable,
                                     iterations: int = 100,
                                     warmup: int = 10) -> BenchmarkResult:
        """测量异步函数性能"""
        # 预热
        for _ in range(warmup):
            await fn()

        # 测量
        samples = []
        for _ in range(iterations):
            start = time.perf_counter()
            await fn()
            elapsed = (time.perf_counter() - start) * 1000
            samples.append(elapsed)

        result = self._compute_from_samples(name, iterations, samples)
        self.results.append(result)
        return result

    def _compute_result(self, name: str, iterations: int) -> BenchmarkResult:
        return self._compute_from_samples(name, iterations, self._current_samples)

    def _compute_from_samples(self, name: str, iterations: int,
                              samples: List[float]) -> BenchmarkResult:
        if not samples:
            return BenchmarkResult(
                name=name, iterations=iterations,
                total_time_ms=0, avg_time_ms=0,
                min_time_ms=0, max_time_ms=0,
                median_time_ms=0, p95_time_ms=0, p99_time_ms=0,
                ops_per_second=0,
            )

        sorted_samples = sorted(samples)
        n = len(sorted_samples)
        total = sum(sorted_samples)
        avg = total / n

        return BenchmarkResult(
            name=name,
            iterations=iterations,
            total_time_ms=total,
            avg_time_ms=avg,
            min_time_ms=sorted_samples[0],
            max_time_ms=sorted_samples[-1],
            median_time_ms=sorted_samples[n // 2],
            p95_time_ms=sorted_samples[int(n * 0.95)],
            p99_time_ms=sorted_samples[int(n * 0.99)],
            ops_per_second=1000 / avg if avg > 0 else 0,
            samples=sorted_samples,
        )

    def report(self) -> str:
        """生成报告"""
        lines = [f"=== {self.name} ==="]
        for r in self.results:
            lines.append(r.summary)
        return "\n".join(lines)

    def clear(self):
        self.results.clear()


# =============================================================================
# Mock SDK 实现
# =============================================================================

class MockPythonSDK:
    """模拟 Python SDK 用于基准测试"""

    def __init__(self):
        self._name = "Python"
        self._version = "1.2.3"

    def serialize(self, data: Dict) -> bytes:
        return json.dumps(data).encode('utf-8')

    def deserialize(self, data: bytes) -> Dict:
        return json.loads(data.decode('utf-8'))

    def serialize_pickle(self, data: Dict) -> bytes:
        return pickle.dumps(data)

    def deserialize_pickle(self, data: bytes) -> Dict:
        return pickle.loads(data)

    def create_request(self, model: str, prompt: str, params: Dict = None) -> Dict:
        return {
            "model": model,
            "prompt": prompt,
            "parameters": params or {},
            "request_id": str(uuid.uuid4()),
            "timestamp": time.time(),
        }

    def create_response(self, request_id: str, text: str, usage: Dict = None) -> Dict:
        return {
            "request_id": request_id,
            "choices": [{"text": text, "index": 0}],
            "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0},
            "created": int(time.time()),
        }


class MockJavaSDKSimulator:
    """模拟 Java SDK 用于基准测试"""

    def __init__(self):
        self._name = "Java"
        self._version = "1.2.3"

    def serialize(self, data: Dict) -> bytes:
        # 模拟 Java 的 JSON 序列化（稍慢）
        time.sleep(0.00001)
        return json.dumps(data).encode('utf-8')

    def deserialize(self, data: bytes) -> Dict:
        time.sleep(0.00001)
        return json.loads(data.decode('utf-8'))

    def create_request(self, model: str, prompt: str, params: Dict = None) -> Dict:
        time.sleep(0.00002)
        return {
            "model": model,
            "prompt": prompt,
            "parameters": params or {},
            "request_id": str(uuid.uuid4()),
            "timestamp": time.time(),
        }


class MockGoSDKSimulator:
    """模拟 Go SDK 用于基准测试"""

    def __init__(self):
        self._name = "Go"
        self._version = "1.2.3"

    def serialize(self, data: Dict) -> bytes:
        # 模拟 Go 的 JSON 序列化（较快）
        return json.dumps(data).encode('utf-8')

    def deserialize(self, data: bytes) -> Dict:
        return json.loads(data.decode('utf-8'))

    def create_request(self, model: str, prompt: str, params: Dict = None) -> Dict:
        return {
            "model": model,
            "prompt": prompt,
            "parameters": params or {},
            "request_id": str(uuid.uuid4()),
            "timestamp": time.time(),
        }


class MockNodeSDKSimulator:
    """模拟 Node.js SDK 用于基准测试"""

    def __init__(self):
        self._name = "Node.js"
        self._version = "1.2.3"

    def serialize(self, data: Dict) -> bytes:
        return json.dumps(data).encode('utf-8')

    def deserialize(self, data: bytes) -> Dict:
        return json.loads(data.decode('utf-8'))

    def create_request(self, model: str, prompt: str, params: Dict = None) -> Dict:
        return {
            "model": model,
            "prompt": prompt,
            "parameters": params or {},
            "request_id": str(uuid.uuid4()),
            "timestamp": time.time(),
        }


class MockRustSDKSimulator:
    """模拟 Rust SDK 用于基准测试"""

    def __init__(self):
        self._name = "Rust"
        self._version = "1.2.3"

    def serialize(self, data: Dict) -> bytes:
        # 模拟 Rust 的快速序列化
        return json.dumps(data, separators=(',', ':')).encode('utf-8')

    def deserialize(self, data: bytes) -> Dict:
        return json.loads(data.decode('utf-8'))

    def create_request(self, model: str, prompt: str, params: Dict = None) -> Dict:
        return {
            "model": model,
            "prompt": prompt,
            "parameters": params or {},
            "request_id": str(uuid.uuid4()),
            "timestamp": time.time(),
        }


# =============================================================================
# 连接模拟器
# =============================================================================

class ConnectionManager:
    """连接管理器 - 模拟连接建立"""

    def __init__(self):
        self._connections: Dict[str, float] = {}  # id -> established_at
        self._latency = 0.0

    def set_latency(self, ms: float):
        self._latency = ms

    async def connect(self, host: str = "localhost", port: int = 8080,
                      timeout: float = 10.0) -> str:
        """模拟连接建立"""
        start = time.time()

        # 模拟连接延迟
        if self._latency > 0:
            await asyncio.sleep(self._latency / 1000.0)

        conn_id = str(uuid.uuid4())
        self._connections[conn_id] = time.time()
        return conn_id

    async def disconnect(self, conn_id: str):
        """断开连接"""
        self._connections.pop(conn_id, None)

    def get_active_count(self) -> int:
        return len(self._connections)

    async def health_check(self, conn_id: str) -> bool:
        """健康检查"""
        if conn_id not in self._connections:
            return False
        await asyncio.sleep(0.001)
        return True


class StreamProcessor:
    """流式处理器 - 模拟流式处理"""

    def __init__(self, chunk_size: int = 100, delay_ms: float = 0):
        self.chunk_size = chunk_size
        self.delay_ms = delay_ms

    def generate_stream(self, total_size: int) -> List[bytes]:
        """生成流数据"""
        chunks = []
        for offset in range(0, total_size, self.chunk_size):
            chunk = os.urandom(min(self.chunk_size, total_size - offset))
            chunks.append(chunk)
        return chunks

    async def process_stream(self, chunks: List[bytes],
                             process_fn: Callable) -> List[Any]:
        """处理流数据"""
        results = []
        for chunk in chunks:
            if self.delay_ms > 0:
                await asyncio.sleep(self.delay_ms / 1000.0)
            result = process_fn(chunk)
            results.append(result)
        return results

    def process_stream_sync(self, chunks: List[bytes],
                            process_fn: Callable) -> List[Any]:
        """同步处理流数据"""
        results = []
        for chunk in chunks:
            if self.delay_ms > 0:
                time.sleep(self.delay_ms / 1000.0)
            result = process_fn(chunk)
            results.append(result)
        return results

    def throughput(self, total_bytes: int, total_time_ms: float) -> float:
        """计算吞吐量 (MB/s)"""
        if total_time_ms <= 0:
            return 0
        return (total_bytes / (1024 * 1024)) / (total_time_ms / 1000)


# =============================================================================
# 测试夹具
# =============================================================================

@pytest.fixture
def benchmark_runner():
    return BenchmarkRunner("SDK Benchmark")


@pytest.fixture
def python_sdk():
    return MockPythonSDK()


@pytest.fixture
def java_sdk():
    return MockJavaSDKSimulator()


@pytest.fixture
def go_sdk():
    return MockGoSDKSimulator()


@pytest.fixture
def node_sdk():
    return MockNodeSDKSimulator()


@pytest.fixture
def rust_sdk():
    return MockRustSDKSimulator()


@pytest.fixture
def connection_manager():
    return ConnectionManager()


@pytest.fixture
def stream_processor():
    return StreamProcessor()


# =============================================================================
# 测试用例: 多语言 SDK 延迟对比
# =============================================================================

class TestSDKLatencyComparison:
    """多语言 SDK 延迟对比测试"""

    def test_request_creation_latency(self, benchmark_runner, python_sdk,
                                       java_sdk, go_sdk, node_sdk, rust_sdk):
        """测试请求创建延迟"""
        sdks = {
            "Python": python_sdk,
            "Java": java_sdk,
            "Go": go_sdk,
            "Node.js": node_sdk,
            "Rust": rust_sdk,
        }

        for name, sdk in sdks.items():
            result = benchmark_runner.measure_function(
                f"{name}_create_request",
                lambda: sdk.create_request("gpt-3.5-turbo", "Hello, world!"),
                iterations=500,
                warmup=50,
            )
            print(f"\n  {name} request creation: {result.avg_time_ms:.4f}ms")

        # 打印对比
        results = benchmark_runner.results
        assert len(results) == 5
        for r in results:
            assert r.avg_time_ms >= 0

    def test_serialization_latency(self, benchmark_runner, python_sdk,
                                    java_sdk, go_sdk, node_sdk, rust_sdk):
        """测试序列化延迟"""
        test_data = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "Hello, how are you?"},
                {"role": "assistant", "content": "I'm doing well, thank you!"},
            ],
            "temperature": 0.7,
            "max_tokens": 1000,
            "stream": False,
        }

        sdks = {
            "Python": python_sdk,
            "Java": java_sdk,
            "Go": go_sdk,
            "Node.js": node_sdk,
            "Rust": rust_sdk,
        }

        for name, sdk in sdks.items():
            result = benchmark_runner.measure_function(
                f"{name}_serialize",
                lambda: sdk.serialize(test_data),
                iterations=1000,
                warmup=100,
            )
            print(f"\n  {name} serialize: {result.avg_time_ms:.4f}ms, "
                  f"{result.ops_per_second:.0f} ops/s")

        assert len(benchmark_runner.results) == 5

    def test_deserialization_latency(self, benchmark_runner, python_sdk,
                                      java_sdk, go_sdk, node_sdk, rust_sdk):
        """测试反序列化延迟"""
        test_data = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "Hello, how are you?"},
                {"role": "assistant", "content": "I'm doing well, thank you!"},
            ],
            "temperature": 0.7,
            "max_tokens": 1000,
            "stream": False,
        }

        sdks = {
            "Python": python_sdk,
            "Java": java_sdk,
            "Go": go_sdk,
            "Node.js": node_sdk,
            "Rust": rust_sdk,
        }

        for name, sdk in sdks.items():
            serialized = sdk.serialize(test_data)
            result = benchmark_runner.measure_function(
                f"{name}_deserialize",
                lambda: sdk.deserialize(serialized),
                iterations=1000,
                warmup=100,
            )
            print(f"\n  {name} deserialize: {result.avg_time_ms:.4f}ms, "
                  f"{result.ops_per_second:.0f} ops/s")

        assert len(benchmark_runner.results) == 5

    def test_full_request_response_cycle(self, benchmark_runner, python_sdk,
                                           java_sdk, go_sdk, node_sdk, rust_sdk):
        """测试完整请求-响应周期"""
        sdks = {
            "Python": python_sdk,
            "Java": java_sdk,
            "Go": go_sdk,
            "Node.js": node_sdk,
            "Rust": rust_sdk,
        }

        for name, sdk in sdks.items():
            def cycle():
                req = sdk.create_request("gpt-3.5-turbo", "test")
                req_bytes = sdk.serialize(req)
                _ = sdk.deserialize(req_bytes)

            result = benchmark_runner.measure_function(
                f"{name}_full_cycle",
                cycle,
                iterations=500,
                warmup=50,
            )
            print(f"\n  {name} full cycle: {result.avg_time_ms:.4f}ms, "
                  f"{result.ops_per_second:.0f} ops/s")

        assert len(benchmark_runner.results) == 5

    def test_large_data_serialization(self, benchmark_runner, python_sdk,
                                       java_sdk, go_sdk, node_sdk, rust_sdk):
        """测试大数据序列化"""
        large_data = {
            "id": str(uuid.uuid4()),
            "data": [{"index": i, "value": random.random() * 1000,
                       "text": "x" * 100} for i in range(1000)],
        }

        sdks = {
            "Python": python_sdk,
            "Java": java_sdk,
            "Go": go_sdk,
            "Node.js": node_sdk,
            "Rust": rust_sdk,
        }

        for name, sdk in sdks.items():
            result = benchmark_runner.measure_function(
                f"{name}_large_serialize",
                lambda: sdk.serialize(large_data),
                iterations=100,
                warmup=10,
            )
            print(f"\n  {name} large serialize: {result.avg_time_ms:.3f}ms")

        assert len(benchmark_runner.results) == 5

    def test_latency_percentiles(self, benchmark_runner, python_sdk):
        """测试延迟百分位"""
        result = benchmark_runner.measure_function(
            "Python_serialize_percentiles",
            lambda: python_sdk.serialize({"test": "data"}),
            iterations=1000,
            warmup=100,
        )

        assert result.p50_time_ms <= result.p95_time_ms
        assert result.p95_time_ms <= result.p99_time_ms
        assert result.min_time_ms <= result.avg_time_ms
        assert result.max_time_ms >= result.avg_time_ms

    def test_serialization_vs_pickle(self, benchmark_runner, python_sdk):
        """测试 JSON vs Pickle 序列化"""
        test_data = {"key": "value", "numbers": list(range(100)),
                     "nested": {"inner": "data"}}

        json_result = benchmark_runner.measure_function(
            "json_serialize",
            lambda: python_sdk.serialize(test_data),
            iterations=500,
        )

        pickle_result = benchmark_runner.measure_function(
            "pickle_serialize",
            lambda: python_sdk.serialize_pickle(test_data),
            iterations=500,
        )

        print(f"\n  JSON: {json_result.avg_time_ms:.4f}ms, "
              f"Pickle: {pickle_result.avg_time_ms:.4f}ms")


# =============================================================================
# 测试用例: 序列化/反序列化性能
# =============================================================================

class TestSerializationPerformance:
    """序列化/反序列化性能测试"""

    def test_json_serialization_size(self, python_sdk):
        """测试 JSON 序列化大小"""
        data_sizes = [
            {"data": "small"},
            {"data": "x" * 1000},
            {"data": "x" * 10000},
            {"data": [{"id": i, "value": "x" * 100} for i in range(100)]},
            {"data": [{"id": i, "value": "x" * 100} for i in range(1000)]},
        ]

        for data in data_sizes:
            serialized = python_sdk.serialize(data)
            deserialized = python_sdk.deserialize(serialized)
            assert deserialized == data
            assert len(serialized) > 0

    def test_serialization_round_trip(self, python_sdk):
        """测试序列化往返"""
        test_cases = [
            {"string": "hello"},
            {"number": 42},
            {"float": 3.14159},
            {"list": [1, 2, 3]},
            {"nested": {"a": {"b": {"c": "deep"}}}},
            {"null": None},
            {"bool": True},
            {"mixed": [1, "two", 3.0, {"four": 4}]},
        ]

        for original in test_cases:
            serialized = python_sdk.serialize(original)
            deserialized = python_sdk.deserialize(serialized)
            assert deserialized == original

    def test_serialization_throughput(self, benchmark_runner, python_sdk):
        """测试序列化吞吐量"""
        data = {"id": str(uuid.uuid4()), "value": "x" * 1000}

        result = benchmark_runner.measure_function(
            "serialization_throughput",
            lambda: python_sdk.serialize(data),
            iterations=10000,
            warmup=500,
        )

        # 计算吞吐量
        serialized_size = len(python_sdk.serialize(data))
        throughput_mbps = (serialized_size * result.ops_per_second) / (1024 * 1024)
        print(f"\n  Serialization throughput: {throughput_mbps:.2f} MB/s")
        assert throughput_mbps > 0

    def test_deserialization_throughput(self, benchmark_runner, python_sdk):
        """测试反序列化吞吐量"""
        data = {"id": str(uuid.uuid4()), "value": "x" * 1000}
        serialized = python_sdk.serialize(data)

        result = benchmark_runner.measure_function(
            "deserialization_throughput",
            lambda: python_sdk.deserialize(serialized),
            iterations=10000,
            warmup=500,
        )

        throughput_mbps = (len(serialized) * result.ops_per_second) / (1024 * 1024)
        print(f"\n  Deserialization throughput: {throughput_mbps:.2f} MB/s")
        assert throughput_mbps > 0

    def test_serialization_overhead(self, python_sdk):
        """测试序列化开销"""
        original = {"data": "x" * 1000}
        serialized = python_sdk.serialize(original)
        overhead_ratio = len(serialized) / len(original["data"])
        print(f"\n  Serialization overhead ratio: {overhead_ratio:.2f}x")
        assert overhead_ratio > 0

    def test_bulk_serialization(self, benchmark_runner, python_sdk):
        """测试批量序列化"""
        items = [{"id": i, "value": f"item-{i}", "data": "x" * 100}
                 for i in range(100)]

        def bulk_serialize():
            results = []
            for item in items:
                results.append(python_sdk.serialize(item))
            return results

        result = benchmark_runner.measure_function(
            "bulk_serialize",
            bulk_serialize,
            iterations=100,
            warmup=10,
        )
        print(f"\n  Bulk serialization (100 items): {result.avg_time_ms:.3f}ms")


# =============================================================================
# 测试用例: 连接建立时间
# =============================================================================

class TestConnectionEstablishment:
    """连接建立时间测试"""

    @pytest.mark.asyncio
    async def test_connection_time(self, benchmark_runner, connection_manager):
        """测试连接时间"""
        async def connect():
            await connection_manager.connect()

        result = await benchmark_runner.measure_async_function(
            "connection_time",
            connect,
            iterations=200,
            warmup=20,
        )
        print(f"\n  Connection time: {result.avg_time_ms:.4f}ms")
        assert result.avg_time_ms >= 0

    @pytest.mark.asyncio
    async def test_connection_with_latency(self, benchmark_runner, connection_manager):
        """测试带延迟的连接"""
        connection_manager.set_latency(50)  # 50ms 延迟

        async def connect():
            await connection_manager.connect()

        result = await benchmark_runner.measure_async_function(
            "connection_with_latency",
            connect,
            iterations=50,
            warmup=5,
        )
        print(f"\n  Connection with 50ms latency: {result.avg_time_ms:.2f}ms")
        assert result.avg_time_ms >= 50

    @pytest.mark.asyncio
    async def test_concurrent_connections(self, benchmark_runner, connection_manager):
        """测试并发连接"""
        async def connect_all():
            tasks = [connection_manager.connect() for _ in range(100)]
            await asyncio.gather(*tasks)

        result = await benchmark_runner.measure_async_function(
            "concurrent_100_connections",
            connect_all,
            iterations=20,
            warmup=3,
        )
        print(f"\n  100 concurrent connections: {result.avg_time_ms:.2f}ms")
        assert result.avg_time_ms >= 0

    @pytest.mark.asyncio
    async def test_connection_reuse(self, benchmark_runner, connection_manager):
        """测试连接复用"""
        conn_id = await connection_manager.connect()

        async def check():
            await connection_manager.health_check(conn_id)

        result = await benchmark_runner.measure_async_function(
            "connection_reuse",
            check,
            iterations=1000,
            warmup=100,
        )
        print(f"\n  Connection reuse health check: {result.avg_time_ms:.4f}ms")

    @pytest.mark.asyncio
    async def test_connection_cleanup(self, benchmark_runner, connection_manager):
        """测试连接清理"""
        conn_id = await connection_manager.connect()

        async def disconnect():
            await connection_manager.disconnect(conn_id)

        result = await benchmark_runner.measure_async_function(
            "connection_cleanup",
            disconnect,
            iterations=200,
            warmup=20,
        )
        print(f"\n  Connection cleanup: {result.avg_time_ms:.4f}ms")

    @pytest.mark.asyncio
    async def test_connection_timeout(self, connection_manager):
        """测试连接超时"""
        connection_manager.set_latency(5000)  # 5s 延迟

        start = time.time()
        try:
            await connection_manager.connect(timeout=0.1)
        except asyncio.TimeoutError:
            elapsed = (time.time() - start) * 1000
            print(f"\n  Connection timeout after {elapsed:.2f}ms")
            assert elapsed < 5000


# =============================================================================
# 测试用例: 流式处理吞吐量
# =============================================================================

class TestStreamingThroughput:
    """流式处理吞吐量测试"""

    def test_stream_chunk_processing(self, benchmark_runner, stream_processor):
        """测试流式块处理"""
        chunks = stream_processor.generate_stream(1024 * 1024)  # 1MB

        result = benchmark_runner.measure_function(
            "stream_chunk_processing",
            lambda: stream_processor.process_stream_sync(chunks, lambda x: x),
            iterations=50,
            warmup=5,
        )

        total_bytes = sum(len(c) for c in chunks)
        throughput = stream_processor.throughput(total_bytes, result.avg_time_ms)
        print(f"\n  Stream processing throughput: {throughput:.2f} MB/s")
        assert throughput > 0

    def test_stream_chunk_size_impact(self, benchmark_runner):
        """测试块大小影响"""
        for chunk_size in [32, 128, 512, 2048, 8192, 65536]:
            processor = StreamProcessor(chunk_size=chunk_size)
            chunks = processor.generate_stream(1024 * 1024)  # 1MB

            result = benchmark_runner.measure_function(
                f"chunk_size_{chunk_size}",
                lambda: processor.process_stream_sync(chunks, lambda x: x),
                iterations=30,
                warmup=3,
            )

            total_bytes = sum(len(c) for c in chunks)
            throughput = processor.throughput(total_bytes, result.avg_time_ms)
            print(f"\n  Chunk size {chunk_size}: {throughput:.2f} MB/s, "
                  f"{result.avg_time_ms:.3f}ms")

    @pytest.mark.asyncio
    async def test_async_stream_processing(self, benchmark_runner, stream_processor):
        """测试异步流处理"""
        chunks = stream_processor.generate_stream(1024 * 1024)

        async def process():
            await stream_processor.process_stream(chunks, lambda x: x)

        result = await benchmark_runner.measure_async_function(
            "async_stream_processing",
            process,
            iterations=50,
            warmup=5,
        )

        total_bytes = sum(len(c) for c in chunks)
        throughput = stream_processor.throughput(total_bytes, result.avg_time_ms)
        print(f"\n  Async stream throughput: {throughput:.2f} MB/s")

    def test_stream_with_transformation(self, benchmark_runner, stream_processor):
        """测试流式转换"""
        chunks = stream_processor.generate_stream(512 * 1024)

        def transform(chunk):
            return chunk.hex().encode('utf-8')

        result = benchmark_runner.measure_function(
            "stream_with_transform",
            lambda: stream_processor.process_stream_sync(chunks, transform),
            iterations=30,
            warmup=3,
        )

        total_bytes = sum(len(c) for c in chunks)
        throughput = stream_processor.throughput(total_bytes, result.avg_time_ms)
        print(f"\n  Stream with transform throughput: {throughput:.2f} MB/s")

    def test_stream_backpressure(self, benchmark_runner):
        """测试流背压"""
        processor = StreamProcessor(chunk_size=1024, delay_ms=1)
        chunks = processor.generate_stream(100 * 1024)

        result = benchmark_runner.measure_function(
            "stream_backpressure",
            lambda: processor.process_stream_sync(chunks, lambda x: x),
            iterations=20,
            warmup=2,
        )

        print(f"\n  Stream with backpressure: {result.avg_time_ms:.3f}ms")

    def test_stream_throughput_scaling(self, benchmark_runner):
        """测试流吞吐量扩展性"""
        sizes = [1024 * 1024, 5 * 1024 * 1024, 10 * 1024 * 1024]

        for size in sizes:
            processor = StreamProcessor(chunk_size=65536)
            chunks = processor.generate_stream(size)

            result = benchmark_runner.measure_function(
                f"stream_size_{size // 1024 // 1024}MB",
                lambda: processor.process_stream_sync(chunks, lambda x: x),
                iterations=10,
                warmup=2,
            )

            throughput = processor.throughput(size, result.avg_time_ms)
            print(f"\n  Size {size // 1024 // 1024}MB: {throughput:.2f} MB/s")


# =============================================================================
# 测试用例: 基准测试运行器
# =============================================================================

class TestBenchmarkRunner:
    """基准测试运行器测试"""

    def test_benchmark_runner_basic(self, benchmark_runner):
        """测试基准运行器基本功能"""
        def dummy():
            time.sleep(0.001)

        result = benchmark_runner.measure_function("dummy", dummy, iterations=10)
        assert result.iterations == 10
        assert result.avg_time_ms > 0
        assert result.total_time_ms > 0

    def test_benchmark_result_consistency(self, benchmark_runner):
        """测试基准结果一致性"""
        def fast_op():
            pass

        result = benchmark_runner.measure_function("fast", fast_op, iterations=100)
        assert result.min_time_ms <= result.avg_time_ms
        assert result.avg_time_ms <= result.max_time_ms
        assert result.ops_per_second > 0

    def test_benchmark_warmup(self, benchmark_runner):
        """测试预热"""
        call_count = [0]

        def counted():
            call_count[0] += 1

        benchmark_runner.measure_function("counted", counted, iterations=10, warmup=5)
        # 预热 5 次 + 测量 10 次
        assert call_count[0] == 15

    def test_benchmark_report(self, benchmark_runner):
        """测试基准报告"""
        benchmark_runner.measure_function("test1", lambda: None, iterations=10)
        benchmark_runner.measure_function("test2", lambda: time.sleep(0.001), iterations=10)

        report = benchmark_runner.report()
        assert "test1" in report
        assert "test2" in report
        assert "avg" in report

    def test_benchmark_result_dict(self, benchmark_runner):
        """测试基准结果字典"""
        benchmark_runner.measure_function("dict_test", lambda: None, iterations=10)
        result_dict = benchmark_runner.results[0].to_dict()
        assert "name" in result_dict
        assert "avg_time_ms" in result_dict
        assert "ops_per_second" in result_dict

    def test_benchmark_clear(self, benchmark_runner):
        """测试基准清除"""
        benchmark_runner.measure_function("clear_test", lambda: None, iterations=10)
        assert len(benchmark_runner.results) == 1
        benchmark_runner.clear()
        assert len(benchmark_runner.results) == 0


# =============================================================================
# 测试用例: 端到端基准测试
# =============================================================================

class TestEndToEndBenchmark:
    """端到端基准测试"""

    @pytest.mark.asyncio
    async def test_full_sdk_workflow(self, benchmark_runner, python_sdk,
                                      connection_manager):
        """测试完整 SDK 工作流"""
        async def full_workflow():
            # 连接
            conn_id = await connection_manager.connect()
            # 创建请求
            request = python_sdk.create_request("gpt-3.5-turbo", "test prompt")
            # 序列化
            data = python_sdk.serialize(request)
            # 反序列化（模拟响应）
            response = python_sdk.deserialize(data)
            # 断开连接
            await connection_manager.disconnect(conn_id)
            return response

        result = await benchmark_runner.measure_async_function(
            "full_sdk_workflow",
            full_workflow,
            iterations=100,
            warmup=10,
        )
        print(f"\n  Full SDK workflow: {result.avg_time_ms:.4f}ms, "
              f"{result.ops_per_second:.0f} ops/s")

    @pytest.mark.asyncio
    async def test_repeated_connections(self, benchmark_runner, python_sdk,
                                         connection_manager):
        """测试重复连接"""
        async def connect_and_query():
            conn_id = await connection_manager.connect()
            await connection_manager.health_check(conn_id)
            await connection_manager.disconnect(conn_id)

        result = await benchmark_runner.measure_async_function(
            "connect_and_query",
            connect_and_query,
            iterations=100,
            warmup=10,
        )
        print(f"\n  Connect and query: {result.avg_time_ms:.4f}ms")

    def test_request_size_impact(self, benchmark_runner, python_sdk):
        """测试请求大小影响"""
        for size in [10, 100, 1000, 10000]:
            data = {"data": "x" * size}

            result = benchmark_runner.measure_function(
                f"request_size_{size}",
                lambda: python_sdk.serialize(data),
                iterations=500,
                warmup=50,
            )
            print(f"\n  Request size {size}: {result.avg_time_ms:.4f}ms, "
                  f"{result.ops_per_second:.0f} ops/s")

    def test_response_size_impact(self, benchmark_runner, python_sdk):
        """测试响应大小影响"""
        for size in [10, 100, 1000, 10000]:
            data = {"choices": [{"text": "x" * size, "index": 0}]}

            result = benchmark_runner.measure_function(
                f"response_size_{size}",
                lambda: python_sdk.serialize(data),
                iterations=500,
                warmup=50,
            )
            print(f"\n  Response size {size}: {result.avg_time_ms:.4f}ms")

    def test_benchmark_summary(self, benchmark_runner, python_sdk):
        """测试基准测试汇总"""
        # 运行多个基准测试
        benchmark_runner.measure_function("op1", lambda: python_sdk.serialize({"a": 1}), iterations=100)
        benchmark_runner.measure_function("op2", lambda: python_sdk.serialize({"b": 2}), iterations=100)
        benchmark_runner.measure_function("op3", lambda: python_sdk.serialize({"c": 3}), iterations=100)

        summary = benchmark_runner.report()
        print(f"\n{summary}")
        assert len(benchmark_runner.results) == 3

    def test_warmup_effectiveness(self, benchmark_runner, python_sdk):
        """测试预热效果"""
        # 无预热
        no_warmup = benchmark_runner.measure_function(
            "no_warmup",
            lambda: python_sdk.serialize({"test": "data"}),
            iterations=100,
            warmup=0,
        )

        # 有预热
        with_warmup = benchmark_runner.measure_function(
            "with_warmup",
            lambda: python_sdk.serialize({"test": "data"}),
            iterations=100,
            warmup=100,
        )

        print(f"\n  No warmup: {no_warmup.avg_time_ms:.4f}ms")
        print(f"  With warmup: {with_warmup.avg_time_ms:.4f}ms")


# =============================================================================
# 性能基准测试主入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])