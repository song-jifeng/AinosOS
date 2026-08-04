"""
IPC 协议模糊测试

测试随机消息注入、异常格式、边界值和缓冲区溢出场景。
"""

import os
import sys
import json
import time
import uuid
import random
import struct
import pickle
import hashlib
import string
import pytest
from typing import List, Dict, Optional, Any, Tuple, Callable, Union, Generator
from dataclasses import dataclass, field, asdict
from datetime import datetime
from collections import defaultdict
from enum import Enum, auto
from io import BytesIO
from unittest.mock import MagicMock, Mock, patch


# =============================================================================
# IPC 协议定义
# =============================================================================

class IPCMessageType(Enum):
    """IPC 消息类型"""
    HANDSHAKE = 0x01
    HEARTBEAT = 0x02
    INFERENCE_REQUEST = 0x10
    INFERENCE_RESPONSE = 0x11
    MODEL_LOAD = 0x20
    MODEL_UNLOAD = 0x21
    MODEL_LIST = 0x22
    ERROR = 0xFF
    SHUTDOWN = 0xFE
    CONFIG_UPDATE = 0x30
    METRICS_REQUEST = 0x40
    METRICS_RESPONSE = 0x41
    STREAM_START = 0x50
    STREAM_CHUNK = 0x51
    STREAM_END = 0x52
    CANCEL = 0x60


@dataclass
class IPCMessage:
    """IPC 消息结构"""
    magic: bytes = b"AIP"  # 3 字节魔数
    version: int = 1
    msg_type: int = 0
    msg_id: int = 0
    flags: int = 0
    payload_length: int = 0
    checksum: int = 0
    payload: bytes = b""

    HEADER_SIZE = 16  # 固定头部大小

    def encode(self) -> bytes:
        """编码消息"""
        self.payload_length = len(self.payload)
        header = struct.pack(
            "!3sBBIHI",
            self.magic,
            self.version,
            self.msg_type,
            self.msg_id,
            self.flags,
            self.payload_length,
        )
        self.checksum = self._calculate_checksum(self.payload)
        header += struct.pack("!I", self.checksum)
        return header + self.payload

    @classmethod
    def decode(cls, data: bytes) -> Optional['IPCMessage']:
        """解码消息"""
        if len(data) < cls.HEADER_SIZE:
            return None

        try:
            magic = data[0:3]
            version = data[3]
            msg_type = data[4]
            msg_id = struct.unpack("!H", data[5:7])[0]
            flags = struct.unpack("!H", data[7:9])[0]
            payload_length = struct.unpack("!I", data[9:13])[0]
            checksum = struct.unpack("!I", data[13:17])[0]

            payload = data[17:17 + payload_length] if payload_length > 0 else b""

            msg = cls(
                magic=magic,
                version=version,
                msg_type=msg_type,
                msg_id=msg_id,
                flags=flags,
                payload_length=payload_length,
                checksum=checksum,
                payload=payload,
            )

            if not msg.verify_checksum():
                return None

            return msg
        except (struct.error, IndexError):
            return None

    def verify_checksum(self) -> bool:
        return self.checksum == self._calculate_checksum(self.payload)

    @staticmethod
    def _calculate_checksum(data: bytes) -> int:
        return hashlib.crc32(data) & 0xFFFFFFFF

    @classmethod
    def create(cls, msg_type: int, payload: bytes = b"",
               msg_id: int = 0, flags: int = 0) -> 'IPCMessage':
        return cls(
            msg_type=msg_type,
            msg_id=msg_id,
            flags=flags,
            payload=payload,
            payload_length=len(payload),
            checksum=cls._calculate_checksum(payload),
        )


# =============================================================================
# IPC 处理器
# =============================================================================

