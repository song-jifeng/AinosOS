"""
校验和计算工具
==============

提供 Internet 校验和、CRC 等校验和计算功能。
"""

import struct
import zlib
from typing import Optional, Union


class ChecksumError(Exception):
    """校验和错误"""
    pass


class InternetChecksum:
    """Internet 校验和计算器 (RFC 1071)"""

    @staticmethod
    def compute(data: bytes, initial_value: int = 0) -> int:
        """计算 Internet 校验和

        Args:
            data: 要计算校验和的数据
            initial_value: 初始值

        Returns:
            16位校验和值
        """
        if len(data) % 2 != 0:
            data += b"\x00"

        total = initial_value
        for i in range(0, len(data), 2):
            word = (data[i] << 8) + data[i + 1]
            total += word

        while total >> 16:
            total = (total & 0xFFFF) + (total >> 16)

        return ~total & 0xFFFF

    @staticmethod
    def verify(data: bytes, checksum: int) -> bool:
        """验证校验和

        Args:
            data: 数据
            checksum: 预期的校验和值

        Returns:
            校验和是否匹配
        """
        computed = InternetChecksum.compute(data)
        return computed == checksum

    @staticmethod
    def compute_ipv4(header: bytes) -> int:
        """计算 IPv4 头部校验和

        Args:
            header: IPv4 头部（校验和字段为0）

        Returns:
            16位校验和值
        """
        if len(header) < 20:
            raise ChecksumError(f"IPv4 头部太短: {len(header)} 字节")

        # 将校验和字段置零后计算
        header = header[:10] + b"\x00\x00" + header[12:]
        return InternetChecksum.compute(header)

    @staticmethod
    def compute_pseudo_header(
        src_ip: bytes,
        dst_ip: bytes,
        protocol: int,
        payload_length: int,
    ) -> bytes:
        """构造 TCP/UDP 伪头部

        Args:
            src_ip: 源 IP 地址 (4字节)
            dst_ip: 目标 IP 地址 (4字节)
            protocol: 协议号 (TCP=6, UDP=17)
            payload_length: 负载长度

        Returns:
            伪头部字节
        """
        return struct.pack(
            "!4s4sBBH",
            src_ip,
            dst_ip,
            0,
            protocol,
            payload_length,
        )

    @staticmethod
    def compute_tcp_udp(
        src_ip: bytes,
        dst_ip: bytes,
        protocol: int,
        header: bytes,
        payload: bytes = b"",
    ) -> int:
        """计算 TCP/UDP 校验和（含伪头部）

        Args:
            src_ip: 源 IP 地址 (4字节)
            dst_ip: 目标 IP 地址 (4字节)
            protocol: 协议号
            header: TCP/UDP 头部（校验和字段为0）
            payload: 负载数据

        Returns:
            16位校验和值
        """
        pseudo_header = InternetChecksum.compute_pseudo_header(
            src_ip, dst_ip, protocol, len(header) + len(payload)
        )

        data = pseudo_header + header + payload
        return InternetChecksum.compute(data)


class CRCCalculator:
    """CRC 校验计算器"""

    @staticmethod
    def crc32(data: bytes) -> int:
        """计算 CRC32 校验值

        Args:
            data: 输入数据

        Returns:
            CRC32 校验值
        """
        return zlib.crc32(data) & 0xFFFFFFFF

    @staticmethod
    def crc16(data: bytes, polynomial: int = 0x8005) -> int:
        """计算 CRC16 校验值

        Args:
            data: 输入数据
            polynomial: 生成多项式，默认 0x8005 (CRC-16-IBM)

        Returns:
            CRC16 校验值
        """
        crc = 0xFFFF
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ polynomial
                else:
                    crc <<= 1
                crc &= 0xFFFF
        return crc

    @staticmethod
    def crc8(data: bytes, polynomial: int = 0x07) -> int:
        """计算 CRC8 校验值

        Args:
            data: 输入数据
            polynomial: 生成多项式，默认 0x07 (CRC-8)

        Returns:
            CRC8 校验值
        """
        crc = 0x00
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = (crc << 1) ^ polynomial
                else:
                    crc <<= 1
                crc &= 0xFF
        return crc

    @staticmethod
    def verify_crc32(data: bytes, expected: int) -> bool:
        """验证 CRC32 校验值

        Args:
            data: 输入数据
            expected: 预期的 CRC32 值

        Returns:
            是否匹配
        """
        return CRCCalculator.crc32(data) == expected


