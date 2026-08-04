"""
IP 协议实现
===========

提供 IPv4 数据包的封装、解析、分片和重组功能。
"""

import struct
import ipaddress
import time
import random
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import IntEnum


logger = logging.getLogger(__name__)


class IPProtocolNumber(IntEnum):
    """IP 协议号"""
    ICMP = 1
    IGMP = 2
    TCP = 6
    UDP = 17
    GRE = 47
    ESP = 50
    AH = 51
    ICMPV6 = 58
    EIGRP = 88
    OSPF = 89
    PIM = 103
    SCTP = 132


class IPFlag(IntEnum):
    """IP 标志位"""
    RESERVED = 0x04
    DF = 0x02  # Don't Fragment
    MF = 0x01  # More Fragments


class IPError(Exception):
    """IP 协议错误"""
    pass


class IPChecksumError(IPError):
    """IP 校验和错误"""
    pass


class IPFragmentError(IPError):
    """IP 分片错误"""
    pass


@dataclass
class IPHeader:
    """IPv4 头部"""
    version: int = 4
    ihl: int = 5
    tos: int = 0
    total_length: int = 20
    identification: int = 0
    flags: int = 0
    fragment_offset: int = 0
    ttl: int = 64
    protocol: int = 6
    header_checksum: int = 0
    src_ip: str = "0.0.0.0"
    dst_ip: str = "0.0.0.0"
    options: bytes = b""

    @property
    def header_length(self) -> int:
        """头部长度（字节）"""
        return self.ihl * 4

    @property
    def is_df(self) -> bool:
        """是否不允许分片"""
        return bool(self.flags & IPFlag.DF)

    @property
    def is_mf(self) -> bool:
        """是否有更多分片"""
        return bool(self.flags & IPFlag.MF)

    @property
    def is_fragment(self) -> bool:
        """是否为分片"""
        return self.is_mf or self.fragment_offset > 0

    def encode(self) -> bytes:
        """编码为字节"""
        version_ihl = (self.version << 4) | self.ihl
        flags_fragment = (self.flags << 13) | self.fragment_offset

        try:
            src_bytes = ipaddress.IPv4Address(self.src_ip).packed
            dst_bytes = ipaddress.IPv4Address(self.dst_ip).packed
        except ValueError as e:
            raise IPError(f"无效的 IP 地址: {e}")

        header = struct.pack(
            "!BBHHHBBH4s4s",
            version_ihl,
            self.tos,
            self.total_length,
            self.identification,
            flags_fragment,
            self.ttl,
            self.protocol,
            self.header_checksum,
            src_bytes,
            dst_bytes,
        )

        header += self.options
        # 填充到 4 字节对齐
        while len(header) < self.header_length:
            header += b"\x00"

        # 计算校验和
        if self.header_checksum == 0:
            checksum = self._compute_checksum(header)
            header = header[:10] + struct.pack("!H", checksum) + header[12:]

        return header

    @classmethod
    def decode(cls, data: bytes) -> "IPHeader":
        """从字节解码"""
        if len(data) < 20:
            raise IPError(f"IP 头部太短: {len(data)} 字节")

        version_ihl = data[0]
        version = version_ihl >> 4
        ihl = version_ihl & 0x0F

        if version != 4:
            raise IPError(f"不支持的 IP 版本: {version}")

        header_length = ihl * 4
        if len(data) < header_length:
            raise IPError(f"IP 数据包被截断")

        tos = data[1]
        total_length = struct.unpack("!H", data[2:4])[0]
        identification = struct.unpack("!H", data[4:6])[0]
        flags_fragment = struct.unpack("!H", data[6:8])[0]
        flags = (flags_fragment >> 13) & 0x07
        fragment_offset = flags_fragment & 0x1FFF
        ttl = data[8]
        protocol = data[9]
        header_checksum = struct.unpack("!H", data[10:12])[0]
        src_ip = str(ipaddress.IPv4Address(data[12:16]))
        dst_ip = str(ipaddress.IPv4Address(data[16:20]))
        options = data[20:header_length] if header_length > 20 else b""

        return cls(
            version=version,
            ihl=ihl,
            tos=tos,
            total_length=total_length,
            identification=identification,
            flags=flags,
            fragment_offset=fragment_offset,
            ttl=ttl,
            protocol=protocol,
            header_checksum=header_checksum,
            src_ip=src_ip,
            dst_ip=dst_ip,
            options=options,
        )

    @staticmethod
    def _compute_checksum(data: bytes) -> int:
        """计算 Internet 校验和"""
        if len(data) % 2 != 0:
            data += b"\x00"
        total = 0
        for i in range(0, len(data), 2):
            word = (data[i] << 8) + data[i + 1]
            total += word
        while total >> 16:
            total = (total & 0xFFFF) + (total >> 16)
        return ~total & 0xFFFF