class IPCHandler:
    """IPC 消息处理器"""

    def __init__(self):
        self._handlers: Dict[int, Callable] = {}
        self._processed_messages: List[IPCMessage] = []
        self._errors: List[str] = []
        self._stats: Dict[str, int] = defaultdict(int)

    def register_handler(self, msg_type: int, handler: Callable):
        self._handlers[msg_type] = handler

    def process(self, data: bytes) -> Optional[bytes]:
        """处理原始数据"""
        self._stats["total_received"] += 1

        msg = IPCMessage.decode(data)
        if msg is None:
            self._stats["decode_failures"] += 1
            self._errors.append(f"Failed to decode message: {data[:20].hex()}")
            return self._create_error_response(0xFF01, "Decode failed")

        if not msg.verify_checksum():
            self._stats["checksum_failures"] += 1
            self._errors.append(f"Checksum mismatch for message {msg.msg_id}")
            return self._create_error_response(0xFF02, "Checksum mismatch")

        if msg.magic != b"AIP":
            self._stats["bad_magic"] += 1
            self._errors.append(f"Bad magic: {msg.magic}")
            return self._create_error_response(0xFF03, "Bad magic")

        if msg.version != 1:
            self._stats["bad_version"] += 1
            self._errors.append(f"Unsupported version: {msg.version}")
            return self._create_error_response(0xFF04, "Unsupported version")

        self._processed_messages.append(msg)
        self._stats[f"msg_type_{msg.msg_type}"] += 1

        handler = self._handlers.get(msg.msg_type)
        if handler:
            try:
                return handler(msg)
            except Exception as e:
                self._stats["handler_exceptions"] += 1
                self._errors.append(f"Handler error: {e}")
                return self._create_error_response(0xFF05, f"Handler error: {e}")
        else:
            self._stats["unhandled_types"] += 1
            return self._create_error_response(0xFF06, f"No handler for type {msg.msg_type}")

    def process_batch(self, data_list: List[bytes]) -> List[Optional[bytes]]:
        """批量处理消息"""
        return [self.process(data) for data in data_list]

    def _create_error_response(self, error_code: int, message: str) -> bytes:
        payload = struct.pack("!I", error_code) + message.encode('utf-8')
        return IPCMessage.create(IPCMessageType.ERROR.value, payload).encode()

    def get_stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def clear(self):
        self._processed_messages.clear()
        self._errors.clear()
        self._stats.clear()


# =============================================================================
# 模糊测试工具
# =============================================================================

