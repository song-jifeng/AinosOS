"""
流量分析模块
============

提供全面的网络流量分析功能，包括流量统计、协议分析、流分析和
带宽使用分析等。
"""

import time
import math
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, Counter
from enum import Enum


logger = logging.getLogger(__name__)


class FlowDirection(Enum):
    """流方向"""
    INGRESS = "ingress"
    EGRESS = "egress"
    INTERNAL = "internal"


@dataclass
class FlowStats:
    """流统计"""
    src_ip: str = ""
    dst_ip: str = ""
    src_port: int = 0
    dst_port: int = 0
    protocol: str = ""
    packets: int = 0
    bytes: int = 0
    start_time: float = 0.0
    last_time: float = 0.0
    direction: FlowDirection = FlowDirection.INTERNAL
    avg_packet_size: float = 0.0
    packet_rate: float = 0.0
    byte_rate: float = 0.0
    duration: float = 0.0

    def __post_init__(self) -> None:
        if self.duration > 0:
            self.packet_rate = self.packets / self.duration
            self.byte_rate = self.bytes / self.duration
        if self.packets > 0:
            self.avg_packet_size = self.bytes / self.packets

    @property
    def flow_key(self) -> str:
        return f"{self.src_ip}:{self.src_port}-{self.dst_ip}:{self.dst_port}-{self.protocol}"


@dataclass
class ProtocolDistribution:
    """协议分布"""
    tcp: float = 0.0
    udp: float = 0.0
    icmp: float = 0.0
    dns: float = 0.0
    http: float = 0.0
    https: float = 0.0
    other: float = 0.0
    total_packets: int = 0
    total_bytes: int = 0


@dataclass
class BandwidthUsage:
    """带宽使用"""
    current: float = 0.0
    avg: float = 0.0
    peak: float = 0.0
    min: float = float("inf")
    total: int = 0
    samples: int = 0
    timestamp: float = field(default_factory=time.time)


