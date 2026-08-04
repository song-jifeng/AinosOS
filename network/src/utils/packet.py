"""
数据包构造与解析工具
====================

提供数据包的构造、解析和模板功能。
"""

import struct
import io
import ipaddress
from typing import Optional, Dict, Any, List, Tuple, Union
from dataclasses import dataclass, field
from enum import IntEnum
from datetime import datetime


class EtherType(IntEnum):
    """以太网类型"""
    IPV4 = 0x0800
    IPV6 = 0x86DD
    ARP = 0x0806
    VLAN = 0x8100


class PacketBuildError(Exception):
    """数据包构造错误"""
    pass


class PacketParseError(Exception):
    """数据包解析错误"""
    pass


@dataclass
class PacketTemplate:
    """数据包模板，用于预定义数据包结构"""
    name: str = ""
    fields: Dict[str, Any] = field(default_factory=dict)
    payload: Optional[bytes] = None
    protocol: Optional[str] = None

    def validate(self) -> bool:
        """验证模板字段是否完整"""
        required = {"src_ip", "dst_ip", "protocol"}
        return required.issubset(set(self.fields.keys()))


@dataclass
class PacketInfo:
    """解析后的数据包信息"""
    raw: bytes = b""
    timestamp: float = 0.0
    length: int = 0
    src_ip: str = ""
    dst_ip: str = ""
    src_port: int = 0
    dst_port: int = 0
    protocol: str = ""
    ttl: int = 64
    flags: Dict[str, bool] = field(default_factory=dict)
    payload: bytes = b""
    headers: Dict[str, Any] = field(default_factory=dict)