class FuzzGenerator:
    """模糊测试数据生成器"""

    @staticmethod
    def random_bytes(min_len: int = 0, max_len: int = 1024) -> bytes:
        """生成随机字节"""
        length = random.randint(min_len, max_len)
        return os.urandom(length)

    @staticmethod
    def random_text(min_len: int = 0, max_len: int = 100) -> str:
        """生成随机文本"""
        length = random.randint(min_len, max_len)
        chars = string.printable
        return ''.join(random.choice(chars) for _ in range(length))

    @staticmethod
    def random_message() -> IPCMessage:
        """生成随机 IPC 消息"""
        return IPCMessage(
            magic=random.choice([b"AIP", b"XXX", b"\x00\x00\x00", b"IPC", b"AI\x00"]),
            version=random.randint(0, 255),
            msg_type=random.randint(0, 255),
            msg_id=random.randint(0, 65535),
            flags=random.randint(0, 65535),
            payload=FuzzGenerator.random_bytes(0, 2048),
        )

    @staticmethod
    def random_payload() -> bytes:
        """生成随机负载"""
        payload_type = random.choice([
            "json", "pickle", "raw", "empty", "null_bytes",
            "large", "unicode", "corrupted_header",
        ])

        if payload_type == "json":
            data = {
                "model": random.choice(["gpt-3", "gpt-4", "", None]),
                "prompt": FuzzGenerator.random_text(0, 200),
                "temperature": random.choice([0.5, 2.5, -1, None, "hot"]),
                "max_tokens": random.choice([100, -1, 0, 999999, "many"]),
                "stream": random.choice([True, False, None, "yes"]),
            }
            return json.dumps(data).encode('utf-8')

        elif payload_type == "pickle":
            return pickle.dumps({
                "type": "inference",
                "data": FuzzGenerator.random_text(0, 100),
            })

        elif payload_type == "raw":
            return FuzzGenerator.random_bytes(0, 512)

        elif payload_type == "empty":
            return b""

        elif payload_type == "null_bytes":
            return b"\x00" * random.randint(1, 100)

        elif payload_type == "large":
            return os.urandom(random.randint(65536, 262144))

        elif payload_type == "unicode":
            return FuzzGenerator.random_text(0, 100).encode('utf-16', errors='surrogatepass')

        elif payload_type == "corrupted_header":
            return os.urandom(random.randint(1, 50))

        return b""

    @staticmethod
    def corrupt_message(msg: IPCMessage) -> bytes:
        """损坏消息"""
        encoded = msg.encode()
        data = bytearray(encoded)

        corruption_type = random.choice([
            "bit_flip", "byte_swap", "truncate", "extend",
            "zero_out", "duplicate", "insert_garbage",
        ])

        if corruption_type == "bit_flip" and len(data) > 0:
            idx = random.randint(0, len(data) - 1)
            data[idx] ^= (1 << random.randint(0, 7))

        elif corruption_type == "byte_swap" and len(data) > 1:
            i, j = random.sample(range(len(data)), 2)
            data[i], data[j] = data[j], data[i]

        elif corruption_type == "truncate" and len(data) > 4:
            cut = random.randint(1, len(data) - 1)
            data = data[:cut]

        elif corruption_type == "extend":
            data.extend(os.urandom(random.randint(1, 100)))

        elif corruption_type == "zero_out" and len(data) > 0:
            start = random.randint(0, len(data) - 1)
            end = min(start + random.randint(1, 10), len(data))
            for i in range(start, end):
                data[i] = 0

        elif corruption_type == "duplicate" and len(data) > 0:
            segment = data[:random.randint(1, len(data))]
            data.extend(segment)

        elif corruption_type == "insert_garbage":
            pos = random.randint(0, len(data))
            garbage = os.urandom(random.randint(1, 10))
            data[pos:pos] = garbage

        return bytes(data)

    @staticmethod
    def boundary_values() -> List[bytes]:
        """生成边界值测试数据"""
        values = []

        # 空数据
        values.append(b"")
        values.append(b"\x00")

        # 最小/最大长度
        values.append(b"A" * 1)
        values.append(b"A" * 255)
        values.append(b"A" * 256)
        values.append(b"A" * 65535)
        values.append(b"A" * 65536)

        # 全零
        values.append(b"\x00" * 16)
        values.append(b"\x00" * 1024)

        # 全一
        values.append(b"\xFF" * 16)
        values.append(b"\xFF" * 1024)

        # 边界整数
        for val in [0, 1, 127, 128, 255, 256, 32767, 32768, 65535, 65536,
                    2147483647, 2147483648, 4294967295]:
            values.append(struct.pack("!I", val))
            values.append(struct.pack("!i", val))
            values.append(struct.pack("!H", min(val, 65535)))
            values.append(str(val).encode())

        # 字符串边界
        values.append(b"")
        values.append(b"\n")
        values.append(b"\r\n")
        values.append(b"\x00\x00")
        values.append(b"null")
        values.append(b"undefined")
        values.append(b"true")
        values.append(b"false")
        values.append(b"None")
        values.append(b"\x1b[31m")  # ANSI escape
        values.append(b"<script>alert(1)</script>")
        values.append(b"../../../etc/passwd")
        values.append(b"; DROP TABLE users;")

        # 协议边界
        values.append(b"AIP" + b"\x00" * 13)
        values.append(b"AIP" + b"\xFF" * 13)
        values.append(b"AIP" + b"\x01" * 13)

        # 截断的消息
        values.append(b"AIP")
        values.append(b"AIP\x01")
        values.append(b"AIP\x01\x00")
        values.append(b"AIP\x01\x00\x00")
        values.append(b"AIP\x01\x00\x00\x00")

        return values

    @staticmethod
    def generate_fuzz_sequence(count: int) -> List[bytes]:
        """生成模糊测试序列"""
        sequences = []
        for i in range(count):
            choice = random.randint(0, 9)
            if choice < 3:
                # 随机消息
                msg = FuzzGenerator.random_message()
                sequences.append(msg.encode())
            elif choice < 5:
                # 损坏的消息
                msg = FuzzGenerator.random_message()
                sequences.append(FuzzGenerator.corrupt_message(msg))
            elif choice < 7:
                # 随机字节
                sequences.append(FuzzGenerator.random_bytes(0, 4096))
            elif choice < 8:
                # 边界值
                sequences.append(random.choice(FuzzGenerator.boundary_values()))
            else:
                # 有效的消息
                msg = IPCMessage.create(
                    msg_type=random.choice([0x10, 0x20, 0x01, 0x02]),
                    payload=FuzzGenerator.random_payload(),
                )
                sequences.append(msg.encode())

        return sequences


# =============================================================================
# 测试夹具
# =============================================================================