class TrafficAnalyzer:
    """流量分析器"""

    def __init__(self, window_size: int = 300, top_flows: int = 100,
                 top_talkers: int = 20) -> None:
        self.window_size = window_size
        self.top_flows = top_flows
        self.top_talkers = top_talkers
        self._flows: Dict[str, FlowStats] = {}
        self._byte_counter: int = 0
        self._packet_counter: int = 0
        self._protocol_counter: Counter = Counter()
        self._port_counter: Counter = Counter()
        self._ip_counter: Counter = Counter()
        self._start_time: float = time.time()
        self._bandwidth_samples: List[float] = []
        self._max_flows: int = 10000
        self._stats: Dict[str, Any] = {
            "total_packets": 0,
            "total_bytes": 0,
            "total_flows": 0,
            "analyzed_packets": 0,
        }

    @property
    def total_packets(self) -> int:
        return self._stats["total_packets"]

    @property
    def total_bytes(self) -> int:
        return self._stats["total_bytes"]

    @property
    def total_flows(self) -> int:
        return len(self._flows)

    @property
    def duration(self) -> float:
        return time.time() - self._start_time

    @property
    def avg_throughput(self) -> float:
        if self.duration > 0:
            return self._stats["total_bytes"] / self.duration
        return 0.0

    def analyze_packet(self, src_ip: str = "", dst_ip: str = "",
                       src_port: int = 0, dst_port: int = 0,
                       protocol: str = "", length: int = 0,
                       timestamp: Optional[float] = None) -> None:
        """分析单个数据包

        Args:
            src_ip: 源 IP
            dst_ip: 目标 IP
            src_port: 源端口
            dst_port: 目标端口
            protocol: 协议
            length: 数据包长度
            timestamp: 时间戳
        """
        ts = timestamp or time.time()
        self._stats["total_packets"] += 1
        self._stats["total_bytes"] += length

        # 更新计数器
        self._byte_counter += length
        self._packet_counter += 1
        self._protocol_counter[protocol] += 1
        self._port_counter[dst_port] += 1
        self._ip_counter[src_ip] += 1
        self._ip_counter[dst_ip] += 1

        # 更新流
        flow_key = f"{src_ip}:{src_port}-{dst_ip}:{dst_port}-{protocol}"
        if flow_key not in self._flows:
            if len(self._flows) >= self._max_flows:
                # 移除最旧的流
                oldest = min(self._flows.keys(), key=lambda k: self._flows[k].last_time)
                del self._flows[oldest]
                self._stats["total_flows"] -= 1

            self._flows[flow_key] = FlowStats(
                src_ip=src_ip, dst_ip=dst_ip,
                src_port=src_port, dst_port=dst_port,
                protocol=protocol,
                start_time=ts, last_time=ts,
            )
            self._stats["total_flows"] += 1

        flow = self._flows[flow_key]
        flow.packets += 1
        flow.bytes += length
        flow.last_time = ts
        flow.duration = ts - flow.start_time

        if flow.duration > 0:
            flow.packet_rate = flow.packets / flow.duration
            flow.byte_rate = flow.bytes / flow.duration
        if flow.packets > 0:
            flow.avg_packet_size = flow.bytes / flow.packets

        # 带宽采样
        now = time.time()
        if self._bandwidth_samples and now - self._bandwidth_samples[-1] >= 1.0:
            self._bandwidth_samples.append(self._byte_counter)
            if len(self._bandwidth_samples) > self.window_size:
                self._bandwidth_samples.pop(0)

    def get_protocol_distribution(self) -> ProtocolDistribution:
        """获取协议分布"""
        total = self._stats["total_packets"]
        if total == 0:
            return ProtocolDistribution()

        return ProtocolDistribution(
            tcp=self._protocol_counter.get("TCP", 0) / total,
            udp=self._protocol_counter.get("UDP", 0) / total,
            icmp=self._protocol_counter.get("ICMP", 0) / total,
            http=self._protocol_counter.get("HTTP", 0) / total,
            https=self._protocol_counter.get("HTTPS", 0) / total,
            dns=self._protocol_counter.get("DNS", 0) / total,
            other=(total - sum(self._protocol_counter.values())) / total if total > 0 else 0,
            total_packets=self._stats["total_packets"],
            total_bytes=self._stats["total_bytes"],
        )

    def get_top_flows(self, n: int = 10) -> List[FlowStats]:
        """获取流量最大的流"""
        sorted_flows = sorted(
            self._flows.values(),
            key=lambda f: f.bytes,
            reverse=True,
        )
        return sorted_flows[:n]

    def get_top_talkers(self, n: int = 10) -> List[Tuple[str, int]]:
        """获取通信最多的 IP"""
        return self._ip_counter.most_common(n)

    def get_top_ports(self, n: int = 10) -> List[Tuple[int, int]]:
        """获取最活跃的端口"""
        return self._port_counter.most_common(n)

    def get_bandwidth_usage(self) -> BandwidthUsage:
        """获取带宽使用情况"""
        now = time.time()
        samples = self._bandwidth_samples

        if not samples:
            return BandwidthUsage()

        # 计算当前带宽（最近1秒）
        current = 0.0
        if len(samples) >= 2:
            current = (samples[-1] - samples[-2])

        avg = sum(samples) / len(samples) if samples else 0
        peak = max(samples) if samples else 0
        min_val = min(samples) if samples else 0

        return BandwidthUsage(
            current=current,
            avg=avg,
            peak=peak,
            min=min_val,
            total=self._stats["total_bytes"],
            samples=len(samples),
            timestamp=now,
        )

    def get_flow_summary(self) -> Dict[str, Any]:
        """获取流摘要"""
        if not self._flows:
            return {}

        active_flows = [f for f in self._flows.values() if time.time() - f.last_time < 60]
        total_bytes = sum(f.bytes for f in self._flows.values())
        total_packets = sum(f.packets for f in self._flows.values())

        return {
            "total_flows": len(self._flows),
            "active_flows": len(active_flows),
            "total_bytes": total_bytes,
            "total_packets": total_packets,
            "avg_flow_bytes": total_bytes / len(self._flows) if self._flows else 0,
            "avg_flow_packets": total_packets / len(self._flows) if self._flows else 0,
            "avg_flow_duration": sum(f.duration for f in self._flows.values()) / len(self._flows) if self._flows else 0,
        }

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "duration": self.duration,
            "avg_throughput": self.avg_throughput,
            "active_flows": len(self._flows),
            "protocol_distribution": {
                k: round(v * 100, 1)
                for k, v in self.get_protocol_distribution().__dict__.items()
                if isinstance(v, float)
            },
            "bandwidth": self.get_bandwidth_usage().__dict__,
            "top_talkers": self.get_top_talkers(5),
            "top_ports": self.get_top_ports(5),
        }

    def reset(self) -> None:
        """重置分析器"""
        self._flows.clear()
        self._byte_counter = 0
        self._packet_counter = 0
        self._protocol_counter.clear()
        self._port_counter.clear()
        self._ip_counter.clear()
        self._bandwidth_samples.clear()
        self._start_time = time.time()
        self._stats = {
            "total_packets": 0,
            "total_bytes": 0,
            "total_flows": 0,
            "analyzed_packets": 0,
        }
        logger.info("流量分析器已重置")