class PacketBuilder:
    """数据包构建器，支持逐层构造网络数据包"""

    def __init__(self) -> None:
        self._layers: List[Dict[str, Any]] = []
        self._payload: Optional[bytes] = None

    def add_ethernet(
        self,
        dst_mac: str = "ff:ff:ff:ff:ff:ff",
        src_mac: str = "00:00:00:00:00:00",
        ether_type: EtherType = EtherType.IPV4,
    ) -> "PacketBuilder":
        """添加以太网层"""
        try:
            dst_bytes = bytes.fromhex(dst_mac.replace(":", ""))
            src_bytes = bytes.fromhex(src_mac.replace(":", ""))
        except ValueError as e:
            raise PacketBuildError(f"无效的 MAC 地址格式: {e}")

        self._layers.append({
            "type": "ethernet",
            "dst": dst_bytes,
            "src": src_bytes,
            "ether_type": ether_type,
        })
        return self

    def add_ipv4(
        self,
        src_ip: str,
        dst_ip: str,
        protocol: int = 6,
        ttl: int = 64,
        tos: int = 0,
        identification: int = 0,
        flags: int = 0,
        fragment_offset: int = 0,
    ) -> "PacketBuilder":
        """添加 IPv4 层"""
        try:
            src_bytes = ipaddress.IPv4Address(src_ip).packed
            dst_bytes = ipaddress.IPv4Address(dst_ip).packed
        except ValueError as e:
            raise PacketBuildError(f"无效的 IP 地址: {e}")

        self._layers.append({
            "type": "ipv4",
            "version": 4,
            "ihl": 5,
            "tos": tos,
            "total_length": 0,  # 将在构建时计算
            "identification": identification,
            "flags": flags,
            "fragment_offset": fragment_offset,
            "ttl": ttl,
            "protocol": protocol,
            "header_checksum": 0,
            "src": src_bytes,
            "dst": dst_bytes,
        })
        return self

    def add_tcp(
        self,
        src_port: int,
        dst_port: int,
        sequence_number: int = 0,
        acknowledgment_number: int = 0,
        data_offset: int = 5,
        flags: int = 0x02,  # SYN
        window_size: int = 65535,
        urgent_pointer: int = 0,
        options: Optional[bytes] = None,
    ) -> "PacketBuilder":
        """添加 TCP 层"""
        if not (0 < src_port < 65536):
            raise PacketBuildError(f"源端口超出范围: {src_port}")
        if not (0 < dst_port < 65536):
            raise PacketBuildError(f"目标端口超出范围: {dst_port}")

        self._layers.append({
            "type": "tcp",
            "src_port": src_port,
            "dst_port": dst_port,
            "sequence_number": sequence_number,
            "acknowledgment_number": acknowledgment_number,
            "data_offset": data_offset,
            "reserved": 0,
            "flags": flags,
            "window_size": window_size,
            "checksum": 0,
            "urgent_pointer": urgent_pointer,
            "options": options or b"",
        })
        return self

    def add_udp(
        self,
        src_port: int,
        dst_port: int,
    ) -> "PacketBuilder":
        """添加 UDP 层"""
        if not (0 < src_port < 65536):
            raise PacketBuildError(f"源端口超出范围: {src_port}")
        if not (0 < dst_port < 65536):
            raise PacketBuildError(f"目标端口超出范围: {dst_port}")

        self._layers.append({
            "type": "udp",
            "src_port": src_port,
            "dst_port": dst_port,
            "length": 0,
            "checksum": 0,
        })
        return self

    def set_payload(self, payload: bytes) -> "PacketBuilder":
        """设置负载数据"""
        self._payload = payload
        return self

    def build(self) -> bytes:
        """构建完整的数据包"""
        if not self._layers:
            raise PacketBuildError("没有添加任何协议层")

        packet = self._payload or b""

        # 从内到外构建各层
        for layer in reversed(self._layers):
            if layer["type"] == "tcp":
                packet = self._build_tcp(layer, packet)
            elif layer["type"] == "udp":
                packet = self._build_udp(layer, packet)
            elif layer["type"] == "ipv4":
                packet = self._build_ipv4(layer, packet)
            elif layer["type"] == "ethernet":
                packet = self._build_ethernet(layer, packet)

        return packet

    def _build_tcp(self, header: Dict[str, Any], payload: bytes) -> bytes:
        """构建 TCP 段"""
        data_offset = header["data_offset"]
        header_len = data_offset * 4
        options = header["options"]
        options_padded = options + b"\x00" * (header_len - 20 - len(options))

        tcp_header = struct.pack(
            "!HHIIBBHHH",
            header["src_port"],
            header["dst_port"],
            header["sequence_number"],
            header["acknowledgment_number"],
            (data_offset << 4) | header["reserved"],
            header["flags"],
            header["window_size"],
            0,  # checksum 占位
            header["urgent_pointer"],
        )

        tcp_header += options_padded

        # 计算校验和（需要伪头部）
        if len(tcp_header) < header_len:
            tcp_header += b"\x00" * (header_len - len(tcp_header))

        return tcp_header + payload

    def _build_udp(self, header: Dict[str, Any], payload: bytes) -> bytes:
        """构建 UDP 数据报"""
        length = 8 + len(payload)
        header["length"] = length

        udp_header = struct.pack(
            "!HHHH",
            header["src_port"],
            header["dst_port"],
            length,
            0,  # checksum 占位
        )

        return udp_header + payload

    def _build_ipv4(self, header: Dict[str, Any], payload: bytes) -> bytes:
        """构建 IPv4 数据包"""
        ihl = header["ihl"]
        total_length = ihl * 4 + len(payload)
        header["total_length"] = total_length

        version_ihl = (header["version"] << 4) | ihl
        flags_fragment = (header["flags"] << 13) | header["fragment_offset"]

        ip_header = struct.pack(
            "!BBHHHBBH4s4s",
            version_ihl,
            header["tos"],
            total_length,
            header["identification"],
            flags_fragment,
            header["ttl"],
            header["protocol"],
            0,  # checksum 占位
            header["src"],
            header["dst"],
        )

        # 计算 IP 校验和
        checksum = self._calculate_checksum(ip_header)
        ip_header = ip_header[:10] + struct.pack("!H", checksum) + ip_header[12:]

        return ip_header + payload

    def _build_ethernet(self, header: Dict[str, Any], payload: bytes) -> bytes:
        """构建以太网帧"""
        return header["dst"] + header["src"] + struct.pack("!H", header["ether_type"]) + payload

    @staticmethod
    def _calculate_checksum(data: bytes) -> int:
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

    def reset(self) -> None:
        """重置构建器"""
        self._layers.clear()
        self._payload = None