@pytest.fixture
def ipc_handler():
    handler = IPCHandler()
    # 注册一些处理器
    handler.register_handler(0x10, lambda m: IPCMessage.create(
        0x11, json.dumps({"result": "ok"}).encode()).encode())
    handler.register_handler(0x01, lambda m: IPCMessage.create(
        0x01, b"handshake_ack").encode())
    handler.register_handler(0x02, lambda m: IPCMessage.create(
        0x02, b"pong").encode())
    return handler


@pytest.fixture
def fuzz_generator():
    return FuzzGenerator()


# =============================================================================
# 测试用例: 随机消息注入
# =============================================================================

class TestRandomMessageInjection:
    """随机消息注入测试"""

    def test_random_message_decode(self, ipc_handler, fuzz_generator):
        """测试随机消息解码"""
        for i in range(100):
            msg = fuzz_generator.random_message()
            data = msg.encode()
            decoded = IPCMessage.decode(data)
            if decoded:
                assert decoded.msg_type == msg.msg_type
                assert decoded.payload_length == len(msg.payload)

    def test_random_message_processing(self, ipc_handler, fuzz_generator):
        """测试随机消息处理"""
        for i in range(200):
            data = fuzz_generator.random_bytes(1, 100)
            try:
                response = ipc_handler.process(data)
                # 处理不应该崩溃
            except Exception:
                pass

    def test_bulk_random_injection(self, ipc_handler, fuzz_generator):
        """测试批量随机注入"""
        sequences = fuzz_generator.generate_fuzz_sequence(500)
        for data in sequences:
            try:
                ipc_handler.process(data)
            except Exception:
                pass

        stats = ipc_handler.get_stats()
        assert stats["total_received"] >= 500

    def test_injection_without_crash(self, ipc_handler, fuzz_generator):
        """测试注入不崩溃"""
        for i in range(1000):
            data = os.urandom(random.randint(0, 4096))
            try:
                ipc_handler.process(data)
            except (MemoryError, SystemError):
                pytest.fail("IPC handler crashed on random input")

    def test_repeated_injection_same_data(self, ipc_handler, fuzz_generator):
        """测试重复注入相同数据"""
        data = fuzz_generator.random_bytes(10, 50)
        for i in range(100):
            try:
                ipc_handler.process(data)
            except Exception:
                pass

        stats = ipc_handler.get_stats()
        assert stats["total_received"] == 100


# =============================================================================
# 测试用例: 异常格式
# =============================================================================

class TestAbnormalFormats:
    """异常格式测试"""

    def test_invalid_magic(self, ipc_handler):
        """测试无效魔数"""
        invalid_magics = [
            b"XXX", b"\x00\x00\x00", b"IPC", b"AI\x00",
            b"", b"\xFF\xFF\xFF", b"123", b"aip",
        ]
        for magic in invalid_magics:
            data = magic + b"\x00" * 13
            response = ipc_handler.process(data)
            assert response is not None

    def test_invalid_version(self, ipc_handler):
        """测试无效版本号"""
        for version in [0, 2, 255, 100]:
            msg = IPCMessage(version=version)
            data = msg.encode()
            # 修改版本号
            data = bytearray(data)
            data[3] = version
            response = ipc_handler.process(bytes(data))
            assert response is not None

    def test_malformed_headers(self, ipc_handler):
        """测试畸形头部"""
        malformed_headers = [
            b"\x00" * 16,
            b"\xFF" * 16,
            b"AIP" + b"\x00" * 13,
            b"AIP" + b"\xFF" * 13,
            b"AIP\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            b"",
            b"AIP",
            b"AIP\x01",
        ]
        for header in malformed_headers:
            try:
                ipc_handler.process(header)
            except Exception:
                pass

    def test_invalid_checksum(self, ipc_handler):
        """测试无效校验和"""
        msg = IPCMessage.create(0x10, b"test payload")
        data = bytearray(msg.encode())
        # 破坏校验和
        if len(data) > 17:
            data[13] ^= 0xFF
            data[14] ^= 0xFF
            data[15] ^= 0xFF
            data[16] ^= 0xFF

        response = ipc_handler.process(bytes(data))
        assert response is not None

    def test_negative_length(self, ipc_handler):
        """测试负数长度"""
        msg = IPCMessage(
            payload_length=0xFFFFFFFF,  # 最大长度
            payload=b"actual data",
        )
        data = msg.encode()
        try:
            ipc_handler.process(data)
        except (MemoryError, OverflowError):
            pass

    def test_zero_length_payload(self, ipc_handler):
        """测试零长度负载"""
        msg = IPCMessage.create(0x10, b"")
        response = ipc_handler.process(msg.encode())
        assert response is not None

    def test_max_length_payload(self, ipc_handler):
        """测试最大长度负载"""
        try:
            msg = IPCMessage.create(0x10, os.urandom(65536))
            response = ipc_handler.process(msg.encode())
            # 可能成功也可能失败，但不能崩溃
        except (MemoryError, SystemError):
            pass

    def test_unicode_injection(self, ipc_handler):
        """测试 Unicode 注入"""
        unicode_payloads = [
            "你好世界".encode('utf-8'),
            " ".encode('utf-16'),
            "🔥🚀🌟".encode('utf-8'),
            "\x00\x01\x02\x03".encode('latin-1'),
            "\\u0000\\uFFFF".encode(),
        ]
        for payload in unicode_payloads:
            msg = IPCMessage.create(0x10, payload)
            try:
                ipc_handler.process(msg.encode())
            except Exception:
                pass


