"""
UDP 协议实现
============

提供 UDP 数据报的收发、多播支持和数据报重组等功能。
"""

import asyncio
import struct
import socket
import time
import random
import logging
from typing import Optional, Dict, Any, List, Tuple, Callable, Set
from dataclasses import dataclass, field
from enum import IntEnum


logger = logging.getLogger(__name__)


class UDPError(Exception):
    """UDP 协议错误"""
    pass


class UDPBufferFull(UDPError):
    """UDP 缓冲区满"""
    pass


class UDPPortUnavailable(UDPError):
    """UDP 端口不可用"""
    pass


@dataclass
class UDPDatagram:
    """UDP 数据报"""
    src_port: int
    dst_port: int
    length: int
    checksum: int = 0
    payload: bytes = b""
    src_ip: str = ""
    dst_ip: str = ""
    timestamp: float = field(default_factory=time.time)
    ttl: int = 64
    interface: str = ""

    def __post_init__(self) -> None:
        self.length = 8 + len(self.payload)

    def encode(self) -> bytes:
        """编码为字节"""
        header = struct.pack("!HHHH", self.src_port, self.dst_port, self.length, self.checksum)
        return header + self.payload

    @classmethod
    def decode(cls, data: bytes) -> "UDPDatagram":
        """从字节解码"""
        if len(data) < 8:
            raise ValueError(f"UDP 数据报太短: {len(data)} 字节")

        src_port, dst_port, length, checksum = struct.unpack("!HHHH", data[0:8])
        payload = data[8:length] if length > 8 else b""

        return cls(
            src_port=src_port,
            dst_port=dst_port,
            length=length,
            checksum=checksum,
            payload=payload,
        )


@dataclass
class UDPSocket:
    """UDP 套接字"""
    local_addr: Tuple[str, int]
    multicast_group: Optional[str] = None
    broadcast: bool = False
    reuse_addr: bool = True
    buffer_size: int = 65536
    timeout: float = 0.0
    ttl: int = 64
    connected: bool = False
    remote_addr: Optional[Tuple[str, int]] = None
    created_at: float = field(default_factory=time.time)
    bytes_sent: int = 0
    bytes_received: int = 0
    datagrams_sent: int = 0
    datagrams_received: int = 0
    is_closed: bool = False

    @property
    def duration(self) -> float:
        """套接字持续时间"""
        if self.is_closed:
            return 0
        return time.time() - self.created_at

    @property
    def throughput(self) -> float:
        """吞吐量"""
        if self.duration > 0:
            return (self.bytes_sent + self.bytes_received) / self.duration
        return 0.0


