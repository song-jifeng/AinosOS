"""
网络抓包模块
============

提供网络数据包捕获功能，支持实时抓包和 pcap 文件读写。
"""

import asyncio
import struct
import time
import os
import logging
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import IntEnum


logger = logging.getLogger(__name__)


class CaptureState(IntEnum):
    """抓包状态"""
    IDLE = 0
    CAPTURING = 1
    PAUSED = 2
    STOPPED = 3


@dataclass
class CaptureFilter:
    """抓包过滤器"""
    src_ip: str = ""
    dst_ip: str = ""
    src_port: int = 0
    dst_port: int = 0
    protocol: str = ""
    interface: str = ""
    bp_filter: str = ""

    @property
    def is_active(self) -> bool:
        return bool(self.src_ip or self.dst_ip or self.src_port or
                    self.dst_port or self.protocol or self.bp_filter)

    def matches(self, src_ip: str = "", dst_ip: str = "",
                src_port: int = 0, dst_port: int = 0,
                protocol: str = "") -> bool:
        """检查是否匹配"""
        if self.src_ip and self.src_ip != src_ip:
            return False
        if self.dst_ip and self.dst_ip != dst_ip:
            return False
        if self.src_port and self.src_port != src_port:
            return False
        if self.dst_port and self.dst_port != dst_port:
            return False
        if self.protocol and self.protocol.lower() != protocol.lower():
            return False
        return True


@dataclass
class CapturedPacket:
    """捕获的数据包"""
    timestamp: float = field(default_factory=time.time)
    length: int = 0
    raw_data: bytes = b""
    src_ip: str = ""
    dst_ip: str = ""
    src_port: int = 0
    dst_port: int = 0
    protocol: str = ""
    info: str = ""
    interface: str = ""

    @property
    def size(self) -> str:
        if self.length < 1024:
            return f"{self.length} B"
        elif self.length < 1048576:
            return f"{self.length / 1024:.1f} KB"
        return f"{self.length / 1048576:.1f} MB"