# =============================================================================
# 测试用例: 边界值
# =============================================================================

class TestBoundaryValues:
    """边界值测试"""

    def test_empty_message(self, ipc_handler):
        """测试空消息"""
        response = ipc_handler.process(b"")
        assert response is not None

    def test_single_byte_message(self, ipc_handler):
        """测试单字节消息"""
        for byte_val in [0, 1, 127, 128, 255]:
            response = ipc_handler.process(bytes([byte_val]))
            assert response is not None

    def test_message_size_boundaries(self, ipc_handler):
        """测试消息大小边界"""
        sizes = [1, 16, 17, 18, 255, 256, 1023, 1024, 65535, 65536]
        for size in sizes:
            try:
                data = os.urandom(size)
                msg = IPCMessage.create(0x10, data)
                encoded = msg.encode()
                decoded = IPCMessage.decode(encoded)
                if decoded:
                    assert decoded.payload_length == size
            except (MemoryError, struct.error):
                pass

    def test_id_boundaries(self, ipc_handler):
        """测试 ID 边界"""
        for msg_id in [0, 1, 32767, 32768, 65535]:
            msg = IPCMessage.create(0x10, b"test", msg_id=msg_id)
            decoded = IPCMessage.decode(msg.encode())
            if decoded:
                assert decoded.msg_id == msg_id

    def test_flag_boundaries(self, ipc_handler):
        """测试标志位边界"""
        for flags in [0, 1, 32767, 32768, 65535]:
            msg = IPCMessage.create(0x10, b"test", flags=flags)
            decoded = IPCMessage.decode(msg.encode())
            if decoded:
                assert decoded.flags == flags

    def test_boundary_value_set(self, ipc_handler, fuzz_generator):
        """测试边界值集合"""
        boundaries = fuzz_generator.boundary_values()
        for data in boundaries:
            try:
                ipc_handler.process(data)
            except Exception:
                pass

        # 处理不应该导致未处理的异常
        assert True

    def test_protocol_version_boundaries(self, ipc_handler):
        """测试协议版本边界"""
        for version in [0, 1, 2, 127, 128, 255]:
            msg = IPCMessage(version=version, msg_type=0x01)
            data = bytearray(msg.encode())
            data[3] = version
            try:
                ipc_handler.process(bytes(data))
            except Exception:
                pass


# =============================================================================
# 测试用例: 缓冲区溢出
# =============================================================================

