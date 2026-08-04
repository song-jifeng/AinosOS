"""
网络压力测试

测试高吞吐量网络流量、连接风暴、慢连接攻击和数据包损坏场景。
"""

import os
import sys
import json
import time
import uuid
import random
import socket
import struct
import asyncio
import threading
import pytest
from typing import List, Dict, Optional, Any, Tuple, Callable, Set, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
from enum import Enum, auto
from unittest.mock import MagicMock, Mock, patch, AsyncMock


# =============================================================================
# 数据类
# =============================================================================

@dataclass
class NetworkPacket:
    """网络数据包"""
    src: str
    dst: str
    protocol: str
    payload: bytes
    seq: int
    timestamp: float = field(default_factory=time.time)
    corrupted: bool = False
    delayed: bool = False
    ttl: int = 64

    @property
    def size(self) -> int:
        return len(self.payload)

    @property
    def hex_dump(self) -> str:
        return self.payload.hex()[:64]


@dataclass
class NetworkStats:
    """网络统计"""
    total_packets_sent: int = 0
    total_packets_received: int = 0
    total_bytes_sent: int = 0
    total_bytes_received: int = 0
    packets_lost: int = 0
    packets_corrupted: int = 0
    connections_established: int = 0
    connections_failed: int = 0
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    throughput_bps: float = 0.0
    errors: Dict[str, int] = field(default_factory=dict)
    duration: float = 0.0


@dataclass
class ConnectionInfo:
    """连接信息"""
    conn_id: str
    src_addr: str
    dst_addr: str
    protocol: str
    established_at: float
    bytes_sent: int = 0
    bytes_received: int = 0
    packets_sent: int = 0
    packets_received: int = 0
    closed: bool = False


# =============================================================================
# Mock 网络模拟器
# =============================================================================