class PacketParser:
    """数据包解析器，解析原始字节为结构化数据"""

    @staticmethod
    def parse_ethernet(data: bytes) -> Dict[str, Any]:
        """解析以太网帧"""
        if len(data) < 14:
            raise PacketParseError(f"以太网帧太短: {len(data)} 字节")

        dst_mac = ":".join(f"{b:02x}" for b in data[0:6])
        src_mac = ":".join(f"{b:02x}" for b in data[6:12])
        ether_type = struct.unpack("!H", data[12:14])[0]

        return {
            "dst_mac": dst_mac,
            "src_mac": src_mac,
            "ether_type": ether_type,
            "payload": data[14:],
        }

    @staticmethod
    def parse_ipv4(data: bytes) -> Dict[str, Any]:
        """解析 IPv4 数据包"""
        if len(data) < 20:
            raise PacketParseError(f"IP 头部太短: {len(data)} 字节")

        version_ihl = data[0]
        version = version_ihl >> 4
        ihl = version_ihl & 0x0F

        if version != 4:
            raise PacketParseError(f"不支持的 IP 版本: {version}")

        header_length = ihl * 4
        if len(data) < header_length:
            raise PacketParseError(f"IP 数据包被截断: {len(data)} < {header_length}")

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

        # 解析选项（如果有）
        options = None
        if header_length > 20:
            options = data[20:header_length]

        # 校验和验证
        received_checksum = header_checksum
        computed_checksum = PacketParser._checksum(data[:header_length])
        checksum_valid = received_checksum == computed_checksum or received_checksum == 0

        return {
            "version": version,
            "ihl": ihl,
            "tos": tos,
            "total_length": total_length,
            "identification": identification,
            "flags": {
                "reserved": bool(flags & 0x04),
                "df": bool(flags & 0x02),
                "mf": bool(flags & 0x01),
            },
            "fragment_offset": fragment_offset,
            "ttl": ttl,
            "protocol": protocol,
            "header_checksum": header_checksum,
            "checksum_valid": checksum_valid,
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "options": options,
            "payload": data[header_length:total_length] if total_length > header_length else b"",
        }

    @staticmethod
    def parse_tcp(data: bytes) -> Dict[str, Any]:
        """解析 TCP 段"""
        if len(data) < 20:
            raise PacketParseError(f"TCP 头部太短: {len(data)} 字节")

        src_port = struct.unpack("!H", data[0:2])[0]
        dst_port = struct.unpack("!H", data[2:4])[0]
        sequence_number = struct.unpack("!I", data[4:8])[0]
        acknowledgment_number = struct.unpack("!I", data[8:12])[0]
        data_offset_reserved = data[12]
        data_offset = (data_offset_reserved >> 4) & 0x0F
        header_length = data_offset * 4

        if len(data) < header_length:
            raise PacketParseError(f"TCP 数据被截断: {len(data)} < {header_length}")

        flags_byte = data[13]
        flags = {
            "fin": bool(flags_byte & 0x01),
            "syn": bool(flags_byte & 0x02),
            "rst": bool(flags_byte & 0x04),
            "psh": bool(flags_byte & 0x08),
            "ack": bool(flags_byte & 0x10),
            "urg": bool(flags_byte & 0x20),
            "ece": bool(flags_byte & 0x40),
            "cwr": bool(flags_byte & 0x80),
        }
        window_size = struct.unpack("!H", data[14:16])[0]
        checksum = struct.unpack("!H", data[16:18])[0]
        urgent_pointer = struct.unpack("!H", data[18:20])[0]

        # 解析选项
        options = None
        if header_length > 20:
            options = data[20:header_length]

        return {
            "src_port": src_port,
            "dst_port": dst_port,
            "sequence_number": sequence_number,
            "acknowledgment_number": acknowledgment_number,
            "data_offset": data_offset,
            "flags": flags,
            "window_size": window_size,
            "checksum": checksum,
            "urgent_pointer": urgent_pointer,
            "options": options,
            "payload": data[header_length:],
        }

    @staticmethod
    def parse_udp(data: bytes) -> Dict[str, Any]:
        """解析 UDP 数据报"""
        if len(data) < 8:
            raise PacketParseError(f"UDP 头部太短: {len(data)} 字节")

        src_port = struct.unpack("!H", data[0:2])[0]
        dst_port = struct.unpack("!H", data[2:4])[0]
        length = struct.unpack("!H", data[4:6])[0]
        checksum = struct.unpack("!H", data[6:8])[0]

        return {
            "src_port": src_port,
            "dst_port": dst_port,
            "length": length,
            "checksum": checksum,
            "payload": data[8:length],
        }

    @staticmethod
    def _checksum(data: bytes) -> int:
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

    @staticmethod
    def parse(data: bytes, layer: str = "auto") -> PacketInfo:
        """自动解析数据包，从以太网层开始"""
        info = PacketInfo(raw=data, timestamp=datetime.now().timestamp(), length=len(data))

        if layer == "auto" or layer == "ethernet":
            try:
                eth = PacketParser.parse_ethernet(data)
                info.headers["ethernet"] = eth
                payload = eth["payload"]

                if eth["ether_type"] == EtherType.IPV4.value:
                    return PacketParser._parse_ip_payload(payload, info)
                elif eth["ether_type"] == EtherType.IPV6.value:
                    info.protocol = "IPv6"
                    return info
                elif eth["ether_type"] == EtherType.ARP.value:
                    info.protocol = "ARP"
                    return info
            except PacketParseError:
                pass

        return info

    @staticmethod
    def _parse_ip_payload(payload: bytes, info: PacketInfo) -> PacketInfo:
        """解析 IP 负载"""
        ip = PacketParser.parse_ipv4(payload)
        info.headers["ip"] = ip
        info.src_ip = ip["src_ip"]
        info.dst_ip = ip["dst_ip"]
        info.ttl = ip["ttl"]

        protocol_map = {6: "TCP", 17: "UDP", 1: "ICMP", 2: "IGMP"}
        info.protocol = protocol_map.get(ip["protocol"], f"IP-{ip['protocol']}")

        if ip["protocol"] == 6:  # TCP
            try:
                tcp = PacketParser.parse_tcp(ip["payload"])
                info.headers["tcp"] = tcp
                info.src_port = tcp["src_port"]
                info.dst_port = tcp["dst_port"]
                info.flags = tcp["flags"]
                info.payload = tcp["payload"]
            except PacketParseError:
                pass

        elif ip["protocol"] == 17:  # UDP
            try:
                udp = PacketParser.parse_udp(ip["payload"])
                info.headers["udp"] = udp
                info.src_port = udp["src_port"]
                info.dst_port = udp["dst_port"]
                info.payload = udp["payload"]
            except PacketParseError:
                pass

        else:
            info.payload = ip["payload"]

        return info


