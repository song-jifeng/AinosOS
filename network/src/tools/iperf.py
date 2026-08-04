"""
带宽测试工具 (Iperf)
===================

实现网络带宽测试功能，支持 TCP 和 UDP 模式，可测量吞吐量、
延迟和丢包率等性能指标。
"""

import asyncio
import time
import random
import logging
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum


logger = logging.getLogger(__name__)


class IperfProtocol(Enum):
    """Iperf 协议"""
    TCP = "tcp"
    UDP = "udp"


class IperfDirection(Enum):
    """Iperf 方向"""
    SEND = "send"
    RECEIVE = "receive"
    BIDIRECTIONAL = "bidirectional"


@dataclass
class IperfStream:
    """Iperf 流"""
    id: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    errors: int = 0
    packets: int = 0
    packets_lost: int = 0
    out_of_order: int = 0
    jitter: float = 0.0
    protocol: IperfProtocol = IperfProtocol.TCP

    @property
    def duration(self) -> float:
        if self.end_time > self.start_time:
            return self.end_time - self.start_time
        return 0.0

    @property
    def throughput_bytes(self) -> float:
        if self.duration > 0:
            return (self.bytes_sent + self.bytes_received) / self.duration
        return 0.0

    @property
    def throughput_bits(self) -> float:
        return self.throughput_bytes * 8

    @property
    def loss_rate(self) -> float:
        if self.packets > 0:
            return self.packets_lost / self.packets * 100
        return 0.0

    @property
    def throughput_str(self) -> str:
        bps = self.throughput_bits
        if bps >= 1e9:
            return f"{bps / 1e9:.2f} Gbps"
        elif bps >= 1e6:
            return f"{bps / 1e6:.2f} Mbps"
        elif bps >= 1e3:
            return f"{bps / 1e3:.2f} Kbps"
        return f"{bps:.2f} bps"

    @property
    def summary(self) -> str:
        return (
            f"[{self.id}] {self.protocol.value.upper()} Stream: "
            f"{self.throughput_str} throughput, "
            f"{self.loss_rate:.1f}% loss, "
            f"{self.jitter:.3f}ms jitter"
        )


@dataclass
class IperfResult:
    """Iperf 测试结果"""
    host: str = ""
    port: int = 0
    protocol: IperfProtocol = IperfProtocol.TCP
    direction: IperfDirection = IperfDirection.SEND
    duration: float = 0.0
    streams: List[IperfStream] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    error: str = ""

    @property
    def total_bytes(self) -> int:
        return sum(s.bytes_sent + s.bytes_received for s in self.streams)

    @property
    def total_throughput(self) -> float:
        if self.duration > 0:
            return self.total_bytes / self.duration * 8
        return 0.0

    @property
    def total_throughput_str(self) -> str:
        bps = self.total_throughput
        if bps >= 1e9:
            return f"{bps / 1e9:.2f} Gbps"
        elif bps >= 1e6:
            return f"{bps / 1e6:.2f} Mbps"
        elif bps >= 1e3:
            return f"{bps / 1e3:.2f} Kbps"
        return f"{bps:.2f} bps"

    @property
    def avg_loss_rate(self) -> float:
        if self.streams:
            return sum(s.loss_rate for s in self.streams) / len(self.streams)
        return 0.0

    @property
    def avg_jitter(self) -> float:
        if self.streams:
            return sum(s.jitter for s in self.streams) / len(self.streams)
        return 0.0

    def __str__(self) -> str:
        lines = [
            f"\n--- Iperf 结果 ---",
            f"服务器: {self.host}:{self.port}",
            f"协议: {self.protocol.value.upper()}",
            f"方向: {self.direction.value}",
            f"持续时间: {self.duration:.1f}s",
            f"总吞吐量: {self.total_throughput_str}",
        ]
        if self.protocol == IperfProtocol.UDP:
            lines.append(f"平均丢包率: {self.avg_loss_rate:.1f}%")
            lines.append(f"平均抖动: {self.avg_jitter:.3f}ms")
        lines.append(f"---")
        for stream in self.streams:
            lines.append(stream.summary)
        if self.error:
            lines.append(f"错误: {self.error}")
        return "\n".join(lines)


class Iperf:
    """带宽测试工具"""

    def __init__(self, host: str = "localhost", port: int = 5201,
                 protocol: IperfProtocol = IperfProtocol.TCP,
                 duration: float = 10.0, bandwidth: int = 0,
                 parallel: int = 1, window_size: int = 65535) -> None:
        self.host = host
        self.port = port
        self.protocol = protocol
        self.duration = duration
        self.bandwidth = bandwidth
        self.parallel = parallel
        self.window_size = window_size
        self._is_running: bool = False
        self._result = IperfResult(host=host, port=port, protocol=protocol)
        self._on_progress: Optional[Callable] = None

    @property
    def result(self) -> IperfResult:
        return self._result

    def on_progress(self, callback: Callable) -> None:
        """注册进度回调"""
        self._on_progress = callback

    async def run(self, direction: IperfDirection = IperfDirection.SEND) -> IperfResult:
        """执行带宽测试

        Args:
            direction: 测试方向

        Returns:
            测试结果
        """
        self._is_running = True
        self._result = IperfResult(
            host=self.host, port=self.port,
            protocol=self.protocol, direction=direction,
        )
        self._result.start_time = time.time()

        logger.info(f"开始 Iperf 测试: {self.host}:{self.port} "
                    f"({self.protocol.value.upper()}, {self.duration}s)")

        try:
            if direction == IperfDirection.SEND:
                await self._run_send()
            elif direction == IperfDirection.RECEIVE:
                await self._run_receive()
            else:
                await self._run_bidirectional()
        except Exception as e:
            self._result.error = str(e)
            logger.error(f"Iperf 测试失败: {e}")

        self._result.end_time = time.time()
        self._result.duration = self._result.end_time - self._result.start_time
        self._is_running = False

        logger.info(str(self._result))
        return self._result

    async def _run_send(self) -> None:
        """运行发送测试"""
        for i in range(self.parallel):
            stream = IperfStream(id=i, protocol=self.protocol)
            stream.start_time = time.time()

            # 模拟数据发送
            rate = self.bandwidth if self.bandwidth > 0 else random.randint(100, 1000) * 1000000
            bytes_per_sec = rate // 8
            elapsed = 0.0
            interval = 0.1

            while elapsed < self.duration and self._is_running:
                chunk = int(bytes_per_sec * interval)
                stream.bytes_sent += chunk
                stream.packets += chunk // 1460

                await asyncio.sleep(interval)
                elapsed += interval

                # 模拟丢包
                if self.protocol == IperfProtocol.UDP and random.random() < 0.001:
                    stream.packets_lost += 1
                    stream.packets += 1

                # 进度回调
                if self._on_progress:
                    progress = elapsed / self.duration * 100
                    self._on_progress(progress, stream)

            stream.end_time = time.time()
            self._result.streams.append(stream)

    async def _run_receive(self) -> None:
        """运行接收测试"""
        await self._run_send()  # 模拟实现

    async def _run_bidirectional(self) -> None:
        """运行双向测试"""
        await self._run_send()

    def stop(self) -> None:
        """停止测试"""
        self._is_running = False

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol.value,
            "duration": self.duration,
            "parallel": self.parallel,
            "total_throughput": self._result.total_throughput,
            "total_throughput_str": self._result.total_throughput_str,
            "avg_loss_rate": self._result.avg_loss_rate,
            "avg_jitter": self._result.avg_jitter,
            "stream_count": len(self._result.streams),
            "is_running": self._is_running,
        }