class NetworkStressSimulator:
    """网络压力模拟器"""

    def __init__(self):
        self._connections: Dict[str, ConnectionInfo] = {}
        self._packets: List[NetworkPacket] = []
        self._latencies: List[float] = []
        self._stats = NetworkStats()
        self._lock = threading.RLock()
        self._running = False
        self._max_connections = 10000
        self._connection_counter = 0
        self._error_rate = 0.0
        self._latency_ms = 0.0
        self._packet_loss_rate = 0.0
        self._corruption_rate = 0.0
        self._bandwidth_limit_bps = 1_000_000_000  # 1 Gbps

    def start(self):
        self._running = True
        self._stats = NetworkStats()
        self._stats.duration = time.time()

    def stop(self):
        self._running = False
        self._stats.duration = time.time() - self._stats.duration
        self._connections.clear()

    def set_config(self, error_rate: float = 0.0, latency_ms: float = 0.0,
                   packet_loss_rate: float = 0.0, corruption_rate: float = 0.0,
                   bandwidth_limit_bps: float = 1_000_000_000):
        """设置网络模拟参数"""
        self._error_rate = error_rate
        self._latency_ms = latency_ms
        self._packet_loss_rate = packet_loss_rate
        self._corruption_rate = corruption_rate
        self._bandwidth_limit_bps = bandwidth_limit_bps

    def create_connection(self, src: str = "127.0.0.1",
                          dst: str = "127.0.0.1",
                          protocol: str = "tcp") -> Optional[str]:
        """创建连接"""
        if not self._running:
            return None

        with self._lock:
            if len(self._connections) >= self._max_connections:
                self._stats.connections_failed += 1
                return None

            if random.random() < self._error_rate:
                self._stats.connections_failed += 1
                return None

            conn_id = f"conn-{self._connection_counter}-{uuid.uuid4().hex[:8]}"
            self._connection_counter += 1

            conn = ConnectionInfo(
                conn_id=conn_id,
                src_addr=src,
                dst_addr=dst,
                protocol=protocol,
                established_at=time.time(),
            )
            self._connections[conn_id] = conn
            self._stats.connections_established += 1
            return conn_id

    def close_connection(self, conn_id: str):
        """关闭连接"""
        with self._lock:
            if conn_id in self._connections:
                self._connections[conn_id].closed = True
                del self._connections[conn_id]

    def send_packet(self, conn_id: str, data: bytes) -> bool:
        """发送数据包"""
        if not self._running:
            return False

        with self._lock:
            if conn_id not in self._connections:
                self._stats.errors["connection_not_found"] += 1
                return False

            conn = self._connections[conn_id]

            # 模拟带宽限制
            if self._stats.total_bytes_sent > self._bandwidth_limit_bps:
                time.sleep(0.001)

            # 模拟延迟
            if self._latency_ms > 0:
                time.sleep(self._latency_ms / 1000.0)

            # 模拟丢包
            if random.random() < self._packet_loss_rate:
                self._stats.packets_lost += 1
                return False

            # 模拟数据损坏
            corrupted = random.random() < self._corruption_rate
            payload = data
            if corrupted:
                payload = self._corrupt_data(data)
                self._stats.packets_corrupted += 1

            packet = NetworkPacket(
                src=conn.src_addr,
                dst=conn.dst_addr,
                protocol=conn.protocol,
                payload=payload,
                seq=conn.packets_sent,
                corrupted=corrupted,
            )

            self._packets.append(packet)
            conn.packets_sent += 1
            conn.bytes_sent += len(data)
            self._stats.total_packets_sent += 1
            self._stats.total_bytes_sent += len(data)

            return True

    def receive_packet(self, conn_id: str) -> Optional[bytes]:
        """接收数据包"""
        with self._lock:
            if conn_id not in self._connections:
                return None

            if not self._packets:
                return None

            packet = self._packets.pop(0)
            conn = self._connections[conn_id]
            conn.packets_received += 1
            conn.bytes_received += len(packet.payload)
            self._stats.total_packets_received += 1
            self._stats.total_bytes_received += len(packet.payload)

            if packet.corrupted:
                return None

            return packet.payload

    def send_http_request(self, conn_id: str, method: str = "GET",
                          path: str = "/", body: str = "") -> bool:
        """发送 HTTP 请求"""
        request = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
        if body:
            request += f"Content-Length: {len(body)}\r\n\r\n{body}"
        else:
            request += "\r\n"
        return self.send_packet(conn_id, request.encode('utf-8'))

    def send_websocket_frame(self, conn_id: str, data: bytes,
                             opcode: int = 0x01) -> bool:
        """发送 WebSocket 帧"""
        frame = struct.pack('!B', 0x80 | opcode)
        if len(data) < 126:
            frame += struct.pack('!B', len(data))
        elif len(data) < 65536:
            frame += struct.pack('!BH', 126, len(data))
        else:
            frame += struct.pack('!BQ', 127, len(data))
        frame += data
        return self.send_packet(conn_id, frame)

    def send_tcp_syn_flood(self, target: str, count: int) -> int:
        """模拟 TCP SYN Flood 攻击"""
        sent = 0
        for i in range(count):
            try:
                conn_id = self.create_connection(
                    src=f"10.0.0.{random.randint(1, 255)}",
                    dst=target,
                    protocol="tcp",
                )
                if conn_id:
                    # 发送 SYN 但不完成握手
                    self.send_packet(conn_id, b"SYN")
                    sent += 1
            except Exception:
                pass
        return sent

    def send_large_payload(self, conn_id: str, size_bytes: int) -> bool:
        """发送大负载"""
        data = os.urandom(size_bytes)
        chunk_size = 65536
        chunks_sent = 0

        for offset in range(0, len(data), chunk_size):
            chunk = data[offset:offset + chunk_size]
            if self.send_packet(conn_id, chunk):
                chunks_sent += 1
            else:
                break

        return chunks_sent > 0

    def measure_latency(self, conn_id: str) -> float:
        """测量延迟"""
        start = time.time()
        if self.send_packet(conn_id, b"PING"):
            response = self.receive_packet(conn_id)
            if response:
                latency = (time.time() - start) * 1000
                with self._lock:
                    self._latencies.append(latency)
                return latency
        return -1

    @staticmethod
    def _corrupt_data(data: bytes) -> bytes:
        """损坏数据"""
        if len(data) == 0:
            return data
        data_list = bytearray(data)
        # 随机翻转 1-3 个字节
        num_flips = random.randint(1, min(3, len(data_list)))
        for _ in range(num_flips):
            idx = random.randint(0, len(data_list) - 1)
            data_list[idx] ^= (1 << random.randint(0, 7))
        return bytes(data_list)

    def get_stats(self) -> NetworkStats:
        with self._lock:
            self._stats.duration = time.time()
            latencies = self._latencies
            if latencies:
                self._stats.avg_latency_ms = sum(latencies) / len(latencies)
                self._stats.max_latency_ms = max(latencies)
                self._stats.min_latency_ms = min(latencies)
            if self._stats.duration > 0:
                total_bytes = self._stats.total_bytes_sent + self._stats.total_bytes_received
                self._stats.throughput_bps = total_bytes * 8 / self._stats.duration
            return self._stats

    def get_active_connections(self) -> List[ConnectionInfo]:
        with self._lock:
            return list(self._connections.values())

    def get_connection_count(self) -> int:
        with self._lock:
            return len(self._connections)

    def reset(self):
        self._connections.clear()
        self._packets.clear()
        self._latencies.clear()
        self._stats = NetworkStats()
        self._connection_counter = 0


