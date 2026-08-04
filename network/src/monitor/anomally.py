"""
网络异常检测模块
==============

基于规则和统计的实时网络异常检测，包括流量异常、协议异常、
连接异常和安全事件检测。
"""

import time
import math
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import deque, defaultdict


logger = logging.getLogger(__name__)


class AnomalyType(Enum):
    """异常类型"""
    TRAFFIC_SURGE = "traffic_surge"
    BANDWIDTH_EXHAUSTION = "bandwidth_exhaustion"
    PACKET_LOSS = "packet_loss"
    LATENCY = "latency"
    PORT_SCAN = "port_scan"
    SYN_FLOOD = "syn_flood"
    DNS_AMPLIFICATION = "dns_amplification"
    CONNECTION_EXHAUSTION = "connection_exhaustion"
    PROTOCOL_VIOLATION = "protocol_violation"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    UNKNOWN = "unknown"


@dataclass
class AnomalyReport:
    """异常报告"""
    timestamp: float = field(default_factory=time.time)
    anomaly_type: AnomalyType = AnomalyType.UNKNOWN
    severity: int = 0
    score: float = 0.0
    source: str = ""
    destination: str = ""
    description: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False

    @property
    def severity_label(self) -> str:
        if self.severity >= 8:
            return "critical"
        elif self.severity >= 6:
            return "high"
        elif self.severity >= 4:
            return "medium"
        elif self.severity >= 2:
            return "low"
        return "info"