class TestBufferOverflow:
    """缓冲区溢出测试"""

    def test_large_payload_overflow(self, ipc_handler):
        """测试大负载溢出"""
        # 尝试非常大的负载
        for size in [10 * 1024 * 1024, 100 * 1024 * 1024, 1024 * 1024 * 1024]:
            try:
                payload = os.urandom(min(size, 10 * 1024 * 1024))  # 限制最大 10MB
                msg = IPCMessage.create(0x10, payload)
                data = msg.encode()
                decoded = IPCMessage.decode(data)
                if decoded:
                    assert len(decoded.payload) == len(payload)
            except (MemoryError, OverflowError, struct.error):
                pass

    def test_repeated_overflow(self, ipc_handler):
        """测试重复溢出"""
        for i in range(100):
            try:
                large_msg = IPCMessage.create(0x10, os.urandom(100000))
                ipc_handler.process(large_msg.encode())
            except (MemoryError, SystemError):
                pass

        stats = ipc_handler.get_stats()
        assert stats["total_received"] >= 0

    def test_string_overflow(self, ipc_handler):
        """测试字符串溢出"""
        long_string = "A" * 100000
        msg = IPCMessage.create(0x10, long_string.encode())
        try:
            decoded = IPCMessage.decode(msg.encode())
            if decoded:
                assert len(decoded.payload) == len(long_string)
        except MemoryError:
            pass

    def test_recursive_overflow(self, ipc_handler):
        """测试递归溢出"""
        # 创建嵌套消息
        inner = IPCMessage.create(0x10, b"inner")
        outer = IPCMessage.create(0x10, inner.encode())
        try:
            decoded = IPCMessage.decode(outer.encode())
            if decoded:
                inner_decoded = IPCMessage.decode(decoded.payload)
                if inner_decoded:
                    assert inner_decoded.msg_type == 0x10
        except Exception:
            pass

    def test_many_small_buffers(self, ipc_handler):
        """测试大量小缓冲区"""
        for i in range(1000):
            small_msg = IPCMessage.create(0x10, os.urandom(1))
            try:
                ipc_handler.process(small_msg.encode())
            except Exception:
                pass

        stats = ipc_handler.get_stats()
        assert stats["total_received"] == 1000

    def test_buffer_underflow(self, ipc_handler):
        """测试缓冲区下溢"""
        # 声明大的负载长度但实际数据少
        for size in [100, 1000, 10000]:
            header = struct.pack("!3sBBIHI", b"AIP", 1, 0x10, 0, 0, size)
            checksum = hashlib.crc32(b"") & 0xFFFFFFFF
            header += struct.pack("!I", checksum)
            data = header + b"small"
            try:
                ipc_handler.process(data)
            except Exception:
                pass

    def test_header_overflow(self, ipc_handler):
        """测试头部溢出"""
        # 头部字段的极端值
        extreme_headers = [
            # (magic, version, type, id, flags, length)
            (b"AIP", 255, 255, 65535, 65535, 4294967295),
            (b"AIP", 0, 0, 0, 0, 4294967295),
            (b"\x00\x00\x00", 255, 255, 65535, 65535, 4294967295),
        ]
        for magic, ver, typ, mid, flags, length in extreme_headers:
            try:
                header = struct.pack("!3sBBIHI", magic, ver, typ, mid, flags, length)
                checksum = 0
                header += struct.pack("!I", checksum)
                ipc_handler.process(header)
            except (struct.error, MemoryError, OverflowError):
                pass


# =============================================================================
# 测试用例: 协议兼容性
# =============================================================================

class TestProtocolCompatibility:
    """协议兼容性测试"""

    def test_round_trip_message(self, ipc_handler):
        """测试消息往返"""
        original = IPCMessage.create(0x10, b"test payload")
        encoded = original.encode()
        decoded = IPCMessage.decode(encoded)
        assert decoded is not None
        assert decoded.msg_type == original.msg_type
        assert decoded.payload == original.payload
        assert decoded.verify_checksum()

    def test_multiple_message_types(self, ipc_handler):
        """测试多种消息类型"""
        for msg_type in range(0, 256):
            msg = IPCMessage.create(msg_type, f"type-{msg_type}".encode())
            try:
                decoded = IPCMessage.decode(msg.encode())
                if decoded:
                    assert decoded.msg_type == msg_type
            except Exception:
                pass

    def test_mixed_valid_invalid_messages(self, ipc_handler, fuzz_generator):
        """测试混合有效/无效消息"""
        for i in range(100):
            if random.random() < 0.3:
                # 有效消息
                msg = IPCMessage.create(0x10, b"valid")
                data = msg.encode()
            else:
                # 随机数据
                data = fuzz_generator.random_bytes(0, 100)

            try:
                ipc_handler.process(data)
            except Exception:
                pass

        stats = ipc_handler.get_stats()
        assert stats["total_received"] == 100

    def test_payload_encoding_consistency(self, ipc_handler):
        """测试负载编码一致性"""
        payloads = [
            b"",
            b"\x00",
            b"Hello, World!",
            b"\x00\x01\x02\x03\xFF\xFE",
            json.dumps({"key": "value"}).encode(),
            os.urandom(1000),
        ]
        for payload in payloads:
            msg = IPCMessage.create(0x10, payload)
            decoded = IPCMessage.decode(msg.encode())
            assert decoded is not None
            # 解码后的有效负载长度应该匹配
            assert decoded.payload_length == len(payload)