@dataclass
class IPPacket:
    """IP 数据包"""
    header: IPHeader
    payload: bytes = b""
    timestamp: float = field(default_factory=time.time)
    interface: str = ""

    @property
    def src_ip(self) -> str:
        return self.header.src_ip

    @property
    def dst_ip(self) -> str:
        return self.header.dst_ip

    @property
    def protocol(self) -> int:
        return self.header.protocol

    @property
    def is_fragment(self) -> bool:
        return self.header.is_fragment

    @property
    def size(self) -> int:
        return self.header.header_length + len(self.payload)

    def encode(self) -> bytes:
        """编码为字节"""
        self.header.total_length = self.size
        return self.header.encode() + self.payload

    @classmethod
    def decode(cls, data: bytes) -> "IPPacket":
        """从字节解码"""
        header = IPHeader.decode(data)
        payload = data[header.header_length:header.total_length]
        return cls(header=header, payload=payload)


@dataclass
class IPFragment:
    """IP 分片"""
    packet: IPPacket
    offset: int
    more_fragments: bool
    data: bytes


class IPFragmentAssembler:
    """IP 分片重组器"""

    def __init__(self, timeout: float = 30.0) -> None:
        self._fragments: Dict[Tuple[str, str, int, int], List[IPFragment]] = {}
        self._timeout = timeout
        self._completed: Dict[Tuple[str, str, int, int], IPPacket] = {}

    def add_fragment(self, fragment: IPPacket) -> Optional[IPPacket]:
        """添加分片并尝试重组

        Args:
            fragment: IP 分片数据包

        Returns:
            如果重组完成返回完整数据包，否则返回 None
        """
        key = (fragment.src_ip, fragment.dst_ip,
               fragment.header.identification, fragment.header.protocol)

        if key not in self._fragments:
            self._fragments[key] = []

        ip_fragment = IPFragment(
            packet=fragment,
            offset=fragment.header.fragment_offset * 8,
            more_fragments=fragment.header.is_mf,
            data=fragment.payload,
        )
        self._fragments[key].append(ip_fragment)

        return self._try_assemble(key)

    def _try_assemble(self, key: Tuple[str, str, int, int]) -> Optional[IPPacket]:
        """尝试重组指定键的分片"""
        fragments = self._fragments.get(key)
        if not fragments:
            return None

        # 检查是否所有分片都已到达
        fragments.sort(key=lambda f: f.offset)
        has_last = not fragments[-1].more_fragments

        if not has_last:
            return None

        # 检查是否有分片缺失
        expected_offset = 0
        for frag in fragments:
            if frag.offset != expected_offset:
                return None
            expected_offset += len(frag.data)

        # 重组
        payload = b"".join(frag.data for frag in fragments)
        header = fragments[0].packet.header
        header.flags = 0
        header.fragment_offset = 0

        packet = IPPacket(header=header, payload=payload)
        self._completed[key] = packet
        del self._fragments[key]

        return packet

    def cleanup(self) -> int:
        """清理超时的分片

        Returns:
            清理的分片数
        """
        now = time.time()
        expired = []
        for key, fragments in self._fragments.items():
            if now - fragments[0].packet.timestamp > self._timeout:
                expired.append(key)

        for key in expired:
            del self._fragments[key]

        return len(expired)