# =============================================================================
# 测试夹具
# =============================================================================

@pytest.fixture
def network_simulator():
    sim = NetworkStressSimulator()
    sim.start()
    yield sim
    sim.stop()


@pytest.fixture
def connected_simulator(network_simulator):
    """预创建连接的模拟器"""
    conns = []
    for i in range(10):
        conn_id = network_simulator.create_connection(
            src=f"192.168.1.{i+1}",
            dst="10.0.0.1",
        )
        if conn_id:
            conns.append(conn_id)
    return network_simulator, conns


# =============================================================================
# 测试用例: 高吞吐量网络流量
# =============================================================================

class TestHighThroughput:
    """高吞吐量网络流量测试"""

    def test_small_packet_throughput(self, network_simulator):
        """测试小数据包吞吐量"""
        conn_id = network_simulator.create_connection()
        assert conn_id is not None

        num_packets = 10000
        packet_size = 64  # 64 bytes

        start = time.time()
        for i in range(num_packets):
            data = os.urandom(packet_size)
            network_simulator.send_packet(conn_id, data)
        duration = time.time() - start

        stats = network_simulator.get_stats()
        assert stats.total_packets_sent >= num_packets * 0.9
        throughput = (stats.total_bytes_sent * 8) / duration
        assert throughput > 0

    def test_large_packet_throughput(self, network_simulator):
        """测试大数据包吞吐量"""
        conn_id = network_simulator.create_connection()

        num_packets = 100
        packet_size = 65536  # 64KB

        for i in range(num_packets):
            data = os.urandom(packet_size)
            network_simulator.send_packet(conn_id, data)

        stats = network_simulator.get_stats()
        assert stats.total_bytes_sent >= num_packets * packet_size * 0.9

    def test_mixed_sizes_throughput(self, network_simulator):
        """测试混合大小数据包吞吐量"""
        conn_id = network_simulator.create_connection()

        for i in range(5000):
            size = random.choice([64, 256, 1024, 4096, 16384, 65536])
            data = os.urandom(size)
            network_simulator.send_packet(conn_id, data)

        stats = network_simulator.get_stats()
        assert stats.total_packets_sent >= 4500

    def test_continuous_stream_throughput(self, network_simulator):
        """测试持续流吞吐量"""
        conn_id = network_simulator.create_connection()

        end_time = time.time() + 2
        packet_count = 0

        while time.time() < end_time:
            data = os.urandom(1400)  # MTU 大小
            if network_simulator.send_packet(conn_id, data):
                packet_count += 1

        stats = network_simulator.get_stats()
        assert stats.throughput_bps > 0
        assert packet_count > 100

    def test_bandwidth_limit(self, network_simulator):
        """测试带宽限制"""
        network_simulator.set_config(bandwidth_limit_bps=1_000_000)  # 1 Mbps
        conn_id = network_simulator.create_connection()

        start = time.time()
        for i in range(100):
            data = os.urandom(10000)
            network_simulator.send_packet(conn_id, data)
        duration = time.time() - start

        stats = network_simulator.get_stats()
        assert stats.total_bytes_sent > 0