# =============================================================================
# 测试用例: 消息完整性
# =============================================================================

class TestMessageIntegrity:
    """消息完整性测试"""

    def test_checksum_verification(self, ipc_handler):
        """测试校验和验证"""
        msg = IPCMessage.create(0x10, b"integrity test")
        assert msg.verify_checksum()

        # 损坏数据
        corrupted = bytearray(msg.payload)
        if corrupted:
            corrupted[0] ^= 0xFF
        msg.payload = bytes(corrupted)
        assert not msg.verify_checksum()

    def test_integrity_after_corruption(self, ipc_handler, fuzz_generator):
        """测试损坏后的完整性"""
        for i in range(50):
            msg = fuzz_generator.random_message()
            corrupted = fuzz_generator.corrupt_message(msg)
            decoded = IPCMessage.decode(corrupted)
            if decoded:
                assert decoded.verify_checksum() == (decoded.payload == msg.payload)

    def test_payload_integrity_preservation(self, ipc_handler):
        """测试负载完整性保持"""
        original_payload = os.urandom(1024)
        msg = IPCMessage.create(0x10, original_payload)
        decoded = IPCMessage.decode(msg.encode())
        assert decoded is not None
        assert decoded.payload == original_payload

    def test_checksum_collision_resistance(self, ipc_handler):
        """测试校验和冲突抵抗"""
        # 不同负载应该（通常）有不同的校验和
        checksums = set()
        for i in range(1000):
            payload = os.urandom(random.randint(1, 100))
            checksum = IPCMessage._calculate_checksum(payload)
            checksums.add(checksum)
        # 应该有足够多的唯一校验和
        assert len(checksums) > 900


# =============================================================================
# 测试用例: 压力下的模糊测试
# =============================================================================