class IPProtocol:
    """IP 协议实现"""

    def __init__(self) -> None:
        self._routes: List[Dict[str, Any]] = []
        self._default_gateway: Optional[str] = None
        self._local_ips: Set[str] = set()
        self._fragment_assembler = IPFragmentAssembler()
        self._protocol_handlers: Dict[int, Any] = {}
        self._packet_filters: List[Any] = []
        self._is_running: bool = False
        self._identification: int = random.randint(0, 65535)
        self._default_ttl: int = 64
        self._mtu: int = 1500
        self._stats: Dict[str, int] = {
            "packets_received": 0,
            "packets_sent": 0,
            "packets_forwarded": 0,
            "packets_dropped": 0,
            "fragments_received": 0,
            "fragments_created": 0,
            "fragments_reassembled": 0,
            "checksum_errors": 0,
            "ttl_exceeded": 0,
        }

    @property
    def stats(self) -> Dict[str, int]:
        return self._stats.copy()

    async def start(self) -> None:
        """启动 IP 协议处理器"""
        self._is_running = True
        logger.info("IP 协议处理器已启动")

    async def stop(self) -> None:
        """停止 IP 协议处理器"""
        self._is_running = False
        self._fragment_assembler.cleanup()
        logger.info("IP 协议处理器已停止")

    def register_protocol(self, protocol_num: int, handler: Any) -> None:
        """注册上层协议处理器

        Args:
            protocol_num: 协议号 (TCP=6, UDP=17)
            handler: 协议处理器
        """
        self._protocol_handlers[protocol_num] = handler
        logger.debug(f"注册协议处理器: {IPProtocolNumber(protocol_num).name} ({protocol_num})")

    def unregister_protocol(self, protocol_num: int) -> bool:
        """注销协议处理器"""
        if protocol_num in self._protocol_handlers:
            del self._protocol_handlers[protocol_num]
            return True
        return False

    def add_route(self, network: str, gateway: str, interface: str = "",
                  metric: int = 0) -> bool:
        """添加路由

        Args:
            network: 目标网络 (如 "192.168.1.0/24")
            gateway: 网关地址
            interface: 出口接口
            metric: 路由度量值

        Returns:
            是否成功添加
        """
        try:
            network_obj = ipaddress.IPv4Network(network, strict=False)
        except ValueError as e:
            raise IPError(f"无效的网络地址: {e}")

        route = {
            "network": network_obj,
            "gateway": gateway,
            "interface": interface,
            "metric": metric,
            "prefixlen": network_obj.prefixlen,
        }
        self._routes.append(route)
        self._routes.sort(key=lambda r: r["prefixlen"], reverse=True)
        logger.info(f"添加路由: {network} -> {gateway}")
        return True

    def remove_route(self, network: str) -> bool:
        """删除路由"""
        for i, route in enumerate(self._routes):
            if str(route["network"]) == network:
                del self._routes[i]
                return True
        return False

    def set_default_gateway(self, gateway: str) -> None:
        """设置默认网关"""
        self._default_gateway = gateway
        logger.info(f"设置默认网关: {gateway}")

    def add_local_ip(self, ip: str) -> bool:
        """添加本地 IP 地址

        Args:
            ip: IP 地址

        Returns:
            是否成功添加
        """
        try:
            ipaddress.IPv4Address(ip)
        except ValueError as e:
            raise IPError(f"无效的 IP 地址: {e}")

        self._local_ips.add(ip)
        return True

    def remove_local_ip(self, ip: str) -> bool:
        """删除本地 IP 地址"""
        return self._local_ips.discard(ip) is not None

    def is_local_ip(self, ip: str) -> bool:
        """检查是否为本地 IP"""
        return ip in self._local_ips

    def add_filter(self, filter_func: Any) -> None:
        """添加数据包过滤器

        Args:
            filter_func: 过滤函数 (packet: IPPacket) -> bool
        """
        self._packet_filters.append(filter_func)

    def remove_filter(self, filter_func: Any) -> bool:
        """移除数据包过滤器"""
        if filter_func in self._packet_filters:
            self._packet_filters.remove(filter_func)
            return True
        return False

    def create_packet(self, src_ip: str, dst_ip: str, protocol: int,
                      payload: bytes = b"", ttl: int = 0, tos: int = 0,
                      df: bool = False) -> IPPacket:
        """创建 IP 数据包

        Args:
            src_ip: 源 IP 地址
            dst_ip: 目标 IP 地址
            protocol: 协议号
            payload: 负载数据
            ttl: TTL 值，0 表示使用默认值
            tos: 服务类型
            df: 是否禁止分片

        Returns:
            IP 数据包
        """
        identification = self._next_identification()
        flags = IPFlag.DF if df else 0

        header = IPHeader(
            identification=identification,
            flags=flags,
            ttl=ttl if ttl > 0 else self._default_ttl,
            protocol=protocol,
            src_ip=src_ip,
            dst_ip=dst_ip,
            tos=tos,
        )

        packet = IPPacket(header=header, payload=payload)
        return packet

    def send_packet(self, packet: IPPacket) -> bool:
        """发送 IP 数据包

        Args:
            packet: IP 数据包

        Returns:
            是否成功发送
        """
        # 检查是否需要分片
        if packet.size > self._mtu and not packet.header.is_df:
            fragments = self._fragment_packet(packet)
            for frag in fragments:
                self._send_raw(frag)
            self._stats["fragments_created"] += len(fragments)
        else:
            self._send_raw(packet)

        self._stats["packets_sent"] += 1
        return True

    def receive_packet(self, packet: IPPacket) -> None:
        """接收 IP 数据包

        Args:
            packet: IP 数据包
        """
        self._stats["packets_received"] += 1

        # 验证校验和
        if not self._verify_checksum(packet):
            self._stats["checksum_errors"] += 1
            logger.warning(f"IP 校验和错误: {packet.src_ip} -> {packet.dst_ip}")
            return

        # 检查 TTL
        if packet.header.ttl <= 0:
            self._stats["ttl_exceeded"] += 1
            logger.warning(f"TTL 超限: {packet.src_ip} -> {packet.dst_ip}")
            return

        # 应用过滤器
        for filter_func in self._packet_filters:
            if not filter_func(packet):
                self._stats["packets_dropped"] += 1
                return

        # 分片处理
        if packet.is_fragment:
            self._stats["fragments_received"] += 1
            reassembled = self._fragment_assembler.add_fragment(packet)
            if reassembled:
                self._stats["fragments_reassembled"] += 1
                packet = reassembled
            else:
                return

        # 递交给上层协议
        if self.is_local_ip(packet.dst_ip):
            handler = self._protocol_handlers.get(packet.protocol)
            if handler:
                handler(packet)
            else:
                logger.debug(f"未注册的协议类型: {packet.protocol}")
        else:
            # 转发
            self._forward_packet(packet)
            self._stats["packets_forwarded"] += 1

    def _fragment_packet(self, packet: IPPacket) -> List[IPPacket]:
        """分片 IP 数据包

        Args:
            packet: 需要分片的数据包

        Returns:
            分片列表
        """
        max_payload = (self._mtu - packet.header.header_length)
        max_payload -= max_payload % 8  # 对齐到 8 字节

        payload = packet.payload
        fragments = []
        offset = 0
        more_fragments = True

        while more_fragments:
            chunk = payload[:max_payload]
            payload = payload[max_payload:]
            more_fragments = len(payload) > 0

            frag_header = IPHeader(
                identification=packet.header.identification,
                flags=IPFlag.MF if more_fragments else 0,
                fragment_offset=offset // 8,
                ttl=packet.header.ttl,
                protocol=packet.header.protocol,
                src_ip=packet.src_ip,
                dst_ip=packet.dst_ip,
                tos=packet.header.tos,
            )

            fragment = IPPacket(header=frag_header, payload=chunk)
            fragments.append(fragment)
            offset += len(chunk)

        return fragments

    def _send_raw(self, packet: IPPacket) -> None:
        """发送原始数据包"""
        pass  # 由底层实现

    def _forward_packet(self, packet: IPPacket) -> None:
        """转发数据包"""
        # 查找路由
        dst_ip = ipaddress.IPv4Address(packet.dst_ip)
        for route in self._routes:
            if dst_ip in route["network"]:
                logger.debug(f"转发数据包: {packet.src_ip} -> {packet.dst_ip} via {route['gateway']}")
                return

        # 默认网关
        if self._default_gateway:
            logger.debug(f"转发数据包 (默认网关): {packet.src_ip} -> {packet.dst_ip} via {self._default_gateway}")
            return

        logger.debug(f"无路由，丢弃数据包: {packet.dst_ip}")

    @staticmethod
    def _verify_checksum(packet: IPPacket) -> bool:
        """验证 IP 校验和"""
        header_data = packet.header.encode()[:packet.header.header_length]
        checksum = struct.unpack("!H", header_data[10:12])[0]
        # 将校验和字段置零后重新计算
        header_data = header_data[:10] + b"\x00\x00" + header_data[12:]
        computed = IPHeader._compute_checksum(header_data)
        return checksum == computed or checksum == 0

    def _next_identification(self) -> int:
        """生成下一个标识符"""
        ident = self._identification
        self._identification = (self._identification + 1) % 65536
        return ident

    def get_routing_table(self) -> List[Dict[str, Any]]:
        """获取路由表"""
        return [
            {
                "network": str(route["network"]),
                "gateway": route["gateway"],
                "interface": route["interface"],
                "metric": route["metric"],
                "prefixlen": route["prefixlen"],
            }
            for route in self._routes
        ]

    def get_statistics(self) -> Dict[str, Any]:
        """获取 IP 协议统计信息"""
        return {
            **self._stats,
            "routes": len(self._routes),
            "local_ips": list(self._local_ips),
            "default_gateway": self._default_gateway,
            "mtu": self._mtu,
            "default_ttl": self._default_ttl,
            "is_running": self._is_running,
            "fragment_assembler_pending": sum(
                len(frags) for frags in self._fragment_assembler._fragments.values()
            ),
        }