class PCAPWriter:
    """PCAP 文件写入器"""

    PCAP_MAGIC_NUMBER = 0xA1B2C3D4
    PCAP_VERSION_MAJOR = 2
    PCAP_VERSION_MINOR = 4
    PCAP_SNAPLEN = 65535
    PCAP_LINKTYPE_ETHERNET = 1

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self._file = None
        self._packet_count = 0
        self._is_open = False

    def open(self) -> bool:
        """打开文件"""
        try:
            self._file = open(self.filepath, "wb")
            self._write_global_header()
            self._is_open = True
            logger.info(f"PCAP 文件已打开: {self.filepath}")
            return True
        except IOError as e:
            logger.error(f"无法打开 PCAP 文件: {e}")
            return False

    def _write_global_header(self) -> None:
        """写入全局文件头"""
        header = struct.pack(
            "IHHiIII",
            self.PCAP_MAGIC_NUMBER,
            self.PCAP_VERSION_MAJOR,
            self.PCAP_VERSION_MINOR,
            0,  # 时区
            0,  # 时间戳精度
            self.PCAP_SNAPLEN,
            self.PCAP_LINKTYPE_ETHERNET,
        )
        self._file.write(header)

    def write_packet(self, data: bytes, timestamp: Optional[float] = None) -> None:
        """写入数据包记录"""
        if not self._is_open or not self._file:
            return

        ts = timestamp or time.time()
        ts_sec = int(ts)
        ts_usec = int((ts - ts_sec) * 1000000)

        packet_len = len(data)
        header = struct.pack("IIII", ts_sec, ts_usec, packet_len, packet_len)
        self._file.write(header)
        self._file.write(data[:self.PCAP_SNAPLEN])
        self._packet_count += 1

    def close(self) -> None:
        """关闭文件"""
        if self._file:
            self._file.close()
            self._is_open = False
            logger.info(f"PCAP 文件已关闭: {self.filepath} ({self._packet_count} 个数据包)")

    @property
    def packet_count(self) -> int:
        return self._packet_count

    def __enter__(self) -> "PCAPWriter":
        self.open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class PCAPReader:
    """PCAP 文件读取器"""

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self._file = None
        self._packet_count = 0
        self._is_open = False
        self._linktype = 0

    def open(self) -> bool:
        """打开文件"""
        try:
            self._file = open(self.filepath, "rb")
            if not self._read_global_header():
                return False
            self._is_open = True
            logger.info(f"PCAP 文件已打开: {self.filepath}")
            return True
        except IOError as e:
            logger.error(f"无法打开 PCAP 文件: {e}")
            return False

    def _read_global_header(self) -> bool:
        """读取全局文件头"""
        header_data = self._file.read(24)
        if len(header_data) < 24:
            logger.error("PCAP 文件头不完整")
            return False

        magic, major, minor, _, _, snaplen, linktype = struct.unpack("IHHiIII", header_data)
        if magic != self.PCAP_MAGIC_NUMBER and magic != 0xD4C3B2A1:
            logger.error(f"无效的 PCAP 文件 (magic=0x{magic:08X})")
            return False

        self._linktype = linktype
        logger.debug(f"PCAP: version={major}.{minor}, snaplen={snaplen}, linktype={linktype}")
        return True

    def read_packet(self) -> Optional[CapturedPacket]:
        """读取下一个数据包"""
        if not self._is_open or not self._file:
            return None

        try:
            packet_header = self._file.read(16)
            if len(packet_header) < 16:
                return None

            ts_sec, ts_usec, incl_len, orig_len = struct.unpack("IIII", packet_header)
            timestamp = ts_sec + ts_usec / 1000000

            data = self._file.read(incl_len)
            if len(data) < incl_len:
                return None

            self._packet_count += 1

            return CapturedPacket(
                timestamp=timestamp,
                length=orig_len,
                raw_data=data,
                info=f"Packet #{self._packet_count} ({incl_len} bytes)",
            )

        except (IOError, struct.error) as e:
            logger.error(f"读取数据包失败: {e}")
            return None

    def read_all(self) -> List[CapturedPacket]:
        """读取所有数据包"""
        packets = []
        while True:
            packet = self.read_packet()
            if packet:
                packets.append(packet)
            else:
                break
        return packets

    def close(self) -> None:
        """关闭文件"""
        if self._file:
            self._file.close()
            self._is_open = False
            logger.info(f"PCAP 文件已关闭: {self.filepath} ({self._packet_count} 个数据包)")

    @property
    def packet_count(self) -> int:
        return self._packet_count

    def __enter__(self) -> "PCAPReader":
        self.open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class PacketSniffer:
    """数据包嗅探器"""

    def __init__(self, max_packets: int = 10000, buffer_size: int = 65536) -> None:
        self.max_packets = max_packets
        self.buffer_size = buffer_size
        self._packets: List[CapturedPacket] = []
        self._state = CaptureState.IDLE
        self._callbacks: List[Callable] = []
        self._filter = CaptureFilter()
        self._stats: Dict[str, int] = {
            "captured": 0,
            "filtered": 0,
            "dropped": 0,
            "errors": 0,
        }

    @property
    def state(self) -> CaptureState:
        return self._state

    @property
    def packets(self) -> List[CapturedPacket]:
        return self._packets.copy()

    @property
    def packet_count(self) -> int:
        return len(self._packets)

    def set_filter(self, filter_obj: CaptureFilter) -> None:
        """设置过滤器"""
        self._filter = filter_obj

    def on_packet(self, callback: Callable) -> None:
        """注册数据包回调"""
        self._callbacks.append(callback)

    async def start_capture(self, interface: str = "any",
                              promiscuous: bool = True) -> None:
        """开始捕获

        Args:
            interface: 网络接口
            promiscuous: 是否启用混杂模式
        """
        self._state = CaptureState.CAPTURING
        logger.info(f"开始抓包: interface={interface}, promiscuous={promiscuous}")

    async def stop_capture(self) -> None:
        """停止捕获"""
        self._state = CaptureState.STOPPED
        logger.info(f"抓包已停止，共捕获 {self._stats['captured']} 个数据包")

    def pause(self) -> None:
        """暂停捕获"""
        if self._state == CaptureState.CAPTURING:
            self._state = CaptureState.PAUSED

    def resume(self) -> None:
        """恢复捕获"""
        if self._state == CaptureState.PAUSED:
            self._state = CaptureState.CAPTURING

    def add_packet(self, packet: CapturedPacket) -> None:
        """添加捕获的数据包"""
        if self._state != CaptureState.CAPTURING:
            return

        # 应用过滤器
        if self._filter.is_active:
            if not self._filter.matches(
                src_ip=packet.src_ip, dst_ip=packet.dst_ip,
                src_port=packet.src_port, dst_port=packet.dst_port,
                protocol=packet.protocol,
            ):
                self._stats["filtered"] += 1
                return

        self._packets.append(packet)
        self._stats["captured"] += 1

        if len(self._packets) > self.max_packets:
            self._packets.pop(0)
            self._stats["dropped"] += 1

        # 通知回调
        for callback in self._callbacks:
            try:
                callback(packet)
            except Exception as e:
                logger.error(f"回调执行出错: {e}")

    def clear(self) -> None:
        """清空捕获的数据包"""
        self._packets.clear()
        self._stats = {"captured": 0, "filtered": 0, "dropped": 0, "errors": 0}

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "state": self._state.name,
            "buffer_size": len(self._packets),
            "max_packets": self.max_packets,
            "filter_active": self._filter.is_active,
        }