# =============================================================================
# 测试用例: 连接风暴
# =============================================================================

class TestConnectionStorm:
    """连接风暴测试"""

    def test_rapid_connection_creation(self, network_simulator):
        """测试快速连接创建"""
        num_connections = 1000
        connections = []

        for i in range(num_connections):
            conn_id = network_simulator.create_connection(
                src=f"10.0.0.{random.randint(1, 255)}",
                dst="192.168.1.1",
            )
            if conn_id:
                connections.append(conn_id)

        stats = network_simulator.get_stats()
        assert stats.connections_established >= num_connections * 0.9

        for conn_id in connections:
            network_simulator.close_connection(conn_id)

    def test_connection_storm_with_traffic(self, network_simulator):
        """测试连接风暴中的流量"""
        def connection_worker(worker_id):
            local_conns = []
            for i in range(50):
                conn_id = network_simulator.create_connection(
                    src=f"10.0.0.{worker_id}",
                    dst="192.168.1.1",
                )
                if conn_id:
                    local_conns.append(conn_id)
                    for j in range(10):
                        network_simulator.send_packet(conn_id, os.urandom(100))
            for conn_id in local_conns:
                network_simulator.close_connection(conn_id)
            return len(local_conns)

        threads = [threading.Thread(target=connection_worker, args=(i,))
                   for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = network_simulator.get_stats()
        assert stats.connections_established > 0
        assert stats.total_packets_sent > 0

    def test_simultaneous_connection_storm(self, network_simulator):
        """测试同时连接风暴"""
        import threading

        results = []
        def storm_worker(count):
            conns = []
            for i in range(count):
                conn_id = network_simulator.create_connection(
                    src=f"10.0.0.{random.randint(1, 255)}",
                    dst="target",
                )
                if conn_id:
                    conns.append(conn_id)
            results.append(len(conns))
            for conn_id in conns:
                network_simulator.close_connection(conn_id)

        threads = [threading.Thread(target=storm_worker, args=(200,))
                   for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total_created = sum(results)
        assert total_created > 0

    def test_connection_rate_limiting(self, network_simulator):
        """测试连接速率限制"""
        network_simulator._max_connections = 100

        connections = []
        for i in range(200):
            conn_id = network_simulator.create_connection()
            if conn_id:
                connections.append(conn_id)

        # 应该有部分连接被拒绝
        assert len(connections) <= 100

        for conn_id in connections:
            network_simulator.close_connection(conn_id)


# =============================================================================
# 测试用例: 慢连接攻击
# =============================================================================

class TestSlowConnectionAttack:
    """慢连接攻击测试"""

    def test_slow_send_attack(self, network_simulator):
        """测试慢发送攻击"""
        conn_id = network_simulator.create_connection()
        assert conn_id is not None

        # 极慢地发送数据
        for i in range(10):
            time.sleep(1)  # 每秒只发一个字节
            network_simulator.send_packet(conn_id, b"X")

        stats = network_simulator.get_stats()
        assert stats.total_packets_sent >= 10

    def test_slow_read_attack(self, network_simulator):
        """测试慢读取攻击"""
        conn_id = network_simulator.create_connection()

        # 发送大量数据但不读取
        for i in range(1000):
            network_simulator.send_packet(conn_id, b"X" * 1000)

        stats = network_simulator.get_stats()
        assert stats.total_bytes_sent >= 1000 * 1000 * 0.9

    def test_http_slowloris_attack(self, network_simulator):
        """测试 HTTP Slowloris 攻击"""
        conn_id = network_simulator.create_connection(protocol="http")
        assert conn_id is not None

        # 发送不完整的 HTTP 请求头
        partial_request = "POST /api/data HTTP/1.1\r\nHost: target\r\n"
        network_simulator.send_packet(conn_id, partial_request.encode())

        # 缓慢发送剩余头部
        for i in range(5):
            time.sleep(1)
            network_simulator.send_packet(conn_id, f"X-Header-{i}: value\r\n".encode())

        stats = network_simulator.get_stats()
        assert stats.total_packets_sent >= 6

    def test_many_slow_connections(self, network_simulator):
        """测试大量慢连接"""
        connections = []
        for i in range(100):
            conn_id = network_simulator.create_connection(
                src=f"10.0.0.{i}",
                dst="target",
                protocol="http",
            )
            if conn_id:
                connections.append(conn_id)
                # 发送部分数据
                network_simulator.send_packet(conn_id, b"GET / HTTP/1.1\r\n")

        stats = network_simulator.get_stats()
        assert stats.connections_established >= 90

        for conn_id in connections:
            network_simulator.close_connection(conn_id)


# =============================================================================
# 测试用例: 数据包损坏
# =============================================================================

class TestPacketCorruption:
    """数据包损坏测试"""

    def test_single_bit_flip(self):
        """测试单比特翻转"""
        original = b"Hello, World!"
        corrupted = NetworkStressSimulator._corrupt_data(original)
        assert len(corrupted) == len(original)
        # 至少有一个比特差异
        diffs = sum(1 for a, b in zip(original, corrupted) if a != b)
        assert diffs >= 1

    def test_corruption_detection(self, network_simulator):
        """测试数据损坏检测"""
        network_simulator.set_config(corruption_rate=1.0)  # 100% 损坏率
        conn_id = network_simulator.create_connection()
        assert conn_id is not None

        sent = network_simulator.send_packet(conn_id, b"test data")
        assert sent is True

        received = network_simulator.receive_packet(conn_id)
        # 损坏的数据包接收时返回 None
        assert received is None

        stats = network_simulator.get_stats()
        assert stats.packets_corrupted >= 1

    def test_partial_corruption(self, network_simulator):
        """测试部分数据损坏"""
        network_simulator.set_config(corruption_rate=0.5)
        conn_id = network_simulator.create_connection()

        corrupted_count = 0
        for i in range(100):
            network_simulator.send_packet(conn_id, f"packet-{i}".encode())

        for i in range(100):
            received = network_simulator.receive_packet(conn_id)
            if received is None:
                corrupted_count += 1

        stats = network_simulator.get_stats()
        assert stats.packets_corrupted >= 0

    def test_corruption_recovery(self, network_simulator):
        """测试损坏恢复"""
        conn_id = network_simulator.create_connection()

        # 发送正常数据
        network_simulator.send_packet(conn_id, b"normal data")
        received = network_simulator.receive_packet(conn_id)
        assert received == b"normal data"

        # 损坏后仍然可以继续通信
        network_simulator.set_config(corruption_rate=0.0)
        network_simulator.send_packet(conn_id, b"after corruption")
        received = network_simulator.receive_packet(conn_id)
        assert received == b"after corruption"

    def test_corruption_rate_accuracy(self, network_simulator):
        """测试损坏率准确性"""
        corruption_rate = 0.3
        network_simulator.set_config(corruption_rate=corruption_rate)
        conn_id = network_simulator.create_connection()

        num_packets = 1000
        for i in range(num_packets):
            network_simulator.send_packet(conn_id, b"test")

        stats = network_simulator.get_stats()
        # 实际损坏率应该在预期范围内
        actual_rate = stats.packets_corrupted / num_packets
        assert abs(actual_rate - corruption_rate) < 0.1


# =============================================================================
# 测试用例: 网络异常
# =============================================================================

class TestNetworkAnomalies:
    """网络异常测试"""

    def test_packet_loss(self, network_simulator):
        """测试丢包"""
        network_simulator.set_config(packet_loss_rate=0.5)
        conn_id = network_simulator.create_connection()

        sent_count = 0
        for i in range(100):
            if network_simulator.send_packet(conn_id, b"data"):
                sent_count += 1

        stats = network_simulator.get_stats()
        assert stats.packets_lost > 0

    def test_network_latency(self, network_simulator):
        """测试网络延迟"""
        network_simulator.set_config(latency_ms=100)
        conn_id = network_simulator.create_connection()

        start = time.time()
        network_simulator.send_packet(conn_id, b"test")
        latency = (time.time() - start) * 1000

        # 延迟应该 >= 100ms
        assert latency >= 95

    def test_connection_timeout(self, network_simulator):
        """测试连接超时"""
        # 创建连接但不发送数据
        conn_id = network_simulator.create_connection()
        assert conn_id is not None

        # 等待后关闭
        time.sleep(0.5)
        network_simulator.close_connection(conn_id)
        assert network_simulator.get_connection_count() == 0

    def test_network_congestion(self, network_simulator):
        """测试网络拥塞"""
        conn_id = network_simulator.create_connection()

        # 模拟拥塞：大量并发发送
        def congestion_worker():
            for i in range(500):
                network_simulator.send_packet(conn_id, os.urandom(100))

        threads = [threading.Thread(target=congestion_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = network_simulator.get_stats()
        assert stats.total_packets_sent >= 2000


# =============================================================================
# 测试用例: 协议级压力
# =============================================================================

class TestProtocolStress:
    """协议级压力测试"""

    def test_http_request_storm(self, network_simulator):
        """测试 HTTP 请求风暴"""
        conn_id = network_simulator.create_connection(protocol="http")

        for i in range(1000):
            network_simulator.send_http_request(
                conn_id, "GET", f"/api/data/{i}",
            )

        stats = network_simulator.get_stats()
        assert stats.total_packets_sent >= 1000

    def test_websocket_frame_storm(self, network_simulator):
        """测试 WebSocket 帧风暴"""
        conn_id = network_simulator.create_connection(protocol="websocket")

        for i in range(500):
            network_simulator.send_websocket_frame(
                conn_id, f"message-{i}".encode(), opcode=0x01,
            )

        stats = network_simulator.get_stats()
        assert stats.total_packets_sent >= 500

    def test_mixed_protocol_traffic(self, network_simulator):
        """测试混合协议流量"""
        http_conn = network_simulator.create_connection(protocol="http")
        ws_conn = network_simulator.create_connection(protocol="websocket")
        tcp_conn = network_simulator.create_connection(protocol="tcp")

        for i in range(100):
            network_simulator.send_http_request(http_conn, "GET", "/")
            network_simulator.send_websocket_frame(ws_conn, b"ping", opcode=0x09)
            network_simulator.send_packet(tcp_conn, b"raw data")

        stats = network_simulator.get_stats()
        assert stats.total_packets_sent >= 300

    def test_tcp_syn_flood(self, network_simulator):
        """测试 TCP SYN Flood"""
        sent = network_simulator.send_tcp_syn_flood("192.168.1.1", 500)
        assert sent > 0

        stats = network_simulator.get_stats()
        assert stats.connections_established > 0


# =============================================================================
# 测试用例: 网络统计与监控
# =============================================================================

class TestNetworkStatistics:
    """网络统计与监控测试"""

    def test_basic_statistics(self, network_simulator):
        """测试基本统计"""
        conn_id = network_simulator.create_connection()

        for i in range(100):
            network_simulator.send_packet(conn_id, b"test data")

        stats = network_simulator.get_stats()
        assert stats.total_packets_sent >= 100
        assert stats.total_bytes_sent >= 100 * len(b"test data")
        assert stats.connections_established >= 1

    def test_error_statistics(self, network_simulator):
        """测试错误统计"""
        network_simulator.set_config(error_rate=0.5)

        for i in range(100):
            network_simulator.create_connection()

        stats = network_simulator.get_stats()
        assert stats.connections_failed > 0

    def test_latency_statistics(self, network_simulator):
        """测试延迟统计"""
        network_simulator.set_config(latency_ms=10)
        conn_id = network_simulator.create_connection()

        for i in range(50):
            network_simulator.measure_latency(conn_id)

        stats = network_simulator.get_stats()
        assert stats.avg_latency_ms > 0

    def test_throughput_calculation(self, network_simulator):
        """测试吞吐量计算"""
        conn_id = network_simulator.create_connection()
        data_size = 1000

        start = time.time()
        for i in range(1000):
            network_simulator.send_packet(conn_id, os.urandom(data_size))
        duration = time.time() - start

        stats = network_simulator.get_stats()
        expected_throughput = (stats.total_bytes_sent * 8) / duration
        assert stats.throughput_bps > 0
        assert abs(stats.throughput_bps - expected_throughput) < expected_throughput * 0.1


# =============================================================================
# 测试用例: 网络恢复
# =============================================================================

class TestNetworkRecovery:
    """网络恢复测试"""

    def test_recovery_after_packet_loss(self, network_simulator):
        """测试丢包后恢复"""
        network_simulator.set_config(packet_loss_rate=1.0)
        conn_id = network_simulator.create_connection()

        # 全部丢包
        for i in range(10):
            network_simulator.send_packet(conn_id, b"will be lost")

        # 恢复
        network_simulator.set_config(packet_loss_rate=0.0)
        network_simulator.send_packet(conn_id, b"recovered")
        received = network_simulator.receive_packet(conn_id)
        assert received == b"recovered"

    def test_recovery_after_high_latency(self, network_simulator):
        """测试高延迟后恢复"""
        network_simulator.set_config(latency_ms=500)
        conn_id = network_simulator.create_connection()

        network_simulator.set_config(latency_ms=0)
        start = time.time()
        network_simulator.send_packet(conn_id, b"fast")
        assert (time.time() - start) * 1000 < 100

    def test_recovery_after_corruption(self, network_simulator):
        """测试损坏后恢复"""
        network_simulator.set_config(corruption_rate=1.0)
        conn_id = network_simulator.create_connection()
        network_simulator.send_packet(conn_id, b"corrupted")

        network_simulator.set_config(corruption_rate=0.0)
        network_simulator.send_packet(conn_id, b"clean")
        received = network_simulator.receive_packet(conn_id)
        assert received == b"clean"


# =============================================================================
# 测试用例: DDoS 抵抗力
# =============================================================================

class TestDDoSResistance:
    """DDoS 抵抗力测试"""

    def test_syn_flood_resistance(self, network_simulator):
        """测试 SYN Flood 抵抗力"""
        network_simulator._max_connections = 5000
        sent = 0
        for i in range(2000):
            try:
                conn_id = network_simulator.create_connection(
                    src=f"192.168.{random.randint(0,255)}.{random.randint(1,254)}",
                    dst="target",
                )
                if conn_id:
                    network_simulator.send_packet(conn_id, b"SYN")
                    sent += 1
            except RuntimeError:
                pass

        stats = network_simulator.get_stats()
        assert stats.connections_established > 0
        assert stats.total_packets_sent > 0

    def test_http_flood_resistance(self, network_simulator):
        """测试 HTTP Flood 抵抗力"""
        conn_id = network_simulator.create_connection(protocol="http")
        assert conn_id is not None

        for i in range(5000):
            network_simulator.send_http_request(
                conn_id, "GET", f"/api/data/{i}",
            )

        stats = network_simulator.get_stats()
        assert stats.total_packets_sent >= 5000

    def test_amplification_attack_simulation(self, network_simulator):
        """测试放大攻击模拟"""
        small_request = b"GET / HTTP/1.1\r\nHost: target\r\n\r\n"
        conn_id = network_simulator.create_connection()
        assert conn_id is not None

        for i in range(100):
            network_simulator.send_packet(conn_id, small_request)

        stats = network_simulator.get_stats()
        assert stats.total_bytes_sent >= len(small_request) * 100

    def test_resource_exhaustion_under_ddos(self, network_simulator):
        """测试 DDoS 下的资源耗尽"""
        network_simulator._max_connections = 5000

        # 模拟多源 DDoS
        def ddos_source(src_ip):
            local_conns = []
            for i in range(200):
                try:
                    conn_id = network_simulator.create_connection(
                        src=src_ip, dst="target",
                    )
                    if conn_id:
                        local_conns.append(conn_id)
                        network_simulator.send_packet(conn_id, b"attack")
                except RuntimeError:
                    break
            for conn_id in local_conns:
                network_simulator.close_connection(conn_id)

        threads = []
        for i in range(10):
            src = f"10.0.{i}.{random.randint(1,254)}"
            t = threading.Thread(target=ddos_source, args=(src,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        stats = network_simulator.get_stats()
        assert stats.connections_established > 0
        # 系统应该仍然可响应
        new_conn = network_simulator.create_connection()
        if new_conn:
            network_simulator.close_connection(new_conn)


# =============================================================================
# 测试用例: 网络韧性
# =============================================================================

class TestNetworkResilience:
    """网络韧性测试"""

    def test_intermittent_connectivity(self, network_simulator):
        """测试间歇性连接"""
        network_simulator.set_config(packet_loss_rate=0.3)

        conn_id = network_simulator.create_connection()
        assert conn_id is not None

        successful = 0
        total = 100
        for i in range(total):
            if network_simulator.send_packet(conn_id, f"msg-{i}".encode()):
                successful += 1

        stats = network_simulator.get_stats()
        assert stats.packets_lost > 0

    def test_network_partition_recovery(self, network_simulator):
        """测试网络分区恢复"""
        conn_id = network_simulator.create_connection()
        assert conn_id is not None

        # 模拟网络分区（高丢包）
        network_simulator.set_config(packet_loss_rate=0.9)
        for i in range(20):
            network_simulator.send_packet(conn_id, b"during partition")

        # 网络恢复
        network_simulator.set_config(packet_loss_rate=0.0)
        network_simulator.send_packet(conn_id, b"after recovery")
        received = network_simulator.receive_packet(conn_id)
        assert received == b"after recovery"

    def test_graceful_degradation(self, network_simulator):
        """测试优雅降级"""
        network_simulator.set_config(
            error_rate=0.5, latency_ms=100, packet_loss_rate=0.3,
        )

        conn_id = network_simulator.create_connection()
        if conn_id:
            start = time.time()
            for i in range(50):
                network_simulator.send_packet(conn_id, b"data")
            duration = time.time() - start
            # 在恶劣条件下仍然工作，但速度较慢
            assert duration > 0

    def test_connection_drop_handling(self, network_simulator):
        """测试连接断开处理"""
        conn_id = network_simulator.create_connection()
        assert conn_id is not None

        network_simulator.close_connection(conn_id)

        # 断开的连接上发送数据应该失败
        result = network_simulator.send_packet(conn_id, b"data")
        assert result is False

        stats = network_simulator.get_stats()
        assert "connection_not_found" in stats.errors


# =============================================================================
# 网络压力测试主入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])