class UDPProtocol:
    """UDP 协议实现"""

    def __init__(self) -> None:
        self._sockets: Dict[int, UDPSocket] = {}
        self._recv_callbacks: Dict[int, Callable] = {}
        self._error_callbacks: Dict[int, Callable] = {}
        self._multicast_groups: Dict[str, Set[int]] = {}
        self._datagram_queue: Dict[int, asyncio.Queue] = {}
        self._max_datagram_size: int = 65507
        self._is_running: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def active_sockets(self) -> int:
        return len([s for s in self._sockets.values() if not s.is_closed])

    @property
    def total_datagrams_sent(self) -> int:
        return sum(s.datagrams_sent for s in self._sockets.values())

    @property
    def total_datagrams_received(self) -> int:
        return sum(s.datagrams_received for s in self._sockets.values())

    @property
    def total_bytes_sent(self) -> int:
        return sum(s.bytes_sent for s in self._sockets.values())

    @property
    def total_bytes_received(self) -> int:
        return sum(s.bytes_received for s in self._sockets.values())

    async def start(self) -> None:
        """启动 UDP 协议处理器"""
        self._is_running = True
        self._loop = asyncio.get_event_loop()
        logger.info("UDP 协议处理器已启动")

    async def stop(self) -> None:
        """停止 UDP 协议处理器"""
        self._is_running = False
        for port in list(self._sockets.keys()):
            await self.close(port)
        logger.info("UDP 协议处理器已停止")

    def create_socket(self, port: int = 0, host: str = "0.0.0.0") -> UDPSocket:
        """创建 UDP 套接字

        Args:
            port: 绑定端口，0 表示自动分配
            host: 绑定地址

        Returns:
            UDP 套接字对象

        Raises:
            UDPPortUnavailable: 端口已被占用
        """
        if port > 0 and port in self._sockets:
            raise UDPPortUnavailable(f"端口 {port} 已被占用")

        if port == 0:
            port = self._find_available_port()

        sock = UDPSocket(local_addr=(host, port))
        self._sockets[port] = sock
        self._datagram_queue[port] = asyncio.Queue(maxsize=10000)

        logger.info(f"创建 UDP 套接字: {host}:{port}")
        return sock

    async def close(self, port: int) -> bool:
        """关闭 UDP 套接字

        Args:
            port: 端口号

        Returns:
            是否成功关闭
        """
        sock = self._sockets.get(port)
        if not sock:
            return False

        sock.is_closed = True
        self._sockets.pop(port, None)
        self._recv_callbacks.pop(port, None)
        self._error_callbacks.pop(port, None)
        self._datagram_queue.pop(port, None)

        # 离开多播组
        for group, ports in list(self._multicast_groups.items()):
            ports.discard(port)
            if not ports:
                del self._multicast_groups[group]

        logger.info(f"UDP 套接字已关闭: {sock.local_addr[0]}:{port}")
        return True

    async def sendto(self, data: bytes, dst_addr: Tuple[str, int],
                     src_port: int = 0) -> int:
        """发送数据报到指定地址

        Args:
            data: 要发送的数据
            dst_addr: 目标地址 (host, port)
            src_port: 源端口，0 表示自动分配

        Returns:
            发送的字节数

        Raises:
            UDPError: 发送失败
            ValueError: 数据报太大
        """
        if len(data) > self._max_datagram_size:
            raise ValueError(f"数据报太大: {len(data)} > {self._max_datagram_size}")

        # 获取或创建套接字
        if src_port == 0:
            src_port = self._find_available_port()
            self.create_socket(src_port)

        sock = self._sockets.get(src_port)
        if not sock or sock.is_closed:
            raise UDPError(f"套接字未打开: 端口 {src_port}")

        datagram = UDPDatagram(
            src_port=src_port,
            dst_port=dst_addr[1],
            payload=data,
            src_ip=sock.local_addr[0],
            dst_ip=dst_addr[0],
        )

        # 更新统计
        sock.bytes_sent += len(data)
        sock.datagrams_sent += 1

        logger.debug(f"UDP 发送: {datagram.src_ip}:{src_port} -> {datagram.dst_ip}:{datagram.dst_port} "
                     f"({len(data)} 字节)")
        return len(data)

    async def send(self, data: bytes, port: int) -> int:
        """通过已连接的套接字发送数据

        Args:
            data: 要发送的数据
            port: 本地端口

        Returns:
            发送的字节数
        """
        sock = self._sockets.get(port)
        if not sock or not sock.connected:
            raise UDPError("套接字未连接")

        if sock.remote_addr:
            return await self.sendto(data, sock.remote_addr, port)
        raise UDPError("未设置远程地址")

    async def recvfrom(self, port: int, timeout: Optional[float] = None) -> Tuple[bytes, Tuple[str, int]]:
        """从指定端口接收数据

        Args:
            port: 端口号
            timeout: 超时时间（秒），None 表示无限等待

        Returns:
            (数据, (源地址, 源端口)) 元组

        Raises:
            UDPError: 接收失败
            asyncio.TimeoutError: 超时
        """
        sock = self._sockets.get(port)
        if not sock or sock.is_closed:
            raise UDPError(f"套接字未打开: 端口 {port}")

        queue = self._datagram_queue.get(port)
        if not queue:
            raise UDPError(f"接收队列未初始化: 端口 {port}")

        try:
            if timeout is not None:
                datagram = await asyncio.wait_for(queue.get(), timeout=timeout)
            else:
                datagram = await queue.get()

            sock.datagrams_received += 1
            sock.bytes_received += len(datagram.payload)

            return datagram.payload, (datagram.src_ip, datagram.src_port)

        except asyncio.TimeoutError:
            raise

    async def recv(self, port: int, timeout: Optional[float] = None) -> bytes:
        """从已连接的套接字接收数据

        Args:
            port: 端口号
            timeout: 超时时间

        Returns:
            接收到的数据
        """
        data, addr = await self.recvfrom(port, timeout)
        return data

    def on_recv(self, port: int, callback: Callable[[bytes, Tuple[str, int]], None]) -> None:
        """注册接收回调

        Args:
            port: 端口号
            callback: 回调函数 (data, addr) -> None
        """
        self._recv_callbacks[port] = callback

    def on_error(self, port: int, callback: Callable[[Exception], None]) -> None:
        """注册错误回调

        Args:
            port: 端口号
            callback: 回调函数 (error) -> None
        """
        self._error_callbacks[port] = callback

    def connect(self, port: int, remote_addr: Tuple[str, int]) -> None:
        """连接 UDP 套接字到远程地址

        Args:
            port: 本地端口
            remote_addr: 远程地址 (host, port)
        """
        sock = self._sockets.get(port)
        if not sock:
            raise UDPError(f"套接字未打开: 端口 {port}")

        sock.connected = True
        sock.remote_addr = remote_addr
        logger.info(f"UDP 套接字 {port} 已连接到 {remote_addr[0]}:{remote_addr[1]}")

    def disconnect(self, port: int) -> None:
        """断开 UDP 套接字连接

        Args:
            port: 端口号
        """
        sock = self._sockets.get(port)
        if sock:
            sock.connected = False
            sock.remote_addr = None

    async def join_multicast_group(self, port: int, group: str, interface: str = "0.0.0.0") -> bool:
        """加入多播组

        Args:
            port: 端口号
            group: 多播组地址
            interface: 接口地址

        Returns:
            是否成功加入
        """
        sock = self._sockets.get(port)
        if not sock:
            raise UDPError(f"套接字未打开: 端口 {port}")

        if group not in self._multicast_groups:
            self._multicast_groups[group] = set()
        self._multicast_groups[group].add(port)
        sock.multicast_group = group

        logger.info(f"UDP 套接字 {port} 已加入多播组 {group}")
        return True

    async def leave_multicast_group(self, port: int, group: str) -> bool:
        """离开多播组

        Args:
            port: 端口号
            group: 多播组地址

        Returns:
            是否成功离开
        """
        if group in self._multicast_groups:
            self._multicast_groups[group].discard(port)
            if not self._multicast_groups[group]:
                del self._multicast_groups[group]
            logger.info(f"UDP 套接字 {port} 已离开多播组 {group}")
            return True
        return False

    def set_broadcast(self, port: int, enabled: bool = True) -> None:
        """设置广播选项

        Args:
            port: 端口号
            enabled: 是否启用广播
        """
        sock = self._sockets.get(port)
        if sock:
            sock.broadcast = enabled

    def set_ttl(self, port: int, ttl: int) -> None:
        """设置 TTL

        Args:
            port: 端口号
            ttl: TTL 值
        """
        if not (0 < ttl <= 255):
            raise ValueError(f"TTL 值无效: {ttl}")

        sock = self._sockets.get(port)
        if sock:
            sock.ttl = ttl

    def process_datagram(self, datagram: UDPDatagram) -> None:
        """处理接收到的 UDP 数据报

        Args:
            datagram: UDP 数据报
        """
        port = datagram.dst_port
        sock = self._sockets.get(port)

        if not sock or sock.is_closed:
            logger.debug(f"丢弃 UDP 数据报: 端口 {port} 未监听")
            return

        # 验证连接状态
        if sock.connected and sock.remote_addr:
            if (datagram.src_ip, datagram.src_port) != sock.remote_addr:
                logger.debug(f"丢弃 UDP 数据报: 来源不匹配")
                return

        # 入队
        queue = self._datagram_queue.get(port)
        if queue:
            try:
                queue.put_nowait(datagram)
            except asyncio.QueueFull:
                logger.warning(f"UDP 接收队列已满，丢弃数据报 (端口 {port})")

        # 回调通知
        callback = self._recv_callbacks.get(port)
        if callback:
            try:
                callback(datagram.payload, (datagram.src_ip, datagram.src_port))
            except Exception as e:
                logger.error(f"UDP 接收回调执行出错: {e}")

    def _find_available_port(self) -> int:
        """查找可用端口"""
        for port in range(49152, 65535):
            if port not in self._sockets:
                return port
        raise UDPError("无可用端口")

    def get_socket_info(self, port: int) -> Optional[Dict[str, Any]]:
        """获取套接字信息

        Args:
            port: 端口号

        Returns:
            套接字信息字典
        """
        sock = self._sockets.get(port)
        if not sock:
            return None

        return {
            "local_addr": f"{sock.local_addr[0]}:{sock.local_addr[1]}",
            "remote_addr": f"{sock.remote_addr[0]}:{sock.remote_addr[1]}" if sock.remote_addr else None,
            "connected": sock.connected,
            "broadcast": sock.broadcast,
            "multicast_group": sock.multicast_group,
            "ttl": sock.ttl,
            "buffer_size": sock.buffer_size,
            "timeout": sock.timeout,
            "duration": sock.duration,
            "bytes_sent": sock.bytes_sent,
            "bytes_received": sock.bytes_received,
            "datagrams_sent": sock.datagrams_sent,
            "datagrams_received": sock.datagrams_received,
            "throughput": sock.throughput,
            "is_closed": sock.is_closed,
        }

    def get_statistics(self) -> Dict[str, Any]:
        """获取 UDP 协议统计信息"""
        return {
            "active_sockets": self.active_sockets,
            "total_datagrams_sent": self.total_datagrams_sent,
            "total_datagrams_received": self.total_datagrams_received,
            "total_bytes_sent": self.total_bytes_sent,
            "total_bytes_received": self.total_bytes_received,
            "multicast_groups": {g: list(ports) for g, ports in self._multicast_groups.items()},
            "max_datagram_size": self._max_datagram_size,
            "is_running": self._is_running,
        }