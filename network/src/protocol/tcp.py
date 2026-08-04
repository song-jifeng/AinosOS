"""
TCP 协议实现
============

完整的 TCP 协议实现，包括连接管理、拥塞控制、重传机制和状态机。
"""

import asyncio
import struct
import time
import random
import logging
from enum import IntEnum, auto
from typing import Optional, Dict, Any, Callable, List, Tuple, Set
from dataclasses import dataclass, field
from collections import deque
from src.utils.checksum import InternetChecksum


logger = logging.getLogger(__name__)


class TCPState(IntEnum):
    """TCP 连接状态"""
    CLOSED = 0
    LISTEN = 1
    SYN_SENT = 2
    SYN_RECEIVED = 3
    ESTABLISHED = 4
    FIN_WAIT_1 = 5
    FIN_WAIT_2 = 6
    CLOSE_WAIT = 7
    CLOSING = 8
    LAST_ACK = 9
    TIME_WAIT = 10


class TCPFlag(IntEnum):
    """TCP 标志位"""
    FIN = 0x01
    SYN = 0x02
    RST = 0x04
    PSH = 0x08
    ACK = 0x10
    URG = 0x20
    ECE = 0x40
    CWR = 0x80


class CongestionState(IntEnum):
    """拥塞控制状态"""
    SLOW_START = 0
    CONGESTION_AVOIDANCE = 1
    FAST_RECOVERY = 2


class TCPOption(IntEnum):
    """TCP 选项类型"""
    END = 0
    NOP = 1
    MSS = 2
    WINDOW_SCALE = 3
    SACK_PERMITTED = 4
    SACK = 5
    TIMESTAMP = 8
    FAST_OPEN = 34


@dataclass
class TCPPacket:
    """TCP 数据包"""
    src_port: int
    dst_port: int
    sequence_number: int
    acknowledgment_number: int
    data_offset: int = 5
    flags: int = 0
    window_size: int = 65535
    checksum: int = 0
    urgent_pointer: int = 0
    options: bytes = b""
    payload: bytes = b""
    timestamp: float = 0.0
    retransmitted: bool = False
    rtt: Optional[float] = None

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def header_length(self) -> int:
        """获取头部长度（字节）"""
        return self.data_offset * 4

    @property
    def is_syn(self) -> bool:
        return bool(self.flags & TCPFlag.SYN)

    @property
    def is_ack(self) -> bool:
        return bool(self.flags & TCPFlag.ACK)

    @property
    def is_fin(self) -> bool:
        return bool(self.flags & TCPFlag.FIN)

    @property
    def is_rst(self) -> bool:
        return bool(self.flags & TCPFlag.RST)

    @property
    def is_psh(self) -> bool:
        return bool(self.flags & TCPFlag.PSH)

    @property
    def is_urg(self) -> bool:
        return bool(self.flags & TCPFlag.URG)

    def encode(self) -> bytes:
        """编码为字节"""
        data_offset_byte = (self.data_offset << 4) | 0
        header = struct.pack(
            "!HHIIBBHHH",
            self.src_port,
            self.dst_port,
            self.sequence_number,
            self.acknowledgment_number,
            data_offset_byte,
            self.flags,
            self.window_size,
            self.checksum,
            self.urgent_pointer,
        )
        header += self.options
        # 填充到 4 字节对齐
        while len(header) < self.header_length:
            header += b"\x00"
        return header + self.payload

    @classmethod
    def decode(cls, data: bytes) -> "TCPPacket":
        """从字节解码"""
        if len(data) < 20:
            raise ValueError(f"TCP 数据包太短: {len(data)} 字节")

        src_port, dst_port = struct.unpack("!HH", data[0:4])
        seq_num, ack_num = struct.unpack("!II", data[4:12])
        data_offset_byte, flags = struct.unpack("!BB", data[12:14])
        data_offset = (data_offset_byte >> 4) & 0x0F
        window_size = struct.unpack("!H", data[14:16])[0]
        checksum = struct.unpack("!H", data[16:18])[0]
        urgent_pointer = struct.unpack("!H", data[18:20])[0]

        header_length = data_offset * 4
        options = data[20:header_length] if header_length > 20 else b""
        payload = data[header_length:] if len(data) > header_length else b""

        return cls(
            src_port=src_port,
            dst_port=dst_port,
            sequence_number=seq_num,
            acknowledgment_number=ack_num,
            data_offset=data_offset,
            flags=flags,
            window_size=window_size,
            checksum=checksum,
            urgent_pointer=urgent_pointer,
            options=options,
            payload=payload,
        )