class PacketTemplate:
    """数据包模板管理器"""

    def __init__(self) -> None:
        self._templates: Dict[str, PacketTemplate] = {}

    def register(self, name: str, template: PacketTemplate) -> None:
        """注册模板"""
        self._templates[name] = template

    def get(self, name: str) -> Optional[PacketTemplate]:
        """获取模板"""
        return self._templates.get(name)

    def list_templates(self) -> List[str]:
        """列出所有模板名称"""
        return list(self._templates.keys())

    def build_from_template(self, name: str, **overrides: Any) -> bytes:
        """根据模板构建数据包"""
        template = self._templates.get(name)
        if not template:
            raise PacketBuildError(f"模板未找到: {name}")

        fields = {**template.fields, **overrides}
        builder = PacketBuilder()

        protocol = template.protocol or fields.get("protocol", "tcp")

        if protocol.lower() == "tcp":
            builder.add_ipv4(
                src_ip=fields.get("src_ip", "127.0.0.1"),
                dst_ip=fields.get("dst_ip", "127.0.0.1"),
            ).add_tcp(
                src_port=fields.get("src_port", 12345),
                dst_port=fields.get("dst_port", 80),
            )
        elif protocol.lower() == "udp":
            builder.add_ipv4(
                src_ip=fields.get("src_ip", "127.0.0.1"),
                dst_ip=fields.get("dst_ip", "127.0.0.1"),
                protocol=17,
            ).add_udp(
                src_port=fields.get("src_port", 12345),
                dst_port=fields.get("dst_port", 53),
            )

        if template.payload:
            builder.set_payload(template.payload)

        return builder.build()

    def remove(self, name: str) -> bool:
        """删除模板"""
        if name in self._templates:
            del self._templates[name]
            return True
        return False