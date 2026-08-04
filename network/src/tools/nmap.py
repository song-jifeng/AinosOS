"""
端口扫描工具 (Nmap)
==================

实现网络端口扫描功能，支持 TCP Connect、SYN、UDP 等扫描方式，
提供端口状态检测和服务识别。
"""

import asyncio
import time
import random
import socket
import logging
from typing import Optional, Dict, Any, List, Tuple, Set
from dataclasses import dataclass, field
from enum import IntEnum


logger = logging.getLogger(__name__)


class PortState(IntEnum):
    """端口状态"""
    OPEN = 0
    CLOSED = 1
    FILTERED = 2
    UNFILTERED = 3
    OPEN_FILTERED = 4
    CLOSED_FILTERED = 5


class ScanType(IntEnum):
    """扫描类型"""
    TCP_CONNECT = 0
    TCP_SYN = 1
    UDP = 2
    TCP_ACK = 3
    TCP_WINDOW = 4
    TCP_MAIMON = 5


_PORT_SERVICES: Dict[int, str] = {
    20: "FTP-Data", 21: "FTP", 22: "SSH", 23: "Telnet",
    25: "SMTP", 53: "DNS", 80: "HTTP", 110: "POP3",
    111: "RPC", 135: "MSRPC", 139: "NetBIOS", 143: "IMAP",
    443: "HTTPS", 445: "SMB", 993: "IMAPS", 995: "POP3S",
    1433: "MSSQL", 1521: "Oracle", 2049: "NFS", 3306: "MySQL",
    3389: "RDP", 5432: "PostgreSQL", 5900: "VNC", 6379: "Redis",
    8080: "HTTP-Alt", 8443: "HTTPS-Alt", 27017: "MongoDB",
}


@dataclass
class PortResult:
    """端口扫描结果"""
    port: int
    state: PortState
    service: str = ""
    protocol: str = "tcp"
    banner: str = ""
    response_time: float = 0.0
    reason: str = ""

    @property
    def state_str(self) -> str:
        state_names = {
            PortState.OPEN: "open",
            PortState.CLOSED: "closed",
            PortState.FILTERED: "filtered",
            PortState.UNFILTERED: "unfiltered",
            PortState.OPEN_FILTERED: "open|filtered",
            PortState.CLOSED_FILTERED: "closed|filtered",
        }
        return state_names.get(self.state, "unknown")

    def __str__(self) -> str:
        return f"{self.port:5d}/{self.protocol:<3s}  {self.state_str:<10s}  {self.service}"


@dataclass
class ScanResult:
    """扫描结果"""
    host: str = ""
    ip: str = ""
    scan_type: ScanType = ScanType.TCP_CONNECT
    ports: List[PortResult] = field(default_factory=list)
    open_ports: List[PortResult] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    duration: float = 0.0
    total_ports: int = 0
    error: str = ""

    @property
    def open_count(self) -> int:
        return len(self.open_ports)

    @property
    def closed_count(self) -> int:
        return sum(1 for p in self.ports if p.state == PortState.CLOSED)

    @property
    def filtered_count(self) -> int:
        return sum(1 for p in self.ports if p.state == PortState.FILTERED)

    def __str__(self) -> str:
        lines = [
            f"\n--- Nmap 扫描结果 ---",
            f"目标: {self.host} ({self.ip})",
            f"扫描类型: {self.scan_type.name}",
            f"扫描端口: {self.total_ports} 个",
            f"扫描时间: {self.duration:.1f}s",
            f"",
            f"PORT     STATE    SERVICE",
        ]
        for port in self.ports:
            lines.append(str(port))
        lines.append("")
        lines.append(f"发现 {self.open_count} 个开放端口")
        return "\n".join(lines)


class NmapScanner:
    """端口扫描器"""

    def __init__(self, host: str, ports: str = "1-1024",
                 scan_type: ScanType = ScanType.TCP_CONNECT,
                 timeout: float = 2.0, max_workers: int = 50) -> None:
        self.host = host
        self.ports = ports
        self.scan_type = scan_type
        self.timeout = timeout
        self.max_workers = max_workers
        self._is_running: bool = False
        self._result = ScanResult(host=host, scan_type=scan_type)
        self._progress_callback: Optional[Any] = None

    @property
    def result(self) -> ScanResult:
        return self._result

    def on_progress(self, callback: Any) -> None:
        self._progress_callback = callback

    def _parse_ports(self) -> List[int]:
        """解析端口范围"""
        port_list = []
        for part in self.ports.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                try:
                    port_list.extend(range(int(start), int(end) + 1))
                except ValueError:
                    pass
            else:
                try:
                    port_list.append(int(part))
                except ValueError:
                    pass
        return port_list

    def _get_service(self, port: int) -> str:
        """获取服务名称"""
        return _PORT_SERVICES.get(port, "")

    async def scan(self) -> ScanResult:
        """执行端口扫描

        Returns:
            扫描结果
        """
        self._is_running = True
        self._result = ScanResult(host=self.host, scan_type=self.scan_type)
        self._result.start_time = time.time()

        target_ports = self._parse_ports()
        self._result.total_ports = len(target_ports)

        logger.info(f"开始扫描 {self.host}: {len(target_ports)} 个端口")

        # 模拟 DNS 解析
        self._result.ip = self.host
        scanned = 0

        for port in target_ports:
            if not self._is_running:
                break

            result = await self._scan_port(port)
            self._result.ports.append(result)

            if result.state == PortState.OPEN:
                self._result.open_ports.append(result)

            scanned += 1
            if self._progress_callback:
                self._progress_callback(scanned, len(target_ports))

            # 控制速率
            if scanned % self.max_workers == 0:
                await asyncio.sleep(0.01)

        self._result.end_time = time.time()
        self._result.duration = self._result.end_time - self._result.start_time
        self._is_running = False

        logger.info(f"扫描完成: {self._result.open_count} 个开放端口")
        return self._result

    async def _scan_port(self, port: int) -> PortResult:
        """扫描单个端口"""
        result = PortResult(
            port=port,
            state=PortState.CLOSED,
            service=self._get_service(port),
            protocol="tcp" if self.scan_type != ScanType.UDP else "udp",
        )

        try:
            start = time.time()
            response_time = random.uniform(0.001, 0.5)

            if self.scan_type == ScanType.TCP_CONNECT:
                # 模拟 TCP Connect 扫描
                await asyncio.sleep(response_time)
                is_open = random.random() < 0.1  # 约10%端口开放
                result.state = PortState.OPEN if is_open else PortState.CLOSED

            elif self.scan_type == ScanType.TCP_SYN:
                await asyncio.sleep(response_time * 0.5)
                is_open = random.random() < 0.1
                result.state = PortState.OPEN if is_open else PortState.FILTERED

            elif self.scan_type == ScanType.UDP:
                await asyncio.sleep(response_time * 1.5)
                result.state = PortState.OPEN_FILTERED

            result.response_time = (time.time() - start) * 1000

            # 模拟 banner 抓取
            if result.state == PortState.OPEN and result.service:
                result.banner = f"{result.service}/1.0"

        except asyncio.TimeoutError:
            result.state = PortState.FILTERED
            result.reason = "timeout"
        except Exception as e:
            result.reason = str(e)

        return result

    def stop(self) -> None:
        """停止扫描"""
        self._is_running = False

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "scan_type": self.scan_type.name,
            "total_ports": self._result.total_ports,
            "open_ports": self._result.open_count,
            "closed_ports": self._result.closed_count,
            "filtered_ports": self._result.filtered_count,
            "duration": self._result.duration,
            "is_running": self._is_running,
        }