@dataclass
class TCPConnection:
    """TCP 连接"""
    local_addr: Tuple[str, int]
    remote_addr: Tuple[str, int]
    state: TCPState = TCPState.CLOSED
    send_unacked: int = 0
    send_next: int = 0
    send_window: int = 65535
    send_wl1: int = 0
    send_wl2: int = 0
    iss: int = 0
    rcv_next: int = 0
    rcv_window: int = 65535
    rcv_wl1: int = 0
    rcv_wl2: int = 0
    irs: int = 0
    mss: int = 1460
    snd_cwnd: int = 1
    snd_ssthresh: int = 65535
    rtt_estimate: float = 0.0
    rtt_dev: float = 0.0
    rto: float = 1.0
    srtt: float = 0.0
    rttvar: float = 0.75
    congestion_state: CongestionState = CongestionState.SLOW_START
    duplicate_acks: int = 0
    retransmit_queue: deque = field(default_factory=deque)
    out_of_order_queue: Dict[int, TCPPacket] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    bytes_sent: int = 0
    bytes_received: int = 0
    packets_sent: int = 0
    packets_received: int = 0
    retransmissions: int = 0
    connection_id: str = ""

    def __post_init__(self) -> None:
        self.connection_id = f"{self.local_addr[0]}:{self.local_addr[1]}-{self.remote_addr[0]}:{self.remote_addr[1]}"

    @property
    def is_established(self) -> bool:
        return self.state == TCPState.ESTABLISHED

    @property
    def is_closing(self) -> bool:
        return self.state in (TCPState.FIN_WAIT_1, TCPState.FIN_WAIT_2,
                              TCPState.CLOSE_WAIT, TCPState.CLOSING,
                              TCPState.LAST_ACK, TCPState.TIME_WAIT)

    @property
    def is_closed(self) -> bool:
        return self.state == TCPState.CLOSED

    @property
    def duration(self) -> float:
        """连接持续时间（秒）"""
        return time.time() - self.created_at

    @property
    def throughput(self) -> float:
        """吞吐量 (bytes/sec)"""
        if self.duration > 0:
            return (self.bytes_sent + self.bytes_received) / self.duration
        return 0.0

    @property
    def loss_rate(self) -> float:
        """丢包率"""
        total = self.packets_sent
        if total > 0:
            return self.retransmissions / total
        return 0.0