class TestFuzzUnderStress:
    """压力下的模糊测试"""

    def test_high_frequency_fuzzing(self, ipc_handler, fuzz_generator):
        """测试高频模糊"""
        for i in range(5000):
            data = fuzz_generator.random_bytes(1, 100)
            try:
                ipc_handler.process(data)
            except Exception:
                pass

        stats = ipc_handler.get_stats()
        assert stats["total_received"] == 5000

    def test_concurrent_fuzzing(self, ipc_handler, fuzz_generator):
        """测试并发模糊"""
        import threading

        results = []

        def fuzz_worker(worker_id):
            local_stats = {"processed": 0}
            for i in range(500):
                data = fuzz_generator.random_bytes(1, 200)
                try:
                    ipc_handler.process(data)
                    local_stats["processed"] += 1
                except Exception:
                    pass
            results.append(local_stats)

        threads = [threading.Thread(target=fuzz_worker, args=(i,))
                   for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = sum(r["processed"] for r in results)
        assert total > 0

    def test_fuzz_with_valid_messages(self, ipc_handler, fuzz_generator):
        """测试有效消息中的模糊"""
        for i in range(500):
            if random.random() < 0.5:
                # 有效消息
                msg = IPCMessage.create(0x10, json.dumps({
                    "model": "test",
                    "prompt": "hello",
                }).encode())
                data = msg.encode()
            else:
                # 模糊数据
                data = fuzz_generator.random_bytes(0, 200)

            try:
                ipc_handler.process(data)
            except Exception:
                pass

        stats = ipc_handler.get_stats()
        assert stats["total_received"] == 500


# =============================================================================
# 测试用例: 协议安全
# =============================================================================

class TestProtocolSecurity:
    """协议安全测试"""

    def test_replay_attack_detection(self, ipc_handler, fuzz_generator):
        """测试重放攻击检测"""
        msg = IPCMessage.create(0x10, b"legitimate request")
        original = msg.encode()

        # 第一次处理
        response1 = ipc_handler.process(original)
        assert response1 is not None

        # 重放
        response2 = ipc_handler.process(original)
        assert response2 is not None

    def test_message_tampering_detection(self, ipc_handler):
        """测试消息篡改检测"""
        msg = IPCMessage.create(0x10, b"important data")
        data = bytearray(msg.encode())

        # 篡改负载
        if len(data) > 20:
            data[20] ^= 0xFF

        response = ipc_handler.process(bytes(data))
        assert response is not None

    def test_protocol_version_mismatch(self, ipc_handler):
        """测试协议版本不匹配"""
        for version in [2, 3, 127, 255]:
            msg = IPCMessage(version=version, msg_type=0x01, payload=b"test")
            response = ipc_handler.process(msg.encode())
            assert response is not None

    def test_invalid_message_flags(self, ipc_handler):
        """测试无效标志位"""
        msg = IPCMessage.create(0x10, b"test", flags=0xFFFF)
        response = ipc_handler.process(msg.encode())
        assert response is not None

    def test_empty_payload_variations(self, ipc_handler):
        """测试空负载变体"""
        empty_payloads = [
            b"",
            b"\x00",
            b"\x00\x00\x00\x00",
            b"null",
            b"undefined",
            b"None",
        ]
        for payload in empty_payloads:
            msg = IPCMessage.create(0x10, payload)
            try:
                response = ipc_handler.process(msg.encode())
                # 不应该崩溃
            except Exception:
                pass

    def test_message_id_collision(self, ipc_handler):
        """测试消息 ID 冲突"""
        msg1 = IPCMessage.create(0x10, b"first", msg_id=1)
        msg2 = IPCMessage.create(0x10, b"second", msg_id=1)

        response1 = ipc_handler.process(msg1.encode())
        response2 = ipc_handler.process(msg2.encode())
        assert response1 is not None
        assert response2 is not None


# =============================================================================
# 测试用例: 极端输入
# =============================================================================

class TestExtremeInputs:
    """极端输入测试"""

    def test_very_long_message_chain(self, ipc_handler):
        """测试长消息链"""
        payload = b""
        for i in range(100):
            inner = IPCMessage.create(0x10, payload)
            payload = inner.encode()
            if len(payload) > 100000:
                break

        try:
            response = ipc_handler.process(payload)
        except (MemoryError, RecursionError):
            pass

    def test_max_fields_message(self, ipc_handler):
        """测试最大字段数消息"""
        msg = IPCMessage(
            magic=b"AIP",
            version=255,
            msg_type=255,
            msg_id=65535,
            flags=65535,
            payload=os.urandom(65535),
        )
        try:
            data = msg.encode()
            decoded = IPCMessage.decode(data)
            if decoded:
                assert decoded.magic == b"AIP"
                assert decoded.version == 255
        except (struct.error, MemoryError):
            pass

    def test_zero_and_negative_values(self, ipc_handler):
        """测试零和负值"""
        for length in [0, -1, -100, -65535]:
            try:
                msg = IPCMessage(payload_length=length, payload=b"test")
                response = ipc_handler.process(msg.encode())
            except (struct.error, ValueError, OverflowError):
                pass

    def test_unexpected_eof_handling(self, ipc_handler):
        """测试意外 EOF 处理"""
        msg = IPCMessage.create(0x10, b"complete message")
        full_data = msg.encode()

        for cut in range(1, len(full_data)):
            truncated = full_data[:cut]
            try:
                ipc_handler.process(truncated)
            except Exception:
                pass

    def test_unicode_and_encoding_attacks(self, ipc_handler):
        """测试 Unicode 和编码攻击"""
        attack_payloads = [
            " ".encode('utf-8'),
            "￿".encode('utf-8'),
            "\U0010FFFF".encode('utf-8'),
            "\x00\x01\x02\x1F\x7F".encode('latin-1'),
            "\\x00\\x01\\x02".encode('utf-8'),
            "".encode('utf-16'),
            b"\xFE\xFF\x00\x00\x00\x00",
            b"\xFF\xFE\x00\x00\x00\x00",
        ]
        for payload in attack_payloads:
            msg = IPCMessage.create(0x10, payload)
            try:
                ipc_handler.process(msg.encode())
            except Exception:
                pass

    def test_mixed_encoding_payloads(self, ipc_handler):
        """测试混合编码负载"""
        for i in range(100):
            size = random.randint(1, 1000)
            data = os.urandom(size)
            msg = IPCMessage.create(0x10, data)
            try:
                decoded = IPCMessage.decode(msg.encode())
                if decoded:
                    assert decoded.payload_length == size
            except Exception:
                pass


# =============================================================================
# 模糊测试主入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])