class FlowAnalyzer:
    """流分析器"""

    def __init__(self) -> None:
        self._flows: Dict[str, FlowStats] = {}
        self._max_flows: int = 10000
        self._flow_timeout: float = 300.0  # 5分钟无更新视为超时

    def add_flow(self, flow: FlowStats) -> None:
        """添加流"""
        key = flow.flow_key
        self._flows[key] = flow
        if len(self._flows) > self._max_flows:
            self._cleanup()

    def get_flow(self, key: str) -> Optional[FlowStats]:
        return self._flows.get(key)

    def remove_flow(self, key: str) -> bool:
        if key in self._flows:
            del self._flows[key]
            return True
        return False

    def _cleanup(self) -> int:
        """清理超时流"""
        now = time.time()
        expired = [k for k, v in self._flows.items() if now - v.last_time > self._flow_timeout]
        for k in expired:
            del self._flows[k]
        return len(expired)

    def get_active_flows(self) -> List[FlowStats]:
        return [f for f in self._flows.values() if time.time() - f.last_time < 60]

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "total_flows": len(self._flows),
            "active_flows": len(self.get_active_flows()),
            "flow_timeout": self._flow_timeout,
        }


class ProtocolAnalyzer:
    """协议分析器"""

    def __init__(self) -> None:
        self._protocols: Dict[str, int] = Counter()
        self._port_protocols: Dict[int, str] = {
            80: "HTTP", 443: "HTTPS", 53: "DNS", 22: "SSH",
            21: "FTP", 25: "SMTP", 110: "POP3", 143: "IMAP",
            3306: "MySQL", 5432: "PostgreSQL", 6379: "Redis",
            27017: "MongoDB", 8080: "HTTP-Alt",
        }

    def analyze(self, dst_port: int, protocol: str = "") -> str:
        """分析协议类型"""
        self._protocols[protocol] += 1
        if not protocol:
            return self._port_protocols.get(dst_port, "Unknown")
        return protocol

    def get_protocol_mix(self) -> Dict[str, float]:
        """获取协议组成"""
        total = sum(self._protocols.values())
        if total == 0:
            return {}
        return {k: v / total * 100 for k, v in self._protocols.most_common()}

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "protocol_count": len(self._protocols),
            "protocols": dict(self._protocols.most_common(20)),
            "protocol_mix": self.get_protocol_mix(),
        }