class CongestionControl:
    """TCP 拥塞控制算法实现"""

    def __init__(self, connection: TCPConnection) -> None:
        self.conn = connection
        self._initial_ssthresh = 65535
        self._min_cwnd = 1
        self._max_cwnd = 65535 * 2
        self._beta = 0.5  # 乘法减小因子
        self._alpha = 0.125  # AIMD 增长因子

    def on_packet_loss(self) -> None:
        """处理丢包事件"""
        self.conn.retransmissions += 1
        self.conn.snd_ssthresh = max(
            int(self.conn.snd_cwnd * self._beta),
            self._min_cwnd * 2
        )
        self.conn.snd_cwnd = self._min_cwnd
        self.conn.congestion_state = CongestionState.SLOW_START
        self.conn.duplicate_acks = 0

    def on_duplicate_ack(self, count: int = 3) -> None:
        """处理重复 ACK（快速重传）"""
        if count >= 3:
            if self.conn.congestion_state != CongestionState.FAST_RECOVERY:
                self.conn.snd_ssthresh = max(
                    int(self.conn.snd_cwnd * self._beta),
                    self._min_cwnd * 2
                )
                self.conn.snd_cwnd = self.conn.snd_ssthresh + 3
                self.conn.congestion_state = CongestionState.FAST_RECOVERY
            else:
                self.conn.snd_cwnd += 1

    def on_new_ack(self, acked_bytes: int = 1) -> None:
        """处理新 ACK"""
        if self.conn.congestion_state == CongestionState.SLOW_START:
            self.conn.snd_cwnd += min(acked_bytes, self.conn.mss)
            if self.conn.snd_cwnd >= self.conn.snd_ssthresh:
                self.conn.congestion_state = CongestionState.CONGESTION_AVOIDANCE

        elif self.conn.congestion_state == CongestionState.CONGESTION_AVOIDANCE:
            self.conn.snd_cwnd += (self.conn.mss * self.conn.mss) // (2 * self.conn.snd_cwnd)

        elif self.conn.congestion_state == CongestionState.FAST_RECOVERY:
            self.conn.snd_cwnd = self.conn.snd_ssthresh
            self.conn.congestion_state = CongestionState.CONGESTION_AVOIDANCE
            self.conn.duplicate_acks = 0

        self.conn.snd_cwnd = min(self.conn.snd_cwnd, self._max_cwnd)

    def on_timeout(self) -> None:
        """处理超时（RTO 到期）"""
        self.conn.snd_ssthresh = max(
            int(self.conn.snd_cwnd * self._beta),
            self._min_cwnd * 2
        )
        self.conn.snd_cwnd = self._min_cwnd
        self.conn.congestion_state = CongestionState.SLOW_START
        self.conn.duplicate_acks = 0

        # RTO 指数退避
        self.conn.rto = min(self.conn.rto * 2, 120.0)

    def update_rtt(self, measured_rtt: float) -> None:
        """更新 RTT 估计

        Args:
            measured_rtt: 测量的 RTT 值（秒）
        """
        if measured_rtt <= 0:
            return

        if self.conn.srtt == 0:
            self.conn.srtt = measured_rtt
            self.conn.rttvar = measured_rtt / 2
        else:
            alpha = 0.125
            beta = 0.25
            self.conn.rttvar = (1 - beta) * self.conn.rttvar + beta * abs(self.conn.srtt - measured_rtt)
            self.conn.srtt = (1 - alpha) * self.conn.srtt + alpha * measured_rtt

        self.conn.rto = min(max(self.conn.srtt + 4 * self.conn.rttvar, 0.2), 120.0)
        self.conn.rtt_estimate = self.conn.srtt
        self.conn.rtt_dev = self.conn.rttvar

    @property
    def send_window(self) -> int:
        """计算发送窗口大小"""
        return min(self.conn.snd_cwnd, self.conn.send_window)

    def __repr__(self) -> str:
        return (f"CongestionControl(state={self.conn.congestion_state.name}, "
                f"cwnd={self.conn.snd_cwnd}, ssthresh={self.conn.snd_ssthresh}, "
                f"rto={self.conn.rto:.3f}s)")


class RetransmissionManager:
    """重传管理器"""

    def __init__(self, connection: TCPConnection, rto: float = 1.0) -> None:
        self.conn = connection
        self._retransmit_queue: deque = deque()
        self._pending: Dict[int, Tuple[TCPPacket, float]] = {}
        self._max_retries: int = 5
        self._rto = rto
        self._backoff_factor: float = 2.0

    def add_packet(self, packet: TCPPacket) -> None:
        """添加待确认的数据包"""
        key = (packet.sequence_number, len(packet.payload))
        self._pending[key] = (packet, time.time() + self._rto)

    def ack_received(self, ack_number: int) -> List[TCPPacket]:
        """处理 ACK 确认

        Args:
            ack_number: 确认号

        Returns:
            被确认的数据包列表
        """
        confirmed = []
        to_remove = []
        for key, (packet, expiry) in self._pending.items():
            if packet.sequence_number + len(packet.payload) <= ack_number:
                confirmed.append(packet)
                to_remove.append(key)

        for key in to_remove:
            del self._pending[key]

        return confirmed

    def check_timeouts(self) -> List[TCPPacket]:
        """检查超时并返回需要重传的数据包"""
        now = time.time()
        timed_out = []
        for key, (packet, expiry) in list(self._pending.items()):
            if now >= expiry:
                packet.retransmitted = True
                packet.rtt = time.time() - packet.timestamp
                timed_out.append(packet)

        return timed_out

    def get_pending_count(self) -> int:
        """获取待确认的数据包数量"""
        return len(self._pending)

    def reset(self) -> None:
        """重置管理器"""
        self._pending.clear()
        self._retransmit_queue.clear()