class AnomalyDetector:
    """异常检测器"""

    def __init__(self) -> None:
        self._packet_rates: deque = deque(maxlen=60)
        self._byte_rates: deque = deque(maxlen=60)
        self._error_rates: deque = deque(maxlen=60)
        self._connection_rates: deque = deque(maxlen=60)
        self._syn_rates: deque = deque(maxlen=60)
        self._latency_samples: deque = deque(maxlen=100)
        self._port_scan_tracker: Dict[str, set] = defaultdict(set)
        self._alert_history: List[AnomalyReport] = []
        self._max_alerts: int = 100
        self._baseline: Dict[str, float] = {}
        self._thresholds: Dict[str, float] = {
            "packet_rate": 10000,
            "byte_rate": 100000000,
            "error_rate": 0.1,
            "connection_rate": 500,
            "syn_rate": 200,
            "latency": 1.0,
            "port_scan_ports": 50,
            "port_scan_window": 10,
        }
        self._alerts: List[AnomalyReport] = []
        self._last_cleanup: float = time.time()

    def update_rates(self, packet_rate: float, byte_rate: float,
                     error_rate: float, connection_rate: float,
                     syn_rate: float) -> None:
        """更新速率指标"""
        self._packet_rates.append(packet_rate)
        self._byte_rates.append(byte_rate)
        self._error_rates.append(error_rate)
        self._connection_rates.append(connection_rate)
        self._syn_rates.append(syn_rate)

        # 更新基线
        self._update_baseline()

    def add_latency_sample(self, latency: float) -> None:
        """添加延迟样本"""
        self._latency_samples.append(latency)

    def record_port_scan(self, src_ip: str, dst_port: int) -> None:
        """记录端口扫描事件"""
        self._port_scan_tracker[src_ip].add(dst_port)

    def _update_baseline(self) -> None:
        """更新基线数据"""
        if self._packet_rates:
            self._baseline["packet_rate"] = sum(self._packet_rates) / len(self._packet_rates)
        if self._byte_rates:
            self._baseline["byte_rate"] = sum(self._byte_rates) / len(self._byte_rates)
        if self._error_rates:
            self._baseline["error_rate"] = sum(self._error_rates) / len(self._error_rates)
        if self._connection_rates:
            self._baseline["connection_rate"] = sum(self._connection_rates) / len(self._connection_rates)
        if self._syn_rates:
            self._baseline["syn_rate"] = sum(self._syn_rates) / len(self._syn_rates)

    def detect(self) -> List[AnomalyReport]:
        """执行检测并返回新发现的异常"""
        alerts = []
        now = time.time()

        # 流量突增检测
        if len(self._packet_rates) >= 10:
            avg = sum(self._packet_rates) / len(self._packet_rates)
            current = self._packet_rates[-1]
            if avg > 0 and current > avg * 5:
                alerts.append(AnomalyReport(
                    anomaly_type=AnomalyType.TRAFFIC_SURGE,
                    severity=7,
                    score=min(1.0, current / (avg * 10)),
                    description=f"流量突增: {current:.0f} pkt/s (基线: {avg:.0f} pkt/s)",
                    details={"current": current, "baseline": avg, "ratio": current / avg},
                ))

        # 连接耗尽检测
        if len(self._connection_rates) >= 10:
            avg = sum(self._connection_rates) / len(self._connection_rates)
            current = self._connection_rates[-1]
            if avg > 0 and current > avg * 10:
                alerts.append(AnomalyReport(
                    anomaly_type=AnomalyType.CONNECTION_EXHAUSTION,
                    severity=8,
                    score=min(1.0, current / (avg * 20)),
                    description=f"连接异常: {current:.0f} conn/s (基线: {avg:.0f} conn/s)",
                    details={"current": current, "baseline": avg},
                ))

        # SYN Flood 检测
        if len(self._syn_rates) >= 5:
            avg = sum(self._syn_rates) / len(self._syn_rates)
            current = self._syn_rates[-1]
            if current > self._thresholds["syn_rate"] and current > avg * 5:
                alerts.append(AnomalyReport(
                    anomaly_type=AnomalyType.SYN_FLOOD,
                    severity=9,
                    score=min(1.0, current / (avg * 10)),
                    description=f"SYN Flood 检测: {current:.0f} syn/s",
                    details={"current": current, "baseline": avg},
                ))

        # 端口扫描检测
        for src_ip, ports in list(self._port_scan_tracker.items()):
            if len(ports) > self._thresholds["port_scan_ports"]:
                alerts.append(AnomalyReport(
                    anomaly_type=AnomalyType.PORT_SCAN,
                    severity=6,
                    score=min(1.0, len(ports) / 100),
                    source=src_ip,
                    description=f"端口扫描检测: {len(ports)} 个端口",
                    details={"src_ip": src_ip, "port_count": len(ports)},
                ))
                # 清理已报告源
                del self._port_scan_tracker[src_ip]

        # 延迟异常检测
        if len(self._latency_samples) >= 10:
            avg = sum(self._latency_samples) / len(self._latency_samples)
            current = self._latency_samples[-1]
            if avg > 0 and current > avg * 3 and current > self._thresholds["latency"]:
                alerts.append(AnomalyReport(
                    anomaly_type=AnomalyType.LATENCY,
                    severity=5,
                    score=min(1.0, current / (avg * 5)),
                    description=f"延迟异常: {current*1000:.0f}ms (基线: {avg*1000:.0f}ms)",
                    details={"current": current, "baseline": avg},
                ))

        # 记录告警
        for alert in alerts:
            self._alerts.append(alert)
            if len(self._alerts) > self._max_alerts:
                self._alerts.pop(0)

        # 定期清理
        if now - self._last_cleanup > 300:
            self._cleanup()
            self._last_cleanup = now

        return alerts

    def _cleanup(self) -> None:
        """清理过期数据"""
        now = time.time()
        # 清理端口扫描跟踪
        for src_ip in list(self._port_scan_tracker.keys()):
            if len(self._port_scan_tracker[src_ip]) > 1000:
                self._port_scan_tracker[src_ip] = set()

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "total_alerts": len(self._alerts),
            "recent_alerts": len([a for a in self._alerts if time.time() - a.timestamp < 300]),
            "baseline": self._baseline,
            "thresholds": self._thresholds,
            "packet_rate_samples": len(self._packet_rates),
            "latency_samples": len(self._latency_samples),
            "port_scan_tracked_ips": len(self._port_scan_tracker),
        }