class PacketCapture:
    """网络抓包管理器"""

    def __init__(self, max_packets: int = 10000) -> None:
        self.max_packets = max_packets
        self._sniffer = PacketSniffer(max_packets=max_packets)
        self._pcap_writer: Optional[PCAPWriter] = None
        self._is_capturing: bool = False
        self._capture_start_time: float = 0.0
        self._stats: Dict[str, int] = {
            "sessions": 0,
            "packets_captured": 0,
            "files_written": 0,
        }

    @property
    def is_capturing(self) -> bool:
        return self._is_capturing

    @property
    def sniffer(self) -> PacketSniffer:
        return self._sniffer

    async def start(self, interface: str = "any",
                     save_to_file: Optional[str] = None) -> None:
        """开始抓包

        Args:
            interface: 网络接口
            save_to_file: 可选的保存路径
        """
        self._is_capturing = True
        self._capture_start_time = time.time()
        self._stats["sessions"] += 1

        if save_to_file:
            self._pcap_writer = PCAPWriter(save_to_file)
            self._pcap_writer.open()

        await self._sniffer.start_capture(interface)
        logger.info("抓包管理器已启动")

    async def stop(self) -> Optional[str]:
        """停止抓包

        Returns:
            如果保存到文件则返回文件路径
        """
        await self._sniffer.stop_capture()
        self._is_capturing = False

        filepath = None
        if self._pcap_writer:
            self._pcap_writer.close()
            filepath = self._pcap_writer.filepath
            self._stats["files_written"] += 1
            self._pcap_writer = None

        logger.info(f"抓包管理器已停止，捕获 {self._stats['packets_captured']} 个数据包")
        return filepath

    def save_to_file(self, filepath: str) -> bool:
        """保存捕获的数据包到文件"""
        try:
            with PCAPWriter(filepath) as writer:
                for packet in self._sniffer.packets:
                    writer.write_packet(packet.raw_data, packet.timestamp)
            self._stats["files_written"] += 1
            logger.info(f"数据包已保存到: {filepath} ({len(self._sniffer.packets)} 个)")
            return True
        except Exception as e:
            logger.error(f"保存数据包失败: {e}")
            return False

    def load_from_file(self, filepath: str) -> List[CapturedPacket]:
        """从文件加载数据包"""
        try:
            with PCAPReader(filepath) as reader:
                packets = reader.read_all()
            logger.info(f"从文件加载了 {len(packets)} 个数据包: {filepath}")
            return packets
        except Exception as e:
            logger.error(f"加载数据包失败: {e}")
            return []

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "is_capturing": self._is_capturing,
            "capture_duration": time.time() - self._capture_start_time if self._is_capturing else 0,
            "sniffer_stats": self._sniffer.get_statistics(),
        }