class ChecksumCalculator:
    """综合校验和计算器，提供多种校验方式"""

    def __init__(self) -> None:
        self._internet = InternetChecksum()
        self._crc = CRCCalculator()

    @staticmethod
    def compute_checksum(data: bytes, algorithm: str = "internet") -> int:
        """计算指定算法的校验和

        Args:
            data: 输入数据
            algorithm: 校验算法 (internet, crc32, crc16, crc8, md5, sha1, sha256)

        Returns:
            校验和/哈希值

        Raises:
            ChecksumError: 不支持的算法
        """
        algorithm = algorithm.lower()

        if algorithm == "internet":
            return InternetChecksum.compute(data)
        elif algorithm == "crc32":
            return CRCCalculator.crc32(data)
        elif algorithm == "crc16":
            return CRCCalculator.crc16(data)
        elif algorithm == "crc8":
            return CRCCalculator.crc8(data)
        elif algorithm == "md5":
            import hashlib
            return int(hashlib.md5(data).hexdigest(), 16)
        elif algorithm == "sha1":
            import hashlib
            return int(hashlib.sha1(data).hexdigest(), 16)
        elif algorithm == "sha256":
            import hashlib
            return int(hashlib.sha256(data).hexdigest(), 16)
        else:
            raise ChecksumError(f"不支持的校验算法: {algorithm}")

    @staticmethod
    def verify_checksum(data: bytes, expected: int, algorithm: str = "internet") -> bool:
        """验证校验和

        Args:
            data: 输入数据
            expected: 预期的校验和值
            algorithm: 校验算法

        Returns:
            是否匹配
        """
        computed = ChecksumCalculator.compute_checksum(data, algorithm)
        return computed == expected

    @staticmethod
    def compute_file_checksum(filepath: str, algorithm: str = "sha256", chunk_size: int = 8192) -> str:
        """计算文件的校验和

        Args:
            filepath: 文件路径
            algorithm: 哈希算法 (md5, sha1, sha256)
            chunk_size: 读取块大小

        Returns:
            十六进制字符串表示的校验和
        """
        import hashlib

        hash_funcs = {
            "md5": hashlib.md5,
            "sha1": hashlib.sha1,
            "sha256": hashlib.sha256,
            "sha512": hashlib.sha512,
        }

        if algorithm not in hash_funcs:
            raise ChecksumError(f"不支持的文件校验算法: {algorithm}")

        h = hash_funcs[algorithm]()
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)

        return h.hexdigest()


class FCS32:
    """以太网帧校验序列 (FCS-32) 计算"""

    # CRC32 查找表
    _TABLE: Optional[list] = None

    @classmethod
    def _build_table(cls) -> list:
        """构建 CRC32 查找表"""
        table = []
        for i in range(256):
            crc = i
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xEDB88320
                else:
                    crc >>= 1
            table.append(crc)
        return table

    @classmethod
    def compute(cls, data: bytes) -> int:
        """计算以太网 FCS-32

        Args:
            data: 帧数据

        Returns:
            32位 FCS 值
        """
        if cls._TABLE is None:
            cls._TABLE = cls._build_table()

        crc = 0xFFFFFFFF
        for byte in data:
            crc = cls._TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)

        return crc ^ 0xFFFFFFFF

    @classmethod
    def verify(cls, data: bytes, fcs: int) -> bool:
        """验证 FCS-32

        Args:
            data: 帧数据
            fcs: 预期的 FCS 值

        Returns:
            是否匹配
        """
        computed = cls.compute(data)
        return computed == fcs


class ChecksumContext:
    """校验和计算上下文管理器，用于增量计算"""

    def __init__(self, algorithm: str = "internet") -> None:
        self.algorithm = algorithm
        self._is_internet = algorithm == "internet"
        self._internet_total = 0

        if algorithm in ("md5", "sha1", "sha256", "sha512"):
            import hashlib
            hash_funcs = {
                "md5": hashlib.md5,
                "sha1": hashlib.sha1,
                "sha256": hashlib.sha256,
                "sha512": hashlib.sha512,
            }
            self._hash = hash_funcs[algorithm]()
        else:
            self._hash = None

    def update(self, data: bytes) -> "ChecksumContext":
        """增量更新校验和

        Args:
            data: 数据块

        Returns:
            self (支持链式调用)
        """
        if self._hash:
            self._hash.update(data)
        elif self._is_internet:
            for i in range(0, len(data), 2):
                chunk = data[i:i+2]
                if len(chunk) == 2:
                    word = (chunk[0] << 8) + chunk[1]
                else:
                    word = chunk[0] << 8
                self._internet_total += word

        return self

    def digest(self) -> Union[int, str]:
        """获取校验和结果

        Returns:
            数字校验和或十六进制字符串
        """
        if self._hash:
            return self._hash.hexdigest()
        elif self._is_internet:
            total = self._internet_total
            while total >> 16:
                total = (total & 0xFFFF) + (total >> 16)
            return ~total & 0xFFFF
        return 0

    def __enter__(self) -> "ChecksumContext":
        return self

    def __exit__(self, *args: object) -> None:
        pass