class TCPProtocol:
    """TCP 协议实现"""

    def __init__(self) -> None:
        self._connections: Dict[str, TCPConnection] = {}
        self._listeners: Dict[int, Callable] = {}
        self._congestion_controls: Dict[str, CongestionControl] = {}
        self._retransmission_managers: Dict[str, RetransmissionManager] = {}
        self._data_callbacks: Dict[str, Callable] = {}
        self._close_callbacks: Dict[str, Callable] = {}
        self._max_connections: int = 1000
        self._is_running: bool = False
        self._sequence_number: int = random.randint(0, 2**32 - 1)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def connections(self) -> Dict[str, TCPConnection]:
        """获取所有连接"""
        return self._connections.copy()

    @property
    def active_connections(self) -> int:
        """获取活跃连接数"""
        return len([c for c in self._connections.values() if c.is_established])

    @property
    def total_connections(self) -> int:
        """获取总连接数"""
        return len(self._connections)

    async def start(self) -> None:
        """启动 TCP 协议处理器"""
        self._is_running = True
        self._loop = asyncio.get_event_loop()
        logger.info("TCP 协议处理器已启动")

    async def stop(self) -> None:
        """停止 TCP 协议处理器"""
        self._is_running = False
        # 关闭所有连接
        for conn_id in list(self._connections.keys()):
            await self.close_connection(conn_id)
        logger.info("TCP 协议处理器已停止")

    def create_connection(self, local_addr: Tuple[str, int], remote_addr: Tuple[str, int]) -> TCPConnection:
        """创建新的 TCP 连接

        Args:
            local_addr: 本地地址 (IP, port)
            remote_addr: 远程地址 (IP, port)

        Returns:
            创建的连接对象

        Raises:
            ConnectionError: 连接数已达上限
        """
        if len(self._connections) >= self._max_connections:
            raise ConnectionError(f"已达到最大连接数限制 ({self._max_connections})")

        conn = TCPConnection(
            local_addr=local_addr,
            remote_addr=remote_addr,
            state=TCPState.SYN_SENT,
            iss=self._next_sequence_number(),
            send_next=self._next_sequence_number(),
        )

        conn_id = conn.connection_id
        self._connections[conn_id] = conn
        self._congestion_controls[conn_id] = CongestionControl(conn)
        self._retransmission_managers[conn_id] = RetransmissionManager(conn)

        logger.info(f"创建 TCP 连接: {conn_id}")
        return conn

    def listen(self, port: int, callback: Callable) -> None:
        """监听端口

        Args:
            port: 监听端口
            callback: 新连接回调函数 (connection: TCPConnection) -> None
        """
        self._listeners[port] = callback
        logger.info(f"开始在端口 {port} 监听 TCP 连接")

    def unlisten(self, port: int) -> bool:
        """停止监听端口

        Args:
            port: 端口号

        Returns:
            是否成功取消监听
        """
        if port in self._listeners:
            del self._listeners[port]
            logger.info(f"停止端口 {port} 的监听")
            return True
        return False

    async def connect(self, host: str, port: int, timeout: float = 30.0) -> TCPConnection:
        """建立 TCP 连接

        Args:
            host: 目标主机
            port: 目标端口
            timeout: 连接超时（秒）

        Returns:
            TCP 连接对象

        Raises:
            ConnectionError: 连接失败
            TimeoutError: 连接超时
        """
        local_port = self._get_ephemeral_port()
        local_addr = ("0.0.0.0", local_port)
        remote_addr = (host, port)

        conn = self.create_connection(local_addr, remote_addr)
        conn.state = TCPState.SYN_SENT

        # 发送 SYN
        syn_packet = TCPPacket(
            src_port=local_port,
            dst_port=port,
            sequence_number=conn.iss,
            acknowledgment_number=0,
            flags=TCPFlag.SYN,
            mss=self._get_mss(host),
        )

        # 等待 SYN-ACK
        try:
            await asyncio.wait_for(
                self._wait_for_state(conn, TCPState.ESTABLISHED),
                timeout=timeout
            )
            logger.info(f"TCP 连接建立成功: {conn.connection_id}")
            return conn
        except asyncio.TimeoutError:
            conn.state = TCPState.CLOSED
            raise TimeoutError(f"连接超时 ({host}:{port})")

    async def close_connection(self, conn_id: str) -> bool:
        """关闭连接

        Args:
            conn_id: 连接 ID

        Returns:
            是否成功关闭
        """
        conn = self._connections.get(conn_id)
        if not conn:
            return False

        conn.state = TCPState.CLOSED
        self._cleanup_connection(conn_id)

        callback = self._close_callbacks.get(conn_id)
        if callback:
            try:
                await callback(conn)
            except Exception as e:
                logger.error(f"连接关闭回调执行出错: {e}")

        logger.info(f"TCP 连接已关闭: {conn_id}")
        return True

    async def send_data(self, conn_id: str, data: bytes) -> int:
        """发送数据

        Args:
            conn_id: 连接 ID
            data: 要发送的数据

        Returns:
            发送的字节数

        Raises:
            ConnectionError: 连接未建立
        """
        conn = self._connections.get(conn_id)
        if not conn or not conn.is_established:
            raise ConnectionError(f"连接未建立: {conn_id}")

        # 分段发送
        sent = 0
        while sent < len(data):
            chunk = data[sent:sent + conn.mss]
            packet = TCPPacket(
                src_port=conn.local_addr[1],
                dst_port=conn.remote_addr[1],
                sequence_number=conn.send_next,
                acknowledgment_number=conn.rcv_next,
                flags=TCPFlag.ACK | TCPFlag.PSH,
                payload=chunk,
            )

            conn.send_next += len(chunk)
            conn.bytes_sent += len(chunk)
            conn.packets_sent += 1
            sent += len(chunk)

            # 注册重传
            retrans_mgr = self._retransmission_managers.get(conn_id)
            if retrans_mgr:
                retrans_mgr.add_packet(packet)

        return sent

    async def receive_data(self, conn_id: str, buffer_size: int = 65536) -> bytes:
        """接收数据

        Args:
            conn_id: 连接 ID
            buffer_size: 接收缓冲区大小

        Returns:
            接收到的数据

        Raises:
            ConnectionError: 连接未建立
        """
        conn = self._connections.get(conn_id)
        if not conn or not conn.is_established:
            raise ConnectionError(f"连接未建立: {conn_id}")

        # 等待数据到达
        while True:
            if conn.out_of_order_queue:
                seq = min(conn.out_of_order_queue.keys())
                if seq == conn.rcv_next:
                    packet = conn.out_of_order_queue.pop(seq)
                    conn.rcv_next += len(packet.payload)
                    conn.bytes_received += len(packet.payload)
                    conn.packets_received += 1
                    return packet.payload[:buffer_size]

            await asyncio.sleep(0.001)

    def on_data(self, conn_id: str, callback: Callable) -> None:
        """注册数据接收回调

        Args:
            conn_id: 连接 ID
            callback: 回调函数 (data: bytes) -> None
        """
        self._data_callbacks[conn_id] = callback

    def on_close(self, conn_id: str, callback: Callable) -> None:
        """注册连接关闭回调

        Args:
            conn_id: 连接 ID
            callback: 回调函数 (connection: TCPConnection) -> None
        """
        self._close_callbacks[conn_id] = callback

    def process_packet(self, packet: TCPPacket, src_ip: str, dst_ip: str) -> None:
        """处理接收到的 TCP 数据包

        Args:
            packet: TCP 数据包
            src_ip: 源 IP 地址
            dst_ip: 目标 IP 地址
        """
        # 查找或创建连接
        conn_id = f"{dst_ip}:{packet.dst_port}-{src_ip}:{packet.src_port}"
        conn = self._connections.get(conn_id)

        if not conn:
            if packet.is_syn and packet.dst_port in self._listeners:
                # 新的连接请求
                conn = TCPConnection(
                    local_addr=(dst_ip, packet.dst_port),
                    remote_addr=(src_ip, packet.src_port),
                    state=TCPState.SYN_RECEIVED,
                    irs=packet.sequence_number,
                    rcv_next=packet.sequence_number + 1,
                )
                self._connections[conn_id] = conn
                self._congestion_controls[conn_id] = CongestionControl(conn)
                self._retransmission_managers[conn_id] = RetransmissionManager(conn)

                # 通知监听器
                callback = self._listeners.get(packet.dst_port)
                if callback:
                    try:
                        callback(conn)
                    except Exception as e:
                        logger.error(f"连接回调执行出错: {e}")
            else:
                # 发送 RST
                self._send_rst(packet, dst_ip, src_ip)
                return

        # 更新连接统计
        conn.packets_received += 1
        conn.bytes_received += len(packet.payload)

        # 处理正常数据
        if packet.is_ack and conn.is_established:
            conn.send_window = packet.window_size
            retrans_mgr = self._retransmission_managers.get(conn_id)
            if retrans_mgr:
                retrans_mgr.ack_received(packet.acknowledgment_number)

            cc = self._congestion_controls.get(conn_id)
            if cc:
                cc.on_new_ack()

        # 数据到达
        if packet.payload:
            if packet.sequence_number == conn.rcv_next:
                conn.rcv_next += len(packet.payload)
                callback = self._data_callbacks.get(conn_id)
                if callback:
                    try:
                        callback(packet.payload)
                    except Exception as e:
                        logger.error(f"数据回调执行出错: {e}")
            else:
                conn.out_of_order_queue[packet.sequence_number] = packet

    def _next_sequence_number(self) -> int:
        """生成下一个序列号"""
        seq = self._sequence_number
        self._sequence_number = (self._sequence_number + random.randint(1, 1000)) % (2**32)
        return seq

    def _get_ephemeral_port(self) -> int:
        """获取临时端口"""
        return random.randint(49152, 65535)

    def _get_mss(self, host: str) -> int:
        """获取 MSS 值"""
        return 1460

    async def _wait_for_state(self, conn: TCPConnection, target_state: TCPState) -> None:
        """等待连接状态变化"""
        while conn.state != target_state and conn.state != TCPState.CLOSED:
            await asyncio.sleep(0.01)
        if conn.state == TCPState.CLOSED:
            raise ConnectionError("连接已关闭")

    def _send_rst(self, packet: TCPPacket, src_ip: str, dst_ip: str) -> None:
        """发送 RST 包"""
        rst_packet = TCPPacket(
            src_port=packet.dst_port,
            dst_port=packet.src_port,
            sequence_number=0,
            acknowledgment_number=packet.sequence_number + len(packet.payload) + 1,
            flags=TCPFlag.RST | TCPFlag.ACK,
        )
        logger.debug(f"发送 RST: {src_ip}:{packet.dst_port} -> {dst_ip}:{packet.src_port}")

    def _cleanup_connection(self, conn_id: str) -> None:
        """清理连接资源"""
        self._connections.pop(conn_id, None)
        self._congestion_controls.pop(conn_id, None)
        self._retransmission_managers.pop(conn_id, None)
        self._data_callbacks.pop(conn_id, None)
        self._close_callbacks.pop(conn_id, None)

    def get_connection_info(self, conn_id: str) -> Optional[Dict[str, Any]]:
        """获取连接信息

        Args:
            conn_id: 连接 ID

        Returns:
            连接信息字典
        """
        conn = self._connections.get(conn_id)
        if not conn:
            return None

        cc = self._congestion_controls.get(conn_id)
        retrans = self._retransmission_managers.get(conn_id)

        return {
            "connection_id": conn_id,
            "state": conn.state.name,
            "local_addr": f"{conn.local_addr[0]}:{conn.local_addr[1]}",
            "remote_addr": f"{conn.remote_addr[0]}:{conn.remote_addr[1]}",
            "duration": conn.duration,
            "bytes_sent": conn.bytes_sent,
            "bytes_received": conn.bytes_received,
            "packets_sent": conn.packets_sent,
            "packets_received": conn.packets_received,
            "retransmissions": conn.retransmissions,
            "throughput": conn.throughput,
            "loss_rate": conn.loss_rate,
            "congestion_control": {
                "state": cc.conn.congestion_state.name if cc else "N/A",
                "cwnd": cc.conn.snd_cwnd if cc else 0,
                "ssthresh": cc.conn.snd_ssthresh if cc else 0,
                "rto": cc.conn.rto if cc else 0,
            } if cc else None,
            "pending_packets": retrans.get_pending_count() if retrans else 0,
        }

    def get_connections_by_state(self, state: TCPState) -> List[TCPConnection]:
        """获取指定状态的连接列表

        Args:
            state: TCP 状态

        Returns:
            连接列表
        """
        return [c for c in self._connections.values() if c.state == state]

    def get_statistics(self) -> Dict[str, Any]:
        """获取 TCP 协议统计信息"""
        established = self.active_connections
        total = self.total_connections
        total_bytes_sent = sum(c.bytes_sent for c in self._connections.values())
        total_bytes_received = sum(c.bytes_received for c in self._connections.values())
        total_retrans = sum(c.retransmissions for c in self._connections.values())

        return {
            "active_connections": established,
            "total_connections": total,
            "listening_ports": list(self._listeners.keys()),
            "total_bytes_sent": total_bytes_sent,
            "total_bytes_received": total_bytes_received,
            "total_retransmissions": total_retrans,
            "retransmission_rate": total_retrans / max(total_bytes_sent, 1),
            "connection_limit": self._max_connections,
            "is_running": self._is_running,
        }